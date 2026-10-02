"""管理后台 · 播放与客户端策略（v2.26.0）

策略本身与判定都在 ``backend/playback_policy.py``（EM 与 EA 共用同一个库，所以面板上
改完，出流的 EA 立刻按新策略放行/拒绝）。这一组端点只做两件事：

- ``GET  /api/admin/playback/policy``：当前策略 + **运行态**（本进程正在转码几路、
  上限多少、由谁出流）——运营改「并发上限」之前得先知道现在跑到什么程度；
- ``PUT  /api/admin/playback/policy``：写回策略（仅超级管理员，前缀规则见 admin_roles）。

播放线路可观测（Phase 3）：

- ``GET  /api/admin/playback/lines``：direct / cdn / cache / relay 四条线路各一张卡片：
  能不能用（配置就绪）、是不是在降级（配置缺口 + 本进程降级原因）、有多少人 / 多少
  流量在这条线上（用户分布 + 本进程计数）、效果如何（缓存命中率 / CDN 缓存口径）。
  **纯只读**：不在这里改线路配置；灰度发布 / 影子流量本期不做。

CDN 域名预留（播放三层第 2/3 层极简预留版）：

- ``GET  /api/admin/playback/cdn``：当前域名/开关/归一化结果/分片缓存头口径；
- ``PUT  /api/admin/playback/cdn``：写回域名与启用开关（仅超级管理员）。
  只做域名预留：不做备案、不做厂商对接；CDN 侧的回源与缓存规则由管理员
  在厂商控制台配置，本服务只保证「启用后播放 URL 走该域名」。

VPS 本地缓存（播放线路「本地缓存」）：

- ``GET  /api/admin/playback/local-cache``：配置 + 占用/命中率统计 + 条目列表；
- ``PUT  /api/admin/playback/local-cache``：写回开关/目录/配额/热门规则/限速；
- ``POST /api/admin/playback/local-cache/clean``：手动清理（ready / failed / all）。
  写端点一律仅超级管理员，并写审计日志。

运行态只反映**本进程**：一体化部署时它就是全部；分离部署时转码跑在 EA 上，
面板这边会显示 ``playback_node=ea``，并提示去「服务器与线路」看节点状态——
不谎报一个自己看不到的数字。
"""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend import playback_policy
from backend.api.admin_core import _audit, get_current_admin
from backend.database import get_db
from backend.ratelimit import get_client_ip
from backend.emby_server import cdn, line_health, local_cache, mount_health
from backend.emby_server.streaming import (
    active_transcode_ids,
    transcode_capacity,
    transcode_idle_seconds,
)

router = APIRouter(prefix="/api/admin/playback", tags=["管理后台·播放与客户端策略"])


def _runtime(db: Session) -> dict:
    """本进程的转码运行态（不谎报自己看不到的东西）"""
    active = active_transcode_ids()
    try:
        node = mount_health.playback_node(db, None)
    except Exception:  # noqa: BLE001 — 出流方式读不到不影响策略页
        node = "panel"
    return {
        "active_transcodes": len(active),
        "capacity": transcode_capacity(),
        "idle_timeout_seconds": int(transcode_idle_seconds()),
        "playback_node": node,
        "ffmpeg_available": bool(shutil.which(os.getenv("EMBY_FFMPEG_PATH", "ffmpeg"))),
        "max_transcodes_env": (os.getenv("EMBY_MAX_TRANSCODES") or "").strip(),
    }


