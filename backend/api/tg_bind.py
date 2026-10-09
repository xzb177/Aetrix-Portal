# -*- coding: utf-8 -*-
"""
用户端 Telegram 绑定 API 模块

职责：
- 提供用户端 Telegram 账号绑定相关接口：生成绑定码、校验绑定、查询绑定状态、解绑
- 写操作（bind-code / verify / unbind）均受速率限制保护
- status 为只读查询接口，不加门禁
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import models
from backend.api.user import get_current_user
from backend.database import get_db
from backend.ratelimit import check_rate_limit
from backend.tg_bind import generate_bind_code, verify_bind, get_bind_status, unbind as do_unbind

router = APIRouter(prefix="/api/user/telegram", tags=["用户端-TG绑定"])


@router.post("/bind-code")
def create_bind_code(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed, _ = check_rate_limit(f"tg-bind:{current_user.id}", 5, 60)
    if not allowed:
        raise HTTPException(429, "操作过于频繁，请稍后再试")
    data = generate_bind_code(db, current_user)
    db.commit()
    return {"success": True, **data}


@router.post("/verify")
def verify_bind_code(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed, _ = check_rate_limit(f"tg-bind:{current_user.id}", 5, 60)
    if not allowed:
        raise HTTPException(429, "操作过于频繁，请稍后再试")
    try:
        result = verify_bind(db, current_user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    if isinstance(result, dict) and result.get("success"):
        return {"success": True, "telegram_id": result.get("telegram_id")}
    return result


@router.get("/status")
def bind_status(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_bind_status(db, current_user)


@router.delete("/unbind")
def unbind(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed, _ = check_rate_limit(f"tg-bind:{current_user.id}", 5, 60)
    if not allowed:
        raise HTTPException(429, "操作过于频繁，请稍后再试")
    do_unbind(db, current_user)
    db.commit()
    return {"success": True}
