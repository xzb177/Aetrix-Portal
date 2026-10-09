"""TG Bot 长轮询：getUpdates 接收消息，offset 持久化。"""
from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# update 分发队列（poller 线程只做 IO，业务在工作线程执行）
_UPDATE_QUEUE: queue.Queue = queue.Queue(maxsize=1000)
_EXECUTOR: ThreadPoolExecutor | None = None


def _get_offset(db) -> int:
    """从 SystemConfig 读取 offset。"""
    from backend.integrations import store
    try:
        return int(store.get_value(db, "tg_bot_update_offset", "0") or "0")
    except (ValueError, TypeError):
        return 0


def _save_offset(db, offset: int) -> None:
    """持久化 offset 到 SystemConfig。"""
    from backend.integrations import store
    # 注意：store 只有 write_values，没有 set_value
    store.write_values(db, {_OFFSET_KEY: str(offset)})


def _poll_once(token: str, offset: int, timeout: int = 30) -> list:
    """单次 getUpdates 长轮询，返回 updates 列表。"""
    import httpx

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    with httpx.Client(timeout=timeout + 10) as client:
        resp = client.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"getUpdates HTTP {resp.status_code}")
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"getUpdates API error: {body.get('description')}")
    return body.get("result") or []


def _worker_loop() -> None:
    """工作线程：从队列取 update 并分发。"""
    from backend.database import SessionLocal
    from backend.tg_bot import router

    while True:
        update = _UPDATE_QUEUE.get()
        if update is None:  # 退出信号
            break
        db = SessionLocal()
        try:
            router.dispatch(db, update)
        except Exception as exc:  # noqa: BLE001
            logger.error("tg worker dispatch failed: %s", exc, exc_info=True)
        finally:
            db.close()


def poll_forever() -> None:
    """主循环：长轮询 getUpdates。token 未配置则直接返回。"""
    from backend.database import SessionLocal
    from backend.integrations.telegram import token as get_token
    from backend.integrations import store

    global _EXECUTOR

    # 启动工作线程池
    _EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tg-bot-worker")
    for _ in range(4):
        t = threading.Thread(target=_worker_loop, daemon=True, name="tg-bot-worker")
        t.start()

    backoff = 5
    while True:
        db = SessionLocal()
        try:
            bot_token = get_token(db)
            if not bot_token:
                logger.warning("tg_bot_poller: token 未配置，线程退出")
                return
            # 检查总开关
            enabled = store.get_value(db, "tg_bot_commands_enabled", "1")
            if enabled != "1":
                logger.info("tg_bot_poller: 开关关闭，休眠 60s")
                time.sleep(60)
                continue
            offset = _get_offset(db)
        finally:
            db.close()

        try:
            updates = _poll_once(bot_token, offset, timeout=30)
            backoff = 5  # 成功后重置退避
            if updates:
                max_id = offset
                for u in updates:
                    uid = u.get("update_id", 0)
                    if uid >= max_id:
                        max_id = uid + 1
                    try:
                        _UPDATE_QUEUE.put_nowait(u)
                    except queue.Full:
                        logger.warning("tg update queue full, dropping update %s", uid)
                # 持久化 offset
                db2 = SessionLocal()
                try:
                    _save_offset(db2, max_id)
                finally:
                    db2.close()
        except Exception as exc:  # noqa: BLE001
            logger.error("tg poll failed: %s, retry in %ss", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
