# -*- coding: utf-8 -*-
"""影评 API 路由（公益服模块3-娱乐板块）

手动编写（OpenRouter 免费模型 429 限流，按 backend/api/points.py 模式手写）。

用户端（前缀 /api/reviews）：
- POST /            发表影评 {item_guid, rating, content}
- GET  /{guid}      某影片的影评列表
- POST /{id}/like   点赞
- GET  /my/list     我的影评
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend import welfare_reviews as review_mod
from backend.api.user import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/api/reviews", tags=["娱乐-影评"])


class CreateReview(BaseModel):
    item_guid: str = Field(..., description="影片 GUID")
    rating: int = Field(5, ge=1, le=5, description="评分 1-5")
    content: str = Field(..., description="影评内容")


@router.post("")
def create(
    req: CreateReview,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发表影评"""
    try:
        r = review_mod.create_review(db, current_user, req.item_guid, req.rating, req.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "id": r.id,
        "item_guid": r.item_guid,
        "rating": r.rating,
        "content": r.content,
        "likes": r.likes,
    }


@router.get("/my/list")
def my_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的影评"""
    return review_mod.my_reviews(db, current_user, page, page_size)


@router.get("/{guid}")
def list_by_guid(
    guid: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """某影片的影评列表"""
    return review_mod.list_reviews(db, guid, page, page_size)


@router.post("/{review_id}/like")
def like(
    review_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """点赞"""
    try:
        return review_mod.like_review(db, review_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
