"""播放与客户端策略（v2.26.0）

以前这些策略散在两处：一部分是环境变量（``EMBY_MAX_TRANSCODES`` / ``EMBY_TRANSCODE_IDLE``，
改一次要登机器重启进程），一部分是设置页里的下载 / 设备开关。运营想要的是
「客户端这边到底允许做什么」——一句话能回答的问题：

- **允许转码吗**（关掉只放直连/直接播放：省 CPU，代价是客户端兼容性变差）；
- **同时几路转码**（超了直接拒绝新的，而不是把正在看的人挤掉）；
- **码率上限**（客户端要 40Mbps 也只给到设定值，防止一条链路打满上行）；
- **哪些客户端不许进**（老版本 / 盗版客户端的 UA 子串黑名单，也支持白名单模式）。

判定口径与 ``backend/subscriptions.py`` 一致：**管理员不受限**（排障时不能被自己的策略挡住），
缺省配置 = 与升级前完全一样的行为（允许转码、不限并发、不限码率、不拦客户端）。

落库仍然是 ``SystemConfig`` 键值（EM 与 EA 用的是同一个库，见 deploy-ea.md），
所以面板上改完，EA 立刻按新策略放行/拒绝。
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend import models

CONFIG_TRANSCODE_ENABLED = "playback_transcode_enabled"
CONFIG_MAX_TRANSCODES = "playback_max_concurrent_transcodes"
CONFIG_MAX_BITRATE = "playback_max_bitrate_kbps"
CONFIG_BLOCKED_AGENTS = "client_blocked_agents"
CONFIG_ALLOWED_AGENTS = "client_allowed_agents"

# 键 → 类型（设置页与 PUT 接口共用一份，避免两边各写一套白名单）
POLICY_KEYS = {
    CONFIG_TRANSCODE_ENABLED: "bool",
    CONFIG_MAX_TRANSCODES: "int",
    CONFIG_MAX_BITRATE: "int",
    CONFIG_BLOCKED_AGENTS: "str",
    CONFIG_ALLOWED_AGENTS: "str",
}

DEFAULT_BITRATE_CEILING_KBPS = 0  # 0 = 不限


def _raw(db: Session, key: str) -> Optional[str]:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return row.value if row else None


def _config_bool(db: Session, key: str, default: bool) -> bool:
    raw = _raw(db, key)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() == "true"


def _config_int(db: Session, key: str, default: int) -> int:
    raw = _raw(db, key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def transcode_enabled(db: Session) -> bool:
    """是否允许服务端转码（缺省允许；关掉只放直连）"""
    return _config_bool(db, CONFIG_TRANSCODE_ENABLED, True)


def max_transcodes(db: Session) -> int:
    """并发转码上限；0 = 用进程内置上限（``EMBY_MAX_TRANSCODES`` / CPU 核数）"""
    return max(0, _config_int(db, CONFIG_MAX_TRANSCODES, 0))


def max_bitrate_kbps(db: Session) -> int:
    """码率上限（kbps）；0 = 不限"""
    return max(0, _config_int(db, CONFIG_MAX_BITRATE, DEFAULT_BITRATE_CEILING_KBPS))


def _agent_list(db: Session, key: str) -> list[str]:
    raw = (_raw(db, key) or "").strip()
    if not raw:
        return []
    parts = raw.replace("，", ",").replace("\n", ",").split(",")
    return [p.strip().lower() for p in parts if p.strip()]


def client_denied_reason(db: Session, user_agent: Optional[str], *, is_staff: bool = False) -> Optional[str]:
    """这个客户端能不能进（None = 放行）

    白名单优先于黑名单（都配了就按白名单放行，与运维直觉一致）；
    UA 为空的行（脚本 / 测试）只在白名单模式下被拦，黑名单不误伤。
    """
    if is_staff:
        return None
    ua = (user_agent or "").strip().lower()
    allowed = _agent_list(db, CONFIG_ALLOWED_AGENTS)
    if allowed:
        if not ua:
            return "本站只允许指定客户端播放，请使用官方客户端"
        if not any(rule in ua for rule in allowed):
            return "当前客户端不在允许列表内，请联系管理员"
        return None
    blocked = _agent_list(db, CONFIG_BLOCKED_AGENTS)
    if blocked and ua and any(rule in ua for rule in blocked):
        return "当前客户端已被停用（版本过旧或不受支持），请升级后再试"
    return None


def ensure_client_allowed(db: Session, user, user_agent: Optional[str]) -> None:
    """播放入口统一调用：被策略拦下的客户端直接 403，并说清原因"""
    reason = client_denied_reason(db, user_agent, is_staff=bool(getattr(user, "is_staff", False)))
    if reason:
        raise HTTPException(status_code=403, detail=reason)


def ensure_transcode_allowed(db: Session, user, *, running: int, capacity: int) -> None:
    """建立转码会话前校验：关掉转码 / 并发已满都直接拒绝

    与 ``streaming.enforce_transcode_capacity`` 的分工：那里只回收**闲置**会话、宁可短暂
    超限也不打断正在看的人；这里的上限是运营**明确设定**的（``playback_max_concurrent_transcodes``），
    超了就该让新请求排队或降级直连，而不是把整台机器的 CPU 打满、所有人都卡。
    """
    if getattr(user, "is_staff", False):
        return
    if not transcode_enabled(db):
        raise HTTPException(status_code=403, detail="本站已关闭服务端转码，请使用直连播放")
    limit = max_transcodes(db)
    if limit and running >= limit:
        raise HTTPException(
            status_code=503,
            detail=f"当前转码路数已达上限（{running}/{limit}），请稍后再试或使用直连播放",
        )


def clamp_bitrate_kbps(db: Session, requested_kbps: int) -> int:
    """把客户端请求的码率压到上限内（0 表示不限）"""
    limit = max_bitrate_kbps(db)
    if not limit:
        return requested_kbps
    return min(requested_kbps, limit) if requested_kbps else limit


def policy_payload(db: Session) -> dict:
    """当前策略（面板读一份，前端不维护默认值）"""
    return {
        "transcode_enabled": transcode_enabled(db),
        "max_concurrent_transcodes": max_transcodes(db),
        "max_bitrate_kbps": max_bitrate_kbps(db),
        "blocked_agents": _raw(db, CONFIG_BLOCKED_AGENTS) or "",
        "allowed_agents": _raw(db, CONFIG_ALLOWED_AGENTS) or "",
    }


def write_policy(db: Session, values: dict) -> dict:
    """写回策略（只认白名单里的键；非法值保持原值不动）"""
    applied: dict = {}
    for key, value in (values or {}).items():
        if key not in POLICY_KEYS:
            continue
        if POLICY_KEYS[key] == "int":
            try:
                number = int(float(str(value).strip() or "0"))
            except (TypeError, ValueError):
                continue
            text = str(max(0, number))
        elif POLICY_KEYS[key] == "bool":
            text = "true" if str(value).strip().lower() in ("true", "1", "yes", "on") else "false"
        else:
            text = str(value or "").strip()[:500]
        row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if row:
            row.value = text
        else:
            db.add(models.SystemConfig(key=key, value=text))
        applied[key] = text
    return applied
