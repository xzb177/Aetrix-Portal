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

import hashlib
import json
import logging
import os
import secrets
import shutil
import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from backend import models
from backend.database import SessionLocal, get_db
from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib
from backend.emby_server import subtitles as subs
from backend.emby_server.auth import (
    get_emby_user,
    parse_emby_authorization,
    resolve_token,
)
from backend.emby_server.scanner import (
    item_guid,
    parse_media_filename,
    scan_library_sync,
    count_virtual_items,
)
from backend.emby_server.search import (
    CANDIDATE_LIMIT as SEARCH_CANDIDATE_LIMIT,
    rank_items,
    search_variants,
)
from backend.emby_server.streaming import (
    get_transcode,
    serve_file,
    serve_image,
    serve_remote,
    start_transcode,
    stop_all_transcodes,
    stop_transcode,
    stop_user_transcodes,
    transcode_alive,
    wait_for_file,
)
from backend.subscriptions import ensure_download_allowed, ensure_playback_allowed

logger = logging.getLogger(__name__)

emby_router = APIRouter(tags=["EmbyServer"])

TICKS = 10_000_000
SERVER_VERSION = "4.8.0.0"
SERVER_ID = os.getenv("EMBY_SERVER_ID", "royalbot-emby-server")


def _iso(dt) -> str:
    return dt.isoformat() if dt else None


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _image_chain(item: em.MediaItem, kind: str, db: Session) -> list[str]:
    """图片回退链：条目自身 → 季 → 剧集海报

    季与集常常没有自己的图片；不回退就会整库空白图。
    """
    def srcs(it: em.MediaItem) -> list[str]:
        if kind == "Primary":
            return [it.primary_image_url or "", it.poster_path or ""]
        return [it.backdrop_image_url or "", it.backdrop_path or ""]

    chain = srcs(item)
    if item.item_type in ("episode", "season"):
        parents: list[em.MediaItem] = []
        if item.parent_id:
            parent = db.query(em.MediaItem).filter(em.MediaItem.id == item.parent_id).first()
            if parent:
                parents.append(parent)
        series = item.series
        if series is not None and series not in parents:
            parents.append(series)
        for parent in parents:
            chain.extend(srcs(parent))
    return [s for s in chain if s]


def _first_image(item: em.MediaItem, kind: str, db: Session) -> str | None:
    chain = _image_chain(item, kind, db)
    return chain[0] if chain else None


def _queue_image_repair(db: Session, item: em.MediaItem, stale_src: str) -> None:
    """把“数据库有图、取不到图”的条目排进修复队列

    重新刮削时会换成 TMDB 远程图；同时把失效的本地路径清掉，避免每次请求都白读一次磁盘。
    """
    try:
        changed = False
        if stale_src and not stale_src.startswith("http"):
            if item.poster_path == stale_src:
                item.poster_path = None
                changed = True
            if item.backdrop_path == stale_src:
                item.backdrop_path = None
                changed = True
        if item.repair_requested_at is None:
            item.repair_requested_at = datetime.now()
            changed = True
        if changed:
            db.commit()
    except Exception as e:  # noqa: BLE001 — 修复排队失败不能影响图片接口本身
        logger.warning("图片修复排队失败 item=%s: %s", item.guid, e)
        db.rollback()


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


def _download_ok(db: Session) -> bool:
    """站点是否允许下载（按 Session 缓存，避免列表里每个条目都查一次配置）"""
    cache = db.info.setdefault("_royalbot_download_ok", {})
    if "value" not in cache:
        from backend.subscriptions import download_allowed

        cache["value"] = download_allowed(db)
    return cache["value"]


def _item_dto(item: em.MediaItem, base: str, user_id: int, db: Session, full: bool = False,
              api_key: str = "") -> dict:
    download_ok = _download_ok(db)
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
        # 客户端靠 RunTimeTicks 展示时长/进度条，缺失会导致进度条不可用
        "RunTimeTicks": item.duration_ticks or None,
        "Container": item.container,
        "Bitrate": item.bitrate or None,
        "IsHD": bool((item.height or 0) >= 720),
        "OriginalTitle": item.original_title or None,
        # 客户端会用 ProviderIds 展示/跳转元数据源；补上 IMDb
        "ProviderIds": {
            k: v for k, v in (("Tmdb", item.tmdb_id), ("Imdb", item.imdb_id)) if v
        },
        "ImageTags": {"Primary": "1"} if _image_url(base, item) else {},
        "BackdropImageTags": ["1"] if _image_url(base, item, "Backdrop") else {},
        "UserData": _user_data_dto(umd),
        # 下载能力随站点配置变化（关闭下载后客户端不再展示下载入口）
        "CanDownload": download_ok,
        "SupportsContentDownloading": download_ok,
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
        dto["MediaSources"] = [_media_source(item, base, api_key)]
        dto["MediaSourceCount"] = 1
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


def _bearer_raw(request: Request) -> str:
    """提取原始 Bearer 值（JWT 或客户端 token），用于拼接 api_key 查询参数"""
    raw = request.headers.get("Authorization", "")
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return request.query_params.get("api_key", "")


