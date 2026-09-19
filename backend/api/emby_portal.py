"""用户门户认证 API：注册 / 登录 / JWT 刷新 / 当前用户 / 改密

端点（前缀 /api/user/auth）：
- POST /register          注册新用户，返回 access_token + refresh_token + user
- POST /login             用户名密码登录，返回 access_token + refresh_token + user
- POST /refresh           用 refresh_token 换新 access_token
- GET  /me                当前用户信息（JWT 鉴权）
- POST /logout            登出（无状态 JWT：客户端清除 token 即可）
- POST /change-password   修改密码（JWT 鉴权，需验证旧密码）
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db
from backend.emby_server.auth import ensure_emby_credentials
from backend.ratelimit import check_rate_limit, client_ip
from backend.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    resolve_jwt_user_id,
    verify_password,
)

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/user/auth", tags=["用户端-认证"])

bearer_scheme = HTTPBearer(auto_error=False)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


# ==================== Schemas ====================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=64)
    email: str | None = None
    invitation_code: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=64)


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None = None
    emby_username: str | None = None
    is_vip: bool = False
    is_active: bool = True
    created_at: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ==================== Helpers ====================

def _user_out(user: models.WebUser) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        emby_username=user.emby_username,
        is_vip=False,  # VIP 状态由订阅系统维护，此处仅展示基础字段
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


def _issue_auth_response(user: models.WebUser, db: Session) -> AuthResponse:
    """签发 access + refresh token，并确保自建 Emby 凭据存在"""
    ensure_emby_credentials(db, user)
    access = create_access_token(user.id, {"username": user.username})
    refresh = create_refresh_token(user.id)

    return AuthResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_user_out(user),
    )


def get_current_user_jwt(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.WebUser:
    """JWT 鉴权依赖：Authorization: Bearer <access_token>"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证凭证")
    user_id = resolve_jwt_user_id(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或已过期的凭证")
    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")
    return user


def get_current_user_compat(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.WebUser:
    """兼容鉴权：JWT 优先，回退到旧数字 token（向后兼容已部署前端）"""
    if credentials and credentials.credentials:
        user_id = resolve_jwt_user_id(credentials.credentials)
        if user_id is None and credentials.credentials.isdigit():
            user_id = int(credentials.credentials)  # 旧版数字 token
        if user_id is not None:
            user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
            if user and user.is_active:
                return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证凭证")


# ==================== Endpoints ====================

@auth_router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, req: RegisterRequest, db: Session = Depends(get_db)):
    """注册新用户（用户名唯一，密码 bcrypt 存储，自动生成自建 Emby 凭据）"""
    allowed, retry_after = check_rate_limit(f"register:{client_ip(request)}", 5, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail="注册过于频繁，请稍后再试")
    username = req.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="用户名只能包含字母、数字、下划线，长度 3-32 位",
        )

    existing = db.query(models.WebUser).filter(models.WebUser.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已被注册")

    if req.email:
        email = req.email.strip()
        if "@" not in email:
            raise HTTPException(status_code=400, detail="邮箱格式不正确")
        existing_email = db.query(models.WebUser).filter(models.WebUser.email == email).first()
        if existing_email:
            raise HTTPException(status_code=409, detail="邮箱已被注册")

    user = models.WebUser(
        username=username,
        password_hash=hash_password(req.password),
        email=req.email.strip() if req.email else None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("新用户注册: %s (id=%s)", username, user.id)
    return _issue_auth_response(user, db)


@auth_router.post("/login", response_model=AuthResponse)
async def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """用户名密码登录，成功返回 JWT（同 IP 每分钟最多 8 次尝试）"""
    allowed, retry_after = check_rate_limit(f"login:{client_ip(request)}", 8, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")
    user = (
        db.query(models.WebUser)
        .filter(models.WebUser.username == req.username.strip())
        .first()
    )
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")

    user.last_login_at = datetime.now()
    db.commit()
    return _issue_auth_response(user, db)


@auth_router.post("/refresh")
async def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    """用 refresh_token 换取新的 access_token（+ 可选轮换的 refresh_token）"""
    payload = decode_token(req.refresh_token, expected_type="refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="无效或已过期的刷新凭证")
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="无效的刷新凭证")

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    return {
        "access_token": create_access_token(user.id, {"username": user.username}),
        "refresh_token": create_refresh_token(user.id),  # 轮换
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": _user_out(user),
    }


@auth_router.get("/me", response_model=UserOut)
async def me(current_user: models.WebUser = Depends(get_current_user_jwt)):
    """当前登录用户信息"""
    return _user_out(current_user)


@auth_router.post("/logout")
async def logout(current_user: models.WebUser = Depends(get_current_user_jwt)):
    """登出（无状态 JWT，客户端清除 token）"""
    return {"success": True, "message": "已登出"}


@auth_router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: models.WebUser = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
):
    """修改密码（验证旧密码，同步更新自建 Emby 播放密码）"""
    if not verify_password(req.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if req.old_password == req.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    current_user.password_hash = hash_password(req.new_password)
    # 同步自建 Emby 播放密码（bcrypt 哈希存储），保持两端一致
    current_user.emby_password = hash_password(req.new_password)
    db.commit()
    return {"success": True, "message": "密码已更新"}
