"""自建 Emby 服务器：Emby 协议兼容 API

覆盖 Emby 客户端核心接口：
- 系统信息 / 认证（Users/AuthenticateByName, /Users/{id}）
- 项目列表 / 详情 / 精选（/Users/{uid}/Items, /Users/{uid}/Items/Resume, Latest）
- 播放信息（PlaybackInfo, /Videos/{id}/stream, /Videos/{id}/master.m3u8, /videos/{id}/hls1/...）
- 图片（/Items/{id}/Images/Primary|Backdrop|Logo|Thumb）
- 会话上报（/Sessions/Playing, /Sessions/Playing/Progress, /Sessions/Playing/Stopped）
- 收藏/已看（/Users/{uid}/FavoriteItems, PlayedItems, /Users/{uid}/Items/{iid}/Rating）
- 电视首页（/Shows/{id}/Seasons, /Shows/{id}/Episodes, /Shows/NextUp）
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from backend import models
from backend.database import get_db
from backend.emby_server import models as em
from backend.emby_server.auth import (
    get_emby_user,
    parse_emby_authorization,
    resolve_token,
)
from backend.emby_server.scanner import item_guid, parse_media_filename
from backend.emby_server.streaming import (
    get_transcode,
    serve_file,
    serve_image,
    start_transcode,
    stop_transcode,
)

logger = logging.getLogger(__name__)

emby_router = APIRouter(tags=["EmbyServer"])

TICKS = 10_000_000
SERVER_VERSION = "4.8.0.0"
SERVER_ID = os.getenv("EMBY_SERVER_ID", "royalbot-emby-server")


def _iso(dt) -> str:
    return dt.isoformat() if dt else None


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _image_url(base: str, item: em.MediaItem, kind: str = "Primary") -> str | None:
    if kind == "Primary":
        src = item.primary_image_url or item.poster_path
    else:
        src = item.backdrop_image_url or item.backdrop_path
    if not src:
        return None
    if src.startswith("http"):
        return src
    return f"{base}/emby/Items/{item.guid}/Images/{kind}"


def _image_urls(base: str, item: em.MediaItem) -> list[dict]:
    urls = []
    primary = _image_url(base, item, "Primary")
    backdrop = _image_url(base, item, "Backdrop")
    if primary:
        urls.append({"imageType": "Primary", "url": primary})
    if backdrop:
        urls.append({"imageTags": {"Backdrop": "1"}, "url": backdrop, "imageType": "Backdrop"})
    return urls


def _ticks_to_pos(ticks: int) -> str:
    secs = ticks // TICKS
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _item_dto(item: em.MediaItem, base: str, user_id: int, db: Session, full: bool = False) -> dict:
    umd = (
        db.query(em.UserMediaData)
        .filter(em.UserMediaData.user_id == user_id, em.UserMediaData.item_id == item.id)
        .first()
    )
    dto = {
        "Name": item.name,
        "Id": item.guid,
        "ServerId": SERVER_ID,
        "Type": _emby_type(item.item_type),
        "IsFolder": item.item_type in ("series", "season"),
        "ChildCount": _child_count(item, db),
        "MediaType": "Video" if item.item_type in ("movie", "episode") else None,
        "LocationType": "FileSystem",
        "ProductionYear": item.production_year,
        "CommunityRating": item.community_rating,
        "OfficialRating": item.official_rating,
        "Overview": item.overview if full else (item.overview or "")[:300] or None,
        "Genres": [g for g in (item.genres or "").split(",") if g],
        "Tags": [t for t in (item.tags or "").split(",") if t],
        "Studios": [s for s in (item.studios or "").split(",") if s],
        "PremiereDate": _iso(item.premiere_date),
        "DateCreated": _iso(item.date_added),
        "ProviderIds": {"Tmdb": item.tmdb_id} if item.tmdb_id else {},
        "ImageTags": {"Primary": "1"} if _image_url(base, item) else {},
        "BackdropImageTags": ["1"] if _image_url(base, item, "Backdrop") else {},
        "UserData": _user_data_dto(umd),
        "CanDownload": True,
        "SupportsContentDownloading": True,
    }
    if item.item_type == "episode":
        dto.update({
            "SeriesId": item.series.guid if item.series else None,
            "SeriesName": item.series.name if item.series else None,
            "SeasonId": item.parent.guid if item.parent else None,
            "SeasonName": item.parent.name if item.parent else None,
            "ParentIndexNumber": item.season_number,
            "IndexNumber": item.episode_number,
        })
    if item.item_type == "season":
        dto.update({"SeriesId": item.series.guid if item.series else None,
                    "SeriesName": item.series.name if item.series else None,
                    "IndexNumber": item.season_number})
    if full:
        dto["MediaSources"] = [_media_source(item, base)]
        dto["Chapters"] = []
    return dto


def _emby_type(t: str) -> str:
    return {"movie": "Movie", "series": "Series", "season": "Season", "episode": "Episode"}.get(t, "Movie")


def _child_count(item: em.MediaItem, db: Session) -> int | None:
    if item.item_type == "series":
        return db.query(em.MediaItem).filter(em.MediaItem.series_id == item.id,
                                             em.MediaItem.item_type == "episode").count() or None
    if item.item_type == "season":
        return db.query(em.MediaItem).filter(em.MediaItem.parent_id == item.id).count() or None
    return None


def _user_data_dto(umd) -> dict:
    if not umd:
        return {"PlaybackPositionTicks": 0, "PlayCount": 0, "Played": False,
                "IsFavorite": False, "Key": "", "UnplayedItemCount": 1}
    return {
        "PlaybackPositionTicks": umd.playback_position_ticks or 0,
        "PlayCount": umd.play_count or 0,
        "Played": bool(umd.played),
        "IsFavorite": bool(umd.is_favorite),
        "LastPlayedDate": _iso(umd.last_played_at),
    }


def _media_source(item: em.MediaItem, base: str) -> dict:
    src_id = item.guid
    return {
        "Id": src_id,
        "Name": item.name,
        "Path": item.file_path,
        "Protocol": "File",
        "Container": item.container,
        "Size": item.size,
        "SupportsDirectPlay": True,
        "SupportsDirectStream": True,
        "SupportsTranscoding": True,
        "IsRemote": False,
        "MediaStreams": [
            {
                "Index": s.stream_index, "Type": s.stream_type, "Codec": s.codec,
                "Language": s.language, "DisplayTitle": s.display_title or s.language,
                "Title": s.title, "IsDefault": bool(s.is_default),
                "IsForced": bool(s.is_forced), "IsExternal": bool(s.is_external),
                "Channels": s.channels, "BitRate": s.bit_rate,
                "IsTextSubtitleStream": bool(s.is_external),
            }
            for s in item.streams
        ],
    }


def _require_item(db: Session, item_id: str) -> em.MediaItem:
    item = db.query(em.MediaItem).filter(em.MediaItem.guid == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def _run_time_ticks(item: em.MediaItem) -> int:
    return item.duration_ticks or 0


def _now_playing_dto(session: em.PlaybackSession, item: em.MediaItem, user) -> dict:
    return {
        "Id": session.session_key,
        "UserId": str(user.id),
        "UserName": user.username,
        "Client": session.client_name or "Emby Web",
        "DeviceName": session.device_name or "Unknown Device",
        "ApplicationVersion": session.client_version or "1.0",
        "NowPlayingItem": {
            "Id": item.guid, "Name": item.name, "Type": _emby_type(item.item_type),
            "RunTimeTicks": _run_time_ticks(item), "ProductionYear": item.production_year,
            "MediaType": "Video",
        },
        "PlayState": {
            "PositionTicks": session.position_ticks or 0,
            "IsPaused": bool(session.is_paused),
            "PlayMethod": session.play_method or "DirectStream",
            "CanSeek": True,
        },
        "PlayMethod": session.play_method or "DirectStream",
        "TranscodingInfo": {"CompletionPercentage": 100} if session.play_method == "Transcode" else None,
    }


# ==================== 系统信息 ====================

@emby_router.get("/emby/system/info")
@emby_router.get("/emby/system/info/public")
@emby_router.get("/System/Info")
@emby_router.get("/System/Info/Public")
async def system_info(request: Request):
    return {
        "Id": SERVER_ID,
        "ServerName": os.getenv("EMBY_SERVER_NAME", "RoyalBot Media Server"),
        "Version": SERVER_VERSION,
        "ProductName": "Emby Server",
        "OperatingSystem": "Linux",
        "TranscodingJobs": 0,
        "LocalAddress": _base_url(request),
        "WanAddress": _base_url(request),
        "SupportsLibraryMonitor": False,
        "SupportsSynchronization": True,
        "HasUpdateAvailable": False,
        "CanSelfRestart": False,
        "CanLaunchWebApp": True,
        "HavePendingRestart": False,
        "CompletedInstallations": [],
    }


@emby_router.get("/emby/system/ping")
@emby_router.get("/System/Ping")
async def system_ping():
    return PlainTextResponse("Emby Server")


@emby_router.post("/emby/system/ping")
@emby_router.post("/System/Ping")
async def system_ping_post():
    return PlainTextResponse("Emby Server")


@emby_router.get("/emby/branding/config")
@emby_router.get("/Branding/Configuration")
async def branding_config():
    return {"LoginDisclaimer": "", "CustomCss": "", "SplashscreenEnabled": False}


@emby_router.get("/emby")
async def emby_root():
    return {"ProductName": "Emby Server", "Version": SERVER_VERSION, "Id": SERVER_ID}


# ==================== 认证 ====================

@emby_router.post("/emby/Users/AuthenticateByName")
@emby_router.post("/Users/AuthenticateByName")
async def authenticate_by_name(
    request: Request,
    credentials: dict = Body(...),
    db: Session = Depends(get_db),
):
    # 限流：同 IP 每分钟最多 10 次认证尝试（防暴力破解）
    from backend.ratelimit import check_rate_limit, client_ip

    ip = client_ip(request)
    allowed, retry_after = check_rate_limit(f"emby-auth:{ip}", 10, 60)
    if not allowed:
        return Response(
            content='{"error": "TooManyAttempts"}',
            status_code=429, media_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )

    username = (credentials.get("Username") or "").strip()
    password = credentials.get("Pw") or credentials.get("password") or ""

    user = None
    if username:
        # 优先自建 Emby 凭据，其次门户账号
        user = db.query(models.WebUser).filter(
            or_(models.WebUser.emby_username == username, models.WebUser.username == username)
        ).first()

    from backend.emby_server.auth import ensure_emby_credentials, issue_token, verify_emby_password

    def _auth_fail():
        return Response(
            content='{"error": "InvalidUsernameOrPassword"}',
            status_code=401, media_type="application/json",
        )

    if not user or not user.is_active or not password:
        return _auth_fail()

    # 密码校验：支持哈希与明文（明文用于兼容旧数据，校验后自动升级为哈希）
    if not verify_emby_password(password, user.emby_password or ""):
        return _auth_fail()
    if user.emby_password and not user.emby_password.startswith("$2"):
        # 透明升级：明文 -> bcrypt
        ensure_emby_credentials(db, user, password=password)

    ensure_emby_credentials(db, user)
    token_value, token_row = issue_token(db, user, request)

    auth = parse_emby_authorization(request.headers.get("X-Emby-Authorization"))
    access_token = token_value
    server_id = SERVER_ID
    user_dto = _user_dto(user, db)
    return {
        "User": user_dto,
        "AccessToken": access_token,
        "ServerId": server_id,
        "SessionInfo": {
            "UserId": str(user.id),
            "UserName": user.username,
            "Client": auth.get("Client") or "Emby",
            "DeviceName": auth.get("Device") or "Unknown Device",
            "DeviceId": token_row.device_id,
            "Id": token_row.token[:16],
            "ServerId": server_id,
            "ApplicationVersion": auth.get("Version") or "1.0",
            "IsAuthenticated": True,
            "SupportsRemoteControl": True,
        },
    }


def _user_dto(user: models.WebUser, db: Session) -> dict:
    policy = {
        "IsAdministrator": bool(user.is_staff),
        "EnableContentDeletion": bool(user.is_staff),
        "EnableContentDownloading": True,
        "EnableMediaPlayback": True,
        "EnableAudioPlaybackTranscoding": True,
        "EnableVideoPlaybackTranscoding": True,
        "EnablePlaybackRemuxing": True,
        "EnableSyncTranscoding": True,
        "EnableAllDevices": True,
        "EnableAllFolders": True,
        "SimultaneousStreamLimit": 3,
        "InvalidLoginAttemptCount": 0,
    }
    return {
        "Id": str(user.id),
        "Name": user.emby_username or user.username,
        "ServerId": SERVER_ID,
        "HasPassword": True,
        "HasConfiguredPassword": True,
        "PrimaryImageTag": None,
        "IsAdministrator": bool(user.is_staff),
        "Policy": policy,
        "Configuration": {"SubtitleLanguagePreference": "chi", "AudioLanguagePreference": "chi",
                          "PlayDefaultAudioTrack": True, "DisplayMissingEpisodes": False},
    }


@emby_router.get("/emby/Users/{user_id}")
@emby_router.get("/Users/{user_id}")
async def get_user(user_id: str, user: models.WebUser = Depends(get_emby_user),
                   db: Session = Depends(get_db)):
    if user_id not in (str(user.id), "me", user.emby_username or "", user.username):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _user_dto(user, db)


@emby_router.get("/emby/Users/{user_id}/Views")
@emby_router.get("/Users/{user_id}/Views")
async def user_views(user_id: str, user: models.WebUser = Depends(get_emby_user),
                     db: Session = Depends(get_db)):
    libs = db.query(em.Library).filter(em.Library.is_enabled == True).all()  # noqa: E712
    items = []
    for lib in libs:
        items.append({
            "Name": lib.name,
            "Id": lib.guid,
            "Type": "CollectionFolder",
            "CollectionType": lib.collection_type,
            "IsFolder": True,
            "UserData": {"PlaybackPositionTicks": 0, "PlayCount": 0, "Played": False, "IsFavorite": False},
            "ImageTags": {"Primary": "1"},
            "ChildCount": lib.item_count,
        })
    return {"Items": items, "TotalRecordCount": len(items), "StartIndex": 0}


@emby_router.get("/emby/Users/{user_id}/Items")
@emby_router.get("/Users/{user_id}/Items")
async def get_items(
    request: Request,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    return _query_items(request, user, db, _base_url(request))


def _query_items(request: Request, user: models.WebUser, db: Session, base: str) -> dict:
    q = request.query_params
    parent_id = q.get("ParentId")
    include_types = (q.get("IncludeItemTypes") or "").split(",")
    exclude_types = (q.get("ExcludeItemTypes") or "").split(",")
    sort_by = (q.get("SortBy") or "SortName").split(",")
    sort_order = (q.get("SortOrder") or "Ascending").split(",")
    search = (q.get("SearchTerm") or "").strip()
    genres = (q.get("Genres") or "").split("|")
    years = (q.get("Years") or "").split(",")
    start = int(q.get("StartIndex") or 0)
    limit = int(q.get("Limit") or 100)
    recursive = (q.get("Recursive") or "false").lower() == "true"
    user_id = q.get("UserId") or str(user.id)

    query = db.query(em.MediaItem).filter(em.MediaItem.is_hidden == False)  # noqa: E712

    if parent_id:
        parent = db.query(em.MediaItem).filter(em.MediaItem.guid == parent_id).first()
        if parent:
            if parent.item_type in ("series", "season"):
                if parent.item_type == "series":
                    query = query.filter(
                        or_(em.MediaItem.series_id == parent.id, em.MediaItem.id == parent.id)
                    )
                else:
                    query = query.filter(
                        or_(em.MediaItem.parent_id == parent.id, em.MediaItem.id == parent.id)
                    )
        else:
            # 可能是媒体库
            lib = db.query(em.Library).filter(em.Library.guid == parent_id).first()
            if lib:
                query = query.filter(em.MediaItem.library_id == lib.id)
            else:
                query = query.filter(em.MediaItem.guid == parent_id)
    elif not recursive:
        # 非递归默认返回顶层
        query = query.filter(em.MediaItem.item_type.in_(["movie", "series"]))

    if include_types and include_types[0]:
        type_map = {"Movie": "movie", "Series": "series", "Season": "season", "Episode": "episode"}
        mapped = [type_map.get(t.strip(), t.strip().lower()) for t in include_types if t.strip()]
        if mapped:
            query = query.filter(em.MediaItem.item_type.in_(mapped))

    if exclude_types and exclude_types[0]:
        type_map = {"Movie": "movie", "Series": "series", "Season": "season", "Episode": "episode"}
        mapped = [type_map.get(t.strip(), t.strip().lower()) for t in exclude_types if t.strip()]
        if mapped:
            query = query.filter(~em.MediaItem.item_type.in_(mapped))

    if search:
        like = f"%{search}%"
        query = query.filter(or_(em.MediaItem.name.ilike(like), em.MediaItem.original_title.ilike(like)))

    if genres and genres[0]:
        query = query.filter(or_(*[em.MediaItem.genres.ilike(f"%{g}%") for g in genres if g]))

    if years and years[0]:
        try:
            year_list = [int(y) for y in years if y]
            if year_list:
                query = query.filter(em.MediaItem.production_year.in_(year_list))
        except ValueError:
            pass

    # 排序
    order_cols = []
    for col in sort_by:
        c = {
            "SortName": em.MediaItem.sort_name, "Name": em.MediaItem.name,
            "DateCreated": em.MediaItem.date_added, "ProductionYear": em.MediaItem.production_year,
            "CommunityRating": em.MediaItem.community_rating, "DatePlayed": em.UserMediaData.last_played_at,
        }.get(col.strip())
        if c is None:
            continue
        order_cols.append(c.desc() if sort_order and sort_order[0].lower().startswith("desc") else c.asc())
    if not order_cols:
        order_cols = [em.MediaItem.sort_name.asc()]

    total = query.count()
    items = query.order_by(*order_cols).offset(start).limit(limit).all()

    return {
        "Items": [_item_dto(i, base, user.id, db) for i in items],
        "TotalRecordCount": total,
        "StartIndex": start,
    }


@emby_router.get("/emby/Users/{user_id}/Items/Resume")
@emby_router.get("/Users/{user_id}/Items/Resume")
async def get_resume(request: Request, user: models.WebUser = Depends(get_emby_user),
                     db: Session = Depends(get_db)):
    limit = int(request.query_params.get("Limit") or 12)
    rows = (
        db.query(em.UserMediaData, em.MediaItem)
        .join(em.MediaItem, em.MediaItem.id == em.UserMediaData.item_id)
        .filter(
            em.UserMediaData.user_id == user.id,
            em.UserMediaData.playback_position_ticks > 0,
            em.UserMediaData.played == False,  # noqa: E712
        )
        .order_by(em.UserMediaData.last_played_at.desc())
        .limit(limit)
        .all()
    )
    base = _base_url(request)
    return {"Items": [_item_dto(i, base, user.id, db) for _umd, i in rows],
            "TotalRecordCount": len(rows), "StartIndex": 0}


@emby_router.get("/emby/Users/{user_id}/Items/Latest")
@emby_router.get("/Users/{user_id}/Items/Latest")
async def get_latest(request: Request, user: models.WebUser = Depends(get_emby_user),
                     db: Session = Depends(get_db)):
    limit = int(request.query_params.get("Limit") or 16)
    items = (
        db.query(em.MediaItem)
        .filter(em.MediaItem.item_type.in_(["movie", "series"]), em.MediaItem.is_hidden == False)  # noqa: E712
        .order_by(em.MediaItem.date_added.desc())
        .limit(limit)
        .all()
    )
    base = _base_url(request)
    result = []
    for item in items:
        dto = _item_dto(item, base, user.id, db)
        dto["UserData"]["UnplayedItemCount"] = 1
        result.append(dto)
    return result


@emby_router.get("/emby/Items/{item_id}")
@emby_router.get("/Items/{item_id}")
@emby_router.get("/emby/Users/{user_id}/Items/{item_id}")
@emby_router.get("/Users/{user_id}/Items/{item_id}")
async def get_item_detail(
    item_id: str,
    request: Request,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    item = _require_item(db, item_id)
    return _item_dto(item, _base_url(request), user.id, db, full=True)


@emby_router.get("/emby/Shows/{item_id}/Seasons")
@emby_router.get("/Shows/{item_id}/Seasons")
async def get_seasons(item_id: str, request: Request,
                      user: models.WebUser = Depends(get_emby_user),
                      db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    seasons = (
        db.query(em.MediaItem)
        .filter(em.MediaItem.series_id == item.id, em.MediaItem.item_type == "season")
        .order_by(em.MediaItem.season_number)
        .all()
    )
    base = _base_url(request)
    return {"Items": [_item_dto(s, base, user.id, db) for s in seasons],
            "TotalRecordCount": len(seasons), "StartIndex": 0}


@emby_router.get("/emby/Shows/{item_id}/Episodes")
@emby_router.get("/Shows/{item_id}/Episodes")
async def get_episodes(item_id: str, request: Request,
                       user: models.WebUser = Depends(get_emby_user),
                       db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    season_id = request.query_params.get("SeasonId")
    query = db.query(em.MediaItem).filter(
        or_(em.MediaItem.series_id == item.id, em.MediaItem.parent_id == item.id),
        em.MediaItem.item_type == "episode",
    )
    if season_id:
        season = db.query(em.MediaItem).filter(em.MediaItem.guid == season_id).first()
        if season:
            query = query.filter(em.MediaItem.parent_id == season.id)
    episodes = query.order_by(em.MediaItem.season_number, em.MediaItem.episode_number).all()
    base = _base_url(request)
    return {"Items": [_item_dto(e, base, user.id, db) for e in episodes],
            "TotalRecordCount": len(episodes), "StartIndex": 0}


@emby_router.get("/emby/Shows/NextUp")
@emby_router.get("/Shows/NextUp")
async def get_next_up(request: Request, user: models.WebUser = Depends(get_emby_user),
                      db: Session = Depends(get_db)):
    limit = int(request.query_params.get("Limit") or 20)
    played_eps = (
        db.query(em.UserMediaData.item_id)
        .filter(em.UserMediaData.user_id == user.id, em.UserMediaData.played == True)  # noqa: E712
    )
    episodes = (
        db.query(em.MediaItem)
        .filter(em.MediaItem.item_type == "episode")
        .filter(~em.MediaItem.id.in_(played_eps))
        .order_by(em.MediaItem.season_number, em.MediaItem.episode_number)
        .limit(limit)
        .all()
    )
    base = _base_url(request)
    return {"Items": [_item_dto(e, base, user.id, db) for e in episodes],
            "TotalRecordCount": len(episodes), "StartIndex": 0}


@emby_router.get("/emby/Users/{user_id}/FavoriteItems")
@emby_router.get("/Users/{user_id}/FavoriteItems")
async def get_favorites(request: Request, user: models.WebUser = Depends(get_emby_user),
                        db: Session = Depends(get_db)):
    rows = (
        db.query(em.MediaItem)
        .join(em.UserMediaData, em.UserMediaData.item_id == em.MediaItem.id)
        .filter(em.UserMediaData.user_id == user.id, em.UserMediaData.is_favorite == True)  # noqa: E712
        .order_by(em.UserMediaData.updated_at.desc())
        .all()
    )
    base = _base_url(request)
    return {"Items": [_item_dto(i, base, user.id, db) for i in rows],
            "TotalRecordCount": len(rows), "StartIndex": 0}


@emby_router.get("/emby/Users/{user_id}/PlayedItems")
@emby_router.get("/Users/{user_id}/PlayedItems")
async def get_played_items(request: Request, user: models.WebUser = Depends(get_emby_user),
                           db: Session = Depends(get_db)):
    rows = (
        db.query(em.MediaItem)
        .join(em.UserMediaData, em.UserMediaData.item_id == em.MediaItem.id)
        .filter(em.UserMediaData.user_id == user.id, em.UserMediaData.played == True)  # noqa: E712
        .order_by(em.UserMediaData.last_played_at.desc())
        .all()
    )
    base = _base_url(request)
    return {"Items": [_item_dto(i, base, user.id, db) for i in rows],
            "TotalRecordCount": len(rows), "StartIndex": 0}


@emby_router.post("/emby/Users/{user_id}/Items/{item_id}/Rating")
@emby_router.post("/Users/{user_id}/Items/{item_id}/Rating")
async def rate_item(
    item_id: str, user_id: str, request: Request,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    item = _require_item(db, item_id)
    body = await request.json()
    umd = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == user.id, em.UserMediaData.item_id == item.id
    ).first()
    if not umd:
        umd = em.UserMediaData(user_id=user.id, item_id=item.id)
        db.add(umd)
    if "IsFavorite" in body:
        umd.is_favorite = bool(body["IsFavorite"])
    if "Played" in body:
        umd.played = bool(body["Played"])
        if umd.played:
            umd.play_count = (umd.play_count or 0) + 1
            umd.last_played_at = datetime.now()
    db.commit()
    return _user_data_dto(umd)


@emby_router.post("/emby/Users/{user_id}/PlayedItems/{item_id}")
@emby_router.post("/Users/{user_id}/PlayedItems/{item_id}")
async def mark_played(item_id: str, user_id: str,
                      user: models.WebUser = Depends(get_emby_user),
                      db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    umd = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == user.id, em.UserMediaData.item_id == item.id
    ).first()
    if not umd:
        umd = em.UserMediaData(user_id=user.id, item_id=item.id)
        db.add(umd)
    umd.played = True
    umd.play_count = (umd.play_count or 0) + 1
    umd.last_played_at = datetime.now()
    umd.playback_position_ticks = 0
    db.commit()
    return _user_data_dto(umd)


@emby_router.delete("/emby/Users/{user_id}/PlayedItems/{item_id}")
@emby_router.delete("/Users/{user_id}/PlayedItems/{item_id}")
async def mark_unplayed(item_id: str, user_id: str,
                        user: models.WebUser = Depends(get_emby_user),
                        db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    umd = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == user.id, em.UserMediaData.item_id == item.id
    ).first()
    if umd:
        umd.played = False
        umd.play_count = 0
        umd.playback_position_ticks = 0
        db.commit()
    return _user_data_dto(umd)


# ==================== 播放 ====================

@emby_router.post("/emby/Items/{item_id}/PlaybackInfo")
@emby_router.post("/Items/{item_id}/PlaybackInfo")
async def playback_info(
    item_id: str, request: Request,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    item = _require_item(db, item_id)
    base = _base_url(request)
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        pass
    device_profile = body.get("DeviceProfile") or {}
    max_bitrate = int(body.get("MaxStreamingBitrate") or 0) or int(
        (device_profile.get("MaxStreamingBitrate") or 0)
    ) or 120_000_000

    media_source = _media_source(item, base)
    direct = item.bitrate and item.bitrate <= max_bitrate
    media_source.update({
        "SupportsDirectPlay": True,
        "SupportsDirectStream": bool(direct),
        "SupportsTranscoding": True,
        "DirectStreamUrl": f"{base}/emby/Videos/{item.guid}/stream?static=true&MediaSourceId={item.guid}&api_key={resolve_token(db, request)[1].token if resolve_token(db, request) else ''}",
        "TranscodingUrl": f"{base}/emby/videos/{item.guid}/master.m3u8?MediaSourceId={item.guid}",
    })

    return {
        "MediaSources": [media_source],
        "PlaySessionId": item.guid[:16],
        "ErrorCode": None,
    }


@emby_router.get("/emby/Videos/{item_id}/stream")
@emby_router.get("/Videos/{item_id}/stream")
async def video_stream(
    item_id: str, request: Request,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    item = _require_item(db, item_id)
    # 授权校验：api_key 必须有效
    if not resolve_token(db, request):
        raise HTTPException(status_code=401, detail="Invalid access token")
    media_type = f"video/{item.container}" if item.container else "video/mp4"
    return serve_file(item.file_path, request, media_type)


@emby_router.get("/emby/videos/{item_id}/{transcode_path:path}")
@emby_router.get("/videos/{item_id}/{transcode_path:path}")
async def video_hls(
    item_id: str, transcode_path: str, request: Request,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    item = _require_item(db, item_id)
    base = _base_url(request)
    q = request.query_params

    # 已存在的转码会话：直接回放列表/切片
    existing = q.get("session")
    if existing and get_transcode(existing):
        info = get_transcode(existing)
        file_path = os.path.join(info["dir"], os.path.basename(transcode_path))
        if transcode_path.endswith(".m3u8"):
            content = _rewrite_playlist(info["dir"], base, item.guid, existing)
            return Response(content, media_type="application/vnd.apple.mpegurl")
        if os.path.isfile(file_path):
            media_type = "video/mp2t" if transcode_path.endswith(".ts") else "application/octet-stream"
            return FileResponse(file_path, media_type=media_type)
        raise HTTPException(status_code=404, detail="Segment not ready")

    # 新转码请求
    video_bitrate = int(q.get("VideoBitrate") or q.get("videoBitrate") or 4_000_000)
    height = int(q.get("Height") or 0) or None
    start_ticks = int(q.get("PositionTicks") or 0)
    start_seconds = start_ticks / TICKS
    session_id = start_transcode(item.file_path, start_seconds, video_bitrate, height)
    playlist_url = f"{base}/emby/videos/{item.guid}/master.m3u8?session={session_id}"
    return Response(
        content=f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH={video_bitrate},RESOLUTION=1920x1080\n{playlist_url}\n",
        media_type="application/vnd.apple.mpegurl",
    )


def _rewrite_playlist(out_dir: str, base: str, item_guid_value: str, session_id: str) -> str:
    master = os.path.join(out_dir, "master.m3u8")
    if not os.path.isfile(master):
        return "#EXTM3U\n"
    with open(master, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    lines = []
    for line in content.splitlines():
        if line.endswith(".ts"):
            lines.append(f"{base}/emby/videos/{item_guid_value}/{line}?session={session_id}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


@emby_router.get("/emby/Videos/{item_id}/hls1")
@emby_router.get("/Videos/{item_id}/hls1")
async def video_hls1(item_id: str, request: Request,
                     user: models.WebUser = Depends(get_emby_user),
                     db: Session = Depends(get_db)):
    # Emby 客户端直接请求 hls1 路径
    return await video_hls(item_id, "master.m3u8", request, user, db)


@emby_router.get("/emby/Items/{item_id}/Download")
@emby_router.get("/Items/{item_id}/Download")
async def download_item(item_id: str, request: Request,
                        user: models.WebUser = Depends(get_emby_user),
                        db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    if not item.file_path or not os.path.isfile(item.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(item.file_path, filename=os.path.basename(item.file_path))


@emby_router.get("/emby/Items/{item_id}/Images/{image_type}")
@emby_router.get("/Items/{item_id}/Images/{image_type}")
async def item_image(item_id: str, image_type: str, request: Request,
                     db: Session = Depends(get_db)):
    item = db.query(em.MediaItem).filter(em.MediaItem.guid == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if image_type == "Primary":
        src = item.poster_path or item.primary_image_url
    elif image_type in ("Backdrop", "Art", "Thumb", "Logo"):
        src = item.backdrop_path or item.backdrop_image_url
    else:
        src = None
    if not src:
        raise HTTPException(status_code=404, detail="Image not found")
    if src.startswith("http://") or src.startswith("https://"):
        # 仅允许代理 http(s) 远程图片（防 SSRF）
        import httpx

        r = httpx.get(src, timeout=10, follow_redirects=True)
        return Response(
            content=r.content,
            media_type=r.headers.get("content-type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=86400"},
        )
    return serve_image(src)


@emby_router.get("/emby/Items/{item_id}/Images/Primary/{index}")
@emby_router.get("/Items/{item_id}/Images/Primary/{index}")
async def item_image_index(item_id: str, image_type: str, index: str, request: Request,
                           db: Session = Depends(get_db)):
    return await item_image(item_id, "Primary", request, db)


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
async def session_capabilities(request: Request, user: models.WebUser = Depends(get_emby_user)):
    return {"success": True}


@emby_router.get("/emby/Sessions")
@emby_router.get("/Sessions")
async def get_sessions(request: Request, db: Session = Depends(get_db)):
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
async def stop_session(session_key: str, db: Session = Depends(get_db)):
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
async def livetv_channels():
    return {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}


@emby_router.get("/emby/DisplayPreferences/users")
@emby_router.get("/DisplayPreferences/users")
async def display_prefs(request: Request, user: models.WebUser = Depends(get_emby_user)):
    return {"Id": "users", "CustomPrefs": {}}


@emby_router.post("/emby/DisplayPreferences/users")
@emby_router.post("/DisplayPreferences/users")
async def save_display_prefs(request: Request, user: models.WebUser = Depends(get_emby_user)):
    return {"success": True}


@emby_router.get("/emby/Localization/Culture")
@emby_router.get("/Localization/Culture")
async def localization_cultures():
    return [
        {"Name": "Chinese (Simplified)", "TwoLetterISOLanguageName": "zh", "ThreeLetterISOLanguageName": "chi"},
        {"Name": "English", "TwoLetterISOLanguageName": "en", "ThreeLetterISOLanguageName": "eng"},
    ]


@emby_router.get("/emby/Localization/countries")
@emby_router.get("/Localization/countries")
async def localization_countries():
    return [{"Name": "China", "TwoLetterISOLanguageName": "cn", "ThreeLetterISOLanguageName": "CHN"}]


@emby_router.get("/emby/Web/DefaultRoutingMap")
@emby_router.get("/Web/DefaultRoutingMap")
async def default_routing_map():
    return {"Routes": []}


@emby_router.get("/emby/MediaBackup/Status")
@emby_router.get("/MediaBackup/Status")
async def media_backup_status():
    return {"Status": "Disabled"}


@emby_router.get("/emby/swagger.json")
@emby_router.get("/swagger.json")
async def swagger_json():
    return {"swagger": "2.0", "info": {"title": "Emby", "version": SERVER_VERSION}, "paths": {}}


@emby_router.get("/emby/quickconnect/info")
@emby_router.get("/quickconnect/info")
async def quickconnect_info():
    return {"Available": False, "State": "Unavailable"}
