"""
管理后台 API 路由

借鉴 twilight-kotomi 的运营面板设计：
- 统一 JWT 管理员鉴权（is_staff 的 WebUser），全端点强制鉴权
- 卡码体系：注册码生成/停用/审计 + 注册模式开关（开放/需要码/关闭）
- 用户管理：列表/搜索/禁用/启用/重置密码
- 实时播放统计：今日榜/热门条目/最近注册（低 IO，直接读本地会话表）
- 操作审计：全部管理操作落 AdminLog（admin_user_id 存 WebUser.id）

管理员操作会触发通知发送到用户前台，实现前后台联动。
"""
import logging
import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db
from backend.notifications import (
    AdminEvent,
    notify_admin_event,
    notify_all_users,
)
from backend.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    resolve_jwt_user_id,
    verify_password,
)

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin", tags=["管理后台"])

security = HTTPBearer(auto_error=False)

CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code(length: int = 12) -> str:
    """生成人类易读的卡码（去掉易混淆的 0/O/1/I）"""
    alphabet = "".join(c for c in CODE_ALPHABET if c not in "0O1I")
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ==================== 鉴权依赖 ====================

async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> models.WebUser:
    """管理员鉴权：JWT access token，且必须是 is_staff 的 WebUser

    与用户端相同的 token 体系；权限差异仅由 is_staff 决定，
    不再有独立的 AdminUser 账号体系。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
        )

    user_id = resolve_jwt_user_id(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的凭证",
        )

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user or not user.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员已被禁用",
        )

    return user


def _audit(
    db: Session,
    admin: models.WebUser,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict | None = None,
    ip: str | None = None,
) -> None:
    """写操作审计日志（admin_user_id 存 WebUser.id）"""
    db.add(models.AdminLog(
        admin_user_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip,
    ))


def _log_out(model) -> str:
    return model.created_at.isoformat() if model.created_at else ""


# ==================== 管理员认证 API ====================

class AdminLoginRequest(BaseModel):
    username: str
    password: str


@admin_router.post("/auth/login")
async def admin_login(
    request: AdminLoginRequest,
    db: Session = Depends(get_db),
):
    """管理员登录：仅 is_staff 的 WebUser 可登录管理后台"""
    user = db.query(models.WebUser).filter(
        models.WebUser.username == request.username
    ).first()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_staff:
        raise HTTPException(status_code=403, detail="该账号没有管理员权限")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    user.last_login_at = datetime.now()
    db.commit()

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
async def admin_me(
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
async def admin_change_password(
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


# ==================== 请求/响应模型 ====================

class AnnouncementCreateRequest(BaseModel):
    title: str
    content: str
    type: str = "system"
    is_pinned: bool = False


class AnnouncementUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_active: Optional[bool] = None


class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None


class TicketReplyRequest(BaseModel):
    message: str
    close_ticket: bool = False


class MediaSeekUpdateRequest(BaseModel):
    status: str  # approved, rejected, completed
    admin_note: Optional[str] = None


class UserMessageSendRequest(BaseModel):
    user_id: Optional[int] = None  # 以路径参数为准，保留字段兼容旧调用
    title: str
    content: str
    message_type: str = "system"


class BroadcastMessageRequest(BaseModel):
    title: str
    content: str


class SubscriptionGrantRequest(BaseModel):
    """授予订阅请求"""
    plan_id: int
    duration_days: int


class SubscriptionExtendRequest(BaseModel):
    """延长订阅请求"""
    days: int = Field(..., ge=1, le=3650)


# ==================== 订阅管理 API ====================

@admin_router.get("/plans")
async def list_plans(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """订阅套餐列表（授予订阅时选择用）"""
    plans = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.is_active == True  # noqa: E712
    ).order_by(models.SubscriptionPlan.sort_order).all()
    return {"plans": [
        {
            "id": p.id, "name": p.name, "description": p.description,
            "price": float(p.price), "duration_days": p.duration_days,
            "is_popular": p.is_popular,
        }
        for p in plans
    ]}


@admin_router.post("/users/{user_id}/subscriptions")
async def grant_subscription(
    user_id: int,
    request: SubscriptionGrantRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """授予用户订阅 - 联动：通知用户"""
    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == request.plan_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")

    end_date = datetime.now() + timedelta(days=request.duration_days)
    subscription = models.UserSubscription(
        user_id=user_id,
        plan_id=request.plan_id,
        start_date=datetime.now(),
        end_date=end_date,
        status="active",
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    _audit(db, current_admin, "grant_subscription", "subscription",
           subscription.id, {"user_id": user_id, "plan_id": request.plan_id,
                             "duration_days": request.duration_days})
    db.commit()

    await notify_admin_event(
        event_type=AdminEvent.SUBSCRIPTION_MANUAL,
        user_id=user_id,
        title="🎉 恭喜获得订阅",
        content=(f"管理员已为您开通「{plan.name}」订阅，有效期 {request.duration_days} 天"
                 f"\n到期时间：{end_date.strftime('%Y-%m-%d')}"),
        related_id=subscription.id,
        from_admin_id=current_admin.id,
    )
    return {"success": True, "subscription_id": subscription.id,
            "message": "订阅授予成功并已通知用户"}


@admin_router.post("/subscriptions/{subscription_id}/extend")
async def extend_subscription(
    subscription_id: int,
    request: SubscriptionExtendRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """延长订阅有效期 - 联动：通知用户"""
    subscription = db.query(models.UserSubscription).filter(
        models.UserSubscription.id == subscription_id
    ).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")

    subscription.end_date = max(
        subscription.end_date or datetime.now(), datetime.now()
    ) + timedelta(days=request.days)
    subscription.updated_at = datetime.now()
    db.commit()

    _audit(db, current_admin, "extend_subscription", "subscription",
           subscription.id, {"days": request.days})
    db.commit()

    await notify_admin_event(
        event_type=AdminEvent.SUBSCRIPTION_EXTENDED,
        user_id=subscription.user_id,
        title="订阅已延长",
        content=(f"您的订阅已延长 {request.days} 天，"
                 f"新到期时间：{subscription.end_date.strftime('%Y-%m-%d')}"),
        related_id=subscription.id,
        from_admin_id=current_admin.id,
    )
    return {"success": True, "message": "订阅延长成功"}


# ==================== 用户管理 API ====================

@admin_router.get("/users")
async def list_users(
    search: str = "",
    active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """用户列表：搜索（用户名/邮箱）+ 状态筛选 + 分页"""
    query = db.query(models.WebUser)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            models.WebUser.username.ilike(like),
            models.WebUser.email.ilike(like),
        ))
    if active is not None:
        query = query.filter(models.WebUser.is_active == active)

    total = query.count()
    users = query.order_by(models.WebUser.id.desc()).offset(offset).limit(min(limit, 200)).all()
    now = datetime.now()

    items = []
    for u in users:
        active_sub = db.query(models.UserSubscription).filter(
            models.UserSubscription.user_id == u.id,
            models.UserSubscription.status == "active",
            models.UserSubscription.end_date > now,
        ).order_by(models.UserSubscription.end_date.desc()).first()
        items.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_active": u.is_active,
            "is_staff": u.is_staff,
            "emby_username": u.emby_username,
            "has_subscription": active_sub is not None,
            "subscription_id": active_sub.id if active_sub else None,
            "subscription_end": active_sub.end_date.isoformat() if active_sub else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": _log_out(u),
        })

    return {"total": total, "users": items}


class UserUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    is_staff: Optional[bool] = None


@admin_router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新用户状态（禁用/启用/授权管理员）

    安全约束：不能禁用/降级自己，避免把自己锁在门外。
    """
    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if user.id == current_admin.id and (
        request.is_active is False or request.is_staff is False
    ):
        raise HTTPException(status_code=400, detail="不能禁用或降级自己的账号")

    changed = {}
    if request.is_active is not None:
        user.is_active = request.is_active
        changed["is_active"] = request.is_active
    if request.is_staff is not None:
        user.is_staff = request.is_staff
        changed["is_staff"] = request.is_staff

    db.commit()
    _audit(db, current_admin, "update_user", "user", user.id, changed)
    db.commit()
    return {"success": True, "changed": changed}


class UserResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=64)


@admin_router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    request: UserResetPasswordRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重置用户密码（门户密码同步为 Emby 播放密码）"""
    from backend.emby_server.auth import ensure_emby_credentials

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.password_hash = hash_password(request.new_password)
    db.commit()

    # 同步 Emby 播放密码，保持"门户账号即 Emby 账号"
    try:
        ensure_emby_credentials(db, user, password=request.new_password)
    except Exception:  # noqa: BLE001 — Emby 凭据同步失败不阻塞密码重置
        logger.warning("重置密码后同步 Emby 凭据失败: user_id=%s", user_id, exc_info=True)

    _audit(db, current_admin, "reset_user_password", "user", user.id)
    db.commit()
    return {"success": True, "message": "密码已重置"}


@admin_router.post("/users/{user_id}/messages")
async def send_user_message(
    user_id: int,
    request: UserMessageSendRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """给指定用户发送站内消息"""
    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    _audit(db, current_admin, "send_user_message", "user", user_id,
           {"title": request.title})
    db.commit()

    await notify_admin_event(
        event_type=f"station.{request.message_type}",
        user_id=user_id,
        title=request.title,
        content=request.content,
        from_admin_id=current_admin.id,
    )
    return {"success": True, "message": "消息发送成功"}


@admin_router.post("/messages/broadcast")
async def broadcast_message(
    request: BroadcastMessageRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """广播消息给所有用户"""
    _audit(db, current_admin, "broadcast_message", "all_users", None,
           {"title": request.title})
    db.commit()

    count = await notify_all_users(
        event_type="system.broadcast",
        title=request.title,
        content=request.content,
    )
    return {"success": True, "message": f"广播已发送，预计接收 {count} 位在线用户"}


# ==================== 卡码体系 API ====================

class RegistrationCodeBatchRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_days: int = Field(default=30, ge=1, le=365)
    note: str = ""


@admin_router.get("/registration-codes")
async def list_registration_codes(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    """注册码列表 + 使用审计"""
    codes = db.query(models.RegistrationCode).order_by(
        models.RegistrationCode.created_at.desc()
    ).limit(min(limit, 200)).all()

    items = []
    for c in codes:
        used_by = []
        if c.used_by:
            ids = [int(i) for i in str(c.used_by).split(",") if i.strip().isdigit()]
            users = db.query(models.WebUser).filter(models.WebUser.id.in_(ids)).all()
            used_by = [{"id": u.id, "username": u.username} for u in users]

        items.append({
            "id": c.id,
            "code": c.code,
            "max_uses": c.max_uses,
            "use_count": c.use_count,
            "is_active": c.is_active,
            "note": c.note,
            "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            "used_by": used_by,
            "created_at": _log_out(c),
        })
    return {"codes": items}


@admin_router.post("/registration-codes")
async def create_registration_codes(
    request: RegistrationCodeBatchRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量生成注册码"""
    expires_at = datetime.now() + timedelta(days=request.expires_days)
    created = []
    for _ in range(request.count):
        code = models.RegistrationCode(
            code=_generate_code(),
            max_uses=request.max_uses,
            use_count=0,
            is_active=True,
            note=request.note or None,
            expires_at=expires_at,
            created_by=current_admin.id,
        )
        db.add(code)
        created.append(code)

    db.commit()
    for c in created:
        db.refresh(c)

    _audit(db, current_admin, "create_registration_codes", "registration_code",
           created[0].id if created else None,
           {"count": request.count, "max_uses": request.max_uses})
    db.commit()

    return {
        "success": True,
        "codes": [{"id": c.id, "code": c.code, "max_uses": c.max_uses,
                   "expires_at": c.expires_at.isoformat()} for c in created],
    }


class RegistrationCodeUpdateRequest(BaseModel):
    is_active: bool


