# -*- coding: utf-8 -*-
"""抽奖 API 路由（公益服模块3-娱乐板块）

手动编写（OpenRouter 免费模型 429 限流，按 backend/api/points.py 模式手写）。

用户端（前缀 /api/lottery）：
- GET  /prizes   奖品列表
- POST /draw     抽奖一次
- GET  /logs     我的抽奖记录
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend import models
from backend import welfare_lottery as lottery_mod
from backend.api.user import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/api/lottery", tags=["娱乐-抽奖"])


@router.get("/prizes")
def prizes(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """奖品列表"""
    return {"prizes": lottery_mod.list_prizes(db)}


@router.post("/draw")
def draw(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """抽奖一次"""
    try:
        return lottery_mod.draw(db, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/logs")
def logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的抽奖记录"""
    return lottery_mod.my_logs(db, current_user, page, page_size)