def _stream_dto(s, base: str, item: em.MediaItem, api_key: str) -> dict:
    dto = {
        "Index": s.stream_index, "Type": s.stream_type, "Codec": s.codec,
        "Language": s.language, "DisplayTitle": s.display_title or s.language,
        "Title": s.title, "IsDefault": bool(s.is_default),
        "IsForced": bool(s.is_forced), "IsExternal": bool(s.is_external),
        "Channels": s.channels, "BitRate": s.bit_rate,
    }
    if (s.stream_type or "").lower() == "subtitle":
        text_track = subs.is_text_track(s.codec)
        dto["IsTextSubtitleStream"] = text_track
        dto["SupportsExternalStream"] = text_track
        dto["DeliveryMethod"] = "External"
        if text_track:
            # 客户端靠 DeliveryUrl 发现字幕地址；缺失会表现为“服务器无字幕”
            dto["DeliveryUrl"] = (
                f"{base}/emby/Videos/{item.guid}/{item.guid}"
                f"/Subtitles/{s.stream_index}/Stream.vtt?api_key={api_key}"
            )
    return dto


def _default_subtitle_index(item: em.MediaItem):
    for s in item.streams:
        if (s.stream_type or "").lower() == "subtitle" and subs.is_text_track(s.codec):
            return s.stream_index
    return None


def _media_source(item: em.MediaItem, base: str, api_key: str = "") -> dict:
    return {
        "Id": item.guid,
        "Name": item.name,
        "Path": item.file_path,
        "Protocol": "File",
        "Type": "Default",
        "Container": item.container,
        "Size": item.size,
        "RunTimeTicks": item.duration_ticks or None,
        "Bitrate": item.bitrate or None,
        "SupportsDirectPlay": True,
        "SupportsDirectStream": True,
        "SupportsTranscoding": True,
        "IsRemote": False,
        "DefaultSubtitleStreamIndex": _default_subtitle_index(item),
        "MediaStreams": [_stream_dto(s, base, item, api_key) for s in item.streams],
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

# 客户端发现服务时第一条请求就是它：Emby 官方文档写的是 /emby/System/Info/Public，
# 而别的客户端可能会用裸路径或全小写，所以三种写法都注册（缺一个就会 404 连不上）。
@emby_router.get("/emby/System/Info")
@emby_router.get("/emby/System/Info/Public")
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
        # 未实现 /Sync/* 离线同步接口，如实上报 False，避免客户端尝试无法完成的离线同步
        "SupportsSynchronization": False,
        "StartupWizardCompleted": True,
        "HasUpdateAvailable": False,
        "CastReceiverApplications": [],
        "CanSelfRestart": False,
        "CanLaunchWebApp": True,
        "HavePendingRestart": False,
        "CompletedInstallations": [],
    }


@emby_router.get("/emby/System/Ping")
@emby_router.get("/emby/system/ping")
@emby_router.get("/System/Ping")
async def system_ping():
    return PlainTextResponse("Emby Server")


@emby_router.post("/emby/System/Ping")
@emby_router.post("/emby/system/ping")
@emby_router.post("/System/Ping")
async def system_ping_post():
    return PlainTextResponse("Emby Server")


@emby_router.get("/emby/Branding/Configuration")
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

    def _auth_fail(detail: str = "用户名或密码错误"):
        from backend.authlog import record_event

        record_event(
            db, username=username, user_id=user.id if user else None, ip=ip,
            agent=request.headers.get("user-agent"), success=False,
            reason="emby_login_failed", detail=detail,
        )
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

    # 设备数上限：超限时拒绝签发（管理员不受限），并落安全日志
    from backend.authlog import record_event
    from backend.devices import DeviceLimitExceeded

    try:
        token_value, token_row = issue_token(db, user, request)
    except DeviceLimitExceeded as exc:
        record_event(
            db, username=user.username, user_id=user.id, ip=ip,
            agent=request.headers.get("user-agent"), success=False,
            reason="device_limit", detail=exc.message,
        )
        return Response(
            content=json.dumps({"error": "DeviceLimitExceeded", "message": exc.message},
                               ensure_ascii=False),
            status_code=403, media_type="application/json; charset=utf-8",
        )

    auth = parse_emby_authorization(request.headers.get("X-Emby-Authorization"))
    record_event(
        db, username=user.username, user_id=user.id, ip=ip,
        agent=request.headers.get("user-agent"), success=True, reason="emby_login",
        detail=f"{auth.get('Client') or 'Emby Client'} / {token_row.device_id}",
    )
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


# ==================== 客户端兼容公共工具 ====================


def _guid_of(kind: str, name: str) -> str:
    """按名称生成稳定的 Emby 风格 32 位 Id（用于 Genre/Studio 等虚拟条目）"""
    return hashlib.md5(f"{kind}:{name}".encode("utf-8")).hexdigest()


def _virtual_libraries_enabled() -> bool:
    """虚拟媒体库总开关（按 EA 实例生效）

    关闭时虚拟媒体库既不出现在客户端视图里，直接用 guid 访问也会 404，
    与“未开启时不会出现在客户端或直达接口”一致。
    """
    return os.getenv("ENABLE_VIRTUAL_LIBRARIES", "true").strip().lower() not in ("0", "false", "no")


