# -*- coding: utf-8 -*-
"""红包 API 路由（公益服模块3-娱乐板块）

手动编写（OpenRouter 免费模型 429 限流，按 backend/api/points.py 模式手写）。

用户端（前缀 /api/redpacket）：
- POST /send          发红包 {total_amount, total_count}
- POST /{id}/claim    抢红包
- GET  /{id}          红包详情
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend import welfare_redpacket as rp_mod
from backend.api.user import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/api/redpacket", tags=["娱乐-红包"])


class SendPacket(BaseModel):
    total_amount: int = Field(..., ge=1, description="总积分")
    total_count: int = Field(..., ge=1, le=100, description="总个数")


@router.post("/send")
def send(
    req: SendPacket,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发红包"""
    try:
        p = rp_mod.send_packet(db, current_user, req.total_amount, req.total_count)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": p.id, "total_amount": p.total_amount, "total_count": p.total_count}


@router.post("/{packet_id}/claim")
def claim(
    packet_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """抢红包"""
    try:
        return rp_mod.claim_packet(db, current_user, packet_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{packet_id}")
def detail(
    packet_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """红包详情"""
    try:
        return rp_mod.get_packet(db, packet_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