@router.get("/lines")
def get_play_lines(
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """四条播放线路各一张可观测卡片（健康 / 降级 / 流量 / 效果）

    只读端点：面板不提供「在这里改线路」的能力——线路是用户侧偏好，
    改配置在 CDN / 本地缓存那两个卡片里，不在可观测卡片里。
    """
    return line_health.snapshot(db)


@router.get("/policy")
def get_playback_policy(
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return {
        "policy": playback_policy.policy_payload(db),
        "keys": dict(playback_policy.POLICY_KEYS),
        "runtime": _runtime(db),
    }


class PlaybackPolicyRequest(BaseModel):
    policy: dict


@router.put("/policy")
def update_playback_policy(
    payload: PlaybackPolicyRequest,
    request: Request,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """写回策略（只认白名单里的键，非法值保持原值不动）"""
    applied = playback_policy.write_policy(db, payload.policy)
    _audit(db, current_admin, "playback_policy_update", "system", None,
           {"applied": applied}, ip=_client_ip(request))
    db.commit()
    return {"success": True, "applied": applied, "policy": playback_policy.policy_payload(db)}


def _client_ip(request: Request) -> str:
    # 统一用防伪造的 IP 获取（可信代理校验），保留函数名做兼容
    return get_client_ip(request)


# ==================== CDN 域名预留（播放三层第 2/3 层） ====================

@router.get("/cdn")
def get_cdn_config(
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """当前 CDN 预留配置（域名/开关/归一化结果/分片缓存头口径）"""
    return {"success": True, "cdn": cdn.config_payload(db),
            "play_lines": list(cdn.play_lines())}


class CdnConfigRequest(BaseModel):
    domain: str = ""
    enabled: bool = False


@router.put("/cdn")
def update_cdn_config(
    payload: CdnConfigRequest,
    request: Request,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """写回 CDN 预留配置；域名非法时 400 并说清怎么改（不会存半个坏配置）"""
    try:
        state = cdn.write_config(db, payload.domain, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, current_admin, "playback_cdn_update", "system", None,
           {"domain": state.get("domain"), "enabled": state.get("enabled")},
           ip=_client_ip(request))
    db.commit()
    return {"success": True, "cdn": state}


# ==================== VPS 本地缓存（播放线路「本地缓存」） ====================

@router.get("/local-cache")
def get_local_cache(
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    """本地缓存配置 + 占用/命中率 + 条目列表（只读，运营与只读角色也能看）"""
    return {
        "success": True,
        "local_cache": local_cache.config_payload(db),
        "stats": local_cache.stats(db),
        "entries": local_cache.entry_list(db, limit=max(1, min(500, int(limit or 100)))),
        "play_lines": list(cdn.play_lines()),
    }


class LocalCacheConfigRequest(BaseModel):
    enabled: bool = False
    dir: str = ""
    max_gb: int = local_cache.DEFAULT_MAX_GB
    hot_days: int = local_cache.DEFAULT_HOT_DAYS
    hot_plays: int = local_cache.DEFAULT_HOT_PLAYS
    rate_mbps: int = local_cache.DEFAULT_RATE_MBPS


@router.put("/local-cache")
def update_local_cache(
    payload: LocalCacheConfigRequest,
    request: Request,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """写回本地缓存配置；参数非法时 400 并说清怎么改（不会存半个坏配置）"""
    try:
        state = local_cache.write_config(
            db,
            enabled=payload.enabled,
            dir=payload.dir,
            max_gb_value=payload.max_gb,
            hot_days_value=payload.hot_days,
            hot_plays_value=payload.hot_plays,
            rate_mbps_value=payload.rate_mbps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, current_admin, "playback_local_cache_update", "system", None,
           {k: state.get(k) for k in ("enabled", "dir", "max_gb", "hot_days",
                                      "hot_plays", "rate_mbps")},
           ip=_client_ip(request))
    db.commit()
    return {"success": True, "local_cache": state, "stats": local_cache.stats(db)}


class LocalCacheCleanRequest(BaseModel):
    # ready = 清本机副本；failed = 清失败记录；all = ready + failed + pending
    mode: str = "ready"


@router.post("/local-cache/clean")
def clean_local_cache(
    payload: LocalCacheCleanRequest,
    request: Request,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """手动清理（只超级管理员）；清理后顺手把命中率统计清零，重新观察水位"""
    try:
        counts = local_cache.clean(db, payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    local_cache.reset_stats(db)
    _audit(db, current_admin, "playback_local_cache_clean", "system", None,
           counts, ip=_client_ip(request))
    db.commit()
    return {"success": True, "cleaned": counts, "stats": local_cache.stats(db)}
