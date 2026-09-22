"""
管理后台 API · 管理员认证

后台登录是整个站点最值钱的入口，所以它单独成篇、方便单独审：

- ``POST /api/admin/auth/login``：限流（8 次 / 分钟 / IP）+ 登录日志 + 人机验证；
- ``GET  /api/admin/auth/me``：当前管理员身份；
- ``POST /api/admin/auth/change-password``：管理员改自己的密码（落审计）。

路由对象与其它后台模块共用 ``admin_core.admin_router``，导入即注册。
"""
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.api.admin_core import (
    _audit,
    _log_out,
    admin_router,
    get_current_admin,
)
from backend.authlog import client_ip as log_ip, record_event, user_agent
from backend.database import get_db
from backend.integrations import captcha as integrations_captcha
from backend.ratelimit import check_rate_limit, client_ip
from backend.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)


# ==================== 管理员认证 API ====================

class AdminLoginRequest(BaseModel):
    username: str
    password: str
    # 人机验证令牌（v2.20.0）：管理员在「系统设置 → 人机验证」里开了「保护管理后台登录」
    # 之后必填。后台登录是最值钱的入口，此前也是唯一没有这道闸的登录路径。
    captcha_token: str | None = None


@admin_router.post("/auth/login")
def admin_login(
    http_request: Request,
    request: AdminLoginRequest,
    db: Session = Depends(get_db),
):
    """管理员登录：仅 is_staff 的 WebUser 可登录管理后台

    安全：与用户端登录同样的限流 + 登录日志。后台登录原先既不限流也不留痕，
    被人跑字典猜管理员密码时站点完全无感，也无法事后审计。
    """
    allowed, retry_after = check_rate_limit(f"admin_login:{client_ip(http_request)}", 8, 60)
    if not allowed:
        record_event(
            db, username=request.username.strip(), ip=log_ip(http_request),
            agent=user_agent(http_request), success=False, reason="admin_login_failed",
            detail=f"尝试过于频繁，已限流（{retry_after}s）",
        )
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")

    integrations_captcha.guard(db, http_request, "admin_login", request.captcha_token,
                               username=request.username.strip())

    user = db.query(models.WebUser).filter(
        models.WebUser.username == request.username.strip()
    ).first()

    if not user or not verify_password(request.password, user.password_hash):
        record_event(
            db, username=request.username.strip(), user_id=user.id if user else None,
            ip=log_ip(http_request), agent=user_agent(http_request), success=False,
            reason="admin_login_failed", detail="用户名或密码错误",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_staff:
        record_event(
            db, username=user.username, user_id=user.id, ip=log_ip(http_request),
            agent=user_agent(http_request), success=False, reason="admin_login_failed",
            detail="账号没有管理员权限（尝试登录后台）",
        )
        raise HTTPException(status_code=403, detail="该账号没有管理员权限")
    if not user.is_active:
        record_event(
            db, username=user.username, user_id=user.id, ip=log_ip(http_request),
            agent=user_agent(http_request), success=False, reason="admin_login_failed",
            detail="账号已被禁用",
        )
        raise HTTPException(status_code=403, detail="账号已被禁用")

    user.last_login_at = datetime.now()
    db.commit()
    record_event(
        db, username=user.username, user_id=user.id, ip=log_ip(http_request),
        agent=user_agent(http_request), success=True, reason="admin_login",
    )

    access = create_access_token(user.id, {"username": user.username, "staff": True})
    refresh = create_refresh_token(user.id)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "is_staff": True,
        },
    }


class AdminMeResponse(BaseModel):
    id: int
    username: str
    is_staff: bool
    created_at: Optional[str] = None


@admin_router.get("/auth/me", response_model=AdminMeResponse)
def admin_me(
    current_admin: models.WebUser = Depends(get_current_admin),
):
    return AdminMeResponse(
        id=current_admin.id,
        username=current_admin.username,
        is_staff=True,
        created_at=_log_out(current_admin),
    )


class AdminChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=64)


@admin_router.post("/auth/change-password")
def admin_change_password(
    request: AdminChangePasswordRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员修改自己的登录密码"""
    if not verify_password(request.old_password, current_admin.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")

    current_admin.password_hash = hash_password(request.new_password)
    db.commit()

    _audit(db, current_admin, "admin_change_password", "self", current_admin.id)
    db.commit()
    return {"success": True, "message": "密码修改成功"}
