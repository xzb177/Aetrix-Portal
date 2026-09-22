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
from backend.emby_server import models as em
from backend.emby_server.auth import get_emby_user, parse_emby_authorization, resolve_token
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
        return serve_remote(
            target.value, request, target.headers,
            media_type="application/octet-stream",
        )
    return FileResponse(target.value, filename=os.path.basename(target.value))


@emby_router.get("/emby/Items/{item_id}/Images/{image_type}")
@emby_router.get("/Items/{item_id}/Images/{image_type}")
def item_image(item_id: str, image_type: str, request: Request,
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
def item_image_index(item_id: str, image_type: str, index: str, request: Request,
                      db: Session = Depends(get_db)):
    # 客户端普遍请求 /Images/Backdrop/0、/Images/Primary/0 这类带序号的地址。
    # 旧实现只注册了 Primary，其它类型（Backdrop/Thumb 等）会直接 404。
    return item_image(item_id, image_type, request, db)


