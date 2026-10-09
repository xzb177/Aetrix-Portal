"""Telegram 用户与站内 WebUser 的身份解析。"""
from __future__ import annotations

import logging

from backend import models

logger = logging.getLogger(__name__)


def resolve_user(db, telegram_id: int) -> models.WebUser | None:
    """按 telegram_id 查找已绑定的站内用户，未绑定返回 None。"""
    try:
        return db.query(models.WebUser).filter(models.WebUser.telegram_id == telegram_id).first()
    except Exception:
        logger.exception("查询 WebUser 失败 telegram_id=%s", telegram_id)
        return None