def _synthetic_map(db: Session) -> dict[str, tuple[str, str]]:
    """{合成 Id: (类型, 名称)} 反查表（类型 / 工作室 / 年份 右键筛选用）

    客户端点开「类型 / 制作公司 / 年份」后会带着我们生成的 Id 再请求 /Items。
    旧实现找不到条目就退回按 guid 匹配，等于返回空（或整库）——点进去白点。
    """
    buckets: dict[str, set[str]] = {"Genre": set(), "Studio": set(), "Year": set()}
    for genres, studios, year in db.query(
        em.MediaItem.genres, em.MediaItem.studios, em.MediaItem.production_year
    ).all():
        buckets["Genre"].update(g for g in (genres or "").split(",") if g)
        buckets["Studio"].update(s for s in (studios or "").split(",") if s)
        if year:
            buckets["Year"].add(str(year))
    return {
        _guid_of(kind, name): (kind, name)
        for kind, names in buckets.items()
        for name in names
    }


def _synthetic_lookup(db: Session) -> dict[str, tuple[str, str]]:
    """按请求缓存反查表，列表接口里不会重复扫描全库"""
    cached = db.info.get("_royalbot_synthetic_ids")
    if cached is None:
        cached = _synthetic_map(db)
        db.info["_royalbot_synthetic_ids"] = cached
    return cached


def _empty_items() -> dict:
    return {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}


def _query_result(items: list, user: models.WebUser, db: Session, base: str) -> dict:
    return {
        "Items": [_item_dto(i, base, user.id, db) for i in items],
        "TotalRecordCount": len(items),
        "StartIndex": 0,
    }


def _api_key_for(db: Session, request: Request) -> str:
    """拼接播放/字幕地址用的 api_key：客户端 token 优先，其次门户 JWT"""
    token_row = resolve_token(db, request)
    return token_row[1].token if token_row else _bearer_raw(request)


def _policy_dto(user: models.WebUser) -> dict:
    return {
        "IsAdministrator": bool(user.is_staff),
        "IsDisabled": not bool(user.is_active),
        "EnableContentDeletion": bool(user.is_staff),
        "EnableContentDownloading": True,
        "EnableMediaPlayback": True,
        "EnableAudioPlaybackTranscoding": True,
        "EnableVideoPlaybackTranscoding": True,
        "EnablePlaybackRemuxing": True,
        "EnableSyncTranscoding": False,
        "EnableAllDevices": True,
        "EnableAllFolders": True,
        "SimultaneousStreamLimit": 3,
        "InvalidLoginAttemptCount": 0,
    }


# ---- 用户：/Users/Public、/Users/Me 必须注册在 /Users/{user_id} 之前 ----

@emby_router.get("/emby/Users/Public")
@emby_router.get("/Users/Public")
async def users_public():
    """客户端登录页的用户列表

    按 Jellyfin 默认隐私策略返回空数组：本服务账号即门户账号，未认证地枚举用户列表
    会泄露全站账号。返回空列表（而非 404）让客户端走“手动输入用户名”分支。
    """
    return []


