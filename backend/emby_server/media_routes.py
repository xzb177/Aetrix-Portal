"""图片与下载路由

由 ``backend/emby_server/api.py`` 拆分而来（v2.13.0），图片投递（含带序号的 Backdrop/Thumb 等）、原始文件下载、HLS 的 hls1 入口。

路由仍注册在同一个 ``emby_router`` 上（从 ``api`` 导入同一实例），注册顺序与拆分前一致，
因此 ``mount_routes`` / ``image_routes`` / ``session_routes`` 的「按路径 + 端点名替换」逻辑不受影响。
模块由 ``backend/main.py`` 与 ``emby_api/main.py`` 在 ``include_router`` 之前导入。
无阻塞的协议路由一律写成同步 ``def``，由 Starlette 线程池执行，避免同步查询/文件 IO 卡住事件循环。
"""
from __future__ import annotations

import logging

from backend import models
from backend.database import SessionLocal, get_db
from backend.emby_server import image_store
from backend.emby_server import models as em
from backend.emby_server.auth import get_emby_user, parse_emby_authorization, resolve_token
from backend.emby_server.streaming import (
    can_redirect_direct,
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
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
import os

from backend.emby_server.api import (
    emby_router,
    _first_image,
    _play_target,
    _queue_image_repair,
    _require_item,
    video_hls,
)

logger = logging.getLogger(__name__)


def _remember_local_image(db: Session, item: em.MediaItem, kind: str, path: str) -> None:
    """把本地化后的图片路径记到条目上（下一次取图直接命中本地）

    写库失败只记日志：图片本身已经在磁盘上，这个函数只是让后续请求少走一步。
    """
    try:
        if kind == "Primary":
            item.poster_path = path
        else:
            item.backdrop_path = path
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("记录本地化图片路径失败 item=%s: %s", getattr(item, "guid", "?"), exc)
        db.rollback()


@emby_router.get("/emby/Videos/{item_id}/hls1")
@emby_router.get("/Videos/{item_id}/hls1")
async def video_hls1(item_id: str, request: Request,
                     user: models.WebUser = Depends(get_emby_user),
                     db: Session = Depends(get_db)):
    # Emby 客户端直接请求 hls1 路径
    return await video_hls(item_id, "master.m3u8", request, user, db)


@emby_router.get("/emby/Items/{item_id}/Download")
@emby_router.get("/Items/{item_id}/Download")
def download_item(item_id: str, request: Request,
                  user: models.WebUser = Depends(get_emby_user),
                  db: Session = Depends(get_db)):
    item = _require_item(db, item_id)
    # 付费墙：下载与在线播放同一门槛，避免绕过
    ensure_playback_allowed(db, user)
    # 站点级下载开关：第三方播放器触发的下载同样拦下。
    # request 带上网关（DownloadGuardMiddleware）已判过的结论，避免同一请求查两遍。
    ensure_download_allowed(db, user, request=request)
    target = _play_target(db, item)
    if target.kind == "url":
        # 无凭据直链（如 Google Drive SA 直链）直接 302，视频字节不经过服务器
        # （借鉴 go-emby 的"默认拒绝中转"思路）；有凭据的（115/WebDAV）才走代理。
        if can_redirect_direct(target):
            return Response(status_code=302, headers={"Location": target.value, "Cache-Control": "no-store"})
        return serve_remote(
            target.value, request, target.headers,
            media_type="application/octet-stream",
        )
    return FileResponse(target.value, filename=os.path.basename(target.value))


def _sized_image(src: str, max_width=None, max_height=None) -> str:
    """按客户端要的尺寸发图：有现成/能生成的缩略图就发小图，否则发原图

    maxWidth/maxHeight 是标准 Emby 查询参数（前端海报墙发 maxWidth=320，
    详情页背景发 maxWidth=1280）；w/h 是同义别名（?w=300），标准参数优先。
    只缩小不放大，失败静默回原图。
    """
    if (max_width or max_height) and src and os.path.isfile(src):
        thumb = image_store.resized_variant(src, max_width=max_width,
                                            max_height=max_height)
        if thumb:
            return thumb
    return src


def serve_thumbnail(path: str) -> Response:
    """缩略图响应：先查内存 LRU（默认 32MB 总量，key=内容寻址文件名）

    内存命中直接发字节、不碰磁盘；未命中读盘一次并回填。ETag 口径与
    streaming.serve_image 一致（mtime-size），image_routes 的 304 逻辑照样生效。
    """
    from email.utils import formatdate

    name = os.path.basename(path)
    data = image_store.thumb_mem_get(name)
    try:
        st = os.stat(path)
    except OSError:
        raise HTTPException(status_code=404, detail="Image not found")
    if data is None:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            raise HTTPException(status_code=404, detail="Image not found")
        image_store.thumb_mem_put(name, data)
    return Response(
        content=data,
        media_type="image/jpeg",  # 缩略图统一转 JPEG（见 resized_variant）
        headers={
            "ETag": f'"{int(st.st_mtime)}-{st.st_size}"',
            "Last-Modified": formatdate(st.st_mtime, usegmt=True),
            "Cache-Control": "public, max-age=86400",
        },
    )


def _serve_sized(src: str, max_width=None, max_height=None):
    """尺寸感知的图片下发：缩略图走内存缓存，原图走 FileResponse"""
    sized = _sized_image(src, max_width, max_height)
    if sized and image_store.is_thumb_variant(sized):
        return serve_thumbnail(sized)
    return serve_image(src)


@emby_router.get("/emby/Items/{item_id}/Images/{image_type}")
@emby_router.get("/Items/{item_id}/Images/{image_type}")
def item_image(item_id: str, image_type: str, request: Request,
               db: Session = Depends(get_db),
               maxWidth: str | None = None, maxHeight: str | None = None,
               w: str | None = None, h: str | None = None):
    """条目图片

    三处修正：

    1. **季/集回退**：季与集经常没有自己的图片，按「条目 → 季 → 剧集海报」回退；
    2. **数据库有记录但文件丢失**：不再把 FileNotFoundError 抛成 5xx（客户端会当成
       鉴权/服务器故障反复重试），而是干净地 404，同时把条目排进修复队列，
       下一轮扫描换成 TMDB 远程图；
    3. **远程图取不到**（404/超时）同样 404 并排队修复，而不是 500。

    尺寸参数：标准 Emby maxWidth/maxHeight 优先，w/h 是同义别名（见
    image_store.pick_dim）。非法值不 422，直接回原图。
    """
    # 按场景精确尺寸：海报墙 320/160、详情页 480、背景 1280，各调各的，不一刀切
    ew, eh = image_store.pick_dim(maxWidth, w), image_store.pick_dim(maxHeight, h)
    # 媒体库封面：第三方客户端用库的 guid 拉 /Images/Primary
    if image_type == "Primary":
        lib = db.query(em.Library).filter(em.Library.guid == item_id).first()
        cover_rel = getattr(lib, "cover_path", None) if lib is not None else None
        if cover_rel:
            import os as _os
            abs_path = cover_rel
            if not _os.path.isabs(abs_path):
                try:
                    abs_path = image_store.local_path(cover_rel)
                except Exception:
                    abs_path = None
                if not abs_path:
                    abs_path = _os.path.abspath(_os.path.join(image_store.image_dir(), cover_rel))
            if abs_path and _os.path.isfile(abs_path):
                return _serve_sized(abs_path, ew, eh)
            raise HTTPException(status_code=404, detail="Image not found")
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
        # 刮削图片本地化：远程图先落一份到本机（缓存）就直接用本地发，
        # 不必每个客户端、每次缓存穿透都去第三方拉一趟。落下就记住路径，
        # 下次请求直接命中本地；落不下来（源站挂了/被限速）就走下面的代理，行为不变。
        cached = image_store.localize(src)
        if cached:
            _remember_local_image(db, item, kind, cached)
            return _serve_sized(cached, ew, eh)
        # 仅允许代理 http(s) 远程图片（防 SSRF）
        # 共享客户端复用连接：海报墙穿透时不用每次建连
        from backend.emby_server import mounts as _mounts

        try:
            r = _mounts._shared_http_client("image_proxy", timeout=10).get(src)
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
    return _serve_sized(src, ew, eh)


@emby_router.get("/emby/Items/{item_id}/Images/{image_type}/{index}")
@emby_router.get("/Items/{item_id}/Images/{image_type}/{index}")
def item_image_index(item_id: str, image_type: str, index: str, request: Request,
                      db: Session = Depends(get_db),
                      maxWidth: str | None = None, maxHeight: str | None = None,
                      w: str | None = None, h: str | None = None):
    # 客户端普遍请求 /Images/Backdrop/0、/Images/Primary/0 这类带序号的地址。
    # 旧实现只注册了 Primary，其它类型（Backdrop/Thumb 等）会直接 404。
    return item_image(item_id, image_type, request, db,
                      maxWidth=maxWidth, maxHeight=maxHeight, w=w, h=h)