@admin_router.put("/registration-codes/{code_id}")
async def update_registration_code(
    code_id: int,
    request: RegistrationCodeUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """启用/停用注册码"""
    code = db.query(models.RegistrationCode).filter(
        models.RegistrationCode.id == code_id
    ).first()
    if not code:
        raise HTTPException(status_code=404, detail="注册码不存在")

    code.is_active = request.is_active
    db.commit()
    _audit(db, current_admin, "update_registration_code", "registration_code",
           code.id, {"is_active": request.is_active})
    db.commit()
    return {"success": True}


class RegistrationModeRequest(BaseModel):
    mode: str  # open / code / closed
    message: str = ""


@admin_router.put("/settings/registration")
async def set_registration_mode(
    request: RegistrationModeRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """设置注册模式：open 开放注册 / code 需要注册码 / closed 关闭注册"""
    if request.mode not in ("open", "code", "closed"):
        raise HTTPException(status_code=400, detail="mode 必须是 open/code/closed")

    for key, value in (("registration_mode", request.mode),
                       ("registration_closed_message", request.message)):
        config = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if config:
            config.value = value
        else:
            db.add(models.SystemConfig(key=key, value=value))

    db.commit()
    _audit(db, current_admin, "set_registration_mode", "system", None,
           {"mode": request.mode})
    db.commit()
    return {"success": True, "mode": request.mode}


@admin_router.get("/settings/registration")
async def get_registration_mode(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    mode_config = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "registration_mode"
    ).first()
    msg_config = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "registration_closed_message"
    ).first()
    return {
        "mode": mode_config.value if mode_config else "open",
        "message": msg_config.value if msg_config else "",
    }


# ==================== 公告管理 API ====================

@admin_router.get("/announcements")
async def get_announcements(
    active_only: bool = False,
    limit: int = 100,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """公告列表（管理端，含未启用项）"""
    query = db.query(models.Announcement)
    if active_only:
        query = query.filter(models.Announcement.is_active == True)  # noqa: E712
    announcements = (
        query.order_by(models.Announcement.is_pinned.desc(), models.Announcement.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [
        {
            "id": a.id,
            "title": a.title,
            "content": a.content,
            "type": a.type,
            "is_active": bool(a.is_active),
            "is_pinned": bool(a.is_pinned),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in announcements
    ]


@admin_router.post("/announcements")
async def create_announcement(
    request: AnnouncementCreateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """创建公告 - 联动：广播通知所有用户"""
    announcement = models.Announcement(
        title=request.title,
        content=request.content,
        type=request.type,
        is_pinned=request.is_pinned,
        is_active=True,
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)

    _audit(db, current_admin, "create_announcement", "announcement",
           announcement.id, {"title": request.title})
    db.commit()

    await notify_all_users(
        event_type=AdminEvent.ANNOUNCEMENT_PUBLISHED,
        title=f"📢 {request.title}",
        content=request.content,
        data={"announcement_id": announcement.id, "type": request.type},
    )
    return {"success": True, "announcement_id": announcement.id,
            "message": "公告创建成功并已推送给所有用户"}


@admin_router.put("/announcements/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    request: AnnouncementUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    announcement = db.query(models.Announcement).filter(
        models.Announcement.id == announcement_id
    ).first()
    if not announcement:
        raise HTTPException(status_code=404, detail="公告不存在")

    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(announcement, key, value)
    announcement.updated_at = datetime.now()
    db.commit()

    _audit(db, current_admin, "update_announcement", "announcement",
           announcement_id, update_data)
    db.commit()

    await notify_all_users(
        event_type=AdminEvent.ANNOUNCEMENT_UPDATED,
        title="公告已更新",
        content=f"公告「{announcement.title}」已更新，请查看",
        data={"announcement_id": announcement_id},
    )
    return {"success": True, "message": "公告更新成功"}


@admin_router.delete("/announcements/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    announcement = db.query(models.Announcement).filter(
        models.Announcement.id == announcement_id
    ).first()
    if not announcement:
        raise HTTPException(status_code=404, detail="公告不存在")

    title = announcement.title
    db.delete(announcement)
    db.commit()
    _audit(db, current_admin, "delete_announcement", "announcement",
           announcement_id, {"title": title})
    db.commit()
    return {"success": True, "message": "公告删除成功"}


# ==================== 工单管理 API ====================

@admin_router.get("/tickets")
async def get_tickets(
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(models.Ticket)
    if status_filter:
        query = query.filter(models.Ticket.status == status_filter)
    if category_filter:
        query = query.filter(models.Ticket.category == category_filter)

    tickets = query.order_by(models.Ticket.created_at.desc()).limit(200).all()

    result = []
    for ticket in tickets:
        user = db.query(models.WebUser).filter(
            models.WebUser.id == ticket.user_id
        ).first()
        latest_message = db.query(models.TicketMessage).filter(
            models.TicketMessage.ticket_id == ticket.id
        ).order_by(models.TicketMessage.created_at.desc()).first()

        result.append({
            "id": ticket.id,
            "title": ticket.title,
            "category": ticket.category,
            "status": ticket.status,
            "priority": ticket.priority,
            "user_name": user.username if user else "未知",
            "created_at": _log_out(ticket),
            "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else "",
            "latest_message": latest_message.message[:100] if latest_message else "",
        })
    return result


@admin_router.get("/tickets/{ticket_id}/messages")
async def get_ticket_messages(
    ticket_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """工单会话内容（管理端）"""
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    messages = (
        db.query(models.TicketMessage)
        .filter(models.TicketMessage.ticket_id == ticket_id)
        .order_by(models.TicketMessage.created_at.asc())
        .all()
    )

    author_ids = [m.user_id for m in messages if m.user_id]
    authors = {
        u.id: u.username
        for u in db.query(models.WebUser).filter(models.WebUser.id.in_(author_ids)).all()
    } if author_ids else {}

    return [
        {
            "id": m.id,
            "message": m.message,
            "is_admin": bool(m.is_admin),
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "admin_name": authors.get(m.user_id, "管理员") if m.is_admin else None,
        }
        for m in messages
    ]


@admin_router.put("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    request: TicketUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ticket, key, value)
    ticket.updated_at = datetime.now()
    db.commit()

    _audit(db, current_admin, "update_ticket", "ticket", ticket_id, update_data)
    db.commit()

    await notify_admin_event(
        event_type=AdminEvent.TICKET_REPLIED,
        user_id=ticket.user_id,
        title="工单状态已更新",
        content=f"您的工单「{ticket.title}」状态已变更为：{ticket.status}",
        related_id=ticket_id,
        from_admin_id=current_admin.id,
    )
    return {"success": True, "message": "工单更新成功"}


@admin_router.post("/tickets/{ticket_id}/reply")
async def reply_ticket(
    ticket_id: int,
    request: TicketReplyRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """回复工单 - 联动：通知用户"""
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    message = models.TicketMessage(
        ticket_id=ticket.id,
        user_id=current_admin.id,  # 统一账号体系：staff 回复记 WebUser.id
        message=request.message,
        is_admin=True,
    )
    db.add(message)

    ticket.status = "closed" if request.close_ticket else "open"
    ticket.updated_at = datetime.now()
    db.commit()

    _audit(db, current_admin, "reply_ticket", "ticket", ticket_id,
           {"closed": request.close_ticket})
    db.commit()

    await notify_admin_event(
        event_type=AdminEvent.TICKET_REPLIED if not request.close_ticket else AdminEvent.TICKET_CLOSED,
        user_id=ticket.user_id,
        title="工单有新回复" if not request.close_ticket else "工单已关闭",
        content=request.message,
        related_id=ticket_id,
        from_admin_id=current_admin.id,
    )
    return {"success": True, "message": "回复成功"}


@admin_router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    ticket.status = "closed"
    ticket.updated_at = datetime.now()
    db.commit()

    await notify_admin_event(
        event_type=AdminEvent.TICKET_CLOSED,
        user_id=ticket.user_id,
        title="工单已关闭",
        content=f"您的工单「{ticket.title}」已被管理员关闭",
        related_id=ticket_id,
        from_admin_id=current_admin.id,
    )
    return {"success": True, "message": "工单已关闭"}


# ==================== 求片管理 API ====================

@admin_router.get("/media-seek")
async def get_media_seeks(
    status_filter: Optional[str] = None,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(models.MovieRequest)
    if status_filter:
        query = query.filter(models.MovieRequest.status == status_filter)

    requests = query.order_by(models.MovieRequest.created_at.desc()).limit(200).all()

    result = []
    for req in requests:
        user = db.query(models.WebUser).filter(
            models.WebUser.id == req.user_id
        ).first()
        result.append({
            "id": req.id,
            "movie_name": req.movie_name,
            "year": req.year,
            "type": req.type,
            "note": req.note,
            "status": req.status,
            "admin_note": req.admin_note,
            "user_name": user.username if user else "未知",
            "created_at": _log_out(req),
        })
    return result


@admin_router.put("/media-seek/{request_id}")
async def update_media_seek(
    request_id: int,
    request: MediaSeekUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    media_request = db.query(models.MovieRequest).filter(
        models.MovieRequest.id == request_id
    ).first()
    if not media_request:
        raise HTTPException(status_code=404, detail="求片请求不存在")

    media_request.status = request.status
    media_request.admin_note = request.admin_note
    media_request.updated_at = datetime.now()
    db.commit()

    _audit(db, current_admin, "update_media_seek", "media_seek", request_id,
           {"status": request.status})
    db.commit()

    event_map = {
        "approved": AdminEvent.MEDIA_SEEK_APPROVED,
        "rejected": AdminEvent.MEDIA_SEEK_REJECTED,
        "completed": AdminEvent.MEDIA_SEEK_COMPLETED,
    }
    title_map = {
        "approved": "求片请求已批准",
        "rejected": "求片请求已拒绝",
        "completed": "求片请求已完成",
    }
    await notify_admin_event(
        event_type=event_map.get(request.status, "media_seek.updated"),
        user_id=media_request.user_id,
        title=title_map.get(request.status, "求片状态已更新"),
        content=(f"您的求片《{media_request.movie_name}》状态已更新为：{request.status}"
                 + (f"\n备注：{request.admin_note}" if request.admin_note else "")),
        related_id=request_id,
        from_admin_id=current_admin.id,
    )
    return {"success": True, "message": "求片状态更新成功"}


# ==================== 操作日志 API ====================

@admin_router.get("/logs")
async def get_admin_logs(
    action_filter: Optional[str] = None,
    target_type_filter: Optional[str] = None,
    limit: int = 100,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(models.AdminLog)
    if action_filter:
        query = query.filter(models.AdminLog.action == action_filter)
    if target_type_filter:
        query = query.filter(models.AdminLog.target_type == target_type_filter)

    logs = query.order_by(models.AdminLog.created_at.desc()).limit(min(limit, 500)).all()

    result = []
    for log in logs:
        # 统一账号体系后 admin_user_id 存 WebUser.id
        operator = db.query(models.WebUser).filter(
            models.WebUser.id == log.admin_user_id
        ).first()

        result.append({
            "id": log.id,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "created_at": _log_out(log),
            "admin_name": operator.username if operator else "未知",
        })
    return result


# ==================== 统计数据 API ====================

@admin_router.get("/stats/overview")
async def get_stats_overview(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """系统概览统计"""
    from backend.emby_server import models as em

    total_users = db.query(models.WebUser).count()
    active_users = db.query(models.WebUser).filter(
        models.WebUser.is_active == True  # noqa: E712
    ).count()
    open_tickets = db.query(models.Ticket).filter(
        models.Ticket.status == "open"
    ).count()
    pending_requests = db.query(models.MovieRequest).filter(
        models.MovieRequest.status == "pending"
    ).count()

    # 自建 Emby 实时数据（低 IO：直接读本地表，不扫媒体库）
    total_items = db.query(em.MediaItem).count()
    active_sessions = db.query(em.PlaybackSession).filter(
        em.PlaybackSession.ended_at.is_(None)
    ).count()

    return {
        "users": {"total": total_users, "active": active_users},
        "tickets": {"open": open_tickets},
        "media_seeks": {"pending": pending_requests},
        "emby": {"total_items": total_items, "active_sessions": active_sessions},
    }


@admin_router.get("/stats/playback")
async def get_playback_stats(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """实时播放统计（借鉴 twilight-kotomi 的低 IO 统计）：

    - 今日播放次数 / 今日观看用户数（PlaybackSession 本地表）
    - 用户播放排行（Top 10）
    - 热门条目（Top 10）
    """
    from backend.emby_server import models as em

    day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    today_count = db.query(em.PlaybackSession).filter(
        em.PlaybackSession.start_time >= day_start
    ).count()
    today_users = db.query(func.count(func.distinct(em.PlaybackSession.user_id))).filter(
        em.PlaybackSession.start_time >= day_start
    ).scalar() or 0

    # 用户播放排行（近 7 天）
    week_start = day_start - timedelta(days=6)
    user_ranking = (
        db.query(
            models.WebUser.username,
            func.count(em.PlaybackSession.id).label("plays"),
        )
        .join(em.PlaybackSession, em.PlaybackSession.user_id == models.WebUser.id)
        .filter(em.PlaybackSession.start_time >= week_start)
        .group_by(models.WebUser.username)
        .order_by(func.count(em.PlaybackSession.id).desc())
        .limit(10)
        .all()
    )

    # 热门条目（近 7 天）
    item_ranking = (
        db.query(
            em.MediaItem.name,
            em.MediaItem.item_type,
            func.count(em.PlaybackSession.id).label("plays"),
        )
        .join(em.PlaybackSession, em.PlaybackSession.item_id == em.MediaItem.id)
        .filter(em.PlaybackSession.start_time >= week_start)
        .group_by(em.MediaItem.name, em.MediaItem.item_type)
        .order_by(func.count(em.PlaybackSession.id).desc())
        .limit(10)
        .all()
    )

    return {
        "today": {"plays": today_count, "users": today_users},
        "user_ranking": [
            {"username": name, "plays": plays} for name, plays in user_ranking
        ],
        "item_ranking": [
            {"name": name, "type": item_type, "plays": plays}
            for name, item_type, plays in item_ranking
        ],
    }


# ==================== 经济系统管理 API（v2.3.0） ====================

# ---------- 订阅套餐 CRUD ----------

class PlanUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    duration_days: int = Field(..., ge=1, le=3650)
    features: Optional[list] = None
    is_active: bool = True
    is_popular: bool = False
    sort_order: int = 0


@admin_router.get("/economy/plans")
async def economy_list_plans(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """全部订阅套餐（含停用）"""
    plans = db.query(models.SubscriptionPlan).order_by(
        models.SubscriptionPlan.sort_order, models.SubscriptionPlan.id
    ).all()
    return {"plans": [
        {
            "id": p.id, "name": p.name, "description": p.description,
            "price": float(p.price), "duration_days": p.duration_days,
            "features": p.features, "is_active": p.is_active,
            "is_popular": p.is_popular, "sort_order": p.sort_order,
        }
        for p in plans
    ]}


@admin_router.post("/economy/plans")
async def economy_create_plan(
    request: PlanUpsertRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    plan = models.SubscriptionPlan(
        name=request.name, description=request.description,
        price=Decimal(str(request.price)), duration_days=request.duration_days,
        features=request.features, is_active=request.is_active,
        is_popular=request.is_popular, sort_order=request.sort_order,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    _audit(db, current_admin, "economy_create_plan", "plan", plan.id,
           {"name": plan.name, "price": float(plan.price)})
    db.commit()
    return {"success": True, "id": plan.id}


@admin_router.put("/economy/plans/{plan_id}")
async def economy_update_plan(
    plan_id: int,
    request: PlanUpsertRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == plan_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")

    plan.name = request.name
    plan.description = request.description
    plan.price = Decimal(str(request.price))
    plan.duration_days = request.duration_days
    plan.features = request.features
    plan.is_active = request.is_active
    plan.is_popular = request.is_popular
    plan.sort_order = request.sort_order
    plan.updated_at = datetime.now()
    db.commit()

    _audit(db, current_admin, "economy_update_plan", "plan", plan.id)
    db.commit()
    return {"success": True}


@admin_router.delete("/economy/plans/{plan_id}")
async def economy_delete_plan(
    plan_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == plan_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")

    in_use = db.query(models.SubscriptionOrder).filter(
        models.SubscriptionOrder.plan_id == plan_id
    ).first()
    if in_use:
        plan.is_active = False
        db.commit()
        return {"success": True, "soft_deleted": True,
                "message": "套餐已有订单引用，已停用而非删除"}

    db.delete(plan)
    db.commit()
    _audit(db, current_admin, "economy_delete_plan", "plan", plan_id)
    db.commit()
    return {"success": True}


# ---------- 充值套餐 CRUD ----------

class PackageUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    amount: int = Field(..., ge=1, description="积分数量")
    price: float = Field(..., ge=0)
    bonus: int = Field(default=0, ge=0)
    is_active: bool = True
    is_popular: bool = False
    sort_order: int = 0


@admin_router.get("/economy/packages")
async def economy_list_packages(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    packages = db.query(models.RechargePackage).order_by(
        models.RechargePackage.sort_order, models.RechargePackage.id
    ).all()
    return {"packages": [
        {
            "id": p.id, "name": p.name, "amount": p.amount,
            "price": float(p.price), "bonus": p.bonus,
            "is_active": p.is_active, "is_popular": p.is_popular,
            "sort_order": p.sort_order,
        }
        for p in packages
    ]}


@admin_router.post("/economy/packages")
async def economy_create_package(
    request: PackageUpsertRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    package = models.RechargePackage(
        name=request.name, amount=request.amount,
        price=Decimal(str(request.price)), bonus=request.bonus,
        is_active=request.is_active, is_popular=request.is_popular,
        sort_order=request.sort_order,
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    _audit(db, current_admin, "economy_create_package", "package", package.id,
           {"name": package.name})
    db.commit()
    return {"success": True, "id": package.id}


@admin_router.put("/economy/packages/{package_id}")
async def economy_update_package(
    package_id: int,
    request: PackageUpsertRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    package = db.query(models.RechargePackage).filter(
        models.RechargePackage.id == package_id
    ).first()
    if not package:
        raise HTTPException(status_code=404, detail="充值套餐不存在")

    package.name = request.name
    package.amount = request.amount
    package.price = Decimal(str(request.price))
    package.bonus = request.bonus
    package.is_active = request.is_active
    package.is_popular = request.is_popular
    package.sort_order = request.sort_order
    db.commit()
    _audit(db, current_admin, "economy_update_package", "package", package.id)
    db.commit()
    return {"success": True}


@admin_router.delete("/economy/packages/{package_id}")
async def economy_delete_package(
    package_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    package = db.query(models.RechargePackage).filter(
        models.RechargePackage.id == package_id
    ).first()
    if not package:
        raise HTTPException(status_code=404, detail="充值套餐不存在")

    in_use = db.query(models.RechargeOrder).filter(
        models.RechargeOrder.package_id == package_id
    ).first()
    if in_use:
        package.is_active = False
        db.commit()
        return {"success": True, "soft_deleted": True,
                "message": "套餐已有订单引用，已停用而非删除"}

    db.delete(package)
    db.commit()
    _audit(db, current_admin, "economy_delete_package", "package", package_id)
    db.commit()
    return {"success": True}


# ---------- 兑换码管理 ----------

class ExchangeCodeBatchRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    type: str = Field(default="points")  # points / subscription
    points_value: int = Field(default=0, ge=0)
    plan_id: Optional[int] = None
    duration_days: int = Field(default=0, ge=0)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_days: int = Field(default=30, ge=1, le=3650)
    note: str = ""


@admin_router.get("/economy/exchange-codes")
async def economy_list_exchange_codes(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    codes = db.query(models.ExchangeCode).order_by(
        models.ExchangeCode.created_at.desc()
    ).limit(min(limit, 200)).all()

    plan_ids = {c.plan_id for c in codes if c.plan_id}
    plans = {p.id: p.name for p in db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id.in_(plan_ids)).all()} if plan_ids else {}

    items = []
    for c in codes:
        used_by = []
        if c.used_by:
            ids = [int(i) for i in str(c.used_by).split(",") if i.strip().isdigit()]
            users = db.query(models.WebUser).filter(models.WebUser.id.in_(ids)).all()
            used_by = [{"id": u.id, "username": u.username} for u in users]
        items.append({
            "id": c.id, "code": c.code, "type": c.type,
            "points_value": c.points_value,
            "plan_name": plans.get(c.plan_id),
            "duration_days": c.duration_days,
            "max_uses": c.max_uses, "use_count": c.use_count,
            "is_active": c.is_active, "note": c.note,
            "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            "used_by": used_by,
            "created_at": _log_out(c),
        })
    return {"codes": items}


@admin_router.post("/economy/exchange-codes")
async def economy_create_exchange_codes(
    request: ExchangeCodeBatchRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量生成兑换码（积分型 / 订阅型）"""
    if request.type not in ("points", "subscription"):
        raise HTTPException(status_code=400, detail="type 必须是 points 或 subscription")
    if request.type == "points" and request.points_value <= 0:
        raise HTTPException(status_code=400, detail="积分型兑换码必须设置 points_value")
    if request.type == "subscription":
        if not request.plan_id:
            raise HTTPException(status_code=400, detail="订阅型兑换码必须选择套餐")
        if request.duration_days <= 0:
            raise HTTPException(status_code=400, detail="订阅型兑换码必须设置时长")

    expires_at = datetime.now() + timedelta(days=request.expires_days)
    created = []
    for _ in range(request.count):
        code = models.ExchangeCode(
            code=_generate_code(),
            type=request.type,
            points_value=request.points_value if request.type == "points" else 0,
            plan_id=request.plan_id if request.type == "subscription" else None,
            duration_days=request.duration_days if request.type == "subscription" else 0,
            max_uses=request.max_uses,
            is_active=True,
            note=request.note or None,
            expires_at=expires_at,
            created_by=current_admin.id,
        )
        db.add(code)
        created.append(code)

    db.commit()
    for c in created:
        db.refresh(c)

    _audit(db, current_admin, "economy_create_exchange_codes", "exchange_code",
           created[0].id if created else None,
           {"count": request.count, "type": request.type})
    db.commit()
    return {
        "success": True,
        "codes": [{"id": c.id, "code": c.code, "type": c.type} for c in created],
    }


@admin_router.put("/economy/exchange-codes/{code_id}")
async def economy_update_exchange_code(
    code_id: int,
    request: RegistrationCodeUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """启用/停用兑换码"""
    code = db.query(models.ExchangeCode).filter(
        models.ExchangeCode.id == code_id
    ).first()
    if not code:
        raise HTTPException(status_code=404, detail="兑换码不存在")

    code.is_active = request.is_active
    db.commit()
    _audit(db, current_admin, "economy_update_exchange_code", "exchange_code",
           code.id, {"is_active": request.is_active})
    db.commit()
    return {"success": True}


# ---------- 订单管理 ----------

@admin_router.get("/economy/orders")
async def economy_list_orders(
    status_filter: Optional[str] = None,
    kind: Optional[str] = None,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """充值/订阅订单列表（合并视图）"""
    items = []
    total = 0

    want_recharge = kind in (None, "recharge")
    want_sub = kind in (None, "subscription")

    if want_recharge:
        q = db.query(models.RechargeOrder)
        if status_filter:
            q = q.filter(models.RechargeOrder.status == status_filter)
        if search:
            like = f"%{search}%"
            q = q.join(models.WebUser, models.RechargeOrder.user_id == models.WebUser.id).filter(
                or_(models.RechargeOrder.order_id.ilike(like),
                    models.WebUser.username.ilike(like))
            )
        total += q.count()
        for o in q.order_by(models.RechargeOrder.created_at.desc()).offset(offset).limit(limit).all():
            user = db.query(models.WebUser).filter(models.WebUser.id == o.user_id).first()
            items.append({
                "order_id": o.order_id, "kind": "recharge",
                "item_name": f"积分充值（+{o.amount}）",
                "username": user.username if user else "未知",
                "user_id": o.user_id,
                "amount": float(o.price), "status": o.status,
                "payment_method": o.payment_method,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            })

    if want_sub:
        q = db.query(models.SubscriptionOrder)
        if status_filter:
            q = q.filter(models.SubscriptionOrder.status == status_filter)
        if search:
            like = f"%{search}%"
            q = q.join(models.WebUser, models.SubscriptionOrder.user_id == models.WebUser.id).filter(
                or_(models.SubscriptionOrder.order_id.ilike(like),
                    models.WebUser.username.ilike(like))
            )
        total += q.count()
        for o in q.order_by(models.SubscriptionOrder.created_at.desc()).offset(offset).limit(limit).all():
            user = db.query(models.WebUser).filter(models.WebUser.id == o.user_id).first()
            items.append({
                "order_id": o.order_id, "kind": "subscription",
                "item_name": f"订阅 - {o.item_name}",
                "username": user.username if user else "未知",
                "user_id": o.user_id,
                "amount": float(o.amount), "status": o.status,
                "payment_method": o.payment_method,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            })

    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return {"total": total, "orders": items[:limit]}


@admin_router.post("/economy/orders/{order_id}/mark-paid")
async def economy_mark_order_paid(
    order_id: str,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """人工补单（标记已支付并履约）— 用于线下收款/支付回调丢失"""
    from backend.api.economy import _fulfill_order

    recharge_order = db.query(models.RechargeOrder).filter(
        models.RechargeOrder.order_id == order_id
    ).first()
    subscription_order = None
    if not recharge_order:
        subscription_order = db.query(models.SubscriptionOrder).filter(
            models.SubscriptionOrder.order_id == order_id
        ).first()
    if not recharge_order and not subscription_order:
        raise HTTPException(status_code=404, detail="订单不存在")

    if (recharge_order and recharge_order.status == "paid") or (
        subscription_order and subscription_order.status == "paid"
    ):
        raise HTTPException(status_code=400, detail="订单已是已支付状态")

    await _fulfill_order(db, recharge_order=recharge_order,
                         subscription_order=subscription_order)
    db.commit()

    _audit(db, current_admin, "economy_mark_order_paid", "order", None,
           {"order_id": order_id})
    db.commit()
    return {"success": True, "message": "订单已标记支付并发货"}


# ---------- 邀请与返利管理 ----------

@admin_router.get("/economy/invitations")
async def economy_list_invitations(
    limit: int = 100,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """邀请记录列表（谁邀请了谁、奖励多少）"""
    records = db.query(models.InvitationRecord).order_by(
        models.InvitationRecord.created_at.desc()
    ).limit(min(limit, 200)).all()

    user_ids = {r.inviter_id for r in records} | {r.invitee_id for r in records}
    users = {u.id: u.username for u in db.query(models.WebUser).filter(
        models.WebUser.id.in_(user_ids)).all()} if user_ids else {}

    return {"records": [
        {
            "id": r.id,
            "inviter": users.get(r.inviter_id, "未知"),
            "invitee": users.get(r.invitee_id, "未知"),
            "reward_points": r.reward_points,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]}


@admin_router.get("/economy/points-logs")
async def economy_points_logs(
    user_id: Optional[int] = None,
    type_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """全站积分流水台账"""
    q = db.query(models.PointsLog)
    if user_id:
        q = q.filter(models.PointsLog.user_id == user_id)
    if type_filter:
        q = q.filter(models.PointsLog.type == type_filter)

    total = q.count()
    logs = q.order_by(models.PointsLog.created_at.desc()).offset(offset).limit(min(limit, 200)).all()

    user_ids = {l.user_id for l in logs}
    users = {u.id: u.username for u in db.query(models.WebUser).filter(
        models.WebUser.id.in_(user_ids)).all()} if user_ids else {}

    return {
        "total": total,
        "logs": [
            {
                "id": l.id, "user_id": l.user_id,
                "username": users.get(l.user_id, "未知"),
                "amount": l.amount, "balance_after": l.balance_after,
                "type": l.type, "description": l.description,
                "ref_id": l.ref_id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


class PointsAdjustRequest(BaseModel):
    amount: int  # 正数发放 / 负数扣除
    reason: str = ""


@admin_router.post("/economy/users/{user_id}/points")
async def economy_adjust_points(
    user_id: int,
    request: PointsAdjustRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员手动调整用户积分（记账，留审计）"""
    from backend.api.economy import _add_points

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if request.amount == 0:
        raise HTTPException(status_code=400, detail="调整数量不能为 0")

    balance = _add_points(
        db, user, request.amount,
        "admin_grant" if request.amount > 0 else "admin_deduct",
        request.reason or f"管理员调整（{request.amount:+d}）",
        f"admin:{current_admin.id}",
    )
    db.commit()

    _audit(db, current_admin, "economy_adjust_points", "user", user_id,
           {"amount": request.amount, "reason": request.reason})
    db.commit()

    await notify_admin_event(
        event_type="economy.admin_adjust",
        user_id=user_id,
        title=f"💰 积分变动 {request.amount:+d}",
        content=f"{request.reason or '管理员调整'}\n当前余额：{balance} 积分",
        from_admin_id=current_admin.id,
    )
    return {"success": True, "balance": balance}


# ---------- 经济系统设置 ----------

ECONOMY_CONFIG_KEYS = {
    "checkin_enabled": "bool", "checkin_base_points": "int", "checkin_streak_bonus": "int",
    "checkin_streak_max_bonus": "int",
    "exchange_enabled": "bool",
    "recharge_enabled": "bool", "subscription_purchase_enabled": "bool",
    "payment_gateway_url": "str", "payment_partner_id": "str",
    "payment_partner_key": "secret", "payment_qqpay_enabled": "bool",
    "site_url": "str",
    "invitation_enabled": "bool", "invitation_reward_points": "int",
    "invitation_invitee_reward_points": "int", "invitation_rebate_percent": "int",
}


class EconomySettingsRequest(BaseModel):
    settings: dict


@admin_router.get("/economy/settings")
async def economy_get_settings(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    result = {}
    for key, value_type in ECONOMY_CONFIG_KEYS.items():
        config = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if value_type == "secret":
            result[key] = "******" if (config and config.value) else ""
        else:
            result[key] = config.value if config else ""
    return {"settings": result}


@admin_router.put("/economy/settings")
async def economy_update_settings(
    request: EconomySettingsRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新经济系统配置（secret 值为 ****** 时保持不变）"""
    changed = {}
    for key, value in request.settings.items():
        if key not in ECONOMY_CONFIG_KEYS:
            continue
        if ECONOMY_CONFIG_KEYS[key] == "secret" and (not value or value == "******"):
            continue
        config = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if config:
            config.value = str(value)
        else:
            db.add(models.SystemConfig(key=key, value=str(value)))
        changed[key] = str(value) if ECONOMY_CONFIG_KEYS[key] != "secret" else "(已更新)"

    db.commit()
    _audit(db, current_admin, "economy_update_settings", "system", None, changed)
    db.commit()
    return {"success": True, "changed": list(changed.keys())}


# ---------- 经济统计 ----------

@admin_router.get("/economy/stats")
async def economy_stats(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """经济系统概览：用户/积分/订单/兑换/邀请"""
    from sqlalchemy import func as _func

    total_points = db.query(_func.coalesce(_func.sum(models.WebUser.points), 0)).scalar() or 0
    pending_recharge = db.query(models.RechargeOrder).filter(
        models.RechargeOrder.status == "pending").count()
    paid_recharge = db.query(_func.coalesce(_func.sum(models.RechargeOrder.price), 0)).filter(
        models.RechargeOrder.status == "paid").scalar() or 0
    paid_sub = db.query(_func.coalesce(_func.sum(models.SubscriptionOrder.amount), 0)).filter(
        models.SubscriptionOrder.status == "paid").scalar() or 0

    return {
        "total_points": int(total_points),
        "checkins_today": db.query(models.CheckinRecord).filter(
            models.CheckinRecord.checkin_date >= datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0)).count(),
        "orders": {"pending": pending_recharge,
                   "revenue": round(float(paid_recharge) + float(paid_sub), 2)},
        "exchange_codes": {
            "total": db.query(models.ExchangeCode).count(),
            "used": db.query(models.ExchangeCode).filter(
                models.ExchangeCode.use_count > 0).count(),
        },
        "invitations": db.query(models.InvitationRecord).count(),
    }


# ==================== 用户详情 / 趋势 / 订阅总览（v2.4.0 补齐） ====================


def _days_left(end_date: Optional[datetime], now: datetime) -> int:
    if not end_date:
        return 0
    return max(0, (end_date - now).days)


@admin_router.get("/users/{user_id}")
async def get_user_detail(
    user_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """用户 360° 详情：资料 / 订阅 / 积分 / 订单 / 邀请 / 签到 / 观看"""
    from backend.emby_server import models as em

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    now = datetime.now()

    # ---------- 订阅 ----------
    subs = (
        db.query(models.UserSubscription)
        .filter(models.UserSubscription.user_id == user_id)
        .order_by(models.UserSubscription.end_date.desc())
        .limit(10)
        .all()
    )
    active_sub = next(
        (s for s in subs if s.status == "active" and s.end_date and s.end_date > now), None
    )

    def _sub_row(s: models.UserSubscription) -> dict:
        return {
            "id": s.id,
            "plan_name": s.plan.name if s.plan else f"套餐 #{s.plan_id}",
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "days_left": _days_left(s.end_date, now),
            "status": s.status,
        }

    # ---------- 积分 ----------
    income = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user_id, models.PointsLog.amount > 0
    ).scalar() or 0
    expense = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user_id, models.PointsLog.amount < 0
    ).scalar() or 0
    recent_logs = (
        db.query(models.PointsLog)
        .filter(models.PointsLog.user_id == user_id)
        .order_by(models.PointsLog.created_at.desc())
        .limit(10)
        .all()
    )

    # ---------- 订单 ----------
    recharge_orders = (
        db.query(models.RechargeOrder)
        .filter(models.RechargeOrder.user_id == user_id)
        .order_by(models.RechargeOrder.created_at.desc())
        .limit(10)
        .all()
    )
    sub_orders = (
        db.query(models.SubscriptionOrder)
        .filter(models.SubscriptionOrder.user_id == user_id)
        .order_by(models.SubscriptionOrder.created_at.desc())
        .limit(10)
        .all()
    )
    paid_total = float(
        db.query(func.coalesce(func.sum(models.RechargeOrder.price), 0)).filter(
            models.RechargeOrder.user_id == user_id,
            models.RechargeOrder.status == "paid",
        ).scalar() or 0
    ) + float(
        db.query(func.coalesce(func.sum(models.SubscriptionOrder.amount), 0)).filter(
            models.SubscriptionOrder.user_id == user_id,
            models.SubscriptionOrder.status == "paid",
        ).scalar() or 0
    )

    # ---------- 邀请 ----------
    invite_records = (
        db.query(models.InvitationRecord)
        .filter(models.InvitationRecord.inviter_id == user_id)
        .order_by(models.InvitationRecord.created_at.desc())
        .limit(10)
        .all()
    )
    invitee_ids = [r.invitee_id for r in invite_records]
    invitee_names = {
        u.id: u.username
        for u in db.query(models.WebUser).filter(models.WebUser.id.in_(invitee_ids)).all()
    } if invitee_ids else {}
    rebate_total = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user_id, models.PointsLog.type == "rebate"
    ).scalar() or 0

    # ---------- 签到 ----------
    checkin_count = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == user_id
    ).count()
    last_checkin = (
        db.query(models.CheckinRecord)
        .filter(models.CheckinRecord.user_id == user_id)
        .order_by(models.CheckinRecord.checkin_date.desc())
        .first()
    )

    # ---------- 观看 ----------
    plays = db.query(em.PlaybackSession).filter(em.PlaybackSession.user_id == user_id).count()
    watched_items = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == user_id,
        em.UserMediaData.played == True,  # noqa: E712
    ).count()

    return {
        "profile": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "emby_username": user.emby_username,
            "points": user.points or 0,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "subscription": {
            "active": _sub_row(active_sub) if active_sub else None,
            "history": [_sub_row(s) for s in subs],
        },
        "points": {
            "balance": user.points or 0,
            "income": int(income),
            "expense": abs(int(expense)),
            "recent": [
                {
                    "id": l.id,
                    "amount": l.amount,
                    "balance_after": l.balance_after,
                    "type": l.type,
                    "description": l.description,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                }
                for l in recent_logs
            ],
        },
        "orders": {
            "paid_total": round(paid_total, 2),
            "recharge": [
                {
                    "order_id": o.order_id,
                    "item_name": o.package.name if o.package else f"套餐 #{o.package_id}",
                    "amount": float(o.price),
                    "points": o.amount,
                    "status": o.status,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in recharge_orders
            ],
            "subscription": [
                {
                    "order_id": o.order_id,
                    "item_name": o.item_name or (o.plan.name if o.plan else f"套餐 #{o.plan_id}"),
                    "amount": float(o.amount),
                    "status": o.status,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in sub_orders
            ],
        },
        "invitation": {
            "count": db.query(models.InvitationRecord).filter(
                models.InvitationRecord.inviter_id == user_id
            ).count(),
            "rebate_total": int(rebate_total),
            "invitees": [
                {
                    "username": invitee_names.get(r.invitee_id, "未知"),
                    "reward_points": r.reward_points,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in invite_records
            ],
        },
        "checkin": {
            "total": checkin_count,
            "last_date": last_checkin.checkin_date.isoformat() if last_checkin else None,
            "streak": last_checkin.streak if last_checkin else 0,
        },
        "watch": {
            "plays": plays,
            "watched_items": watched_items,
        },
    }


@admin_router.get("/stats/trend")
async def get_stats_trend(
    days: int = 14,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """趋势统计（默认近 14 天）：新增用户 / 播放次数 / 营收 / 签到

    单次聚合查询后按日补零，保证折线图连续。
    """
    from backend.emby_server import models as em

    days = max(1, min(days, 90))
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)

    def _series(rows) -> dict:
        out: dict = {}
        for day, value in rows:
            key = str(day)[:10]
            out[key] = out.get(key, 0) + (value or 0)
        return out

    user_rows = db.query(
        func.date(models.WebUser.created_at), func.count(models.WebUser.id)
    ).filter(models.WebUser.created_at >= start).group_by(
        func.date(models.WebUser.created_at)
    ).all()

    play_rows = db.query(
        func.date(em.PlaybackSession.start_time), func.count(em.PlaybackSession.id)
    ).filter(em.PlaybackSession.start_time >= start).group_by(
        func.date(em.PlaybackSession.start_time)
    ).all()

    recharge_rows = db.query(
        func.date(models.RechargeOrder.paid_at), func.coalesce(func.sum(models.RechargeOrder.price), 0)
    ).filter(
        models.RechargeOrder.status == "paid", models.RechargeOrder.paid_at >= start
    ).group_by(func.date(models.RechargeOrder.paid_at)).all()

    sub_rows = db.query(
        func.date(models.SubscriptionOrder.paid_at), func.coalesce(func.sum(models.SubscriptionOrder.amount), 0)
    ).filter(
        models.SubscriptionOrder.status == "paid", models.SubscriptionOrder.paid_at >= start
    ).group_by(func.date(models.SubscriptionOrder.paid_at)).all()

    checkin_rows = db.query(
        func.date(models.CheckinRecord.checkin_date), func.count(models.CheckinRecord.id)
    ).filter(models.CheckinRecord.checkin_date >= start).group_by(
        func.date(models.CheckinRecord.checkin_date)
    ).all()

    users_map = _series(user_rows)
    plays_map = _series(play_rows)
    recharge_map = _series(recharge_rows)
    sub_map = _series(sub_rows)
    checkin_map = _series(checkin_rows)

    series = []
    for i in range(days):
        day = start + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        series.append({
            "date": key,
            "new_users": int(users_map.get(key, 0)),
            "plays": int(plays_map.get(key, 0)),
            "revenue": round(float(recharge_map.get(key, 0)) + float(sub_map.get(key, 0)), 2),
            "checkins": int(checkin_map.get(key, 0)),
        })

    return {
        "days": days,
        "series": series,
        "totals": {
            "new_users": sum(p["new_users"] for p in series),
            "plays": sum(p["plays"] for p in series),
            "revenue": round(sum(p["revenue"] for p in series), 2),
            "checkins": sum(p["checkins"] for p in series),
        },
    }


@admin_router.get("/economy/subscriptions")
async def economy_list_subscriptions(
    status_filter: str = "",
    limit: int = 50,
    offset: int = 0,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """订阅总览：全部订阅记录 + 状态筛选 + 到期概览

    status_filter: active（生效中）/ expiring（7 天内到期）/ expired（已过期）
    """
    now = datetime.now()
    week_later = now + timedelta(days=7)

    q = db.query(models.UserSubscription)
    if status_filter == "active":
        q = q.filter(models.UserSubscription.status == "active",
                     models.UserSubscription.end_date > now)
    elif status_filter == "expiring":
        q = q.filter(models.UserSubscription.status == "active",
                     models.UserSubscription.end_date > now,
                     models.UserSubscription.end_date <= week_later)
    elif status_filter == "expired":
        q = q.filter(or_(models.UserSubscription.status == "expired",
                         models.UserSubscription.end_date <= now))

    total = q.count()
    rows = q.order_by(models.UserSubscription.end_date.asc()).offset(offset).limit(min(limit, 200)).all()

    user_ids = {r.user_id for r in rows}
    users = {
        u.id: u.username
        for u in db.query(models.WebUser).filter(models.WebUser.id.in_(user_ids)).all()
    } if user_ids else {}

    active_count = db.query(models.UserSubscription).filter(
        models.UserSubscription.status == "active", models.UserSubscription.end_date > now
    ).count()
    expiring_count = db.query(models.UserSubscription).filter(
        models.UserSubscription.status == "active",
        models.UserSubscription.end_date > now,
        models.UserSubscription.end_date <= week_later,
    ).count()
    expired_count = db.query(models.UserSubscription).filter(
        or_(models.UserSubscription.status == "expired",
            models.UserSubscription.end_date <= now)
    ).count()

    return {
        "total": total,
        "summary": {
            "active": active_count,
            "expiring_7d": expiring_count,
            "expired": expired_count,
        },
        "subscriptions": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": users.get(r.user_id, "未知"),
                "plan_name": r.plan.name if r.plan else f"套餐 #{r.plan_id}",
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "days_left": _days_left(r.end_date, now),
                "status": "active" if (r.status == "active" and r.end_date and r.end_date > now) else "expired",
            }
            for r in rows
        ],
    }


# ==================== 导出 ====================

__all__ = ["admin_router"]
