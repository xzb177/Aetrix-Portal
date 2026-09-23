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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, realms, subscriptions
from backend.database import get_db, SessionLocal
from backend.emby_server import models as em
from backend.emby_server import nodes as node_lib
from backend.emby_server.api import TICKS, SERVER_ID, item_guid_for
from backend.emby_server.auth import (
    ensure_emby_credentials,
    get_admin_or_emby_user,
)
from backend.emby_server.facets import count_virtual_items  # 索引版（虚拟库条目数）
from backend.emby_server.scanner import (
    PLATFORM_LABELS,
    SCAN_RUN_KEEP,
    LibrarySnapshot,
    ScanInProgress,
    is_scan_active,
    normalize_scrape_policy,
    scan_library_sync,
    scan_result_payload,
    scan_runs_payload,
)
# 本文件里这几个路由都是 async def，所以必须用异步变体：同步的 stop_transcode 会
# terminate 子进程、等它退出（最坏 5 秒）、再递归删分片目录，放在事件循环上等于把全站卡住。
from backend.emby_server.streaming import (
    stop_all_transcodes_async,
    stop_transcodes_for_async,
)
from backend.emby_server import facets
from backend.emby_server import mounts as mount_lib
# 扫描队列（v2.27.0）：按远程挂载串行化 + 并发上限 + 排队状态/进度，见 scan_queue.py
from backend.emby_server import scan_queue
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

    必须与后台「服务器」页保存的 Emby 入口一致，否则会出现“后台填了 EA 地址、
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
        raise HTTPException(status_code=503, detail="分离部署的 EA 尚未连接成功，请先部署 EA 并在后台「服务器」页添加它为后端服")


def require_staff(
    request: Request,
    user: models.WebUser = Depends(get_admin_or_emby_user),
    _: None = Depends(ensure_emby_backend_available),
) -> models.WebUser:
    """管理端鉴权：仅 is_staff 用户可访问（/api/admin/emby/* 全部端点）

    与 ``/api/admin/*`` 用同一套角色判定（backend/admin_roles.py）：只读角色不能扫描 /
    改库 / 删条目这些写操作，否则「只读」在这个路由上是假的。
    """
    from backend import admin_roles

    if not user.is_staff:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    admin_roles.ensure_admin_allowed(request, user)
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
        # 接入方式：free = 公益服（免费开放，不需要订阅）；用户端据此换一套文案
        "access_mode": realms.normalize_access_mode(realm.access_mode) if realm else "paid",
        "is_free": realms.is_free_realm(db, realm_id),
        "access_note": realms.access_note_of(db, realm_id),
        "allow_download": subscriptions.download_allowed(db, realm_id),
        "import_schemes": {} if external else {
            "forward": f"forward://import?type=emby&scheme={os.getenv('EMBY_URL_SCHEME', 'http')}&host={host}&username={user.emby_username}",
            "senplayer": f"senplayer://importserver?type=emby&name=RoyalBot&address={url}&username={user.emby_username}",
        },
    }
    card["realms"] = _user_realm_cards(user, db)
    return card


