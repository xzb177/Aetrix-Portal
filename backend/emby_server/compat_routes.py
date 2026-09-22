"""会话上报与协议补齐路由

由 ``backend/emby_server/api.py`` 拆分而来（v2.13.0），播放会话上报、在线会话列表的旧实现（已被 session_routes 替换），
以及其他 Emby 4.7 协议面补齐端点（筛选值、收藏、相似、演职员、任务、活动日志等）。

路由仍注册在同一个 ``emby_router`` 上（从 ``api`` 导入同一实例），注册顺序与拆分前一致，
因此 ``mount_routes`` / ``image_routes`` / ``session_routes`` 的「按路径 + 端点名替换」逻辑不受影响。
模块由 ``backend/main.py`` 与 ``emby_api/main.py`` 在 ``include_router`` 之前导入。
无阻塞的协议路由一律写成同步 ``def``，由 Starlette 线程池执行，避免同步查询/文件 IO 卡住事件循环。
"""
from __future__ import annotations

import logging

from backend import models
from backend.database import SessionLocal, get_db
from backend.emby_server import models as em
from backend.emby_server.auth import get_emby_user, parse_emby_authorization, resolve_token
from backend.emby_server.scanner import (
    ScanInProgress,
    count_virtual_items,
    item_guid,
    parse_media_filename,
    scan_library_sync,
)
from backend.emby_server.streaming import (
    get_transcode,
    serve_file,
    serve_image,
    serve_remote,
    serve_remote_async,
    start_transcode,
    stop_all_transcodes,
    stop_transcode,
    stop_user_transcodes,
    transcode_alive,
    wait_for_file,
)
from datetime import datetime, timedelta
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from backend.emby_server.api import (
    emby_router,
    SERVER_VERSION,
    _base_url,
    _empty_items,
    _guid_of,
    _now_playing_dto,
    _policy_dto,
    _query_result,
    _require_item,
    _user_data_dto,
    user_views,
)

logger = logging.getLogger(__name__)


# ==================== 会话上报 ====================

def _upsert_session(db: Session, request: Request, user: models.WebUser,
                    item: em.MediaItem, body: dict, ended: bool = False) -> em.PlaybackSession:
    session_key = body.get("PlaySessionId") or f"{user.id}-{item.guid[:16]}"
    session = db.query(em.PlaybackSession).filter(
        em.PlaybackSession.session_key == session_key
    ).first()
    auth = parse_emby_authorization(request.headers.get("X-Emby-Authorization"))
    if not session:
        session = em.PlaybackSession(
            session_key=session_key, user_id=user.id, item_id=item.id,
        )
        db.add(session)
    session.device_name = auth.get("Device") or session.device_name
    session.client_name = auth.get("Client") or session.client_name
    session.client_version = auth.get("Version") or session.client_version
    session.remote_addr = request.client.host if request.client else session.remote_addr
    session.position_ticks = int(body.get("PositionTicks") or 0)
    session.is_paused = bool(body.get("IsPaused", False))
    session.play_method = body.get("PlayMethod") or session.play_method
    if ended:
        session.ended_at = datetime.now()
    db.commit()
    return session


@emby_router.post("/emby/Sessions/Playing")
@emby_router.post("/Sessions/Playing")
async def session_playing(request: Request, user: models.WebUser = Depends(get_emby_user),
                          db: Session = Depends(get_db)):
    body = await request.json()
    item = _require_item(db, body.get("ItemId") or "")
    _upsert_session(db, request, user, item, body)
    return {"success": True}


