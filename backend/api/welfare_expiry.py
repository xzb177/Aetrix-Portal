# -*- coding: utf-8 -*-
"""公益服到期管理 API（模块4）

手动编写（按 backend/api/welfare_requests.py 模式）。

管理端（共用 admin_router）：
- POST /welfare/bulk-extend   批量延期
- GET  /welfare/expiring-soon 即将到期列表
- POST /welfare/check-now     手动触发检查

用户端（前缀 /api/welfare/expiry）：
- GET  /status  我的公益状态
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend import welfare_expiry as exp_mod
from backend.api.admin_core import admin_router, get_current_admin
from backend.api.user import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/api/welfare/expiry", tags=["公益-到期管理"])


class BulkExtendRequest(BaseModel):
    min_expired_days: int = Field(..., ge=0, description="最小过期天数")
    max_expired_days: int = Field(..., ge=0, description="最大过期天数")
    add_days: int = Field(..., gt=0, description="延长的天数")


@admin_router.post("/welfare/bulk-extend")
def bulk_extend(
    req: BulkExtendRequest,
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量延期已过期的公益用户"""
    try:
        result = exp_mod.bulk_extend_welfare(
            db,
            req.min_expired_days,
            req.max_expired_days,
            req.add_days,
            granted_by=admin.id,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.get("/welfare/expiring-soon")
def expiring_soon(
    days: int = Query(3, ge=1, le=30),
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """查询即将到期的公益用户"""
    try:
        return exp_mod.get_expiring_soon(db, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.post("/welfare/check-now")
def check_now(
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """手动触发到期与不活跃检查"""
    try:
        expiry = exp_mod.check_welfare_expiry(db)
        inactive = exp_mod.check_inactive_users(db)
        return {"expiry": expiry, "inactive": inactive}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def my_status(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的公益资格状态（是否有效、到期时间、剩余天数）"""
    try:
        from datetime import datetime
        now = datetime.now()
        exp = current_user.welfare_expires_at
        is_welfare = bool(current_user.is_welfare)
        if is_welfare and exp is not None and exp <= now:
            is_welfare = False
        if exp is None:
            days_left = None
        elif exp > now:
            days_left = (exp - now).days
        else:
            days_left = 0
        return {
            "is_welfare": is_welfare,
            "expires_at": exp.isoformat() if exp else None,
            "days_left": days_left,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