def _user_realm_cards(user: models.WebUser, db: Session) -> list[dict]:
    """用户在各服的地址与订阅状态（多服时前端按卡片列出）

    **公益服不管有没有订阅都下发**：免费开放本身就是这个服对用户的承诺，
    没订阅不等于“不能看”（见 ``backend/subscriptions.py``）。
    """
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
        free = realms.is_free_realm(db, realm.id)
        if sub is None and not free and realm.id != realms.legacy_realm_id(db):
            continue  # 没订阅的付费服不往用户面前推（默认服保留，兼容老前端）
        mode = emby_active_mode(db, realm.id)
        cards.append({
            "id": realm.id,
            "name": realm.name,
            "slug": realm.slug,
            "base_url": resolve_emby_base_url(db, realm.id),
            "mode": mode,
            "external": mode == "external",
            "subscribed": sub is not None,
            # free = 公益服：不需要订阅也能看；"access" 是给前端的一句话口径
            "access_mode": realms.normalize_access_mode(realm.access_mode),
            "is_free": free,
            "access_note": realms.access_note_of(db, realm.id),
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
def get_resume_list(request_user: models.WebUser = Depends(get_admin_or_emby_user),
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
def get_favorite_list(request_user: models.WebUser = Depends(get_admin_or_emby_user),
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
def toggle_favorite(item_id: str, request_user: models.WebUser = Depends(get_admin_or_emby_user),
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
def get_watch_stats(request_user: models.WebUser = Depends(get_admin_or_emby_user),
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
def get_my_sessions(request_user: models.WebUser = Depends(get_admin_or_emby_user),
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
    ended_user_id, ended_item = session.user_id, item_guid_for(db, session.item_id)
    session.ended_at = datetime.now()
    db.commit()
    # 按「用户 + 条目 guid」反查转码会话：播放会话键（PlaySessionId）与转码会话 id（uuid）
    # 不是同一个东西，旧实现拿前者去 pop 等于什么都没停到（见 streaming.find_transcodes）。
    await stop_transcodes_for_async(ended_user_id, item_guid=ended_item)
    return {"success": True}


@user_emby_router.get("/history")
def get_watch_history(request_user: models.WebUser = Depends(get_admin_or_emby_user),
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
def admin_overview(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
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
def list_libraries(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
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
            # 实时状态（v2.27.0）：排队中 / 扫描中（阶段、已发现、已处理、当前目录、本轮远程请求数）
            # 空闲时为 null——列表刷新就能接上刚才那几秒的进度，不用另开接口轮询
            "scan_live": scan_queue.live_payload(lib),
            "scrape_policy": normalize_scrape_policy(lib.scrape_policy),
            "is_virtual": bool(getattr(lib, "is_virtual", False)),
            "platform": lib.platform,
            "account_115_id": getattr(lib, "account_115_id", None),
            "last_scan_at": lib.last_scan_at.isoformat() if lib.last_scan_at else None,
            # 最近一次扫描的结果：新增/更新/删除多少、哪些来源读不到、有没有异常
            "last_scan": scan_result_payload(lib),
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
def create_library(req: LibraryCreate, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
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
def update_library(lib_id: int, req: LibraryUpdate, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
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
def delete_library(lib_id: int, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")
    # 扫描中的库先不删：边扫边删会给已删库继续插条目，而 SQLite 会复用 rowid，
    # 新建一个库撞上同一个 id 时那些孤儿条目会「复活」。
    # 排队中的也算（v2.27.0）：等它排到时会发现库没了——不如在删的时候就说清楚。
    if is_scan_active(lib.id):
        raise HTTPException(status_code=409, detail="该媒体库正在扫描，请等扫描结束后再删除")
    if scan_queue.is_busy(lib.id):
        raise HTTPException(status_code=409, detail="该媒体库在扫描队列中，请先取消排队再删除")

    # 分批删除：老实现把整库条目一次载入内存再逐条删（十万级库会直接把面板拖死）
    removed = 0
    while True:
        chunk = [
            row[0] for row in db.query(em.MediaItem.id)
            .filter(em.MediaItem.library_id == lib.id)
            .limit(500)
            .all()
        ]
        if not chunk:
            break
        db.query(em.MediaStream).filter(
            em.MediaStream.item_id.in_(chunk)
        ).delete(synchronize_session=False)
        db.query(em.UserMediaData).filter(
            em.UserMediaData.item_id.in_(chunk)
        ).delete(synchronize_session=False)
        db.query(em.MediaItem).filter(
            em.MediaItem.id.in_(chunk)
        ).delete(synchronize_session=False)
        db.commit()
        removed += len(chunk)
    db.delete(lib)
    db.commit()
    return {"success": True, "items_removed": removed}


@admin_emby_router.get("/libraries/{lib_id}/scans")
def list_library_scans(lib_id: int, limit: int = 20,
                       staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    """某个媒体库最近的扫描流水（新的在前）

    只看「最近一次」分不出「这个库每轮都失败」和「只是最近一轮失败」——
    流水里带状态、触发方、耗时与同一份统计，失败原因也在。
    """
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")
    return {
        "library_id": lib_id,
        "keep": SCAN_RUN_KEEP,
        "runs": scan_runs_payload(db, lib_id, limit=limit),
    }


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

    # 入队而不是直接起线程（v2.27.0）：不同媒体库引用同一个远程挂载时排队跑，
    # 不让四个任务同时打同一个 WebDAV；重复点击不报 409，直接告诉你「已经在队列/正在扫」。
    # 后台线程用独立 Session（请求结束时请求级 Session 会被关闭，复用会导致
    # "transaction is closed" 与 SQLite 写锁冲突）——那一层现在在 scan_queue 里。
    result = scan_queue.enqueue(lib, trigger="manual")
    task = result["task"]
    if not result["created"]:
        return {"success": True, "queued": False, "already": True, "state": task["state"],
                "message": ("该媒体库正在扫描中" if task["state"] == "running"
                            else f"该媒体库已在扫描队列中（第 {task.get('position') or '-'} 位）"),
                "task": task}
    if task["state"] == "running":
        # 没被任何东西挡住：入队即开扫（就地派发），如实说「已启动」而不是「排队第 1 位」
        return {"success": True, "queued": True, "already": False, "started": True,
                "task": task, "message": "扫描已启动"}
    waiting = [mount_lib.mount_label(m) for m in _waiting_mount_objects(db, task.get("waiting_for"))]
    return {
        "success": True, "queued": True, "already": False, "started": False, "task": task,
        "message": (f"已加入扫描队列（第 {task.get('position') or '-'} 位）"
                    + (f"，正在等挂载：{'、'.join(waiting)}" if waiting
                       else "，前面还有扫描在跑")),
    }


def _waiting_mount_objects(db: Session, mount_ids) -> list:
    """把「在等哪些挂载」变成挂载对象（消息里要写得出名字，而不是只给 id）"""
    ids = [int(m) for m in (mount_ids or [])]
    if not ids:
        return []
    return db.query(em.StorageMount).filter(em.StorageMount.id.in_(ids)).all()


@admin_emby_router.get("/scan-queue")
def scan_queue_snapshot(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    """扫描队列快照：正在跑的、排队等着的、最近完成的，以及远程 IO 计数

    为什么需要它：串联化之后「点了扫描却没动」变成了一件正常的事（在排队），
    没有这个面板就只能靠日志猜「到底在等谁」。
    """
    data = scan_queue.snapshot()
    names = {
        mount.id: mount_lib.mount_label(mount)
        for mount in _waiting_mount_objects(db, data.get("mount_owners", {}).keys())
    }
    # 排队中的任务再带上「在等哪个挂载」的名字：面板要能直接写出名字，
    # 否则管理员只能看到一串 id，还得去存储来源页对号
    waiting_ids = {
        int(m) for task in data.get("waiting", []) for m in (task.get("waiting_for") or [])
    } - set(names)
    if waiting_ids:
        names.update({mount.id: mount_lib.mount_label(mount)
                      for mount in _waiting_mount_objects(db, waiting_ids)})
    data["mount_names"] = {str(key): value for key, value in names.items()}
    return data


@admin_emby_router.delete("/scan-queue/{lib_id}")
def cancel_queued_scan(lib_id: int, staff: models.WebUser = Depends(require_staff)):
    """取消一个**还在排队**的扫描（正在跑的不能取消：停了会留下半个库的状态）"""
    outcome = scan_queue.cancel(lib_id)
    if outcome == "running":
        raise HTTPException(status_code=409, detail="该媒体库正在扫描中，无法取消（请等它跑完）")
    if outcome == "missing":
        raise HTTPException(status_code=404, detail="该媒体库不在扫描队列里")
    return {"success": True, "library_id": lib_id}


@admin_emby_router.post("/libraries/virtual")
def generate_virtual_libraries(
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
        # 库里实际出现过的平台标签：走分类关联表的索引（旧实现要扫一遍全库 platforms 列）
        targets = sorted(facets.kind_values(db, facets.KIND_PLATFORM))

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
def repair_queue(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
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
def run_repair_queue(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    """立即处理修复队列（重新刮削取图）；不传 library_ids 则处理全部启用库"""
    # 走扫描队列（v2.27.0）：修复也要按远程挂载串行化，不然「一键修复」会把前面那批
    # 刚从点击开始跑的库一起推到 WebDAV 上。已在队列/正在扫的库会自动合并，不重复入队。
    libs = [
        lib for lib in db.query(em.Library).filter(em.Library.is_enabled == True).all()  # noqa: E712
    ]
    queued: list[int] = []
    already: list[int] = []
    for lib in libs:
        result = scan_queue.enqueue(lib, trigger="repair")
        (queued if result["created"] else already).append(lib.id)
    return {"success": True, "libraries": queued, "already": already}


@admin_emby_router.get("/libraries/{lib_id}/scan-live")
def library_scan_live(lib_id: int, staff: models.WebUser = Depends(require_staff),
                      db: Session = Depends(get_db)):
    """单个媒体库的实时扫描状态（排队/进度）；空闲返回 204

    列表接口已经带了这个字段，这个端点只是给「盯着一个库看」的页面（轮询间隔更短）。
    """
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")
    live = scan_queue.live_payload(lib)
    if live is None:
        return Response(status_code=204)
    return live


@admin_emby_router.get("/items")
def admin_search_items(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
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
def admin_delete_item(item_id: str, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    item = db.query(em.MediaItem).filter(em.MediaItem.guid == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    db.query(em.MediaStream).filter(em.MediaStream.item_id == item.id).delete()
    db.query(em.UserMediaData).filter(em.UserMediaData.item_id == item.id).delete()
    db.delete(item)
    db.commit()
    return {"success": True}


@admin_emby_router.get("/sessions")
def admin_sessions(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
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
        ended_user_id, ended_item = session.user_id, item_guid_for(db, session.item_id)
        session.ended_at = datetime.now()
        db.commit()
        await stop_transcodes_for_async(ended_user_id, item_guid=ended_item)
    return {"success": True}


@admin_emby_router.post("/transcodes/stop-all")
async def admin_stop_all_transcodes(staff: models.WebUser = Depends(require_staff)):
    count = await stop_all_transcodes_async()
    return {"success": True, "stopped": count}


# ==================== 存储挂载（已拆出） ====================
# 端点实现在 backend/emby_server/portal_mount_routes.py，与本文件共用同一个 admin_emby_router。

# ==================== 115 账号与目录浏览 ====================


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


@admin_emby_router.get("/115/accounts")
def list_pan115_accounts(staff: models.WebUser = Depends(require_staff),
                               db: Session = Depends(get_db)):
    accounts = db.query(em.Pan115Account).order_by(em.Pan115Account.id).all()
    env_cookie = os.getenv(transfer115.PAN115_COOKIE_ENV, "").strip()
    return {
        "accounts": [_serialize_account(a) for a in accounts],
        "env_cookie_configured": bool(env_cookie),
    }


@admin_emby_router.post("/115/accounts")
def create_pan115_account(req: Pan115AccountCreate,
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
def update_pan115_account(account_id: int, req: Pan115AccountUpdate,
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
def delete_pan115_account(account_id: int,
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


