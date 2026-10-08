"""Async 路由里的同步 DB 操作助手。

问题背景（P0，2026-09-29）：
EA 是单 uvicorn worker。``async def`` 路由里直接调同步的 SQLAlchemy
（``db.query`` / ``db.commit`` 等）会阻塞整个事件循环——SQLite 的 commit
是一次 fsync，慢的时候几十到几百毫秒，期间全站请求都在排队。
跑久了退化到登录 15 秒+，重启才恢复。

规则：
- ``async def`` 路由/依赖里，任何碰 DB 的同步函数，都用 ``await run_db(...)``
  扔到线程池，绝不直接调。
- ``run_db`` 只解决「不卡事件循环」；SQLAlchemy Session 本身不是线程安全的，
  所以同一个 Session 在 ``await`` 期间调用方不得再碰它（await 保证了这点）。

静态护栏见 ``tests/test_ea_event_loop.py::test_no_direct_db_in_async``。
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """把同步 DB 函数扔到线程池跑，不阻塞事件循环。

    用法：``item = await run_db(_require_item, db, item_id)``
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


# ---------------------------------------------------------------------------
# S1（稳定性审查）：流式响应不得在整个播放期间占着 DB 连接
# ---------------------------------------------------------------------------
#
# FastAPI ≥0.118 把 ``Depends(get_db)`` 这类 yield 依赖的清理放到「响应发完之后」。
# 对 StreamingResponse / FileResponse 来说就是「整部片播完之后」：一个 2 小时的
# ``bytes=0-`` 请求会让一个连接 idle-in-transaction 2 小时，约 50 路并发流就把
# PG 连接池耗尽，全站 30 秒后 500。
#
# 流式端点在返回响应**之前**把会话关掉（连接还给池；ORM 对象随之 detached，
# 返回前取好需要的字符串即可）。之后 yield 依赖的 ``db.close()`` 再跑一次是空操作。

def _session_arg(sig: inspect.Signature, args, kwargs):
    try:
        return sig.bind_partial(*args, **kwargs).arguments.get("db")
    except TypeError:
        return kwargs.get("db")


def _close_quietly(db) -> None:
    close = getattr(db, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:  # noqa: BLE001 - 关会话失败不能把已经算好的响应变成 500
        logger.debug("释放流式请求的 DB 会话失败", exc_info=True)


def release_db_before_response(fn):
    """装饰流式端点：端点函数返回（或抛错）时立刻关掉参数 ``db`` 那个 Session。

    同时支持 ``async def`` 与 ``def`` 端点；保留原签名（FastAPI 依赖注入照常）。
    async 版本的关闭在线程池里做（``Session.close`` 可能触发一次 ROLLBACK）。
    """
    sig = inspect.signature(fn)

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            finally:
                db = _session_arg(sig, args, kwargs)
                if db is not None:
                    await asyncio.to_thread(_close_quietly, db)
        return _async_wrapper

    @functools.wraps(fn)
    def _sync_wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            db = _session_arg(sig, args, kwargs)
            if db is not None:
                _close_quietly(db)
    return _sync_wrapper
