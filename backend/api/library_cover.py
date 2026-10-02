"""媒体库封面的「自动生成」接口：预览 / 保存 / 重新生成

和直传封面（``portal.upload_library_cover``）并存，规则：

- ``cover_template`` 为空 → 沿用直传的 ``cover_path``，本模块不做任何事；
- 填了模板 → 从库里挑**最新入库**的海报自动拼一张 1920×1080 WebP，
  存回 ``cover_path``（同一张图，客户端侧 URL 不变，不用改任何读图逻辑）。

生成失败（库里没海报 / 字体缺失 / Pillow 没装）**一律不动已有封面**：
封面是锦上添花，不能因为生成不出来把管理员手动传的图也弄丢。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.emby_server import image_store, models as em
from backend.emby_server.portal import require_staff  # 与 admin_emby_router 同一个依赖
from backend.emby_server.library_cover_render import (
    DEFAULT_TEMPLATE,
    TEMPLATES,
    human_media_type,
    render_cover_bytes,
)

logger = logging.getLogger("aetrix.library_cover_api")

# 鉴权跟 portal.py 的 admin_emby_router 同一口径：路由级 require_staff，
# 不靠逐个 handler 挂依赖（漏一个就是越权）。
router = APIRouter(
    prefix="/api/admin/emby/libraries",
    tags=["管理端-媒体库封面"],
    dependencies=[Depends(require_staff)],
)

# 预览图也要有上限，否则管理员连点几下就能把内存打满
_PREVIEW_MAX_BYTES = 8 * 1024 * 1024


def _load_library(db: Session, lib_id: int) -> em.Library:
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")
    return lib


def _validate_template(template: Optional[str]) -> str:
    value = (template or "").strip()
    if value not in TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"封面样式必须是 { '、'.join(TEMPLATES) } 之一",
        )
    return value


def _write_generated_cover(lib: em.Library, data: bytes) -> str:
    """把生成的 WebP 落盘并更新 cover_path；旧图删除

    与直传接口同一套路径规则（``library-covers/<guid>.webp``），所以生成的
    封面和上传的封面在客户端侧是同一个 URL，切换时不用清缓存逻辑。
    """
    relative = os.path.join("library-covers", f"{lib.guid}.webp")
    target = image_store.local_path(relative)
    if not target:
        image_dir = image_store.image_dir()
        target = os.path.abspath(os.path.join(image_dir, relative))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temporary = f"{target}.{os.getpid()}.rendering"
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
    old = lib.cover_path
    lib.cover_path = relative
    if old and old != relative:
        old_abs = image_store.local_path(old)
        if old_abs and os.path.isfile(old_abs):
            try:
                os.remove(old_abs)
            except OSError:
                logger.debug("旧封面删除失败：%s", old_abs, exc_info=True)
    return relative


@router.post("/{lib_id}/cover/preview")
def preview_library_cover(
    lib_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """按传入的模板/标题渲染一张预览图，**不落库**

    管理员每改一个字就调一次，所以不写盘、不动 cover_path，只回图片字节。
    """
    lib = _load_library(db, lib_id)
    template = _validate_template(payload.get("template"))
    data = render_cover_bytes(
        db, lib,
        template=template,
        title=(payload.get("title") or "")[:100],
        subtitle=(payload.get("subtitle") or "")[:100],
    )
    if not data:
        raise HTTPException(
            status_code=422,
            detail="生成失败：这个库还没有可用海报（等刮削补完再试）",
        )
    return Response(
        content=data,
        media_type="image/webp",
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(min(len(data), _PREVIEW_MAX_BYTES)),
        },
    )


@router.post("/{lib_id}/cover/render")
def render_library_cover(
    lib_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """按传入配置生成并保存封面（落库 + 落盘），返回新的封面 URL"""
    lib = _load_library(db, lib_id)
    template = _validate_template(payload.get("template"))
    data = render_cover_bytes(
        db, lib,
        template=template,
        title=(payload.get("title") or "")[:100],
        subtitle=(payload.get("subtitle") or "")[:100],
    )
    if not data:
        raise HTTPException(
            status_code=422,
            detail="生成失败：这个库还没有可用海报（等刮削补完再试）",
        )
    _write_generated_cover(lib, data)
    db.commit()
    return {
        "success": True,
        "cover_url": f"/api/admin/emby/libraries/{lib.id}/cover",
        "content_type": "image/webp",
        "template": template,
        "title": payload.get("title") or "",
        "subtitle": payload.get("subtitle") or "",
        "library_name": lib.name,
        "media_type": human_media_type(lib.collection_type or ""),
    }


@router.post("/{lib_id}/cover/regenerate")
def regenerate_library_cover(
    lib_id: int,
    db: Session = Depends(get_db),
):
    """按库里已保存的模板/标题重新生成（刮削补完新片后点一下就换新封面）"""
    lib = _load_library(db, lib_id)
    if not lib.cover_template:
        raise HTTPException(
            status_code=400,
            detail="该媒体库没有配置封面样式，先选一个样式并保存",
        )
    data = render_cover_bytes(
        db, lib,
        template=lib.cover_template,
        title=lib.cover_title or "",
        subtitle=lib.cover_subtitle or "",
    )
    if not data:
        raise HTTPException(
            status_code=422,
            detail="生成失败：这个库还没有可用海报（等刮削补完再试）",
        )
    _write_generated_cover(lib, data)
    db.commit()
    return {
        "success": True,
        "cover_url": f"/api/admin/emby/libraries/{lib.id}/cover",
        "content_type": "image/webp",
    }