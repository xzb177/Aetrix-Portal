"""订阅有效性判定与付费墙（全站单一事实来源）

订阅行（UserSubscription.status）不会随时间自动翻转为 expired，
因此「是否会员」统一按 end_date 现算，避免各入口口径不一致。

**一个服一个订阅**：多服部署下，判定必须带上服（``realm_id``）——
甲服的白票不应该能在乙服的 EA 上播放。传入方式：

- 显式参数（EM 管理端 / 用户端按具体服查询时）；
- 否则用**本进程的服**（EA 的进程级解析器，启动时按节点身份安装，见
  ``emby_server/nodes.py`` 与 ``emby_api/main.py``）；
- 都没有时不做服过滤（单服部署、以及 EM 侧的跨服查询，行为与以前完全一致）。

付费墙开关：
- SystemConfig["subscription_required"]（布尔，默认 true）是否要求有效订阅才能播放
- SystemConfig["subscription_gate_message"]（字符串，可选）自定义拦截提示文案
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger(__name__)

# 进程级「本进程服务哪个服」的解析器（EA 启动时装上）
_realm_resolver: Optional[Callable[[], Optional[int]]] = None


def set_process_realm_resolver(resolver: Optional[Callable[[], Optional[int]]]) -> None:
    """由 EA 启动流程装上一个「本进程的服」解析器（EM 不装，保持跨服口径）"""
    global _realm_resolver
    _realm_resolver = resolver


def process_realm_id() -> Optional[int]:
    """本进程的服（没装解析器或解析不到时返回 None = 不做服过滤）"""
    if _realm_resolver is None:
        return None
    try:
        return _realm_resolver()
    except Exception as exc:  # noqa: BLE001 — 解析失败不能把播放整体拦住
        logger.warning("解析本进程的服失败（按不过滤处理）: %s", exc)
        return None


def resolve_realm_id(realm_id: Optional[int] = None) -> Optional[int]:
    return realm_id if realm_id is not None else process_realm_id()

CONFIG_REQUIRED = "subscription_required"
CONFIG_MESSAGE = "subscription_gate_message"
CONFIG_ALLOW_DOWNLOAD = "allow_download"

DEFAULT_GATE_MESSAGE = "需要有效的会员订阅才能播放，请先开通会员"
DOWNLOAD_GATE_MESSAGE = "当前站点已关闭下载，仅支持在线观看"


def has_active_subscription(db: Session, user_id: int, realm_id: Optional[int] = None) -> bool:
    """是否持有「生效中且未到期」的订阅（可按服判定）"""
    target = resolve_realm_id(realm_id)
    query = db.query(models.UserSubscription).filter(
        models.UserSubscription.user_id == user_id,
        models.UserSubscription.status == "active",
        models.UserSubscription.end_date > datetime.now(),
    )
    if target is not None:
        query = query.filter(models.UserSubscription.realm_id == target)
    return query.first() is not None


def active_subscription(db: Session, user_id: int, realm_id: Optional[int] = None):
    """取一份生效中的订阅（按服；用于展示用户到底买的是哪个服）"""
    target = resolve_realm_id(realm_id)
    query = db.query(models.UserSubscription).filter(
        models.UserSubscription.user_id == user_id,
        models.UserSubscription.status == "active",
        models.UserSubscription.end_date > datetime.now(),
    )
    if target is not None:
        query = query.filter(models.UserSubscription.realm_id == target)
    return query.order_by(models.UserSubscription.end_date.desc()).first()


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


def can_play(db: Session, user: models.WebUser, realm_id: Optional[int] = None) -> bool:
    """是否放行播放：管理员始终放行；付费墙关闭时全员放行"""
    if getattr(user, "is_staff", False):
        return True
    if not subscription_required(db):
        return True
    return has_active_subscription(db, user.id, realm_id)


def ensure_playback_allowed(db: Session, user: models.WebUser,
                           realm_id: Optional[int] = None) -> None:
    """播放前校验：未订阅时抛 403（前端据此展示付费墙引导）

    ``realm_id`` 留空时按**本进程的服**判定（EA 上就是这台机器所属的服）。
    """
    if not can_play(db, user, realm_id):
        raise HTTPException(status_code=403, detail=gate_message(db))


def download_allowed(db: Session) -> bool:
    """站点是否允许下载（缺省允许；关闭后第三方播放器触发的下载一并拦下）"""
    raw = _config_value(db, CONFIG_ALLOW_DOWNLOAD)
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() == "true"


def ensure_download_allowed(db: Session, user: models.WebUser) -> None:
    """下载前校验：站点关闭下载时抛 403（管理员依然放行，便于排查）"""
    if getattr(user, "is_staff", False):
        return
    if not download_allowed(db):
        raise HTTPException(status_code=403, detail=DOWNLOAD_GATE_MESSAGE)


__all__ = [
    "CONFIG_REQUIRED",
    "CONFIG_MESSAGE",
    "CONFIG_ALLOW_DOWNLOAD",
    "DEFAULT_GATE_MESSAGE",
    "DOWNLOAD_GATE_MESSAGE",
    "active_subscription",
    "has_active_subscription",
    "process_realm_id",
    "resolve_realm_id",
    "set_process_realm_resolver",
    "subscription_required",
    "gate_message",
    "can_play",
    "ensure_playback_allowed",
    "download_allowed",
    "ensure_download_allowed",
]
