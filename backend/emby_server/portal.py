"""用户/管理门户 API：自建 Emby 集成端点

用户端（/api/user/emby/...）：
- 账号卡（服务器地址/用户名/密码/一键导入 scheme）
- 续看列表、继续播放、收藏
- 统计（观看时长/次数/最近观看）

管理端（/api/admin/emby/...）：
- 媒体库 CRUD + 扫描
- 条目搜索/删除
- 在线会话监控/强制下线
- 概览统计
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, realms
from backend.database import get_db, SessionLocal
from backend.emby_server import models as em
from backend.emby_server import nodes as node_lib
from backend.emby_server.api import TICKS, SERVER_ID
from backend.emby_server.auth import (
    ensure_emby_credentials,
    get_admin_or_emby_user,
)
from backend.emby_server.scanner import (
    PLATFORM_LABELS,
    LibrarySnapshot,
    ScanInProgress,
    count_virtual_items,
    is_scan_active,
    normalize_scrape_policy,
    scan_library_sync,
)
from backend.emby_server.streaming import stop_all_transcodes, stop_transcode
from backend.emby_server import mount_health
from backend.emby_server import mount_rclone
from backend.emby_server import mounts as mount_lib
from backend.emby_server import transfer115

logger = logging.getLogger(__name__)


def _config_value(db: Session | None, key: str, realm_id: int | None = None) -> str:
    """读取 SystemConfig 原始值（不做大小写转换——URL 路径区分大小写）

    Emby 入口那几个键是**一个服一个**的（默认服沿用历史键名），见 ``backend/realms.py``。
    """
    if db is None:
        return ""
    try:
        if key in realms.REALM_CONFIG_BASES:
            return realms.realm_config(db, key, realm_id)
        row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    except Exception:  # noqa: BLE001 — 读配置失败不应影响接口返回
        return ""
    return ((row.value if row else "") or "").strip()


def emby_active_mode(db: Session | None, realm_id: int | None = None) -> str:
    """某个服生效的 Emby 服务入口模式：managed_ea（自建/单进程）或 external（已有 Emby 服）"""
    return (_config_value(db, "emby_active_mode", realm_id) or "managed_ea").lower()


def configured_emby_url(db: Session | None = None, realm_id: int | None = None) -> str:
    """只返回该服「Emby 服务入口」里配置的地址（未配置返回空串）

    1. 已有 Emby 服（external）→ emby_external_url
    2. 分离部署 EA（managed_ea 且已填地址）→ emby_managed_url
    另外修复了旧实现把配置值整体 `.lower()` 的问题：URL 路径区分大小写，
    之前保存 `https://Host/Media` 会被降成 `https://host/media`。
    db 传 None 时自建一个短连接，便于非请求上下文（如 EM 的客户端指引）复用。
    """
    own_session = db is None
    if own_session:
        try:
            db = SessionLocal()

        except Exception:  # noqa: BLE001
            db = None
    try:
        if emby_active_mode(db, realm_id) == "external":
            return _config_value(db, "emby_external_url", realm_id).rstrip("/")
        return _config_value(db, "emby_managed_url", realm_id).rstrip("/")
    finally:
        if own_session and db is not None:
            db.close()


def resolve_emby_base_url(db: Session | None = None, realm_id: int | None = None) -> str:
    """解析「用户应该连接的 Emby 服务器地址」（某个服的）

    必须与后台「Emby 服务入口」保存的配置一致，否则会出现“后台填了 EA 地址、
    用户个人中心却仍显示旧的环境变量地址”这种配置不生效的问题。
    优先级：服自己填的对外地址 → 该服的服务入口配置 → 环境变量 EMBY_PUBLIC_URL。
    """
    if realm_id is not None and db is not None:
        realm = realms.get_realm(db, realm_id)
        if realm and (realm.url or "").strip():
            return realm.url.strip().rstrip("/")
    url = configured_emby_url(db, realm_id)
    if url:
        return url
    if realm_id is not None and db is not None and realm_id != realms.legacy_realm_id(db):
        # 非默认服还没配自己的地址：不能回退到默认服的地址（那会把用户导到别的服）
        return ""
    return os.getenv("EMBY_PUBLIC_URL", "").rstrip("/") or "http://localhost:8000"


def _is_account_card_request(request: Request | None) -> bool:
    """是否为只读的账号卡请求（仅用户端 GET /api/user/emby/server）"""
    path = (getattr(getattr(request, "url", None), "path", "") or "").rstrip("/")
    return path.endswith("/api/user/emby/server")


def ensure_emby_backend_available(request: Request, db: Session = Depends(get_db)) -> None:
    """自建 Emby 的统一闸门。

    不配置服务地址时代表单进程模式，继续使用 EM 内置网关；配置了分离 EA
    后则必须通过面板的连接测试。切到“已有 Emby”时，本项目自建媒体库/扫描
    功能明确停用，避免用户误以为它能管理另一台服务器。
    """
    realm_id = realms.active_realm_id(db)

    def config(key: str, default: str = "") -> str:
        if key in realms.REALM_CONFIG_BASES:
            return realms.realm_config(db, key, realm_id, default).strip().lower()
        row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        return (row.value if row and row.value is not None else default).strip().lower()

    mode = config("emby_active_mode", "managed_ea")
    if mode == "external":
        # 账号卡只是只读信息（告诉用户该连哪台服务器、账号归谁管），
        # 外部模式也必须能返回，否则用户在个人中心既看不到地址也不知道找谁开号
        if _is_account_card_request(request):
            return
        raise HTTPException(status_code=503, detail="当前已接入已有 Emby 服，本项目自建媒体库功能已停用")

    managed_url = config("emby_managed_url")
    if managed_url and (config("emby_managed_enabled") != "true" or config("emby_managed_reachable") != "true"):
        raise HTTPException(status_code=503, detail="分离部署的 EA 尚未连接成功，请先部署 EA 并在“Emby 服务入口”测试连接")


def require_staff(
    user: models.WebUser = Depends(get_admin_or_emby_user),
    _: None = Depends(ensure_emby_backend_available),
) -> models.WebUser:
    """管理端鉴权：仅 is_staff 用户可访问（/api/admin/emby/* 全部端点）"""
    if not user.is_staff:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


user_emby_router = APIRouter(
    prefix="/api/user/emby",
    tags=["用户端-自建Emby"],
    dependencies=[Depends(ensure_emby_backend_available)],
)
admin_emby_router = APIRouter(prefix="/api/admin/emby", tags=["管理后台-自建Emby"], dependencies=[Depends(require_staff)])


# ==================== 用户端 ====================

def _account_card(user: models.WebUser, db: Session, realm_id: int | None = None) -> dict:
    """构造账号卡（不含密码明文；导入 scheme 需用户已在播放器中保存密码）

    服务器地址来自该服的「Emby 服务入口」配置（见 ``resolve_emby_base_url``），
    接入已有 Emby 服时不再提供本项目的一键导入 scheme——那台服务器上的账号
    由对方管理，本项目的用户名/密码对它无效。

    多服部署下同一个用户可能在多个服都有订阅，所以账号卡会带上 **每个服的地址与订阅**
    （``realms``），让客户端知道该连哪一台；顶层字段保持默认服的口径不变。
    """
    if realm_id is None:
        realm_id = realms.active_realm_id(db)
    url = resolve_emby_base_url(db, realm_id)
    mode = emby_active_mode(db, realm_id)
    external = mode == "external"
    host = url.split("//")[-1]
    realm = realms.get_realm(db, realm_id)
    card = {
        "server_id": SERVER_ID,
        "server_name": os.getenv("EMBY_SERVER_NAME", "RoyalBot Media Server"),
        "base_url": url,
        "mode": mode,
        "external": external,
        "account_managed_by": "external" if external else "portal",
        "emby_username": user.emby_username,
        "emby_password": None,
        "has_password": bool(user.emby_password),
        "realm_id": realm.id if realm else None,
        "realm_name": realm.name if realm else "",
        "import_schemes": {} if external else {
            "forward": f"forward://import?type=emby&scheme={os.getenv('EMBY_URL_SCHEME', 'http')}&host={host}&username={user.emby_username}",
            "senplayer": f"senplayer://importserver?type=emby&name=RoyalBot&address={url}&username={user.emby_username}",
        },
    }
    card["realms"] = _user_realm_cards(user, db)
    return card


def _user_realm_cards(user: models.WebUser, db: Session) -> list[dict]:
    """用户在各服的地址与订阅状态（多服时前端按卡片列出）"""
    now = datetime.now()
    subs = (db.query(models.UserSubscription)
            .filter(models.UserSubscription.user_id == user.id,
                    models.UserSubscription.status == "active",
                    models.UserSubscription.end_date > now)
            .order_by(models.UserSubscription.end_date.desc())
            .all())
    by_realm: dict[int, models.UserSubscription] = {}
    for sub in subs:
        if sub.realm_id and sub.realm_id not in by_realm:
            by_realm[sub.realm_id] = sub
    cards: list[dict] = []
    for realm in realms.list_realms(db, include_disabled=False):
        sub = by_realm.get(realm.id)
        if sub is None and realm.id != realms.legacy_realm_id(db):
            continue  # 没订阅的服不往用户面前推（默认服保留，兼容老前端）
        mode = emby_active_mode(db, realm.id)
        cards.append({
            "id": realm.id,
            "name": realm.name,
            "slug": realm.slug,
            "base_url": resolve_emby_base_url(db, realm.id),
            "mode": mode,
            "external": mode == "external",
            "subscribed": sub is not None,
            "end_date": sub.end_date.isoformat() if sub and sub.end_date else None,
            "plan_name": (sub.plan.name if sub and sub.plan else ""),
            "is_default": realm.id == realms.legacy_realm_id(db),
        })
    return cards


@user_emby_router.get("/server")
async def get_server_info(request: Request,
                          request_user: models.WebUser = Depends(get_admin_or_emby_user),
                          db: Session = Depends(get_db)):
    """返回账号卡信息：服务器地址 + 自建 Emby 用户名 + 播放器导入 scheme

    ``?realm_id=`` 可以指定要哪个服的地址（多服部署下同一个用户可能持有几个服的会员），
    不传则用面板当前服。

    安全：不返回密码明文。密码仅注册/重置时一次性返回。
    """
    user = request_user
    ensure_emby_credentials(db, user)
    realm_id = None
    raw = request.query_params.get("realm_id")
    if raw and str(raw).strip().isdigit():
        realm_id = int(raw)
    return _account_card(user, db, realm_id)


class SetPasswordRequest(BaseModel):
    password: str


@user_emby_router.post("/password")
async def set_emby_password(
    req: SetPasswordRequest,
    request_user: models.WebUser = Depends(get_admin_or_emby_user),
    db: Session = Depends(get_db),
):
    """设置/修改自建 Emby 播放密码（bcrypt 哈希存储）"""
    if not (3 <= len(req.password) <= 64):
        raise HTTPException(status_code=400, detail="密码长度需为 3-64 位")
    ensure_emby_credentials(db, request_user, password=req.password)
    return {"success": True, "emby_username": request_user.emby_username}


@user_emby_router.get("/resume")
async def get_resume_list(request_user: models.WebUser = Depends(get_admin_or_emby_user),
                          db: Session = Depends(get_db),
                          limit: int = 12):
    rows = (
        db.query(em.UserMediaData, em.MediaItem)
        .join(em.MediaItem, em.MediaItem.id == em.UserMediaData.item_id)
        .filter(
            em.UserMediaData.user_id == request_user.id,
            em.UserMediaData.playback_position_ticks > 0,
            em.UserMediaData.played == False,  # noqa: E712
        )
        .order_by(em.UserMediaData.last_played_at.desc())
        .limit(limit)
        .all()
    )
    items = []
    for umd, item in rows:
        items.append({
            "id": item.guid,
            "name": item.name,
            "type": item.item_type,
            "year": item.production_year,
            "position_ticks": umd.playback_position_ticks,
            "duration_ticks": item.duration_ticks,
            "progress": round((umd.playback_position_ticks or 0) / (item.duration_ticks or 1) * 100, 1),
            "poster_url": f"/emby/Items/{item.guid}/Images/Primary" if (item.poster_path or item.primary_image_url) else None,
        })
    return {"items": items}


@user_emby_router.get("/favorites")
async def get_favorite_list(request_user: models.WebUser = Depends(get_admin_or_emby_user),
                            db: Session = Depends(get_db)):
    rows = (
        db.query(em.MediaItem)
        .join(em.UserMediaData, em.UserMediaData.item_id == em.MediaItem.id)
        .filter(em.UserMediaData.user_id == request_user.id,
                em.UserMediaData.is_favorite == True)  # noqa: E712
        .order_by(em.UserMediaData.updated_at.desc())
        .all()
    )
    return {"items": [
        {"id": i.guid, "name": i.name, "type": i.item_type, "year": i.production_year,
         "rating": i.community_rating,
         "poster_url": f"/emby/Items/{i.guid}/Images/Primary" if (i.poster_path or i.primary_image_url) else None}
        for i in rows
    ]}


@user_emby_router.post("/favorites/{item_id}")
async def toggle_favorite(item_id: str, request_user: models.WebUser = Depends(get_admin_or_emby_user),
                          db: Session = Depends(get_db)):
    item = db.query(em.MediaItem).filter(em.MediaItem.guid == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    umd = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == request_user.id, em.UserMediaData.item_id == item.id
    ).first()
    if not umd:
        umd = em.UserMediaData(user_id=request_user.id, item_id=item.id)
        db.add(umd)
    umd.is_favorite = not umd.is_favorite
    db.commit()
    return {"success": True, "is_favorite": umd.is_favorite}


@user_emby_router.get("/stats")
async def get_watch_stats(request_user: models.WebUser = Depends(get_admin_or_emby_user),
                          db: Session = Depends(get_db)):
    """观看统计：总时长/次数/最近观看"""
    total_rows = db.query(
        func.count(em.UserMediaData.id),
        func.coalesce(func.sum(em.UserMediaData.play_count), 0),
    ).filter(em.UserMediaData.user_id == request_user.id).first()

    sessions = (
        db.query(em.PlaybackSession, em.MediaItem)
        .join(em.MediaItem, em.MediaItem.id == em.PlaybackSession.item_id)
        .filter(em.PlaybackSession.user_id == request_user.id)
        .order_by(em.PlaybackSession.last_update_at.desc())
        .limit(20)
        .all()
    )
    total_seconds = 0
    for session, _item in sessions:
        runtime = _item.duration_ticks or 0
        pos = session.position_ticks or 0
        total_seconds += min(pos, runtime) // TICKS if runtime else pos // TICKS

    recent = [
        {
            "item": _item.name, "type": _item.item_type,
            "device": session.device_name, "client": session.client_name,
            "position_ticks": session.position_ticks,
            "duration_ticks": _item.duration_ticks,
            "at": session.last_update_at.isoformat() if session.last_update_at else None,
        }
        for session, _item in sessions[:10]
    ]
    return {
        "total_plays": int(total_rows[1] or 0),
        "watched_items": int(total_rows[0] or 0),
        "total_seconds": total_seconds,
        "recent": recent,
    }


@user_emby_router.get("/sessions")
async def get_my_sessions(request_user: models.WebUser = Depends(get_admin_or_emby_user),
                          db: Session = Depends(get_db)):
    """我的正在播放会话（设备 / 客户端 / 进度），与管理员会话监控同源"""
    rows = (
        db.query(em.PlaybackSession, em.MediaItem)
        .join(em.MediaItem, em.MediaItem.id == em.PlaybackSession.item_id)
        .filter(
            em.PlaybackSession.user_id == request_user.id,
            em.PlaybackSession.ended_at.is_(None),
        )
        .order_by(em.PlaybackSession.last_update_at.desc())
        .all()
    )
    return {
        "sessions": [
            {
                "session_key": s.session_key,
                "item_id": i.guid,
                "item": i.name,
                "item_type": i.item_type,
                "device": s.device_name,
                "client": s.client_name,
                "remote_addr": s.remote_addr,
                "play_method": s.play_method,
                "is_paused": bool(s.is_paused),
                "position_ticks": s.position_ticks,
                "duration_ticks": i.duration_ticks,
                "progress": round((s.position_ticks or 0) / (i.duration_ticks or 1) * 100, 1),
                "started_at": s.start_time.isoformat() if s.start_time else None,
                "updated_at": s.last_update_at.isoformat() if s.last_update_at else None,
            }
            for s, i in rows
        ]
    }


@user_emby_router.delete("/sessions/{session_key}")
async def stop_my_session(session_key: str,
                          request_user: models.WebUser = Depends(get_admin_or_emby_user),
                          db: Session = Depends(get_db)):
    """结束自己的播放会话（同时释放转码进程）"""
    session = (
        db.query(em.PlaybackSession)
        .filter(
            em.PlaybackSession.session_key == session_key,
            em.PlaybackSession.user_id == request_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="播放会话不存在")
    session.ended_at = datetime.now()
    db.commit()
    stop_transcode(session_key)
    return {"success": True}


@user_emby_router.get("/history")
async def get_watch_history(request_user: models.WebUser = Depends(get_admin_or_emby_user),
                           db: Session = Depends(get_db),
                           limit: int = 30,
                           offset: int = 0,
                           item_type: str = ""):
    """观看历史：按条目去重，取最近一次播放的设备/客户端/进度

    直接读本地会话与用户媒体数据（不触发媒体库扫描），与第三方客户端记录同源。
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    query = (
        db.query(em.PlaybackSession, em.MediaItem)
        .join(em.MediaItem, em.MediaItem.id == em.PlaybackSession.item_id)
        .filter(em.PlaybackSession.user_id == request_user.id)
    )
    if item_type:
        query = query.filter(em.MediaItem.item_type == item_type)

    total = query.count()
    rows = query.order_by(em.PlaybackSession.last_update_at.desc()).all()

    # 按条目去重（保留最近一次会话），再按 offset/limit 切片
    seen: set[int] = set()
    deduped: list[tuple] = []
    for session, item in rows:
        if item.id in seen:
            continue
        seen.add(item.id)
        deduped.append((session, item))
    page = deduped[offset:offset + limit]

    item_ids = [item.id for _s, item in page]
    umd_map: dict[int, em.UserMediaData] = {}
    if item_ids:
        for umd in db.query(em.UserMediaData).filter(
            em.UserMediaData.user_id == request_user.id,
            em.UserMediaData.item_id.in_(item_ids),
        ).all():
            umd_map[umd.item_id] = umd

    items = []
    for session, item in page:
        umd = umd_map.get(item.id)
        items.append({
            "id": item.guid,
            "name": item.name,
            "type": item.item_type,
            "year": item.production_year,
            "poster_url": f"/emby/Items/{item.guid}/Images/Primary"
            if (item.poster_path or item.primary_image_url) else None,
            "duration_ticks": item.duration_ticks,
            "position_ticks": (umd.playback_position_ticks if umd else session.position_ticks),
            "played": bool(umd.played) if umd else False,
            "is_favorite": bool(umd.is_favorite) if umd else False,
            "play_count": int(umd.play_count or 0) if umd else 0,
            "device": session.device_name,
            "client": session.client_name,
            "play_method": session.play_method,
            "watched_at": session.last_update_at.isoformat() if session.last_update_at else None,
        })

    return {"total": total, "unique_total": len(deduped), "items": items}


# ==================== 管理端 ====================

class LibraryCreate(BaseModel):
    name: str
    collection_type: str = "movies"
    # 内容来源：本机目录（可多个）与存储挂载（storage_mounts.id）至少给一个
    paths: list[str] = []
    mount_ids: list[int] = []
    is_enabled: bool = True
    # 刮削策略：missing_only（只补缺，默认）/ 3m / 6m / 1y / all（每次全量重刮）
    scrape_policy: str = "missing_only"
    # 绑定 115 账号配置档（不同媒体库可用不同账号转存/下载）
    account_115_id: int | None = None
    # 归属：服（多服运营）与播放节点（多机同时出流）；留空 = 当前服 / 未分配节点
    realm_id: int | None = None
    node_id: int | None = None


class LibraryUpdate(BaseModel):
    name: str | None = None
    collection_type: str | None = None
    paths: list[str] | None = None
    mount_ids: list[int] | None = None
    is_enabled: bool | None = None
    scrape_policy: str | None = None
    account_115_id: int | None = None
    # 归属：服（多服运营）与播放节点（多机同时出流）。显式传 null 表示「不分配」
    realm_id: int | None = None
    node_id: int | None = None


def _validate_library_sources(db: Session, paths: list[str], mount_ids: list[int]) -> None:
    """校验媒体库来源：本机路径必须存在，挂载必须存在且启用"""
    for path in paths:
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"路径不存在: {path}")
    if not mount_ids:
        return
    found = {
        m.id: m for m in db.query(em.StorageMount).filter(em.StorageMount.id.in_(mount_ids)).all()
    }
    for mount_id in mount_ids:
        mount = found.get(mount_id)
        if mount is None:
            raise HTTPException(status_code=400, detail=f"挂载不存在: #{mount_id}")
        if not mount.is_enabled:
            raise HTTPException(status_code=400, detail=f"挂载「{mount.name}」已停用")


def _mount_ids_field(db: Session, mount_ids: list[int]) -> str:
    return ",".join(str(i) for i in dict.fromkeys(mount_ids))


class VirtualLibraryRequest(BaseModel):
    """按发行平台生成虚拟媒体库

    - platforms 省略 = 按库里**实际出现过的**平台标签逐个生成
    - enabled 控制生成后是否对客户端可见（关闭时客户端与直达接口都看不到）
    - source_library_id 省略 = 跨全部媒体库聚合
    """
    platforms: list[str] | None = None
    enabled: bool = True
    source_library_id: int | None = None
    prune: bool = False  # 清理不再有内容的虚拟库


@admin_emby_router.get("/overview")
async def admin_overview(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
                         realm_id: int | None = None):
    """媒体库概览：默认只统计当前服（“全部服”传 realm_id=0）"""
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    # 内容按「NULL = 所有服」处理（见 realms.scope_inclusive）：未标注服的老库不会被藏起来
    lib_query = realms.scope_inclusive(db.query(em.Library), em.Library.realm_id, scope_id)
    total_libraries = lib_query.count()
    lib_ids = [row[0] for row in realms.scope_inclusive(
        db.query(em.Library.id), em.Library.realm_id, scope_id).all()]
    total_items = (db.query(em.MediaItem).filter(em.MediaItem.library_id.in_(lib_ids)).count()
                   if lib_ids else 0)
    active_sessions = (
        db.query(em.PlaybackSession).filter(em.PlaybackSession.ended_at.is_(None)).count()
    )
    total_users = db.query(models.WebUser).count()
    realm = realms.get_realm(db, scope_id) if scope_id else None
    return {
        "total_items": total_items,
        "total_libraries": total_libraries,
        "active_sessions": active_sessions,
        "total_users": total_users,
        "server_id": SERVER_ID,
        "realm_id": scope_id,
        "realm_name": realm.name if realm else "全部服",
    }


@admin_emby_router.get("/libraries")
async def list_libraries(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
                         realm_id: int | None = None):
    """媒体库清单（按服；realm_id=0 表示全部服）"""
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope_inclusive(db.query(em.Library), em.Library.realm_id, scope_id)
    libs = query.order_by(em.Library.id).all()
    nodes = {n.id: n for n in db.query(models.RemoteServer)
             .filter(models.RemoteServer.kind == "ea").all()}
    realm_names = {r.id: r.name for r in realms.list_realms(db)}
    return {"libraries": [
        {
            "id": lib.id, "guid": lib.guid, "name": lib.name,
            "collection_type": lib.collection_type,
            "paths": [p for p in (lib.paths or "").split(",") if p],
            "mount_ids": mount_lib.parse_mount_ids(lib),
            "is_enabled": lib.is_enabled,
            # 正在扫描以进程内任务为准：数据库标志在进程崩溃后会残留为真
            "is_scanning": is_scan_active(lib.id) or lib.is_scanning,
            "scrape_policy": normalize_scrape_policy(lib.scrape_policy),
            "is_virtual": bool(getattr(lib, "is_virtual", False)),
            "platform": lib.platform,
            "account_115_id": getattr(lib, "account_115_id", None),
            "last_scan_at": lib.last_scan_at.isoformat() if lib.last_scan_at else None,
            "item_count": lib.item_count,
            # 服与播放节点：多服 / 多机部署下“这个库归谁”必须一眼可见
            "realm_id": lib.realm_id,
            "realm_name": realm_names.get(lib.realm_id, "") if lib.realm_id else "",
            "node_id": lib.node_id,
            "node_name": (nodes[lib.node_id].name if lib.node_id in nodes else ""),
            "node_online": (nodes[lib.node_id].last_check_ok is True) if lib.node_id in nodes else None,
        }
        for lib in libs
    ],
        "realm_id": scope_id,
        "active_realm_id": realms.active_realm_id(db),
        "scrape_policies": [
            {"value": "missing_only", "label": "仅缺失时刮削"},
            {"value": "3m", "label": "3 个月重刮"},
            {"value": "6m", "label": "半年重刮"},
            {"value": "1y", "label": "一年重刮"},
            {"value": "all", "label": "全部重刮"},
        ]}


@admin_emby_router.post("/libraries")
async def create_library(req: LibraryCreate, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    import uuid

    if not req.paths and not req.mount_ids:
        raise HTTPException(status_code=400, detail="请至少配置一个路径或一个存储挂载")
    _validate_library_sources(db, req.paths, req.mount_ids)
    guid = uuid.uuid4().hex[:32]
    realm_id = req.realm_id or realms.active_realm_id(db)
    if not realms.get_realm(db, realm_id):
        raise HTTPException(status_code=400, detail=f"服不存在: #{realm_id}")
    node_id = req.node_id
    if node_id is not None:
        node = db.query(models.RemoteServer).filter(models.RemoteServer.id == node_id).first()
        if not node or node.kind != "ea":
            raise HTTPException(status_code=400, detail="只能把媒体库分配给一台后端服（EA）")
        if node.realm_id and node.realm_id != realm_id:
            raise HTTPException(status_code=400, detail="这台节点属于另一个服，不能分配本服的媒体库")
    lib = em.Library(
        guid=guid, name=req.name, collection_type=req.collection_type,
        paths=",".join(req.paths), mount_ids=_mount_ids_field(db, req.mount_ids),
        is_enabled=req.is_enabled,
        scrape_policy=normalize_scrape_policy(req.scrape_policy),
        account_115_id=req.account_115_id,
        realm_id=realm_id, node_id=node_id,
    )
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return {"success": True, "id": lib.id, "guid": lib.guid}


@admin_emby_router.put("/libraries/{lib_id}")
async def update_library(lib_id: int, req: LibraryUpdate, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")
    if req.name is not None:
        lib.name = req.name
    if req.collection_type is not None:
        lib.collection_type = req.collection_type
    if req.paths is not None:
        for p in req.paths:
            if not os.path.isdir(p):
                raise HTTPException(status_code=400, detail=f"路径不存在: {p}")
        lib.paths = ",".join(req.paths)
    if req.mount_ids is not None:
        _validate_library_sources(db, [], req.mount_ids)
        lib.mount_ids = _mount_ids_field(db, req.mount_ids)
    if req.is_enabled is not None:
        lib.is_enabled = req.is_enabled
    if req.scrape_policy is not None:
        lib.scrape_policy = normalize_scrape_policy(req.scrape_policy)
    if "account_115_id" in req.model_fields_set:
        # 允许显式解绑（传 null）
        lib.account_115_id = req.account_115_id
    if "realm_id" in req.model_fields_set:
        if req.realm_id is None:
            # 显式解绑：未标注服 = 所有服可见（与老数据、未分配节点的口径一致）
            lib.realm_id = None
        else:
            if not realms.get_realm(db, req.realm_id):
                raise HTTPException(status_code=400, detail=f"服不存在: #{req.realm_id}")
            # 换服时把绑定的挂载一起带过去，否则库会引用到别的服的存储
            lib.realm_id = req.realm_id
            for mount_id in mount_lib.parse_mount_ids(lib):
                mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
                if mount and mount.realm_id != req.realm_id:
                    mount.realm_id = req.realm_id
            if lib.node_id:
                node = db.query(models.RemoteServer).filter(models.RemoteServer.id == lib.node_id).first()
                if node and node.realm_id != req.realm_id:
                    lib.node_id = None  # 节点属于别的服，解绑避免跨服出流
    if "node_id" in req.model_fields_set:
        if req.node_id is None:
            lib.node_id = None
        else:
            node = db.query(models.RemoteServer).filter(models.RemoteServer.id == req.node_id).first()
            if not node or node.kind != "ea":
                raise HTTPException(status_code=400, detail="只能把媒体库分配给一台后端服（EA）")
            if node.realm_id and lib.realm_id and node.realm_id != lib.realm_id:
                raise HTTPException(status_code=400, detail="这台节点属于另一个服，不能分配本服的媒体库")
            lib.node_id = node.id
    db.commit()
    # 配置变更后需重新触发扫描才生效：扫描任务使用固定配置快照，
    # 所以旧路径不会被正在跑的任务继续扫描，新路径也不会被旧快照漏掉
    return {"success": True, "rescan_required": True}


@admin_emby_router.delete("/libraries/{lib_id}")
async def delete_library(lib_id: int, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")
    items = db.query(em.MediaItem).filter(em.MediaItem.library_id == lib.id).all()
    for it in items:
        db.query(em.MediaStream).filter(em.MediaStream.item_id == it.id).delete()
        db.query(em.UserMediaData).filter(em.UserMediaData.item_id == it.id).delete()
        db.delete(it)
    db.delete(lib)
    db.commit()
    return {"success": True}


@admin_emby_router.post("/libraries/{lib_id}/scan")
async def scan_library_endpoint(lib_id: int, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")

    # 已分配给某台节点的库，只有那台机器碰得到文件（本机路径 / rclone / 挂载）——
    # 由面板本地扫描只会得到一堆 failed_roots，所以转发过去让归属节点扫。
    owner = node_lib.library_owner(db, lib)
    if owner is not None and owner.id != node_lib.self_node_id(db):
        forward = await node_lib.push_scan(owner.url, lib.id)
        if not forward.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=f"这个库归「{owner.name}」扫描，但转发失败了：{forward.get('error')}"
                "（请检查该节点的地址与两端 SECRET_KEY）",
            )
        return {"success": True, "message": f"已让节点「{owner.name}」开始扫描",
                "forwarded_to": {"id": owner.id, "name": owner.name, "url": owner.url},
                "library_id": lib.id}

    if is_scan_active(lib.id):
        raise HTTPException(status_code=409, detail="该媒体库正在扫描中")
    import threading

    # 扫描在后台线程运行：必须用独立 Session（请求结束时请求级 Session 会被关闭，
    # 复用会导致 "transaction is closed" 与 SQLite 写锁冲突）
    lib_id_value = lib.id
    # 配置快照在**请求线程**拍下：后台任务只认这份快照，期间改配置不影响本次任务
    snapshot = LibrarySnapshot.of(lib)

    def _run_scan():
        scan_db = SessionLocal()
        try:
            scan_lib = scan_db.query(em.Library).filter(em.Library.id == lib_id_value).first()
            if scan_lib:
                scan_library_sync(scan_db, scan_lib, snapshot)
        except ScanInProgress:
            pass  # 已有任务在跑：重复请求直接被拒
        finally:
            scan_db.close()

    thread = threading.Thread(target=_run_scan, daemon=True)
    thread.start()
    return {"success": True, "message": "扫描已启动", "scrape_policy": snapshot.scrape_policy}


@admin_emby_router.post("/libraries/virtual")
async def generate_virtual_libraries(
    req: VirtualLibraryRequest,
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """按发行平台自动生成虚拟媒体库（Netflix / Disney+ / Apple TV+ …）

    虚拟媒体库没有自己的目录，它是跨库的“平台视图”：条目仍归属原媒体库，
    打开虚拟库时按 `MediaItem.platforms` 里的平台标签聚合。
    """
    requested = req.platforms
    if requested:
        unknown = [p for p in requested if p not in PLATFORM_LABELS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"未知平台: {', '.join(unknown)}")
        targets = list(dict.fromkeys(requested))
    else:
        # 库里实际出现过的平台标签
        present: set[str] = set()
        for (raw,) in db.query(em.MediaItem.platforms).all():
            present.update(p for p in (raw or "").split(",") if p)
        targets = sorted(present)

    created: list[dict] = []
    updated: list[dict] = []
    for platform in targets:
        lib = (
            db.query(em.Library)
            .filter(em.Library.is_virtual == True, em.Library.platform == platform)  # noqa: E712
            .first()
        )
        label = PLATFORM_LABELS.get(platform, platform)
        if not lib:
            import uuid

            lib = em.Library(
                guid=uuid.uuid4().hex[:32], name=label, collection_type="mixed",
                paths="", is_enabled=req.enabled, is_virtual=True, platform=platform,
                scrape_policy="missing_only",
            )
            db.add(lib)
            db.commit()
            db.refresh(lib)
            created.append({"id": lib.id, "platform": platform, "name": label})
        else:
            lib.is_enabled = req.enabled
            lib.name = lib.name or label
            db.commit()
            updated.append({"id": lib.id, "platform": platform, "name": lib.name})
        lib.item_count = count_virtual_items(db, lib)
        db.commit()

    pruned: list[dict] = []
    if req.prune:
        for lib in db.query(em.Library).filter(em.Library.is_virtual == True).all():  # noqa: E712
            if count_virtual_items(db, lib) == 0:
                pruned.append({"id": lib.id, "platform": lib.platform, "name": lib.name})
                db.delete(lib)
        db.commit()

    return {
        "success": True,
        "created": created,
        "updated": updated,
        "pruned": pruned,
        "available_platforms": [
            {"platform": p, "name": n} for p, n in sorted(PLATFORM_LABELS.items())
        ],
    }


@admin_emby_router.get("/libraries/repair/queue")
async def repair_queue(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    """待修复条目：数据库里有图片记录但取不到图（本地文件丢失 / 远程图失效）"""
    rows = (
        db.query(em.MediaItem)
        .filter(em.MediaItem.repair_requested_at.isnot(None))
        .order_by(em.MediaItem.repair_requested_at.desc())
        .limit(200)
        .all()
    )
    return {
        "total": db.query(em.MediaItem).filter(em.MediaItem.repair_requested_at.isnot(None)).count(),
        "items": [
            {"id": r.guid, "name": r.name, "type": r.item_type, "library_id": r.library_id,
             "requested_at": r.repair_requested_at.isoformat() if r.repair_requested_at else None,
             "file_exists": bool(r.file_path and os.path.isfile(r.file_path))}
            for r in rows
        ],
    }


@admin_emby_router.post("/libraries/repair/run")
async def run_repair_queue(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    """立即处理修复队列（重新刮削取图）；不传 library_ids 则处理全部启用库"""
    lib_ids = [
        lib.id for lib in db.query(em.Library).filter(em.Library.is_enabled == True).all()  # noqa: E712
        if not is_scan_active(lib.id)
    ]
    import threading

    snapshots = [
        LibrarySnapshot.of(lib)
        for lib in db.query(em.Library).filter(em.Library.id.in_(lib_ids)).all()
    ] if lib_ids else []

    def _run() -> None:
        scan_db = SessionLocal()
        try:
            for snapshot in snapshots:
                library = scan_db.query(em.Library).filter(em.Library.id == snapshot.library_id).first()
                if not library:
                    continue
                try:
                    scan_library_sync(scan_db, library, snapshot)
                except ScanInProgress:
                    continue
        finally:
            scan_db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"success": True, "libraries": [s.library_id for s in snapshots]}


@admin_emby_router.get("/items")
async def admin_search_items(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
                             search: str = "", type: str = "", limit: int = 50, offset: int = 0):
    query = db.query(em.MediaItem)
    if search:
        query = query.filter(em.MediaItem.name.ilike(f"%{search}%"))
    if type:
        query = query.filter(em.MediaItem.item_type == type)
    total = query.count()
    items = query.order_by(em.MediaItem.date_added.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [
        {"id": i.guid, "name": i.name, "type": i.item_type, "year": i.production_year,
         "library_id": i.library_id, "file_path": i.file_path, "size": i.size,
         "duration_ticks": i.duration_ticks,
         "added_at": i.date_added.isoformat() if i.date_added else None}
        for i in items
    ]}


@admin_emby_router.delete("/items/{item_id}")
async def admin_delete_item(item_id: str, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    item = db.query(em.MediaItem).filter(em.MediaItem.guid == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    db.query(em.MediaStream).filter(em.MediaStream.item_id == item.id).delete()
    db.query(em.UserMediaData).filter(em.UserMediaData.item_id == item.id).delete()
    db.delete(item)
    db.commit()
    return {"success": True}


@admin_emby_router.get("/sessions")
async def admin_sessions(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    sessions = (
        db.query(em.PlaybackSession, models.WebUser, em.MediaItem)
        .join(models.WebUser, models.WebUser.id == em.PlaybackSession.user_id)
        .join(em.MediaItem, em.MediaItem.id == em.PlaybackSession.item_id)
        .filter(em.PlaybackSession.ended_at.is_(None))
        .order_by(em.PlaybackSession.last_update_at.desc())
        .all()
    )
    return {"sessions": [
        {
            "session_key": s.session_key, "username": u.username,
            "item": i.name, "item_type": i.item_type,
            "device": s.device_name, "client": s.client_name,
            "remote_addr": s.remote_addr,
            "play_method": s.play_method,
            "position_ticks": s.position_ticks,
            "duration_ticks": i.duration_ticks,
            "is_paused": s.is_paused,
            "started_at": s.start_time.isoformat() if s.start_time else None,
        }
        for s, u, i in sessions
    ]}


@admin_emby_router.delete("/sessions/{session_key}")
async def admin_stop_session(session_key: str, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    session = db.query(em.PlaybackSession).filter(
        em.PlaybackSession.session_key == session_key
    ).first()
    if session:
        session.ended_at = datetime.now()
        db.commit()
    stop_transcode(session_key)
    return {"success": True}


@admin_emby_router.post("/transcodes/stop-all")
async def admin_stop_all_transcodes(staff: models.WebUser = Depends(require_staff)):
    count = stop_all_transcodes()
    return {"success": True, "stopped": count}


# ==================== 存储挂载 ====================
# 挂载 = 媒体库的内容来源：local / strm 是本机目录，115 / webdav / alist / s3 / aliyun /
# quark / onedrive 是远程来源（远程挂载的条目入库为 mount://<id>/<rel>，播放时由 EA 按
# Range 代理转发，凭据不下发）。
# 类型、配置字段、必填与脱敏规则都来自类型元数据：backend/emby_server/mounts.py（基础类型）
# 与 backend/emby_server/mount_cloud.py（云端类型）。

def _mask_mount_config(config: dict) -> tuple[dict, list[str]]:
    """脱敏：密钥类字段只报是否已配置，不回明文

    密钥集合由挂载类型元数据算出（见 ``mounts.secret_config_keys``），所以新增
    挂载类型时把字段标成 ``secret`` 就够了，不用动这里。
    """
    secret_keys = mount_lib.secret_config_keys()
    public: dict = {}
    secrets: list[str] = []
    for key, value in (config or {}).items():
        if key in secret_keys and value:
            secrets.append(key)
            continue
        public[key] = value
    return public, secrets


def _merge_mount_config(old: dict, new: dict) -> dict:
    """合并配置：密钥类字段留空 = 不修改（避免前端拿不到明文就被抹掉）"""
    secret_keys = mount_lib.secret_config_keys()
    merged = dict(old or {})
    for key, value in (new or {}).items():
        if key in secret_keys and value in ("", None):
            continue
        merged[key] = value
    return merged


def _validate_mount_fields(mount_type: str, path: str, config: dict) -> None:
    """按类型元数据校验：本机路径 + 必填字段 + 地址格式

    必填字段来自 ``MOUNT_TYPES[*].fields[*].required``，所以新类型的校验也是自动的。
    """
    meta = mount_lib.MOUNT_TYPE_MAP.get(mount_type)
    if meta is None:
        raise HTTPException(status_code=400, detail=f"不支持的挂载类型: {mount_type or '(空)'}")
    if meta["needs_path"]:
        if not (path or "").strip():
            raise HTTPException(status_code=400, detail="请填写目录路径")
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"目录不存在: {path}")
    for field in mount_lib.required_fields(mount_type):
        if not str(config.get(field["key"]) or "").strip():
            raise HTTPException(status_code=400, detail=f"请填写{field.get('label') or field['key']}")
    for field in mount_lib.type_meta(mount_type).get("fields", []):
        if field["key"] not in ("url", "endpoint"):
            continue
        value = str(config.get(field["key"]) or "").strip()
        if value and not value.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail=f"{field.get('label') or field['key']} 必须以 http:// 或 https:// 开头")


def _serialize_mount(db: Session, mount: em.StorageMount, ea_map: dict | None = None) -> dict:
    config, secrets = _mask_mount_config(mount_lib.parse_config(mount))
    meta = mount_lib.MOUNT_TYPE_MAP.get(mount.mount_type, {})
    kind = meta.get("kind", "local")
    path = (mount.path or "").strip()
    # EM 视角 = 后台「测试连接」的结果（跑在 EM 进程里）
    em_result = {
        "ok": mount.last_check_ok,
        "message": mount.last_check_message or "",
        "checked_at": mount.last_checked_at.isoformat() if mount.last_checked_at else None,
    }
    # EA 视角 = 保存 EA 服务入口 / 手动刷新时拉到的那份快照
    if ea_map is None:
        ea_map = mount_health.ea_mount_map(db)
    ea_item = ea_map.get(mount.id) or {}
    return {
        "id": mount.id,
        "name": mount.name,
        "realm_id": mount.realm_id,
        "mount_type": mount.mount_type,
        "mount_type_label": mount_lib.MOUNT_TYPE_LABELS.get(mount.mount_type, mount.mount_type),
        "kind": kind,
        "path": path,
        "config": config,
        "secret_keys": secrets,
        "is_enabled": bool(mount.is_enabled),
        "remark": mount.remark or "",
        "last_checked_at": mount.last_checked_at.isoformat() if mount.last_checked_at else None,
        "last_check_ok": mount.last_check_ok,
        "last_check_message": mount.last_check_message,
        # local / strm 的路径是本机相对资源（远程类型为 None）
        "path_exists": os.path.isdir(path) if kind == "local" and path else None,
        # 两个播放节点各自能不能用它（EA 缺失快照时为 None，表示「未体检」）
        "em_reachable": em_result["ok"],
        "em_message": em_result["message"],
        "em_checked_at": em_result["checked_at"],
        "ea_reachable": ea_item.get("ok"),
        "ea_message": ea_item.get("message") or "",
        "library_ids": [
            lib.id for lib in db.query(em.Library).all()
            if mount.id in mount_lib.parse_mount_ids(lib)
        ],
    }


class MountCreate(BaseModel):
    name: str
    mount_type: str
    path: str = ""
    config: dict = {}
    is_enabled: bool = True
    remark: str = ""
    # 归属哪个服（留空 = 当前服）：存储是主机相对资源，跟着服走
    realm_id: int | None = None


class MountUpdate(BaseModel):
    name: str | None = None
    path: str | None = None
    config: dict | None = None
    is_enabled: bool | None = None
    remark: str | None = None
    realm_id: int | None = None


class MountTestRequest(BaseModel):
    """测试尚未保存的配置（先测再存）"""
    mount_type: str
    path: str = ""
    config: dict = {}


class MountBrowseParams(BaseModel):
    rel: str = "/"


@admin_emby_router.get("/mounts")
async def list_mounts(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
                     realm_id: int | None = None):
    """存储挂载清单（按服；realm_id=0 表示全部服）"""
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope_inclusive(db.query(em.StorageMount), em.StorageMount.realm_id, scope_id)
    mounts = query.order_by(em.StorageMount.id).all()
    ea_map = mount_health.ea_mount_map(db, scope_id)
    snapshot = mount_health.read_ea_health(db, scope_id)
    realm_names = {r.id: r.name for r in realms.list_realms(db)}
    return {
        "mounts": [_serialize_mount(db, m, ea_map) for m in mounts],
        # 类型元数据（标签 / 说明 / 需要哪些字段）由后端下发，前端不再自己维护一份
        "mount_types": [dict(t) for t in mount_lib.MOUNT_TYPES],
        # 当前谁在出流：EA 分离部署 / 外部 Emby / 面板自己。
        # 「被媒体库引用却 EA 不可达」只有 EA 才是阻断性问题，前端据此决定要不要报红。
        "playback_node": mount_health.playback_node(db, scope_id),
        "realm_id": scope_id,
        "realm_names": realm_names,
        "ea_health": {
            "ok": bool(snapshot.get("ok")),
            "checked_at": snapshot.get("checked_at"),
            "error": snapshot.get("error") or "",
        },
    }


@admin_emby_router.post("/mounts/health")
async def check_all_mounts(staff: models.WebUser = Depends(require_staff),
                          db: Session = Depends(get_db)):
    """一键体检（EM 视角）：逐条跑与「测试连接」相同的探测并落库

    只解决「这台面板自己能不能碰到存储」；EA 那一侧要看 ``/mounts`` 响应里的
    ``ea_reachable``（由 EA 服务入口拉取）。"""
    health = await run_in_threadpool(mount_health.mounts_health, db, "panel",
                                     realms.active_realm_id(db))
    checked_at = datetime.now()
    for item in health.get("mounts", []):
        if item.get("ok") is None:
            continue  # 停用的挂载不写测试结果
        mount = db.query(em.StorageMount).filter(em.StorageMount.id == item["id"]).first()
        if not mount:
            continue
        mount.last_checked_at = checked_at
        mount.last_check_ok = bool(item.get("ok"))
        mount.last_check_message = str(item.get("message") or "")[:300]
    db.commit()
    return health


@admin_emby_router.get("/mounts/rclone/remotes")
async def list_rclone_remotes(mode: str = "rc", rc_url: str = "", rc_user: str = "",
                              rc_pass: str = "", rclone_bin: str = "",
                              rclone_config: str = "",
                              staff: models.WebUser = Depends(require_staff)):
    """列出 rclone 已配置的 remote（给 rclone 挂载的「remote」选择器用）

    即使用表单里还没保存的 RC 地址 / 密码也能查，方便先连上再看有哪些 remote。
    """
    try:
        remotes = await run_in_threadpool(
            mount_rclone.list_remotes, rc_url,
            username=rc_user, password=rc_pass,
            bin_path=rclone_bin, config=rclone_config, mode=mode,
        )
    except mount_lib.MountAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except mount_lib.MountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"remotes": remotes, "total": len(remotes)}


@admin_emby_router.post("/mounts")
async def create_mount(req: MountCreate, staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写挂载名称")
    if db.query(em.StorageMount).filter(em.StorageMount.name == name).first():
        raise HTTPException(status_code=400, detail=f"挂载名称已存在: {name}")
    config = _merge_mount_config({}, req.config)
    _validate_mount_fields(req.mount_type, req.path, config)
    realm_id = req.realm_id or realms.active_realm_id(db)
    if not realms.get_realm(db, realm_id):
        raise HTTPException(status_code=400, detail=f"服不存在: #{realm_id}")
    mount = em.StorageMount(
        name=name, mount_type=req.mount_type, path=(req.path or "").strip(),
        config=mount_lib.dump_config(config), is_enabled=req.is_enabled,
        remark=(req.remark or "")[:300], realm_id=realm_id,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)
    return {"success": True, "mount": _serialize_mount(db, mount)}


@admin_emby_router.put("/mounts/{mount_id}")
async def update_mount(mount_id: int, req: MountUpdate,
                       staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写挂载名称")
        exists = db.query(em.StorageMount).filter(
            em.StorageMount.name == name, em.StorageMount.id != mount_id,
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail=f"挂载名称已存在: {name}")
        mount.name = name
    config = _merge_mount_config(mount_lib.parse_config(mount), req.config or {})
    path = (req.path if req.path is not None else mount.path or "").strip()
    # 换类型不允许（条目路径按挂载 id + 类型解析），只允许改配置与路径
    _validate_mount_fields(mount.mount_type, path, config)
    mount.path = path
    mount.config = mount_lib.dump_config(config)
    if req.is_enabled is not None:
        mount.is_enabled = req.is_enabled
    if req.remark is not None:
        mount.remark = req.remark[:300]
    if "realm_id" in req.model_fields_set and req.realm_id is not None:
        if not realms.get_realm(db, req.realm_id):
            raise HTTPException(status_code=400, detail=f"服不存在: #{req.realm_id}")
        mount.realm_id = req.realm_id
        # 引用本挂载的媒体库跟着走，否则库会跨服引用存储
        for lib in db.query(em.Library).filter(
                em.Library.mount_ids.ilike(f"%{mount.id}%")).all():
            if str(mount.id) in [x.strip() for x in (lib.mount_ids or "").split(",") if x.strip()]:
                lib.realm_id = req.realm_id
    db.commit()
    db.refresh(mount)
    # 路径/配置变更后需要重新扫描才生效（扫描任务使用固定配置快照）
    return {"success": True, "mount": _serialize_mount(db, mount), "rescan_required": True}


@admin_emby_router.delete("/mounts/{mount_id}")
async def delete_mount(mount_id: int, staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    # 解除媒体库绑定，不留悬空引用（条目会在下一次扫描时清理）
    unbound = 0
    for lib in db.query(em.Library).all():
        ids = mount_lib.parse_mount_ids(lib)
        if mount_id in ids:
            lib.mount_ids = ",".join(str(i) for i in ids if i != mount_id)
            unbound += 1
    db.delete(mount)
    db.commit()
    return {"success": True, "unbound_libraries": unbound}


@admin_emby_router.post("/mounts/{mount_id}/test")
async def test_saved_mount(mount_id: int, staff: models.WebUser = Depends(require_staff),
                           db: Session = Depends(get_db)):
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    result = await run_in_threadpool(mount_lib.test_mount, mount, db)
    # 测试结果只作展示，不影响扫描（扫描自己会报错）
    mount.last_checked_at = datetime.now()
    mount.last_check_ok = bool(result.get("ok"))
    mount.last_check_message = str(result.get("message") or "")[:300]
    db.commit()
    db.refresh(mount)
    return {"success": bool(result.get("ok")), "result": result,
            "mount": _serialize_mount(db, mount)}


@admin_emby_router.post("/mounts/test")
async def test_unsaved_mount(req: MountTestRequest,
                             staff: models.WebUser = Depends(require_staff)):
    """测试表单里还没保存的配置（Cookie / 令牌不用先存再测）"""
    probe = em.StorageMount(
        name="(未保存)", mount_type=req.mount_type, path=(req.path or "").strip(),
        config=mount_lib.dump_config(_merge_mount_config({}, req.config)), is_enabled=True,
    )
    result = await run_in_threadpool(mount_lib.test_mount, probe, None)
    return {"success": bool(result.get("ok")), "result": result}


@admin_emby_router.get("/mounts/{mount_id}/browse")
async def browse_mount(mount_id: int, rel: str = "/",
                       staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    """浏览挂载目录（给「目标目录 / 目录 ID」选择器用）"""
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    try:
        provider = mount_lib.build_provider(mount, db)
        entries = await run_in_threadpool(provider.list_dir, rel)
    except mount_lib.MountAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except mount_lib.MountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "rel": rel or "/",
        "entries": [
            {"name": e.name, "rel": e.rel, "is_dir": e.is_dir, "size": e.size,
             "entry_id": e.entry_id}
            for e in entries
        ],
        "total": len(entries),
    }


# ==================== 115 下载与转存 ====================


def _mask_cookie(cookie: str) -> str:
    """Cookie 不回传明文：只展示长度与尾部片段，便于管理员核对是哪一个"""
    value = (cookie or "").strip()
    if not value:
        return ""
    return f"…{value[-6:]}" if len(value) > 6 else "…"


def _serialize_account(account: em.Pan115Account) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "cookie_preview": _mask_cookie(account.cookie),
        "has_cookie": bool((account.cookie or "").strip()),
        "is_default": bool(account.is_default),
        "is_enabled": bool(account.is_enabled),
        "remark": account.remark or "",
        "last_verified_at": account.last_verified_at.isoformat() if account.last_verified_at else None,
        "last_verify_ok": account.last_verify_ok,
        "last_verify_message": account.last_verify_message,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


class Pan115AccountCreate(BaseModel):
    name: str
    cookie: str
    is_default: bool = False
    is_enabled: bool = True
    remark: str = ""


class Pan115AccountUpdate(BaseModel):
    name: str | None = None
    cookie: str | None = None
    is_default: bool | None = None
    is_enabled: bool | None = None
    remark: str | None = None


class Pan115VerifyRequest(BaseModel):
    cookie: str


class Pan115ParseRequest(BaseModel):
    share_url: str


class Pan115TaskCreate(BaseModel):
    share_url: str
    target_cid: str = "0"
    target_path: str = ""
    account_id: int | None = None
    library_id: int | None = None
    mode: str = "receive"
    cookie: str | None = None


@admin_emby_router.get("/115/accounts")
async def list_pan115_accounts(staff: models.WebUser = Depends(require_staff),
                               db: Session = Depends(get_db)):
    accounts = db.query(em.Pan115Account).order_by(em.Pan115Account.id).all()
    env_cookie = os.getenv(transfer115.PAN115_COOKIE_ENV, "").strip()
    return {
        "accounts": [_serialize_account(a) for a in accounts],
        "env_cookie_configured": bool(env_cookie),
    }


@admin_emby_router.post("/115/accounts")
async def create_pan115_account(req: Pan115AccountCreate,
                                staff: models.WebUser = Depends(require_staff),
                                db: Session = Depends(get_db)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写账号名称")
    if not transfer115.normalize_cookie(req.cookie):
        raise HTTPException(status_code=400, detail="请填写 115 Cookie")
    if db.query(em.Pan115Account).filter(em.Pan115Account.name == name).first():
        raise HTTPException(status_code=400, detail=f"账号名称「{name}」已存在")
    account = em.Pan115Account(
        name=name, cookie=transfer115.normalize_cookie(req.cookie),
        is_default=req.is_default, is_enabled=req.is_enabled, remark=req.remark or "",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    if account.is_default:
        transfer115.ensure_single_default(db, account.id)
        db.commit()
    return {"success": True, "account": _serialize_account(account)}


@admin_emby_router.put("/115/accounts/{account_id}")
async def update_pan115_account(account_id: int, req: Pan115AccountUpdate,
                                staff: models.WebUser = Depends(require_staff),
                                db: Session = Depends(get_db)):
    account = db.query(em.Pan115Account).filter(em.Pan115Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号配置档不存在")
    if req.name is not None and req.name.strip() and req.name.strip() != account.name:
        name = req.name.strip()
        if db.query(em.Pan115Account).filter(em.Pan115Account.name == name).first():
            raise HTTPException(status_code=400, detail=f"账号名称「{name}」已存在")
        account.name = name
    if req.cookie is not None:
        cookie = transfer115.normalize_cookie(req.cookie)
        if not cookie:
            raise HTTPException(status_code=400, detail="Cookie 不能为空")
        account.cookie = cookie
        # Cookie 变了，上次校验结论作废
        account.last_verify_ok = None
        account.last_verify_message = None
    if req.is_enabled is not None:
        account.is_enabled = req.is_enabled
    if req.remark is not None:
        account.remark = req.remark
    if req.is_default:
        account.is_default = True
    elif req.is_default is False:
        account.is_default = False
    db.commit()
    if account.is_default:
        transfer115.ensure_single_default(db, account.id)
        db.commit()
    return {"success": True, "account": _serialize_account(account)}


@admin_emby_router.delete("/115/accounts/{account_id}")
async def delete_pan115_account(account_id: int,
                                staff: models.WebUser = Depends(require_staff),
                                db: Session = Depends(get_db)):
    account = db.query(em.Pan115Account).filter(em.Pan115Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号配置档不存在")
    # 媒体库绑定随之解除（回退默认账号），避免留下悬空引用
    for lib in db.query(em.Library).filter(em.Library.account_115_id == account_id).all():
        lib.account_115_id = None
    db.delete(account)
    db.commit()
    return {"success": True}


@admin_emby_router.post("/115/accounts/{account_id}/verify")
async def verify_pan115_account(account_id: int,
                                staff: models.WebUser = Depends(require_staff),
                                db: Session = Depends(get_db)):
    account = db.query(em.Pan115Account).filter(em.Pan115Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号配置档不存在")
    # 校验要真的发一次请求：放到线程池执行，避免阻塞整个事件循环
    result = await run_in_threadpool(transfer115.verify_account, account.cookie)
    account.last_verified_at = datetime.now()
    account.last_verify_ok = bool(result.get("ok"))
    account.last_verify_message = str(result.get("message") or ("有效" if result.get("ok") else ""))[:300]
    db.commit()
    return {"success": True, "result": result, "account": _serialize_account(account)}


@admin_emby_router.post("/115/verify")
async def verify_pan115_cookie(req: Pan115VerifyRequest,
                               staff: models.WebUser = Depends(require_staff)):
    """校验尚未保存的 Cookie（新建配置档前先确认可用）"""
    result = await run_in_threadpool(transfer115.verify_account, req.cookie)
    return {"success": True, "result": result}


@admin_emby_router.post("/115/parse")
async def parse_pan115_share(req: Pan115ParseRequest,
                             staff: models.WebUser = Depends(require_staff)):
    """解析分享链接：返回分享码与提取码，供前端确认后再建任务"""
    try:
        return {"success": True, "parsed": transfer115.parse_share_link(req.share_url)}
    except transfer115.ShareLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@admin_emby_router.get("/115/browse")
async def browse_pan115(
    cid: str = "0",
    account_id: int | None = None,
    cookie: str = "",
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """浏览 115 目录（目标路径选择器）

    表单 Cookie 优先，其次账号配置档，最后已保存的默认账号 / 环境变量——
    这样"刚粘贴还没保存"的 Cookie 也能直接用来浏览路径。
    """
    resolved, source = transfer115.resolve_cookie(
        db, account_id=account_id, explicit_cookie=cookie or None,
    )
    if not resolved:
        raise HTTPException(status_code=400, detail="未配置 115 Cookie，请先在账号配置档里添加")
    try:
        entries = await run_in_threadpool(transfer115.Pan115Client(resolved).list_dir, cid or "0")
    except transfer115.Pan115AuthError as exc:
        raise HTTPException(status_code=401, detail=f"115 登录态失效：{exc}")
    except transfer115.Pan115Error as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "cid": cid or "0",
        "cookie_source": source,
        "entries": [e for e in entries if e.get("is_dir")],
        "total": len(entries),
    }


@admin_emby_router.get("/115/tasks")
async def list_pan115_tasks(status: str = "", limit: int = 50,
                            staff: models.WebUser = Depends(require_staff),
                            db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    query = db.query(em.Pan115Task)
    if status:
        query = query.filter(em.Pan115Task.status == status)
    tasks = query.order_by(em.Pan115Task.id.desc()).limit(limit).all()
    pending = (
        db.query(em.Pan115Task)
        .filter(em.Pan115Task.status.in_(transfer115.ACTIVE_STATUSES))
        .count()
    )
    waiting = db.query(em.Pan115Task).filter(
        em.Pan115Task.status == transfer115.STATUS_WAITING_AUTH
    ).count()
    return {
        "tasks": [transfer115.serialize_task(t) for t in tasks],
        "active_count": pending,
        "waiting_auth_count": waiting,
        "modes": [{"value": k, "label": v} for k, v in transfer115.MODE_LABELS.items()],
        "statuses": [{"value": k, "label": v} for k, v in transfer115.STATUS_LABELS.items()],
    }


@admin_emby_router.get("/115/tasks/{task_id}")
async def get_pan115_task(task_id: int, staff: models.WebUser = Depends(require_staff),
                          db: Session = Depends(get_db)):
    task = db.query(em.Pan115Task).filter(em.Pan115Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": transfer115.serialize_task(task)}


@admin_emby_router.post("/115/tasks")
async def create_pan115_task(req: Pan115TaskCreate,
                             staff: models.WebUser = Depends(require_staff),
                             db: Session = Depends(get_db)):
    """创建转存 / 下载任务（重复提交会被合并到未完成的同一分享任务）"""
    if req.library_id is not None:
        if not db.query(em.Library).filter(em.Library.id == req.library_id).first():
            raise HTTPException(status_code=404, detail="媒体库不存在")
    try:
        task = transfer115.create_task(
            db,
            share_url=req.share_url,
            target_cid=req.target_cid or "0",
            target_path=req.target_path or "",
            account_id=req.account_id,
            library_id=req.library_id,
            mode=req.mode or transfer115.MODE_RECEIVE,
            cookie=req.cookie,
            created_by=staff.id,
        )
    except transfer115.ShareLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "task": transfer115.serialize_task(task)}


@admin_emby_router.post("/115/tasks/{task_id}/retry")
async def retry_pan115_task(task_id: int, staff: models.WebUser = Depends(require_staff),
                            db: Session = Depends(get_db)):
    """重试任务：把等待 Cookie / 失败的任务放回队列，已完成文件不会被重复处理"""
    task = db.query(em.Pan115Task).filter(em.Pan115Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != transfer115.STATUS_DONE:
        task.status = transfer115.STATUS_PENDING
        task.error = None
        task.finished_at = None
        db.commit()
        transfer115.spawn_task(task.id)
    return {"success": True, "task": transfer115.serialize_task(task)}


@admin_emby_router.post("/115/tasks/{task_id}/cancel")
async def cancel_pan115_task(task_id: int, staff: models.WebUser = Depends(require_staff),
                             db: Session = Depends(get_db)):
    task = transfer115.cancel_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已结束")
    return {"success": True, "task": transfer115.serialize_task(task)}
