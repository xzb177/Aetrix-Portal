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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db, SessionLocal
from backend.emby_server import models as em
from backend.emby_server.api import TICKS, SERVER_ID
from backend.emby_server.auth import (
    ensure_emby_credentials,
    get_admin_or_emby_user,
)
from backend.emby_server.scanner import scan_library_sync
from backend.emby_server.streaming import stop_all_transcodes, stop_transcode

logger = logging.getLogger(__name__)


def require_staff(user: models.WebUser = Depends(get_admin_or_emby_user)) -> models.WebUser:
    """管理端鉴权：仅 is_staff 用户可访问（/api/admin/emby/* 全部端点）"""
    if not user.is_staff:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


user_emby_router = APIRouter(prefix="/api/user/emby", tags=["用户端-自建Emby"])
admin_emby_router = APIRouter(prefix="/api/admin/emby", tags=["管理后台-自建Emby"], dependencies=[Depends(require_staff)])


# ==================== 用户端 ====================

def _account_card(user: models.WebUser, db: Session) -> dict:
    """构造账号卡（不含密码明文；导入 scheme 需用户已在播放器中保存密码）"""
    return {
        "server_id": SERVER_ID,
        "server_name": os.getenv("EMBY_SERVER_NAME", "RoyalBot Media Server"),
        "base_url": base_url(),
        "emby_username": user.emby_username,
        "emby_password": None,
        "has_password": bool(user.emby_password),
        "import_schemes": {
            "forward": f"forward://import?type=emby&scheme={os.getenv('EMBY_URL_SCHEME', 'http')}&host={base_url().split('//')[-1]}&username={user.emby_username}",
            "senplayer": f"senplayer://importserver?type=emby&name=RoyalBot&address={base_url()}&username={user.emby_username}",
        },
    }


def base_url() -> str:
    return os.getenv("EMBY_PUBLIC_URL", "").rstrip("/") or "http://localhost:8000"


@user_emby_router.get("/server")
async def get_server_info(request_user: models.WebUser = Depends(get_admin_or_emby_user),
                          db: Session = Depends(get_db)):
    """返回账号卡信息：服务器地址 + 自建 Emby 用户名 + 播放器导入 scheme

    安全：不返回密码明文。密码仅注册/重置时一次性返回。
    """
    user = request_user
    ensure_emby_credentials(db, user)
    return _account_card(user, db)


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
    paths: list[str]
    is_enabled: bool = True


class LibraryUpdate(BaseModel):
    name: str | None = None
    collection_type: str | None = None
    paths: list[str] | None = None
    is_enabled: bool | None = None


@admin_emby_router.get("/overview")
async def admin_overview(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    total_items = db.query(em.MediaItem).count()
    total_libraries = db.query(em.Library).count()
    active_sessions = (
        db.query(em.PlaybackSession).filter(em.PlaybackSession.ended_at.is_(None)).count()
    )
    total_users = db.query(models.WebUser).count()
    return {
        "total_items": total_items,
        "total_libraries": total_libraries,
        "active_sessions": active_sessions,
        "total_users": total_users,
        "server_id": SERVER_ID,
    }


@admin_emby_router.get("/libraries")
async def list_libraries(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    libs = db.query(em.Library).order_by(em.Library.id).all()
    return {"libraries": [
        {
            "id": lib.id, "guid": lib.guid, "name": lib.name,
            "collection_type": lib.collection_type,
            "paths": [p for p in (lib.paths or "").split(",") if p],
            "is_enabled": lib.is_enabled, "is_scanning": lib.is_scanning,
            "last_scan_at": lib.last_scan_at.isoformat() if lib.last_scan_at else None,
            "item_count": lib.item_count,
        }
        for lib in libs
    ]}


@admin_emby_router.post("/libraries")
async def create_library(req: LibraryCreate, staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db)):
    import uuid

    guid = uuid.uuid4().hex[:32]
    lib = em.Library(
        guid=guid, name=req.name, collection_type=req.collection_type,
        paths=",".join(req.paths), is_enabled=req.is_enabled,
    )
    for p in req.paths:
        if not os.path.isdir(p):
            raise HTTPException(status_code=400, detail=f"路径不存在: {p}")
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
    if req.is_enabled is not None:
        lib.is_enabled = req.is_enabled
    db.commit()
    return {"success": True}


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
    if lib.is_scanning:
        return {"success": False, "message": "正在扫描中"}
    import threading

    # 扫描在后台线程运行：必须用独立 Session（请求结束时请求级 Session 会被关闭，
    # 复用会导致 "transaction is closed" 与 SQLite 写锁冲突）
    lib_id_value = lib.id

    def _run_scan():
        scan_db = SessionLocal()
        try:
            scan_lib = scan_db.query(em.Library).filter(em.Library.id == lib_id_value).first()
            if scan_lib:
                scan_library_sync(scan_db, scan_lib)
        finally:
            scan_db.close()

    thread = threading.Thread(target=_run_scan, daemon=True)
    thread.start()
    return {"success": True, "message": "扫描已启动"}


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
