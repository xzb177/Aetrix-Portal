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

from backend import codes, models
from backend.authlog import client_ip as log_ip, record_event, user_agent
from backend.database import get_db
from backend.devices import device_limit
from backend.emby_server.auth import ensure_emby_credentials
from backend.subscriptions import (
    download_allowed,
    has_active_subscription,
    is_free_realm,
    realm_access_note,
    realm_requires_subscription,
)
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
    invitation_code: str | None = None  # 邀请码（选填，双向奖励+返利绑定）
    registration_code: str | None = None  # 注册模式下必填


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
    # 是否管理员：用户端据此显示「管理后台」入口（管理后台与门户同一套 JWT）
    is_staff: bool = False
    # 付费墙是否开启（开启且非会员时播放会被拦截）；公益服恒为 false
    subscription_required: bool = False
    # 站点是否允许下载 + 每用户设备上限（0 表示不限）
    download_allowed: bool = True
    device_limit: int = 0
    # 接入方式（v2.7.0 公益服）：free = 本服免费开放，不需要订阅
    realm_access_mode: str = "paid"
    is_free_realm: bool = False
    # 公益服规则文案（用户端展示；付费服为空串）
    realm_access_note: str = ""
    created_at: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ==================== Helpers ====================

def _user_out(user: models.WebUser, db: Session | None = None) -> UserOut:
    """用户信息出参：is_vip 由生效中的订阅派生（无 db 时回退到库内标记）

    ``subscription_required`` 告知前端「这个服要不要会员才能看」，用于提前展示开通引导——
    公益服（``realm_access_mode='free'``）恒为 false，前端据此换一套「免费开放」的文案，
    而不是把一个不需要付费的服宣传成付费墙。
    """
    is_vip = has_active_subscription(db, user.id) if db is not None else bool(user.is_vip)
    requires_sub = realm_requires_subscription(db) if db is not None else False
    free_realm = is_free_realm(db) if db is not None else False
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        emby_username=user.emby_username,
        is_vip=is_vip,
        is_active=user.is_active,
        is_staff=bool(user.is_staff),
        subscription_required=requires_sub,
        download_allowed=download_allowed(db) if db is not None else True,
        device_limit=device_limit(db) if db is not None else 0,
        realm_access_mode="free" if free_realm else "paid",
        is_free_realm=free_realm,
        realm_access_note=realm_access_note(db) if db is not None else "",
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


def _issue_auth_response(
    user: models.WebUser, db: Session, plain_password: str | None = None
) -> AuthResponse:
    """签发 access + refresh token，并确保自建 Emby 凭据存在

    plain_password: 注册/登录成功后把门户密码同步为 Emby 播放密码（bcrypt 存储），
    保证“门户账号即 Emby 账号”——用户无需另行设置即可在 Infuse 等客户端登录。
    """
    if plain_password:
        ensure_emby_credentials(db, user, password=plain_password)
    else:
        ensure_emby_credentials(db, user)
    access = create_access_token(user.id, {"username": user.username})
    refresh = create_refresh_token(user.id)

    return AuthResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_user_out(user, db),
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

    # ===== 注册模式开关（借鉴 twilight-kotomi 的卡码体系）=====
    # open: 开放注册 / code: 必须携带有效注册码 / closed: 关闭注册
    mode_config = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "registration_mode"
    ).first()
    reg_mode = mode_config.value if mode_config else "open"

    reg_code = None  # 命中的注册码（延迟到用户创建成功后再消耗）
    if reg_mode == "closed":
        closed_msg_config = db.query(models.SystemConfig).filter(
            models.SystemConfig.key == "registration_closed_message"
        ).first()
        raise HTTPException(
            status_code=403,
            detail=(closed_msg_config.value if closed_msg_config and closed_msg_config.value
                    else "当前未开放注册"),
        )
    if reg_mode == "code":
        if not req.registration_code:
            raise HTTPException(status_code=400, detail="当前注册需要注册码")
        reg_code = codes.find_reg_code(db, req.registration_code)
        error = codes.reg_code_error(reg_code) if reg_code else "卡码无效"
        if not error and reg_code and reg_code.code_type == codes.CODE_TYPE_RENEW:
            # 与参考实现口径一致：续期码只能由已登录用户使用
            error = "该卡码为续期码，请登录后在个人中心使用"
        if not error and reg_code and reg_code.target_username:
            if reg_code.target_username.strip().lower() != username.lower():
                error = "该卡码限指定账号使用"
        if not error and reg_code and reg_code.is_decoy:
            # 诱饵码：只应出现在盗版/破解渠道，注册即拒绝并落安全日志
            record_event(
                db, username=username, ip=log_ip(request), agent=user_agent(request),
                success=False, reason="decoy_code", detail=f"注册使用了诱饵码 {reg_code.code}",
            )
            error = "注册码无效或已过期"
        if error:
            raise HTTPException(status_code=400, detail=error)

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

    # 卡码消耗 + 按卡码类型授予会员天数（注册码开通、白名单码置为长期有效）
    # 开的是**卡码所属服**的会员：多服下用乙服的注册码注册，就该拿到乙服的会员
    if reg_code is not None:
        codes.consume(db, reg_code, user.id)
        codes.grant_membership_days(db, user, codes.grant_days_for(reg_code),
                                    codes.code_realm_id(db, reg_code))

    # 邀请返利：注册时应用邀请码（双向发奖，失败静默不阻塞注册）
    if req.invitation_code:
        try:
            from backend.api.invitation import apply_invitation
            apply_invitation(db, user, req.invitation_code)
            db.commit()
        except Exception:  # noqa: BLE001 — 邀请奖励失败不阻塞注册
            db.rollback()
            logger.warning("邀请码应用失败: user=%s code=%s", user.id, req.invitation_code,
                           exc_info=True)

    logger.info("新用户注册: %s (id=%s, mode=%s)", username, user.id, reg_mode)
    return _issue_auth_response(user, db, plain_password=req.password)


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
        record_event(
            db, username=req.username.strip(), user_id=user.id if user else None,
            ip=log_ip(request), agent=user_agent(request), success=False,
            reason="portal_login_failed", detail="用户名或密码错误",
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        record_event(
            db, username=user.username, user_id=user.id, ip=log_ip(request),
            agent=user_agent(request), success=False, reason="portal_login_failed",
            detail="账户已被禁用",
        )
        raise HTTPException(status_code=403, detail="账户已被禁用")

    user.last_login_at = datetime.now()
    db.commit()
    record_event(
        db, username=user.username, user_id=user.id, ip=log_ip(request),
        agent=user_agent(request), success=True, reason="portal_login",
    )
    # 旧数据迁移：emby_password 为空的老用户，登录成功后用已验证的门户密码补齐 Emby 凭据
    return _issue_auth_response(user, db, plain_password=req.password)


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
        "user": _user_out(user, db),
    }


@auth_router.get("/me", response_model=UserOut)
async def me(
    current_user: models.WebUser = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
):
    """当前登录用户信息（含派生的 VIP 状态）"""
    return _user_out(current_user, db)


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
