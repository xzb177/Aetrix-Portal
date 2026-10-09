"""TG Bot 轮询器调度器：daemon 线程入口。"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_STARTED = False
_LOCK = threading.Lock()


def start_tg_bot_poller() -> bool:
    """启动 TG Bot 长轮询线程。同一进程只启动一次。

    返回 True 表示本次调用成功启动，False 表示已在运行或未配置。
    """
    global _STARTED
    with _LOCK:
        if _STARTED:
            return False
        _STARTED = True

    # 启动前检查 token 是否配置（未配置则静默不启动）
    try:
        from backend.database import SessionLocal
        from backend.integrations.telegram import token as get_token

        db = SessionLocal()
        try:
            if not get_token(db):
                logger.info("tg_bot_poller: 未配置 Bot Token，跳过启动")
                with _LOCK:
                    _STARTED = False
                return False
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tg_bot_poller: 启动前检查失败（可忽略）: %s", exc)
        with _LOCK:
            _STARTED = False
        return False

    from backend.tg_bot import poller

    t = threading.Thread(
        target=poller.poll_forever,
        name="tg-bot-poller",
        daemon=True,
    )
    t.start()
    logger.info("tg_bot_poller started")
    return True