@emby_router.post("/emby/Sessions/Playing/Progress")
@emby_router.post("/Sessions/Playing/Progress")
async def session_progress(request: Request, user: models.WebUser = Depends(get_emby_user),
                           db: Session = Depends(get_db)):
    body = await request.json()
    item = _require_item(db, body.get("ItemId") or "")
    session = _upsert_session(db, request, user, item, body)

    umd = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == user.id, em.UserMediaData.item_id == item.id
    ).first()
    if not umd:
        umd = em.UserMediaData(user_id=user.id, item_id=item.id)
        db.add(umd)
    pos = int(body.get("PositionTicks") or 0)
    umd.playback_position_ticks = pos
    umd.last_played_at = datetime.now()
    runtime = item.duration_ticks or 0
    if runtime and pos >= runtime * 0.9:
        if not umd.played:
            umd.play_count = (umd.play_count or 0) + 1
        umd.played = True
        umd.playback_position_ticks = 0
    db.commit()
    return {"success": True}


@emby_router.post("/emby/Sessions/Playing/Stopped")
@emby_router.post("/Sessions/Playing/Stopped")
async def session_stopped(request: Request, user: models.WebUser = Depends(get_emby_user),
                          db: Session = Depends(get_db)):
    body = await request.json()
    item = _require_item(db, body.get("ItemId") or "")
    _upsert_session(db, request, user, item, body, ended=True)
    return {"success": True}


@emby_router.post("/emby/Sessions/Capabilities/Full")
@emby_router.post("/Sessions/Capabilities/Full")
@emby_router.post("/emby/Sessions/Capabilities")
@emby_router.post("/Sessions/Capabilities")
def session_capabilities(request: Request, user: models.WebUser = Depends(get_emby_user)):
    return {"success": True}


@emby_router.get("/emby/Sessions")
@emby_router.get("/Sessions")
def get_sessions(request: Request, db: Session = Depends(get_db)):
    sessions = (
        db.query(em.PlaybackSession)
        .filter(em.PlaybackSession.ended_at.is_(None))
        .order_by(em.PlaybackSession.last_update_at.desc())
        .all()
    )
    result = []
    for s in sessions:
        item = db.query(em.MediaItem).filter(em.MediaItem.id == s.item_id).first()
        user = db.query(models.WebUser).filter(models.WebUser.id == s.user_id).first()
        if item and user:
            result.append(_now_playing_dto(s, item, user))
    return result


@emby_router.delete("/emby/Sessions/{session_key}")
@emby_router.delete("/Sessions/{session_key}")
def stop_session(session_key: str, db: Session = Depends(get_db)):
    session = db.query(em.PlaybackSession).filter(
        em.PlaybackSession.session_key == session_key
    ).first()
    if session:
        session.ended_at = datetime.now()
        db.commit()
    stop_transcode(session_key)
    return {"success": True}


# ==================== 其他兼容端点 ====================

@emby_router.get("/emby/LiveTV/Channels")
@emby_router.get("/LiveTV/Channels")
def livetv_channels():
    return {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}


@emby_router.get("/emby/DisplayPreferences/users")
@emby_router.get("/DisplayPreferences/users")
def display_prefs(request: Request, user: models.WebUser = Depends(get_emby_user)):
    return {"Id": "users", "CustomPrefs": {}}


@emby_router.post("/emby/DisplayPreferences/users")
@emby_router.post("/DisplayPreferences/users")
def save_display_prefs(request: Request, user: models.WebUser = Depends(get_emby_user)):
    return {"success": True}


@emby_router.get("/emby/Localization/Culture")
@emby_router.get("/Localization/Culture")
def localization_cultures():
    return [
        {"Name": "Chinese (Simplified)", "TwoLetterISOLanguageName": "zh", "ThreeLetterISOLanguageName": "chi"},
        {"Name": "English", "TwoLetterISOLanguageName": "en", "ThreeLetterISOLanguageName": "eng"},
    ]


@emby_router.get("/emby/Localization/countries")
@emby_router.get("/Localization/countries")
def localization_countries():
    return [{"Name": "China", "TwoLetterISOLanguageName": "cn", "ThreeLetterISOLanguageName": "CHN"}]


@emby_router.get("/emby/Web/DefaultRoutingMap")
@emby_router.get("/Web/DefaultRoutingMap")
def default_routing_map():
    return {"Routes": []}


