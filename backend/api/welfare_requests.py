# -*- coding: utf-8 -*-
"""求片中心 API 路由（公益服模块3-娱乐板块）

.. deprecated::
    求片已并入统一求片流程（backend/media_seek.py + /api/media-seek）。
    本模块所有端点均标记 deprecated，仅保留兼容，不再演进。

用户端（前缀 /api/requests）：
- POST /            提交求片
- GET  /            我的求片列表
- GET  /quota       本月额度

管理端（共用 admin_router）：
- GET  /welfare/requests              全部列表
- POST /welfare/requests/{id}/approve 审核通过
- POST /welfare/requests/{id}/reject  审核拒绝
- POST /welfare/requests/{id}/done    标记已入库
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend import welfare_requests as req_mod
from backend.api.admin_core import admin_router, get_current_admin
from backend.api.user import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/api/requests", tags=["娱乐-求片"])


class SubmitRequest(BaseModel):
    tmdb_id: str = Field(..., description="TMDB ID")
    media_type: str = Field("movie", description="movie 或 tv")
    title: str = Field(..., description="影片标题")


class ReviewNote(BaseModel):
    admin_note: str = Field("", description="审核备注")


@router.post("", deprecated=True)
def submit(
    req: SubmitRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交求片"""
    try:
        r = req_mod.submit_request(db, current_user, req.tmdb_id, req.media_type, req.title)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return req_mod._to_dict(r)


@router.get("", deprecated=True)
def my_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的求片列表"""
    return req_mod.list_my_requests(db, current_user, page, page_size)


@router.get("/quota", deprecated=True)
def quota(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本月求片额度"""
    return req_mod.get_monthly_quota(db, current_user)


# ---------- 管理端 ----------

@admin_router.get("/welfare/requests", deprecated=True)
def admin_list(
    status: str = Query("", description="按状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员：求片列表"""
    return req_mod.list_all_requests(db, status or None, page, page_size)


@admin_router.post("/welfare/requests/{request_id}/approve", deprecated=True)
def admin_approve(
    request_id: int,
    note: ReviewNote,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员：审核通过"""
    try:
        r = req_mod.review_request(db, request_id, True, note.admin_note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return req_mod._to_dict(r)


@admin_router.post("/welfare/requests/{request_id}/reject", deprecated=True)
def admin_reject(
    request_id: int,
    note: ReviewNote,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员：审核拒绝"""
    try:
        r = req_mod.review_request(db, request_id, False, note.admin_note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return req_mod._to_dict(r)


@admin_router.post("/welfare/requests/{request_id}/done", deprecated=True)
def admin_done(
    request_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员：标记已入库"""
    try:
        r = req_mod.mark_done(db, request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return req_mod._to_dict(r)