@emby_router.get("/emby/Users/Me")
@emby_router.get("/Users/Me")
async def users_me(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    return _user_dto(user, db)


@emby_router.get("/emby/Users")
@emby_router.get("/Users")
async def users_list(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    if not user.is_staff:
        raise HTTPException(status_code=403, detail="Forbidden")
    rows = db.query(models.WebUser).filter(models.WebUser.is_active == True).all()  # noqa: E712
    return [_user_dto(u, db) for u in rows]


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
    virtual_on = _virtual_libraries_enabled()
    items = []
    for lib in libs:
        is_virtual = bool(getattr(lib, "is_virtual", False))
        # 虚拟媒体库（按发行平台生成）：只在总开关 + 该库开启时才出现在客户端
        if is_virtual and not virtual_on:
            continue
        items.append({
            "Name": lib.name,
            "Id": lib.guid,
            "Type": "CollectionFolder",
            # 虚拟库跨电影/剧集聚合，统一按 mixed 上报，客户端才能正常当普通文件夹浏览
            "CollectionType": "mixed" if is_virtual else lib.collection_type,
            "IsFolder": True,
            "UserData": {"PlaybackPositionTicks": 0, "PlayCount": 0, "Played": False, "IsFavorite": False},
            "ImageTags": {"Primary": "1"},
            "ChildCount": count_virtual_items(db, lib) if is_virtual else lib.item_count,
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
    random_sort = any(c.strip().lower() == "random" for c in sort_by)
    ids = [x.strip() for value in q.getlist("Ids") for x in value.split(",") if x.strip()]

    def _synthetic_names(kind: str, param: str) -> list[str]:
        """把客户端回传的 类型/工作室/年份 Id 还原成名称

        Emby 客户端点「类型/制作公司/年份」时，会用我们给出的**合成 Id**
        再请求 /Items（ParentId 或 GenreIds/StudioIds 参数）。
        """
        raw = [x.strip() for value in q.getlist(param) for x in value.split(",") if x.strip()]
        if not raw:
            return []
        lookup = _synthetic_lookup(db)
        out: list[str] = []
        for rid in raw:
            hit = lookup.get(rid)
            if hit and hit[0] == kind and hit[1] not in out:
                out.append(hit[1])
        return out

    # Filters / IsFavorite 等筛选：客户端“只看收藏 / 已看 / 未看 / 继续观看”依赖它，
    # 旧实现忽略这些参数，导致筛选后返回全量。
    filters = {f.strip().lower() for f in (q.get("Filters") or "").split(",") if f.strip()}
    for flag in ("IsFavorite", "IsPlayed", "IsUnplayed", "IsResumable"):
        if (q.get(flag) or "").lower() == "true":
            filters.add(flag.lower())

    query = db.query(em.MediaItem).filter(em.MediaItem.is_hidden == False)  # noqa: E712

    if ids:
        query = query.filter(em.MediaItem.guid.in_(ids))

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
                if getattr(lib, "is_virtual", False):
                    # 虚拟媒体库：跨库的发行平台视图；未开启时直达也 404
                    if not (_virtual_libraries_enabled() and lib.is_enabled):
                        raise HTTPException(status_code=404, detail="Not found")
                    platform = (lib.platform or "").strip()
                    query = (
                        query.filter(em.MediaItem.platforms.ilike(f"%{platform}%"))
                        if platform else query.filter(em.MediaItem.id == -1)
                    )
                else:
                    query = query.filter(em.MediaItem.library_id == lib.id)
            else:
                # 类型 / 工作室 / 年份的合成 Id：点进去要得到真实筛选结果
                hit = _synthetic_lookup(db).get(parent_id)
                if hit and hit[0] == "Genre":
                    query = query.filter(em.MediaItem.genres.ilike(f"%{hit[1]}%"))
                elif hit and hit[0] == "Studio":
                    query = query.filter(em.MediaItem.studios.ilike(f"%{hit[1]}%"))
                elif hit and hit[0] == "Year" and str(hit[1]).isdigit():
                    query = query.filter(em.MediaItem.production_year == int(hit[1]))
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
        # SQL 预筛：标题族 + 别名族，并把繁简/发布标签变体一起放进来，
        # 精排交给 rank_items（完全匹配 > 前缀 > 别名 > 分类 > 模糊）。
        clauses = []
        for variant in search_variants(search):
            like = f"%{variant}%"
            clauses.extend([
                em.MediaItem.name.ilike(like),
                em.MediaItem.original_title.ilike(like),
                em.MediaItem.sort_name.ilike(like),
                em.MediaItem.aliases.ilike(like),
            ])
        if clauses:
            query = query.filter(or_(*clauses))

    genre_names = [g for g in genres if g] or _synthetic_names("Genre", "GenreIds")
    if genre_names:
        query = query.filter(or_(*[em.MediaItem.genres.ilike(f"%{g}%") for g in genre_names]))

    studio_names = _synthetic_names("Studio", "StudioIds")
    if studio_names:
        query = query.filter(or_(*[em.MediaItem.studios.ilike(f"%{s}%") for s in studio_names]))

    year_values: list[int] = []
    for y in years:
        if y and y.strip().isdigit():
            year_values.append(int(y))
    for name in _synthetic_names("Year", "Years"):
        if name.isdigit() and int(name) not in year_values:
            year_values.append(int(name))
    if year_values:
        query = query.filter(em.MediaItem.production_year.in_(year_values))

    if filters & {"isfavorite", "isplayed", "isunplayed", "isresumable"}:
        query = query.outerjoin(
            em.UserMediaData,
            (em.UserMediaData.item_id == em.MediaItem.id)
            & (em.UserMediaData.user_id == user.id),
        )
        if "isfavorite" in filters:
            query = query.filter(em.UserMediaData.is_favorite == True)  # noqa: E712
        if "isplayed" in filters:
            query = query.filter(em.UserMediaData.played == True)  # noqa: E712
        if "isunplayed" in filters:
            query = query.filter(
                or_(em.UserMediaData.played == False, em.UserMediaData.played.is_(None))  # noqa: E712
            )
        if "isresumable" in filters:
            query = query.filter(em.UserMediaData.playback_position_ticks > 0)

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

    if search and not random_sort:
        # 搜索时按相关度排版。旧实现只用 SQL LIKE 过滤 + 按名称排序，
        # 于是精确命中的标题会被“名字里恰好也含这几个字”的条目挤到后面。
        candidates = (
            query.order_by(em.MediaItem.sort_name.asc()).limit(SEARCH_CANDIDATE_LIMIT).all()
        )
        ranked = rank_items(candidates, search)  # 相关度排序（完全匹配 > 前缀 > 别名 > 模糊）
        page = ranked[start:start + limit]
        return {
            "Items": [_item_dto(i, base, user.id, db) for i in page],
            "TotalRecordCount": len(ranked),
            "StartIndex": start,
        }

    total = query.count()
    data_query = query.order_by(func.random()) if random_sort else query.order_by(*order_cols)
    items = data_query.offset(start).limit(limit).all()

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


# /Items/Counts、/Items/Filters、/Items/Intros 必须注册在 /Items/{item_id} 之前，
# 否则会被当成 guid 解析而 404。

@emby_router.get("/emby/Items/Counts")
@emby_router.get("/Items/Counts")
async def items_counts(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    def _count(item_type: str) -> int:
        return (
            db.query(em.MediaItem)
            .filter(em.MediaItem.item_type == item_type, em.MediaItem.is_hidden == False)  # noqa: E712
            .count()
        )

    return {
        "MovieCount": _count("movie"),
        "SeriesCount": _count("series"),
        "EpisodeCount": _count("episode"),
        "ItemCount": db.query(em.MediaItem).count(),
        "AlbumCount": 0, "SongCount": 0, "ArtistCount": 0, "AlbumArtistCount": 0,
        "MusicVideoCount": 0, "TrailerCount": 0, "BoxSetCount": 0, "BookCount": 0,
    }


@emby_router.get("/emby/Items/Intros")
@emby_router.get("/Items/Intros")
async def items_intros(user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


def _filters_payload(db: Session) -> dict:
    genres: set = set()
    tags: set = set()
    ratings: set = set()
    years: set = set()
    for item in db.query(em.MediaItem).filter(em.MediaItem.is_hidden == False).all():  # noqa: E712
        genres.update(g for g in (item.genres or "").split(",") if g)
        tags.update(t for t in (item.tags or "").split(",") if t)
        if item.official_rating:
            ratings.add(item.official_rating)
        if item.production_year:
            years.add(item.production_year)
    return {
        "Genres": sorted(genres),
        "Tags": sorted(tags),
        "OfficialRatings": sorted(ratings),
        "Years": sorted(years, reverse=True),
    }


@emby_router.get("/emby/Items/Filters")
@emby_router.get("/Items/Filters")
@emby_router.get("/emby/Items/Filters2")
@emby_router.get("/Items/Filters2")
async def items_filters(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    return _filters_payload(db)


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
    return _item_dto(item, _base_url(request), user.id, db, full=True,
                     api_key=_api_key_for(db, request))


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

def _play_target(db: Session, item: em.MediaItem):
    """把条目的 ``file_path`` 解析成播放目标（本机文件 或 挂载直链）

    挂载来源（115 / WebDAV / AList / STRM）解析失败时给出明确状态码，不抛 500：

    - 挂载被删除 / 停用 → 404（该条目需要重新扫描或重新绑定挂载）
    - 凭据失效（Cookie / 令牌 / 密码）→ 503（可修，修好后重试即可）
    """
    try:
        return mount_lib.resolve_play_target(item.file_path, db, item.library)
    except mount_lib.MountAuthError as exc:
        raise HTTPException(status_code=503, detail=f"媒体来源凭据失效：{exc}")
    except mount_lib.MountError as exc:
        raise HTTPException(status_code=404, detail=f"媒体来源不可用：{exc}")


@emby_router.post("/emby/Items/{item_id}/PlaybackInfo")
@emby_router.post("/Items/{item_id}/PlaybackInfo")
@emby_router.get("/emby/Items/{item_id}/PlaybackInfo")
@emby_router.get("/Items/{item_id}/PlaybackInfo")
@emby_router.post("/emby/Users/{user_id}/Items/{item_id}/PlaybackInfo")
@emby_router.post("/Users/{user_id}/Items/{item_id}/PlaybackInfo")
@emby_router.get("/emby/Users/{user_id}/Items/{item_id}/PlaybackInfo")
@emby_router.get("/Users/{user_id}/Items/{item_id}/PlaybackInfo")
async def playback_info(
    item_id: str, request: Request, user_id: str = "",
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    item = _require_item(db, item_id)
    # 付费墙：未订阅不发放播放地址（网页端据此展示开通引导，客户端同样不能绕过）
    ensure_playback_allowed(db, user)
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
    # api_key：优先 Emby 客户端 token；JWT 访问时（网页端）直接把 JWT 作为 api_key，
    # 流媒体端点（stream/master.m3u8/切片）均可通过 JWT 回退鉴权
    api_key = _api_key_for(db, request)
    media_source.update({
        "SupportsDirectPlay": True,
        "SupportsDirectStream": bool(direct),
        "SupportsTranscoding": True,
        "DirectStreamUrl": f"{base}/emby/Videos/{item.guid}/stream?static=true&MediaSourceId={item.guid}&api_key={api_key}",
        "TranscodingUrl": f"{base}/emby/videos/{item.guid}/master.m3u8?MediaSourceId={item.guid}&api_key={api_key}",
    })

    return {
        "MediaSources": [media_source],
        # 每次播放会话一个独立票据，客户端据此上报进度
        "PlaySessionId": secrets.token_hex(8),
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
    # 授权已由 get_emby_user 依赖完成（Emby token 或 JWT 均可）
    ensure_playback_allowed(db, user)
    media_type = f"video/{item.container}" if item.container else "video/mp4"
    target = _play_target(db, item)
    if target.kind == "url":
        # 挂载来源（115 / WebDAV / AList / STRM 直链）：由本服务代理转发，
        # Range 与状态码透传，凭据不下发。
        return serve_remote(target.value, request, target.headers, media_type)
    return serve_file(target.value, request, media_type)


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
    # 注意：切片请求走 session 票据校验（HLS 播放器无法对切片附加 api_key），
    # 会话本身只在建立转码（master.m3u8 首次请求）时经过完整鉴权创建。
    api_key = _api_key_for(db, request)
    existing = q.get("session")
    if existing and get_transcode(existing):
        info = get_transcode(existing)
        file_path = os.path.join(info["dir"], os.path.basename(transcode_path))
        if transcode_path.endswith(".m3u8"):
            playlist = os.path.join(info["dir"], "master.m3u8")
            # ffmpeg 写完首个切片才落盘播放列表；直接返回空列表会让播放器判定播放失败
            wait_for_file(playlist, timeout=15.0)
            if not os.path.isfile(playlist):
                if not transcode_alive(existing):
                    raise HTTPException(status_code=503, detail="转码进程已退出，请重新发起播放")
                raise HTTPException(status_code=504, detail="转码尚未产出播放列表")
            content = _rewrite_playlist(info["dir"], base, item.guid, existing, api_key)
            return Response(content, media_type="application/vnd.apple.mpegurl")
        # 客户端请求切片往往早于 ffmpeg 写出，短暂等待而非立即 404
        if not wait_for_file(file_path, timeout=12.0):
            if not transcode_alive(existing):
                raise HTTPException(status_code=503, detail="转码进程已退出，请重新发起播放")
            raise HTTPException(status_code=404, detail="Segment not ready")
        media_type = "video/mp2t" if transcode_path.endswith(".ts") else "application/octet-stream"
        return FileResponse(file_path, media_type=media_type)

    # 新转码请求（付费墙：建立转码会话前校验）
    ensure_playback_allowed(db, user)
    if not shutil.which(os.getenv("EMBY_FFMPEG_PATH", "ffmpeg")):
        raise HTTPException(status_code=503, detail="服务器未安装 ffmpeg，无法转码；请使用直连播放")
    video_bitrate = int(q.get("VideoBitrate") or q.get("videoBitrate") or 4_000_000)
    height = int(q.get("Height") or 0) or None
    start_ticks = int(q.get("PositionTicks") or 0)
    start_seconds = start_ticks / TICKS
    target = _play_target(db, item)
    session_id = start_transcode(
        target.value, start_seconds, video_bitrate, height,
        user_id=user.id, item_guid=item.guid, input_headers=target.headers,
    )
    # 变体与切片地址必须自带 api_key：hls.js 等播放器不会给子请求附加认证头，
    # 旧实现只带 session 导致全部子请求 401（网页端 HLS 播放实际不可用）。
    variant_url = (
        f"{base}/emby/videos/{item.guid}/main.m3u8"
        f"?session={session_id}&api_key={urllib.parse.quote(api_key)}"
    )
    return Response(
        content=f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH={video_bitrate}\n{variant_url}\n",
        media_type="application/vnd.apple.mpegurl",
    )


def _rewrite_playlist(out_dir: str, base: str, item_guid_value: str, session_id: str,  # noqa: D401
                     api_key: str = "") -> str:
    """重写 ffmpeg 播放列表：切片指向本服务，并带上 session 票据与 api_key

    不带 api_key 时播放器对切片子请求不会附加认证头，会直接 401。
    """
    master = os.path.join(out_dir, "master.m3u8")
    if not os.path.isfile(master):
        return "#EXTM3U\n"
    with open(master, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    suffix = f"&api_key={urllib.parse.quote(api_key)}" if api_key else ""
    lines = []
    for line in content.splitlines():
        if line.endswith((".ts", ".m4s", ".aac", ".vtt")):
            lines.append(f"{base}/emby/videos/{item_guid_value}/{line}?session={session_id}{suffix}")
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
    # 付费墙：下载与在线播放同一门槛，避免绕过
    ensure_playback_allowed(db, user)
    # 站点级下载开关：第三方播放器触发的下载同样拦下
    ensure_download_allowed(db, user)
    target = _play_target(db, item)
    if target.kind == "url":
        return serve_remote(
            target.value, request, target.headers,
            media_type="application/octet-stream",
        )
    return FileResponse(target.value, filename=os.path.basename(target.value))


@emby_router.get("/emby/Items/{item_id}/Images/{image_type}")
@emby_router.get("/Items/{item_id}/Images/{image_type}")
async def item_image(item_id: str, image_type: str, request: Request,
                     db: Session = Depends(get_db)):
    """条目图片

    三处修正：

    1. **季/集回退**：季与集经常没有自己的图片，按「条目 → 季 → 剧集海报」回退；
    2. **数据库有记录但文件丢失**：不再把 FileNotFoundError 抛成 5xx（客户端会当成
       鉴权/服务器故障反复重试），而是干净地 404，同时把条目排进修复队列，
       下一轮扫描换成 TMDB 远程图；
    3. **远程图取不到**（404/超时）同样 404 并排队修复，而不是 500。
    """
    item = db.query(em.MediaItem).filter(em.MediaItem.guid == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if image_type not in ("Primary", "Backdrop", "Art", "Thumb", "Logo"):
        raise HTTPException(status_code=404, detail="Image not found")
    kind = "Primary" if image_type == "Primary" else "Backdrop"
    src = _first_image(item, kind, db)
    if not src:
        raise HTTPException(status_code=404, detail="Image not found")
    if src.startswith("http://") or src.startswith("https://"):
        # 仅允许代理 http(s) 远程图片（防 SSRF）
        import httpx

        try:
            r = httpx.get(src, timeout=10, follow_redirects=True)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — 远程图失效不能让图片接口 5xx
            logger.warning("远程图片获取失败 %s: %s", src, e)
            _queue_image_repair(db, item, src)
            raise HTTPException(status_code=404, detail="Image not found") from e
        return Response(
            content=r.content,
            media_type=r.headers.get("content-type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=86400"},
        )
    if not os.path.isfile(src):
        # 数据库有图、本地文件已丢（换盘/迁移/挂载掉线）
        logger.warning("本地图片文件缺失，已排队修复：%s", src)
        _queue_image_repair(db, item, src)
        raise HTTPException(status_code=404, detail="Image not found")
    return serve_image(src)


@emby_router.get("/emby/Items/{item_id}/Images/{image_type}/{index}")
@emby_router.get("/Items/{item_id}/Images/{image_type}/{index}")
async def item_image_index(item_id: str, image_type: str, index: str, request: Request,
                           db: Session = Depends(get_db)):
    # 客户端普遍请求 /Images/Backdrop/0、/Images/Primary/0 这类带序号的地址。
    # 旧实现只注册了 Primary，其它类型（Backdrop/Thumb 等）会直接 404。
    return await item_image(item_id, image_type, request, db)


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
async def get_user_policy(user_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _policy_dto(user)


@emby_router.post("/emby/Users/{user_id}/Policy")
@emby_router.post("/Users/{user_id}/Policy")
async def set_user_policy(user_id: str, user: models.WebUser = Depends(get_emby_user)):
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
async def add_favorite(item_id: str, user_id: str,
                       user: models.WebUser = Depends(get_emby_user),
                       db: Session = Depends(get_db)):
    return _set_favorite(db, user, item_id, True)


@emby_router.delete("/emby/Users/{user_id}/FavoriteItems/{item_id}")
@emby_router.delete("/Users/{user_id}/FavoriteItems/{item_id}")
async def remove_favorite(item_id: str, user_id: str,
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
async def similar_items(item_id: str, request: Request,
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
async def item_ancestors(item_id: str, request: Request,
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
async def local_trailers(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/SpecialFeatures")
@emby_router.get("/Items/{item_id}/SpecialFeatures")
async def special_features(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/ThemeVideos")
@emby_router.get("/Items/{item_id}/ThemeVideos")
@emby_router.get("/emby/Items/{item_id}/ThemeSongs")
@emby_router.get("/Items/{item_id}/ThemeSongs")
async def theme_items(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/ThemeMedia")
@emby_router.get("/Items/{item_id}/ThemeMedia")
async def theme_media(item_id: str, user: models.WebUser = Depends(get_emby_user)):
    return {
        "ThemeVideosResult": _empty_items(),
        "ThemeSongsResult": _empty_items(),
        "SoundtrackSongsResult": _empty_items(),
    }


@emby_router.get("/emby/Items/{item_id}/Intros")
@emby_router.get("/Items/{item_id}/Intros")
@emby_router.get("/emby/Users/{user_id}/Items/{item_id}/Intros")
@emby_router.get("/Users/{user_id}/Items/{item_id}/Intros")
async def item_intros(item_id: str, user_id: str = "",
                      user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


@emby_router.get("/emby/Items/{item_id}/CriticReviews")
@emby_router.get("/Items/{item_id}/CriticReviews")
async def critic_reviews(item_id: str, user: models.WebUser = Depends(get_emby_user)):
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
async def genres_list(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    names = sorted({g for row in db.query(em.MediaItem.genres).all()
                    for g in (row[0] or "").split(",") if g})
    return _named_items("Genre", names)


@emby_router.get("/emby/Genres/{name}")
@emby_router.get("/Genres/{name}")
async def genre_by_name(name: str, user: models.WebUser = Depends(get_emby_user)):
    return {"Name": name, "Id": _guid_of("Genre", name), "Type": "Genre",
            "ImageTags": {}, "BackdropImageTags": []}


@emby_router.get("/emby/Studios")
@emby_router.get("/Studios")
async def studios_list(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    names = sorted({s for row in db.query(em.MediaItem.studios).all()
                    for s in (row[0] or "").split(",") if s})
    return _named_items("Studio", names)


@emby_router.get("/emby/Persons")
@emby_router.get("/Persons")
async def persons_list(user: models.WebUser = Depends(get_emby_user)):
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
async def system_endpoint(user: models.WebUser = Depends(get_emby_user)):
    return {"IsLocal": True, "IsInNetwork": True}


@emby_router.post("/emby/Sessions/Logout")
@emby_router.post("/Sessions/Logout")
async def sessions_logout(request: Request, user: models.WebUser = Depends(get_emby_user),
                          db: Session = Depends(get_db)):
    resolved = resolve_token(db, request)
    if resolved:
        resolved[1].is_revoked = True
        db.commit()
    return {"success": True}


@emby_router.get("/emby/Localization/ParentalRatings")
@emby_router.get("/Localization/ParentalRatings")
async def parental_ratings(user: models.WebUser = Depends(get_emby_user)):
    return []


@emby_router.get("/emby/Plugins")
@emby_router.get("/Plugins")
async def plugins(user: models.WebUser = Depends(get_emby_user)):
    return []


@emby_router.get("/emby/ScheduledTasks")
@emby_router.get("/ScheduledTasks")
async def scheduled_tasks(user: models.WebUser = Depends(get_emby_user)):
    return []


@emby_router.get("/emby/Activity/Log/Entries")
@emby_router.get("/Activity/Log/Entries")
async def activity_log(user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


# ---- 转码释放 / 库刷新 ----

@emby_router.delete("/emby/Videos/ActiveEncodings")
@emby_router.delete("/Videos/ActiveEncodings")
@emby_router.post("/emby/Videos/ActiveEncodings/Delete")
@emby_router.post("/Videos/ActiveEncodings/Delete")
async def delete_active_encodings(request: Request,
                                  user: models.WebUser = Depends(get_emby_user)):
    # 管理员释放全部转码，普通用户只能释放自己的（避免互相踢掉播放）
    count = stop_all_transcodes() if user.is_staff else stop_user_transcodes(user.id)
    logger.info("释放转码会话 user=%s count=%s", user.id, count)
    return Response(status_code=204)


@emby_router.post("/emby/Library/Refresh")
@emby_router.post("/Library/Refresh")
async def library_refresh(user: models.WebUser = Depends(get_emby_user),
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
                if library:
                    scan_library_sync(scan_db, library)
        finally:
            scan_db.close()

    import threading

    threading.Thread(target=_run_scan, daemon=True).start()
    return {"success": True, "libraries": len(lib_ids)}


# ---- 播放流（容器后缀变体 / 原始文件）----

@emby_router.get("/emby/Videos/{item_id}/stream.{container}")
@emby_router.get("/Videos/{item_id}/stream.{container}")
async def video_stream_container(item_id: str, container: str, request: Request,
                                 user: models.WebUser = Depends(get_emby_user),
                                 db: Session = Depends(get_db)):
    return await video_stream(item_id, request, user, db)


@emby_router.get("/emby/Items/{item_id}/File")
@emby_router.get("/Items/{item_id}/File")
async def item_file(item_id: str, user: models.WebUser = Depends(get_emby_user),
                    db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    ensure_playback_allowed(db, user)
    if not item.file_path or not os.path.isfile(item.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(item.file_path, filename=os.path.basename(item.file_path))


# ---- 字幕投递 ----

def _find_subtitle_stream(item: em.MediaItem, sub_index: str):
    try:
        index = int(sub_index)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Subtitle stream not found")
    for s in item.streams:
        if (s.stream_type or "").lower() == "subtitle" and s.stream_index == index:
            return s
    raise HTTPException(status_code=404, detail="Subtitle stream not found")


def _subtitle_ordinal(item: em.MediaItem, stream) -> int:
    """该字幕轨在条目内“第几条字幕”（ffmpeg -map 0:s:N 需要序号而非绝对流索引）"""
    ordered = sorted(
        [s for s in item.streams if (s.stream_type or "").lower() == "subtitle"],
        key=lambda s: s.stream_index or 0,
    )
    for i, s in enumerate(ordered):
        if s.id == stream.id:
            return i
    return 0


async def _serve_subtitle(item_id: str, sub_index: str, fmt: str, user, db) -> Response:
    item = _require_item(db, item_id)
    # 字幕与播放同一门槛，避免非会员绕过付费墙拿到内容文本
    ensure_playback_allowed(db, user)
    stream = _find_subtitle_stream(item, sub_index)
    return subs.render_subtitle(
        item_guid=item.guid,
        media_path=item.file_path,
        stream=stream,
        fmt=fmt,
        subtitle_ordinal=_subtitle_ordinal(item, stream),
    )


@emby_router.get("/emby/Videos/{item_id}/{media_source_id}/Subtitles/{sub_index}/Stream.{fmt}")
@emby_router.get("/Videos/{item_id}/{media_source_id}/Subtitles/{sub_index}/Stream.{fmt}")
@emby_router.get("/emby/Videos/{item_id}/subtitles/{sub_index}/Stream.{fmt}")
@emby_router.get("/Videos/{item_id}/subtitles/{sub_index}/Stream.{fmt}")
async def video_subtitle(item_id: str, sub_index: str, fmt: str, request: Request,
                         media_source_id: str = "",
                         user: models.WebUser = Depends(get_emby_user),
                         db: Session = Depends(get_db)):
    return await _serve_subtitle(item_id, sub_index, fmt, user, db)


@emby_router.get("/emby/Videos/{item_id}/{media_source_id}/Subtitles/{sub_index}/{start_ticks}/Stream.{fmt}")
@emby_router.get("/Videos/{item_id}/{media_source_id}/Subtitles/{sub_index}/{start_ticks}/Stream.{fmt}")
@emby_router.get("/emby/Videos/{item_id}/subtitles/{sub_index}/{start_ticks}/Stream.{fmt}")
@emby_router.get("/Videos/{item_id}/subtitles/{sub_index}/{start_ticks}/Stream.{fmt}")
async def video_subtitle_offset(item_id: str, sub_index: str, start_ticks: str, fmt: str,
                                request: Request, media_source_id: str = "",
                                user: models.WebUser = Depends(get_emby_user),
                                db: Session = Depends(get_db)):
    # 非直播场景忽略时间偏移，直接投递完整字幕
    return await _serve_subtitle(item_id, sub_index, fmt, user, db)


# ---- HLS 大小写兼容（必须放在文件最后，避免抢在更具体的路由之前匹配）----

@emby_router.get("/emby/Videos/{item_id}/{transcode_path:path}")
@emby_router.get("/Videos/{item_id}/{transcode_path:path}")
async def video_hls_upper(item_id: str, transcode_path: str, request: Request,
                          user: models.WebUser = Depends(get_emby_user),
                          db: Session = Depends(get_db)):
    """Emby 客户端在不同版本混用 /Videos 与 /videos 前缀，补齐大写前缀的通配"""
    return await video_hls(item_id, transcode_path, request, user, db)