@emby_router.get("/emby/MediaBackup/Status")
@emby_router.get("/MediaBackup/Status")
def media_backup_status():
    return {"Status": "Disabled"}


@emby_router.get("/emby/swagger.json")
@emby_router.get("/swagger.json")
def swagger_json():
    return {"swagger": "2.0", "info": {"title": "Emby", "version": SERVER_VERSION}, "paths": {}}


@emby_router.get("/emby/quickconnect/info")
@emby_router.get("/quickconnect/info")
def quickconnect_info():
    return {"Available": False, "State": "Unavailable"}


# ==================== 客户端兼容补齐（对照 Emby 4.7 官方 API 面）====================
#
# 本节补齐真实客户端（Infuse / Forward / Hills / SenPlayer / 官方 App）会调用、
# 但旧实现未覆盖的端点。原则：
#   1) 有真实数据的给真实数据（搜索、相似、祖先、字幕、分类元数据）
#   2) 本服务没有对应概念的（预告片/主题曲/片头/插件）返回空结果集而不是 404，
#      客户端不会把 404 当错误反复重试
#   3) 涉及隐私的（/Users/Public 用户列表）按 Jellyfin 默认策略返回空


# ---- 用户策略 ----

@emby_router.get("/emby/Users/{user_id}/Policy")
@emby_router.get("/Users/{user_id}/Policy")
def get_user_policy(user_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _policy_dto(user)


@emby_router.post("/emby/Users/{user_id}/Policy")
@emby_router.post("/Users/{user_id}/Policy")
def set_user_policy(user_id: str, user: models.WebUser = Depends(get_emby_user)):
    # 用户策略由门户统一管理：忽略客户端写入，返回当前真实策略，避免客户端状态错乱
    return _policy_dto(user)


# ---- 搜索 ----
# 搜索接口已迁到 backend/emby_server/search_api.py（相关度排序版），
# 并在 main.py / emby_api/main.py 中**先于本路由**注册。



# ---- 收藏的规范路由（客户端除 Rating 外还会直接调 FavoriteItems）----

def _set_favorite(db: Session, user: models.WebUser, item_id: str, value: bool) -> dict:
    item = _require_item(db, item_id)
    umd = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == user.id, em.UserMediaData.item_id == item.id
    ).first()
    if not umd:
        umd = em.UserMediaData(user_id=user.id, item_id=item.id)
        db.add(umd)
    umd.is_favorite = value
    db.commit()
    return _user_data_dto(umd)


@emby_router.post("/emby/Users/{user_id}/FavoriteItems/{item_id}")
@emby_router.post("/Users/{user_id}/FavoriteItems/{item_id}")
def add_favorite(item_id: str, user_id: str,
                 user: models.WebUser = Depends(get_emby_user),
                 db: Session = Depends(get_db)):
    return _set_favorite(db, user, item_id, True)


@emby_router.delete("/emby/Users/{user_id}/FavoriteItems/{item_id}")
@emby_router.delete("/Users/{user_id}/FavoriteItems/{item_id}")
def remove_favorite(item_id: str, user_id: str,
                    user: models.WebUser = Depends(get_emby_user),
                    db: Session = Depends(get_db)):
    return _set_favorite(db, user, item_id, False)


# ---- 相似推荐 ----

