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
import random
import secrets
import shutil
import time
import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import false, func, or_
from sqlalchemy.orm import Session, joinedload

from backend import models
from backend.database import SessionLocal, get_db
from backend.emby_server import facets
from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib
from backend.emby_server import subtitles as subs
from backend.emby_server.auth import (
    get_emby_user,
    parse_emby_authorization,
    resolve_token,
)
from backend.emby_server.facets import count_virtual_items  # 索引版（虚拟库条目数）
from backend.emby_server.scanner import (
    ScanInProgress,
    item_guid,
    parse_media_filename,
    scan_library_sync,
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
    serve_remote_async,
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


# ==================== 列表批量预取（消除 N+1）====================

def _prefetch_list_data(db: Session, user_id: int, items: list[em.MediaItem]) -> None:
    """一次性预取列表页需要的关联数据，消除 _item_dto 的 N+1 查询

    旧实现：一页 100 个条目 = 100 次 UMD 查询 + series/parent 惰性加载
    （每集 2 次）+ series/season 的 ChildCount 各 1 次 ≈ 400+ 次查询。
    客户端首页一次要拉 Resume/Latest/NextUp/多库列表，全站延迟被这些
    小查询成倍放大——这正是比 Emby 慢的主因之一。

    预取结果挂在 ``db.info``（随请求会话销毁，不会跨请求串数据），
    _item_dto 优先用预取结果，单独取条目（详情页等）时回退为原查询。
    """
    if not items:
        return
    item_ids = [i.id for i in items]

    # 1) 用户媒体数据（进度/收藏/已看）
    umd_map: dict[int, em.UserMediaData] = {
        u.item_id: u
        for u in db.query(em.UserMediaData).filter(
            em.UserMediaData.user_id == user_id,
            em.UserMediaData.item_id.in_(item_ids),
        ).all()
    }

    # 2) 集的 series / parent（一次性载入，避免逐条惰性加载）
    series_ids = {i.series_id for i in items if i.series_id}
    parent_ids = {i.parent_id for i in items if i.parent_id}
    relations: dict[int, em.MediaItem] = {}
    related_ids = (series_ids | parent_ids) - set(item_ids)
    if related_ids:
        relations = {
            r.id: r
            for r in db.query(em.MediaItem).filter(em.MediaItem.id.in_(related_ids)).all()
        }
    for it in items:
        if it.series_id is not None and it.series_id not in item_ids:
            it.series = relations.get(it.series_id)
        if it.parent_id is not None and it.parent_id not in item_ids:
            it.parent = relations.get(it.parent_id)

    # 3) series / season 的子项计数（ChildCount）
    counts: dict[int, int] = {}
    series_ids_all = [i.id for i in items if i.item_type == "series"]
    season_ids_all = [i.id for i in items if i.item_type == "season"]
    if series_ids_all:
        rows = (
            db.query(em.MediaItem.series_id, func.count(em.MediaItem.id))
            .filter(em.MediaItem.series_id.in_(series_ids_all),
                    em.MediaItem.item_type == "episode")
            .group_by(em.MediaItem.series_id)
            .all()
        )
        counts.update({sid: n for sid, n in rows})
    if season_ids_all:
        rows = (
            db.query(em.MediaItem.parent_id, func.count(em.MediaItem.id))
            .filter(em.MediaItem.parent_id.in_(season_ids_all))
            .group_by(em.MediaItem.parent_id)
            .all()
        )
        counts.update({pid: n for pid, n in rows})

    db.info["_royalbot_prefetch"] = {
        "umd": umd_map,
        "counts": counts,
        "items": {i.id: i for i in items},
    }


def _prefetched(db: Session) -> dict:
    return db.info.get("_royalbot_prefetch") or {}


def _item_dto(item: em.MediaItem, base: str, user_id: int, db: Session, full: bool = False,
              api_key: str = "") -> dict:
    download_ok = _download_ok(db)
    prefetch = _prefetched(db)
    umd = prefetch.get("umd", {}).get(item.id)
    if umd is None and item.id not in prefetch.get("items", {}):
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
    if item.item_type not in ("series", "season"):
        return None
    prefetch = _prefetched(db)
    counts = prefetch.get("counts", {})
    if item.id in counts:
        return counts[item.id] or None
    return (
        db.query(em.MediaItem).filter(em.MediaItem.series_id == item.id,
                                      em.MediaItem.item_type == "episode").count()
        if item.item_type == "series"
        else db.query(em.MediaItem).filter(em.MediaItem.parent_id == item.id).count()
    ) or None


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
def system_info(request: Request):
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
def system_ping():
    return PlainTextResponse("Emby Server")


@emby_router.post("/emby/System/Ping")
@emby_router.post("/emby/system/ping")
@emby_router.post("/System/Ping")
def system_ping_post():
    return PlainTextResponse("Emby Server")


@emby_router.get("/emby/Branding/Configuration")
@emby_router.get("/emby/branding/config")
@emby_router.get("/Branding/Configuration")
def branding_config():
    return {"LoginDisclaimer": "", "CustomCss": "", "SplashscreenEnabled": False}


@emby_router.get("/emby")
def emby_root():
    return {"ProductName": "Emby Server", "Version": SERVER_VERSION, "Id": SERVER_ID}


# ==================== 认证 ====================

@emby_router.post("/emby/Users/AuthenticateByName")
@emby_router.post("/Users/AuthenticateByName")
def authenticate_by_name(
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


def _facet_or_legacy(column, kind: str, names: list[str], db: Session):
    """分类筛选条件：优先走关联表的索引，老库没回填完就退回全表 ILIKE

    关联表命中后不再碰 `emby_items` 的文本列；两者的匹配语义一致
    （关联表侧是「全等或取值里包含」，与 ``col ILIKE '%x%'`` 相同，含大小写不敏感），
    所以回填过程中混用两种路径也不会出现两种结果。
    传了库里不存在的分类名时返回“空结果”条件（与 ``ILIKE`` 匹配不到任何行一致）。
    """
    if not names:
        return None
    if facets.ensure_ready(db):
        return facets.candidate_condition(kind, names, db)
    return or_(*[column.ilike(f"%{name}%") for name in names])


def _synthetic_map(db: Session) -> dict[str, tuple[str, str]]:
    """{合成 Id: (类型, 名称)} 反查表（类型 / 工作室 / 年份 右键筛选用）

    客户端点开「类型 / 制作公司 / 年份」后会带着我们生成的 Id 再请求 /Items。
    旧实现找不到条目就退回按 guid 匹配，等于返回空（或整库）——点进去白点。
    """
    buckets: dict[str, set[str]] = {"Genre": set(), "Studio": set(), "Year": set()}
    if facets.ensure_ready(db):
        # 走关联表：两次索引扫描（取值很少），不再扫全库文本列
        buckets["Genre"].update(facets.kind_values(db, facets.KIND_GENRE))
        buckets["Studio"].update(facets.kind_values(db, facets.KIND_STUDIO))
    else:
        # 老库还没回填完：沿用旧口径，宁可慢也不能少（否则客户端点类型会空）
        for genres, studios in db.query(
            em.MediaItem.genres, em.MediaItem.studios
        ).all():
            buckets["Genre"].update(g for g in (genres or "").split(",") if g)
            buckets["Studio"].update(s for s in (studios or "").split(",") if s)
    for (year,) in (
        db.query(em.MediaItem.production_year)
        .filter(em.MediaItem.production_year.isnot(None))
        .distinct()
        .all()
    ):
        buckets["Year"].add(str(year))
    return {
        _guid_of(kind, name): (kind, name)
        for kind, names in buckets.items()
        for name in names
    }


def _synthetic_lookup(db: Session) -> dict[str, tuple[str, str]]:
    """两级缓存的反查表：同一请求内复用，跨请求按「关联表代际」复用

    合成 Id 表只随扫描 / 回填变化（代际号会变），因此跨请求缓存不会给出过期结果；
    以前每次带 GenreIds/StudioIds 的列表请求都要扫一遍全库。
    """
    cached = db.info.get("_royalbot_synthetic_ids")
    if cached is None:
        generation = facets.values_generation()
        if _SYNTHETIC_CACHE.get("map") is not None and _SYNTHETIC_CACHE.get("gen") == generation:
            cached = _SYNTHETIC_CACHE["map"]
        else:
            cached = _synthetic_map(db)
            _SYNTHETIC_CACHE["gen"] = generation
            _SYNTHETIC_CACHE["map"] = cached
        db.info["_royalbot_synthetic_ids"] = cached
    return cached


def _empty_items() -> dict:
    return {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}


def _query_result(items: list, user: models.WebUser, db: Session, base: str) -> dict:
    _prefetch_list_data(db, user.id, list(items))
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
def users_public():
    """客户端登录页的用户列表

    按 Jellyfin 默认隐私策略返回空数组：本服务账号即门户账号，未认证地枚举用户列表
    会泄露全站账号。返回空列表（而非 404）让客户端走“手动输入用户名”分支。
    """
    return []


@emby_router.get("/emby/Users/Me")
@emby_router.get("/Users/Me")
def users_me(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    return _user_dto(user, db)


@emby_router.get("/emby/Users")
@emby_router.get("/Users")
def users_list(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
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
def get_user(user_id: str, user: models.WebUser = Depends(get_emby_user),
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
def get_items(
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
                    platform_cond = _facet_or_legacy(
                        em.MediaItem.platforms, facets.KIND_PLATFORM, [platform], db
                    ) if platform else None
                    query = (
                        query.filter(platform_cond) if platform_cond is not None
                        else query.filter(em.MediaItem.id == -1)
                    )
                else:
                    query = query.filter(em.MediaItem.library_id == lib.id)
            else:
                # 类型 / 工作室 / 年份的合成 Id：点进去要得到真实筛选结果
                hit = _synthetic_lookup(db).get(parent_id)
                if hit and hit[0] == "Genre":
                    cond = _facet_or_legacy(em.MediaItem.genres, facets.KIND_GENRE, [hit[1]], db)
                    query = query.filter(cond) if cond is not None else query.filter(false())
                elif hit and hit[0] == "Studio":
                    cond = _facet_or_legacy(em.MediaItem.studios, facets.KIND_STUDIO, [hit[1]], db)
                    query = query.filter(cond) if cond is not None else query.filter(false())
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

    # 分类筛选：关联表命中（索引）为主，老库未回填完时自动退回文本列 ILIKE
    genre_names = [g for g in genres if g] or _synthetic_names("Genre", "GenreIds")
    if genre_names:
        cond = _facet_or_legacy(em.MediaItem.genres, facets.KIND_GENRE, genre_names, db)
        if cond is not None:
            query = query.filter(cond)

    studio_names = _synthetic_names("Studio", "StudioIds")
    if studio_names:
        cond = _facet_or_legacy(em.MediaItem.studios, facets.KIND_STUDIO, studio_names, db)
        if cond is not None:
            query = query.filter(cond)

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
        _prefetch_list_data(db, user.id, page)
        return {
            "Items": [_item_dto(i, base, user.id, db) for i in page],
            "TotalRecordCount": len(ranked),
            "StartIndex": start,
        }

    total = query.count()
    if random_sort:
        # ``ORDER BY RANDOM()`` 会让数据库把整个结果集物化再排序（十万级库就是全表排序）。
        # 随机排序只需要一个随机子集：先取主键、在内存里抽样，再按抽到的 id 取这一页，
        # 成本从「全表排序 + 全行物化」降到「扫主键 + 取 N 行」。
        id_rows = query.with_entities(em.MediaItem.id).all()
        ids = [row[0] for row in id_rows]
        if not ids:
            return {"Items": [], "TotalRecordCount": 0, "StartIndex": start}
        picked = random.sample(ids, min(len(ids), start + limit))[start:start + limit]
        items = db.query(em.MediaItem).filter(em.MediaItem.id.in_(picked)).all() if picked else []
        position = {item_id: index for index, item_id in enumerate(picked)}
        items.sort(key=lambda item: position.get(item.id, 0))
    else:
        items = query.order_by(*order_cols).offset(start).limit(limit).all()
    _prefetch_list_data(db, user.id, items)

    return {
        "Items": [_item_dto(i, base, user.id, db) for i in items],
        "TotalRecordCount": total,
        "StartIndex": start,
    }


@emby_router.get("/emby/Users/{user_id}/Items/Resume")
@emby_router.get("/Users/{user_id}/Items/Resume")
def get_resume(request: Request, user: models.WebUser = Depends(get_emby_user),
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
    _prefetch_list_data(db, user.id, [i for _umd, i in rows])
    return {"Items": [_item_dto(i, base, user.id, db) for _umd, i in rows],
            "TotalRecordCount": len(rows), "StartIndex": 0}


@emby_router.get("/emby/Users/{user_id}/Items/Latest")
@emby_router.get("/Users/{user_id}/Items/Latest")
def get_latest(request: Request, user: models.WebUser = Depends(get_emby_user),
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
    _prefetch_list_data(db, user.id, items)
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
def items_counts(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
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
def items_intros(user: models.WebUser = Depends(get_emby_user)):
    return _empty_items()


# 筛选菜单的取值来自全库（genres/tags/rating/year 都是逗号分隔的文本列）。
# 旧实现每次都把整库 ORM 对象化后遍历：十万级库就是数百 MB 内存尖峰 + 数秒 CPU，
# 而客户端会反复打开这个面板。现改为「只取需要的列 + 分批拉取 + TTL 缓存」。
_FILTERS_CACHE: dict = {"at": 0.0, "payload": None}
# 合成 Id 反查表的跨请求缓存（按关联表代际失效，见 _synthetic_lookup）
_SYNTHETIC_CACHE: dict = {"gen": None, "map": None}
_FILTERS_CACHE_TTL = float(os.getenv("EMBY_FILTERS_CACHE_TTL", "300") or 300)


def invalidate_filters_cache() -> None:
    """媒体库扫描/条目变更后主动失效筛选缓存（未调用时靠 TTL 自然过期）"""
    _FILTERS_CACHE["at"] = 0.0
    _FILTERS_CACHE["payload"] = None


def _filters_payload(db: Session) -> dict:
    cached = _FILTERS_CACHE.get("payload")
    if cached is not None and time.monotonic() - _FILTERS_CACHE["at"] < _FILTERS_CACHE_TTL:
        return cached
    if facets.ensure_ready(db):
        # 流派 / 标签走关联表：一次覆盖索引扇描拿全取值，不再扫全库文本列。
        # （可见性差异：关联表不记 is_hidden，隐藏条目独有的分类值也会出现在菜单里；
        #   点进去的结果集仍会过滤掉隐藏条目，所以只是菜单多一个可选项。）
        genres: set = set(facets.kind_values(db, facets.KIND_GENRE))
        tags: set = set(facets.kind_values(db, facets.KIND_TAG))
    else:
        # 老库还没回填完：沿用旧口径
        genres, tags = set(), set()
        for item_genres, item_tags in (
            db.query(em.MediaItem.genres, em.MediaItem.tags)
            .filter(em.MediaItem.is_hidden == False)  # noqa: E712
            .yield_per(1000)
        ):
            genres.update(g for g in (item_genres or "").split(",") if g)
            tags.update(t for t in (item_tags or "").split(",") if t)
    # 分级与年份是单值列：DISTINCT 只取需要的列（不再把四个列一起读回来物化）
    ratings = {
        r
        for (r,) in db.query(em.MediaItem.official_rating)
        .filter(em.MediaItem.is_hidden == False, em.MediaItem.official_rating.isnot(None))  # noqa: E712
        .distinct()
        .all()
        if r
    }
    years = {
        y
        for (y,) in db.query(em.MediaItem.production_year)
        .filter(em.MediaItem.is_hidden == False, em.MediaItem.production_year.isnot(None))  # noqa: E712
        .distinct()
        .all()
        if y
    }
    payload = {
        "Genres": sorted(genres),
        "Tags": sorted(tags),
        "OfficialRatings": sorted(ratings),
        "Years": sorted(years, reverse=True),
    }
    _FILTERS_CACHE["at"] = time.monotonic()
    _FILTERS_CACHE["payload"] = payload
    return payload


@emby_router.get("/emby/Items/Filters")
@emby_router.get("/Items/Filters")
@emby_router.get("/emby/Items/Filters2")
@emby_router.get("/Items/Filters2")
def items_filters(user: models.WebUser = Depends(get_emby_user), db: Session = Depends(get_db)):
    return _filters_payload(db)


@emby_router.get("/emby/Items/{item_id}")
@emby_router.get("/Items/{item_id}")
@emby_router.get("/emby/Users/{user_id}/Items/{item_id}")
@emby_router.get("/Users/{user_id}/Items/{item_id}")
def get_item_detail(
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
def get_seasons(item_id: str, request: Request,
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
    _prefetch_list_data(db, user.id, seasons)
    return {"Items": [_item_dto(s, base, user.id, db) for s in seasons],
            "TotalRecordCount": len(seasons), "StartIndex": 0}


@emby_router.get("/emby/Shows/{item_id}/Episodes")
@emby_router.get("/Shows/{item_id}/Episodes")
def get_episodes(item_id: str, request: Request,
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
    _prefetch_list_data(db, user.id, episodes)
    return {"Items": [_item_dto(e, base, user.id, db) for e in episodes],
            "TotalRecordCount": len(episodes), "StartIndex": 0}


@emby_router.get("/emby/Shows/NextUp")
@emby_router.get("/Shows/NextUp")
def get_next_up(request: Request, user: models.WebUser = Depends(get_emby_user),
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
    _prefetch_list_data(db, user.id, episodes)
    return {"Items": [_item_dto(e, base, user.id, db) for e in episodes],
            "TotalRecordCount": len(episodes), "StartIndex": 0}


@emby_router.get("/emby/Users/{user_id}/FavoriteItems")
@emby_router.get("/Users/{user_id}/FavoriteItems")
def get_favorites(request: Request, user: models.WebUser = Depends(get_emby_user),
                        db: Session = Depends(get_db)):
    rows = (
        db.query(em.MediaItem)
        .join(em.UserMediaData, em.UserMediaData.item_id == em.MediaItem.id)
        .filter(em.UserMediaData.user_id == user.id, em.UserMediaData.is_favorite == True)  # noqa: E712
        .order_by(em.UserMediaData.updated_at.desc())
        .all()
    )
    base = _base_url(request)
    _prefetch_list_data(db, user.id, rows)
    return {"Items": [_item_dto(i, base, user.id, db) for i in rows],
            "TotalRecordCount": len(rows), "StartIndex": 0}


@emby_router.get("/emby/Users/{user_id}/PlayedItems")
@emby_router.get("/Users/{user_id}/PlayedItems")
def get_played_items(request: Request, user: models.WebUser = Depends(get_emby_user),
                           db: Session = Depends(get_db)):
    rows = (
        db.query(em.MediaItem)
        .join(em.UserMediaData, em.UserMediaData.item_id == em.MediaItem.id)
        .filter(em.UserMediaData.user_id == user.id, em.UserMediaData.played == True)  # noqa: E712
        .order_by(em.UserMediaData.last_played_at.desc())
        .all()
    )
    base = _base_url(request)
    _prefetch_list_data(db, user.id, rows)
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
def mark_played(item_id: str, user_id: str,
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
def mark_unplayed(item_id: str, user_id: str,
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
    if not item.file_path:
        # 没有媒体路径（虚拟库聚合条目 / 容器 / 源文件已丢失）：
        # 不要发放指向不存在目标的播放地址，否则客户端拿到一个必 404 的 URL。
        # 返回空 MediaSources 是 Emby 客户端认可的「无可播放源」。
        return {
            "MediaSources": [],
            "PlaySessionId": secrets.token_hex(8),
            "ErrorCode": None,
        }
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
        # 远程代理用异步客户端：连源站与等首字节都在等待 I/O，
        # 不能让一个用户的拖动进度条把整个事件循环卡住
        return await serve_remote_async(target.value, request, target.headers, media_type)
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
            await wait_for_file(playlist, timeout=15.0)
            if not os.path.isfile(playlist):
                if not transcode_alive(existing):
                    raise HTTPException(status_code=503, detail="转码进程已退出，请重新发起播放")
                raise HTTPException(status_code=504, detail="转码尚未产出播放列表")
            content = _rewrite_playlist(info["dir"], base, item.guid, existing, api_key)
            return Response(content, media_type="application/vnd.apple.mpegurl")
        # 客户端请求切片往往早于 ffmpeg 写出，短暂等待而非立即 404
        if not await wait_for_file(file_path, timeout=12.0):
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

# ==================== 拆分说明（v2.13.0）====================
# 本文件原先 2100+ 行，已按关注点拆出三个模块（路由注册顺序与拆分前完全一致）：
#   - media_routes.py  图片投递 / 下载 / hls1
#   - compat_routes.py 会话上报与协议补齐端点
#   - stream_routes.py 播放流容器变体 / 原始文件 / 字幕投递 / HLS 通配
# 三者把路由注册到上面这个 emby_router 上（由 backend/main.py 与 emby_api/main.py 导入触发）。
