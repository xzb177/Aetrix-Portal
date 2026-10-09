# -*- coding: utf-8 -*-
"""公益服积分 API 路由（挂载到 backend/points.py 的 router）

端点（前缀 /api/points）：
- POST /signin          公益签到（Foam 风格）
- POST /redeem          积分兑换公益天数 {days_option: 7 | 30}
- GET  /balance         积分概览（余额/今日获得/累计获得）
- GET  /logs            积分明细（分页）
- POST /chat-award      发言奖励（内部调用，供聊天模块用）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend import points as points_mod
from backend.api.user import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/api/points", tags=["公益服-积分"])


class RedeemRequest(BaseModel):
    days_option: int = Field(..., description="兑换天数，仅支持 7 或 30")


@router.post("/signin")
def welfare_signin(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """公益服签到"""
    try:
        return points_mod.welfare_signin(db, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/redeem")
def redeem_welfare(
    req: RedeemRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """积分兑换公益天数"""
    try:
        return points_mod.redeem_welfare(db, current_user, req.days_option)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/balance")
def points_balance(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """积分概览"""
    return points_mod.get_points_summary(db, current_user)


@router.get("/logs")
def points_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """积分明细（分页）"""
    q = db.query(models.PointsLog).filter(
        models.PointsLog.user_id == current_user.id
    ).order_by(models.PointsLog.id.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": it.id,
                "amount": it.amount,
                "balance_after": it.balance_after,
                "type": it.type,
                "description": it.description,
                "created_at": it.created_at.isoformat() if it.created_at else None,
            }
            for it in items
        ],
    }


@router.post("/chat-award")
def chat_award(
    user_id: int = Query(..., description="被奖励用户 ID"),
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发言奖励（内部接口）"""
    awarded = points_mod.award_chat_points(db, user_id)
    return {"awarded": awarded}
