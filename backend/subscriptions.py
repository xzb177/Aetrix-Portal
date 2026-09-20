"""订阅有效性判定与付费墙（全站单一事实来源）

订阅行（UserSubscription.status）不会随时间自动翻转为 expired，
因此「是否会员」统一按 end_date 现算，避免各入口口径不一致。

付费墙开关：
- SystemConfig["subscription_required"]（布尔，默认 true）是否要求有效订阅才能播放
- SystemConfig["subscription_gate_message"]（字符串，可选）自定义拦截提示文案
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger(__name__)

CONFIG_REQUIRED = "subscription_required"
CONFIG_MESSAGE = "subscription_gate_message"

DEFAULT_GATE_MESSAGE = "需要有效的会员订阅才能播放，请先开通会员"


def has_active_subscription(db: Session, user_id: int) -> bool:
    """是否持有「生效中且未到期」的订阅"""
    return (
        db.query(models.UserSubscription)
        .filter(
            models.UserSubscription.user_id == user_id,
            models.UserSubscription.status == "active",
            models.UserSubscription.end_date > datetime.now(),
        )
        .first()
        is not None
    )


def _config_value(db: Session, key: str) -> Optional[str]:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return row.value if row else None


def subscription_required(db: Session) -> bool:
    """付费墙是否开启（缺省开启：项目默认按会员制运营）"""
    raw = _config_value(db, CONFIG_REQUIRED)
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() == "true"


def gate_message(db: Session) -> str:
    raw = _config_value(db, CONFIG_MESSAGE)
    text = (raw or "").strip()
    return text or DEFAULT_GATE_MESSAGE


def can_play(db: Session, user: models.WebUser) -> bool:
    """是否放行播放：管理员始终放行；付费墙关闭时全员放行"""
    if getattr(user, "is_staff", False):
        return True
    if not subscription_required(db):
        return True
    return has_active_subscription(db, user.id)


def ensure_playback_allowed(db: Session, user: models.WebUser) -> None:
    """播放前校验：未订阅时抛 403（前端据此展示付费墙引导）"""
    if not can_play(db, user):
        raise HTTPException(status_code=403, detail=gate_message(db))


__all__ = [
    "CONFIG_REQUIRED",
    "CONFIG_MESSAGE",
    "DEFAULT_GATE_MESSAGE",
    "has_active_subscription",
    "subscription_required",
    "gate_message",
    "can_play",
    "ensure_playback_allowed",
]
