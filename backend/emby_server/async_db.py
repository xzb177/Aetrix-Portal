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
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """把同步 DB 函数扔到线程池跑，不阻塞事件循环。

    用法：``item = await run_db(_require_item, db, item_id)``
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