@emby_router.get("/emby/Items/{item_id}/Similar")
@emby_router.get("/Items/{item_id}/Similar")
@emby_router.get("/emby/Movies/{item_id}/Similar")
@emby_router.get("/Movies/{item_id}/Similar")
@emby_router.get("/emby/Shows/{item_id}/Similar")
@emby_router.get("/Shows/{item_id}/Similar")
@emby_router.get("/emby/Trailers/{item_id}/Similar")
@emby_router.get("/Trailers/{item_id}/Similar")
def similar_items(item_id: str, request: Request,
                  user: models.WebUser = Depends(get_emby_user),
                  db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    genres = [g for g in (item.genres or "").split(",") if g]
    if not genres:
        return _empty_items()
    limit = int(request.query_params.get("Limit") or 12)
    rows = (
        db.query(em.MediaItem)
        .filter(
            em.MediaItem.item_type == item.item_type,
            em.MediaItem.id != item.id,
            em.MediaItem.is_hidden == False,  # noqa: E712
            or_(*[em.MediaItem.genres.ilike(f"%{g}%") for g in genres]),
        )
        .order_by(func.coalesce(em.MediaItem.community_rating, 0).desc())
        .limit(limit)
        .all()
    )
    return _query_result(rows, user, db, _base_url(request))


# ---- 祖先链路（客户端靠它做面包屑与“剧 → 季 → 集”导航）----

@emby_router.get("/emby/Items/{item_id}/Ancestors")
@emby_router.get("/Items/{item_id}/Ancestors")
def item_ancestors(item_id: str, request: Request,
                   user: models.WebUser = Depends(get_emby_user),
                   db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    chain: list = []
    seen: set = set()
    if item.item_type == "episode" and item.parent is not None:
        chain.append(item.parent)
        seen.add(item.parent.id)
    if item.item_type in ("episode", "season") and item.series is not None and item.series.id not in seen:
        chain.append(item.series)
    return _query_result(chain, user, db, _base_url(request))


# ---- 本服务没有的媒体附件：返回空结果集而非 404 ----

@emby_router.get("/emby/Items/{item_id}/LocalTrailers")
@emby_router.get("/Items/{item_id}/LocalTrailers")
def local_trailers(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/SpecialFeatures")
@emby_router.get("/Items/{item_id}/SpecialFeatures")
def special_features(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/ThemeVideos")
@emby_router.get("/Items/{item_id}/ThemeVideos")
@emby_router.get("/emby/Items/{item_id}/ThemeSongs")
@emby_router.get("/Items/{item_id}/ThemeSongs")
def theme_items(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/ThemeMedia")
@emby_router.get("/Items/{item_id}/ThemeMedia")
def theme_media(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return {
        "ThemeVideosResult": _empty_items(),
        "ThemeSongsResult": _empty_items(),
        "SoundtrackSongsResult": _empty_items(),
    }


@emby_router.get("/emby/Items/{item_id}/Intros")
@emby_router.get("/Items/{item_id}/Intros")
@emby_router.get("/emby/Users/{user_id}/Items/{item_id}/Intros")
@emby_router.get("/Users/{user_id}/Items/{item_id}/Intros")
def item_intros(item_id: str, user_id: str = "",
                user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/CriticReviews")
@emby_router.get("/Items/{item_id}/CriticReviews")
def critic_reviews(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return []


# ---- 分类元数据 ----

def _named_items(kind: str, names: list) -> dict:
    items = [
        {"Name": n, "Id": _guid_of(kind, n), "Type": kind,
         "ImageTags": {}, "BackdropImageTags": []}
        for n in names
    ]
    return {"Items": items, "TotalRecordCount": len(items), "StartIndex": 0}


@emby_router.get("/emby/Genres")
@emby_router.get("/Genres")
def genres_list(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    names = sorted({g for row in db.query(em.MediaItem.genres).all()
                    for g in (row[0] or "").split(",") if g})
    return _named_items("Genre", names)


@emby_router.get("/emby/Genres/{name}")
@emby_router.get("/Genres/{name}")
def genre_by_name(name: str, user: models.WebUser = Depends(get_emby_user)):
    return {"Name": name, "Id": _guid_of("Genre", name), "Type": "Genre",
            "ImageTags": {}, "BackdropImageTags": []}


@emby_router.get("/emby/Studios")
@emby_router.get("/Studios")
def studios_list(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    names = sorted({s for row in db.query(em.MediaItem.studios).all()
                    for s in (row[0] or "").split(",") if s})
    return _named_items("Studio", names)


@emby_router.get("/emby/Persons")
@emby_router.get("/Persons")
def persons_list(user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()  # 刮削未落演员表，返回空而非 404


# ---- 媒体库视图别名 ----

@emby_router.get("/emby/Library/MediaFolders")
@emby_router.get("/Library/MediaFolders")
async def library_media_folders(user: models.WebUser = Depends(get_emby_user),
                                db: Session = Depends(get_db)):
    return await user_views("me", user, db)


@emby_router.get("/emby/UserViews")
@emby_router.get("/UserViews")
async def user_views_alias(user: models.WebUser = Depends(get_emby_user),
                           db: Session = Depends(get_db)):
    return await user_views("me", user, db)


# ---- 系统 / 诊断 ----

@emby_router.get("/emby/System/Endpoint")
@emby_router.get("/System/Endpoint")
def system_endpoint(user: models.WebUser = Depends(get_emby_user)):
    return {"IsLocal": True, "IsInNetwork": True}


@emby_router.post("/emby/Sessions/Logout")
@emby_router.post("/Sessions/Logout")
def sessions_logout(request: Request, user: models.WebUser = Depends(get_emby_user),
                    db: Session = Depends(get_db)):
    resolved = resolve_token(db, request)
    if resolved:
        resolved[1].is_revoked = True
        db.commit()
    return {"success": True}


@emby_router.get("/emby/Localization/ParentalRatings")
@emby_router.get("/Localization/ParentalRatings")
def parental_ratings(user: models.WebUser = Depends(get_emby_user)):
    return []


@emby_router.get("/emby/Plugins")
@emby_router.get("/Plugins")
def plugins(user: models.WebUser = Depends(get_emby_user)):
    return []


@emby_router.get("/emby/ScheduledTasks")
@emby_router.get("/ScheduledTasks")
def scheduled_tasks(user: models.WebUser = Depends(get_emby_user)):
    return []


@emby_router.get("/emby/Activity/Log/Entries")
@emby_router.get("/Activity/Log/Entries")
def activity_log(user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


# ---- 转码释放 / 库刷新 ----

@emby_router.delete("/emby/Videos/ActiveEncodings")
@emby_router.delete("/Videos/ActiveEncodings")
@emby_router.post("/emby/Videos/ActiveEncodings/Delete")
@emby_router.post("/Videos/ActiveEncodings/Delete")
def delete_active_encodings(request: Request,
                            user: models.WebUser = Depends(get_emby_user)):
    # 管理员释放全部转码，普通用户只能释放自己的（避免互相踢掉播放）
    count = stop_all_transcodes() if user.is_staff else stop_user_transcodes(user.id)
    logger.info("释放转码会话 user=%s count=%s", user.id, count)
    return Response(status_code=204)


@emby_router.post("/emby/Library/Refresh")
@emby_router.post("/Library/Refresh")
def library_refresh(user: models.WebUser = Depends(get_emby_user),
                    db: Session = Depends(get_db)):
    if not user.is_staff:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    lib_ids = [
        lib.id for lib in db.query(em.Library).filter(em.Library.is_enabled == True).all()  # noqa: E712
        if not lib.is_scanning
    ]

    def _run_scan() -> None:
        # 后台线程必须用独立 Session（请求级 Session 结束即关闭）
        scan_db = SessionLocal()
        try:
            for lib_id in lib_ids:
                library = scan_db.query(em.Library).filter(em.Library.id == lib_id).first()
                if not library:
                    continue
                # 单个库失败不能带走整批「刷新全部」：否则后面的库永远没被扫到，
                # 而界面上只会看到“刷新了但没变化”，连原因都没有。
                try:
                    scan_library_sync(scan_db, library)
                except ScanInProgress:
                    continue  # 已有任务在跑：跳过，不是错误
                except Exception:  # noqa: BLE001
                    logger.exception("媒体库 %s 扫描失败", lib_id)
        finally:
            scan_db.close()

    import threading

    threading.Thread(target=_run_scan, daemon=True).start()
    return {"success": True, "libraries": len(lib_ids)}


