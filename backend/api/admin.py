"""
管理后台 API 路由

借鉴 twilight-kotomi 的运营面板设计：
- 统一 JWT 管理员鉴权（is_staff 的 WebUser），全端点强制鉴权
- 卡码体系：注册码生成/停用/审计 + 注册模式开关（开放/需要码/关闭）
- 用户管理：列表/搜索/禁用/启用/重置密码
- 实时播放统计：今日榜/热门条目/最近注册（低 IO，直接读本地会话表）
- 操作审计：全部管理操作落 AdminLog（admin_user_id 存 WebUser.id）

管理员操作会触发通知发送到用户前台，实现前后台联动。

v2.21.0 起按域拆分成同目录的兄弟模块（导入即注册同一个 ``admin_router``）：

- ``admin_core``：公共骨架（路由对象 / 管理员鉴权依赖 / 审计与卡码辅助）
- ``admin_auth``：管理员登录 / 当前身份 / 改密
- ``admin_economy``：邀请返利 / 积分台账 / 经济设置与统计 / 用户详情与趋势

本模块保留订阅、用户、卡码、公告、工单、求片、操作日志、统计与经济系统管理。
原本单文件两千多行，改一个审计点要在几千行里翻，也没法整体复核。
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend import models, realms
from backend import qbittorrent
from backend import servers
from backend.database import get_db
from backend.notifications import (
    AdminEvent,
    notify_admin_event,
    notify_all_users,
)
from backend.security import hash_password

from backend.api.admin_core import (
    _audit,
    _generate_code,
    _log_out,
    admin_router,
    get_current_admin,
    logger,
)

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


class MediaSeekPushRequest(BaseModel):
    """把求片转交给外部服务

    - ``target``：``moviepilot``（提交订阅）/ ``qbittorrent``（加种）/ ``auto``（优先 MoviePilot）
    - ``link``：qB 需要磁力 / 种子链接（它自己不会去找片子；MoviePilot 不需要）
    """
    target: str = "auto"
    link: Optional[str] = Field(default=None, max_length=2000)


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
    # 开哪个服的会员：留空时按套餐所属的服（再回退到面板当前服）
    realm_id: Optional[int] = None


class SubscriptionExtendRequest(BaseModel):
    """延长订阅请求"""
    days: int = Field(..., ge=1, le=3650)


# ==================== 订阅管理 API ====================

@admin_router.get("/plans")
def list_plans(
    realm_id: Optional[int] = None,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """订阅套餐列表（授予订阅时选择用）—— 默认只列当前服的套餐

    ``realm_id=0`` 表示全部服（跨服汇总时用）。
    """
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope(db.query(models.SubscriptionPlan), models.SubscriptionPlan.realm_id, scope_id)
    plans = query.filter(
        models.SubscriptionPlan.is_active == True  # noqa: E712
    ).order_by(models.SubscriptionPlan.sort_order).all()
    return {"plans": [
        {
            "id": p.id, "name": p.name, "description": p.description,
            "price": float(p.price), "duration_days": p.duration_days,
            "is_popular": p.is_popular,
            "realm_id": p.realm_id,
            "realm_name": (p.realm.name if p.realm else ""),
        }
        for p in plans
    ],
        "realm_id": scope_id,
        "active_realm_id": realms.active_realm_id(db)}


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
    # 会员开在哪个服：显式指定 > 套餐所属的服 > 面板当前服。
    # 决定了这份会员能在哪台 EA 上播放（见 backend/subscriptions.py）。
    realm_id = request.realm_id or plan.realm_id or realms.active_realm_id(db)
    subscription = models.UserSubscription(
        user_id=user_id,
        plan_id=request.plan_id,
        realm_id=realm_id,
        start_date=datetime.now(),
        end_date=end_date,
        status="active",
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    _audit(db, current_admin, "grant_subscription", "subscription",
           subscription.id, {"user_id": user_id, "plan_id": request.plan_id,
                             "duration_days": request.duration_days,
                             "realm_id": realm_id})
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
def list_users(
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
def update_user(
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
def reset_user_password(
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
    # count = 真正落了站内消息的用户数（全部启用账号；在线的那部分同时做了实时推送），
    # 旧文案写成「在线用户」与现在的行为不符
    return {"success": True, "notified_users": count,
            "message": f"广播已发送，已为 {count} 位用户生成站内消息"}


# ==================== 卡码体系 API ====================

class RegistrationCodeBatchRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_days: int = Field(default=30, ge=1, le=365)
    note: str = ""
    # 这批码开通哪个服的会员（留空 = 当前服）
    realm_id: Optional[int] = None


@admin_router.get("/registration-codes")
def list_registration_codes(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    realm_id: Optional[int] = None,
    limit: int = 100,
):
    """注册码列表 + 使用审计（按服；``realm_id=0`` 为全部服）"""
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    codes = realms.scope(db.query(models.RegistrationCode),
                         models.RegistrationCode.realm_id, scope_id).order_by(
        models.RegistrationCode.created_at.desc()
    ).limit(min(limit, 200)).all()

    realm_names = {r.id: r.name for r in realms.list_realms(db)}
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
            "realm_id": c.realm_id,
            "realm_name": realm_names.get(c.realm_id, "") if c.realm_id else "",
            "max_uses": c.max_uses,
            "use_count": c.use_count,
            "is_active": c.is_active,
            "note": c.note,
            "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            "used_by": used_by,
            "created_at": _log_out(c),
        })
    return {"codes": items, "realm_id": scope_id}


@admin_router.post("/registration-codes")
def create_registration_codes(
    request: RegistrationCodeBatchRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量生成注册码（默认归当前服，开的就是这个服的会员）"""
    target_realm = realms.claim(db, request.realm_id)
    if not realms.get_realm(db, target_realm):
        raise HTTPException(status_code=400, detail=f"服不存在: #{target_realm}")
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
            realm_id=target_realm,
        )
        db.add(code)
        created.append(code)

    db.commit()
    for c in created:
        db.refresh(c)

    _audit(db, current_admin, "create_registration_codes", "registration_code",
           created[0].id if created else None,
           {"count": request.count, "max_uses": request.max_uses,
            "realm_id": target_realm})
    db.commit()

    return {
        "success": True,
        "realm_id": target_realm,
        "codes": [{"id": c.id, "code": c.code, "realm_id": c.realm_id,
                   "max_uses": c.max_uses,
                   "expires_at": c.expires_at.isoformat()} for c in created],
    }


class RegistrationCodeUpdateRequest(BaseModel):
    is_active: bool


@admin_router.put("/registration-codes/{code_id}")
def update_registration_code(
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
def set_registration_mode(
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
def get_registration_mode(
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
def get_announcements(
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

    # notify_all_users 现在给**每个启用中的用户**落站内消息（不只当时在线的人），
    # 返回值就是实际收到的用户数，文案跟着这个数字走，不再无条件宣称"已推送给所有用户"
    notified = await notify_all_users(
        event_type=AdminEvent.ANNOUNCEMENT_PUBLISHED,
        title=f"📢 {request.title}",
        content=request.content,
        data={"announcement_id": announcement.id, "type": request.type},
    )
    return {"success": True, "announcement_id": announcement.id,
            "notified_users": notified,
            "message": f"公告创建成功，已为 {notified} 位用户生成站内消息"}


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
def delete_announcement(
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
def get_tickets(
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
def get_ticket_messages(
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
def get_media_seeks(
    status_filter: Optional[str] = None,
    realm_id: Optional[int] = None,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """求片清单（可按归属服筛选；``realm_id=0`` = 全部服）

    求片本身是"这部片要进哪个服的库"，用户提交时选的服会被记下来；
    推送出口（MoviePilot / qB）是全局共享一套，所以推的时候不分服。
    """
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope_inclusive(db.query(models.MovieRequest),
                                   models.MovieRequest.realm_id, scope_id)
    if status_filter:
        query = query.filter(models.MovieRequest.status == status_filter)
    else:
        # 用户主动撤回的条目不进待办清单（仍计入用户当天的提交额度，见 user.py）。
        # 想看它们就显式传 status_filter=withdrawn。
        query = query.filter(models.MovieRequest.status != "withdrawn")

    requests = query.order_by(models.MovieRequest.created_at.desc()).limit(200).all()
    realm_names = {r.id: r.name for r in realms.list_realms(db)}

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
            "realm_id": req.realm_id,
            "realm_name": realm_names.get(req.realm_id, "") if req.realm_id else "",
            "user_name": user.username if user else "未知",
            "created_at": _log_out(req),
            # 转交外部服务的结果：让面板能看出「批了但还没真的去下载」
            "push_target": req.push_target,
            "push_status": req.push_status,
            "push_message": req.push_message,
            "pushed_at": req.pushed_at.isoformat() if req.pushed_at else None,
        })
    return result


@admin_router.post("/media-seek/{request_id}/push")
async def push_media_seek(
    request_id: int,
    payload: MediaSeekPushRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """把一条求片交给 MoviePilot（订阅）或 qBittorrent（加种）

    以前求片只能改状态，批了之后得管理员自己去别处搜片子——这个端点把那一步接上。
    失败原因（连不上 / 凭据不对 / 没填链接）原样回给面板，不假装成功。
    """
    media_request = db.query(models.MovieRequest).filter(
        models.MovieRequest.id == request_id
    ).first()
    if not media_request:
        raise HTTPException(status_code=404, detail="求片请求不存在")

    # qB 要链接：直接给磁力最好；只贴了整段分享文本也能从中挑出一条
    link = qbittorrent.pick_link(payload.link or "") or (payload.link or "").strip()
    result = await servers.push_media_seek(db, media_request, payload.target, link=link)

    target = str(result.get("target") or payload.target)
    media_request.push_target = target
    media_request.push_status = "ok" if result.get("ok") else "failed"
    media_request.push_message = str(result.get("message") or "")[:300]
    media_request.pushed_at = datetime.now()
    # 交出去了就代表处理过了：批过的求片推成功时顺手标成已批准，省得管理员再点一次
    if result.get("ok") and media_request.status == "pending":
        media_request.status = "approved"
    db.commit()

    _audit(db, current_admin, "push_media_seek", "media_seek", request_id,
           {"target": target, "ok": bool(result.get("ok")),
            "server": result.get("server")})
    db.commit()

    return {
        "success": bool(result.get("ok")),
        "target": target,
        "server": result.get("server"),
        "message": str(result.get("message") or ""),
        "request_id": request_id,
        "status": media_request.status,
    }


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
def get_admin_logs(
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
def get_stats_overview(
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
def get_playback_stats(
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
    # 套餐一个服一个：留空时归到面板当前服
    realm_id: Optional[int] = None


@admin_router.get("/economy/plans")
def economy_list_plans(
    realm_id: Optional[int] = None,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """订阅套餐（含停用）—— 默认只列当前服；``realm_id=0`` 列全部服"""
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope(db.query(models.SubscriptionPlan), models.SubscriptionPlan.realm_id, scope_id)
    plans = query.order_by(
        models.SubscriptionPlan.sort_order, models.SubscriptionPlan.id
    ).all()
    return {"plans": [
        {
            "id": p.id, "name": p.name, "description": p.description,
            "price": float(p.price), "duration_days": p.duration_days,
            "features": p.features, "is_active": p.is_active,
            "is_popular": p.is_popular, "sort_order": p.sort_order,
            "realm_id": p.realm_id,
            "realm_name": (p.realm.name if p.realm else ""),
        }
        for p in plans
    ],
        "realm_id": scope_id,
        "active_realm_id": realms.active_realm_id(db),
        "realms": [{"id": r.id, "name": r.name} for r in realms.list_realms(db)]}


@admin_router.post("/economy/plans")
def economy_create_plan(
    request: PlanUpsertRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    realm_id = request.realm_id or realms.active_realm_id(db)
    if not realms.get_realm(db, realm_id):
        raise HTTPException(status_code=400, detail=f"服不存在: #{realm_id}")
    plan = models.SubscriptionPlan(
        name=request.name, description=request.description,
        price=Decimal(str(request.price)), duration_days=request.duration_days,
        features=request.features, is_active=request.is_active,
        is_popular=request.is_popular, sort_order=request.sort_order,
        realm_id=realm_id,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    _audit(db, current_admin, "economy_create_plan", "plan", plan.id,
           {"name": plan.name, "price": float(plan.price), "realm_id": realm_id})
    db.commit()
    return {"success": True, "id": plan.id}


@admin_router.put("/economy/plans/{plan_id}")
def economy_update_plan(
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
    if request.realm_id:
        if not realms.get_realm(db, request.realm_id):
            raise HTTPException(status_code=400, detail=f"服不存在: #{request.realm_id}")
        plan.realm_id = request.realm_id
    elif plan.realm_id is None:
        plan.realm_id = realms.active_realm_id(db)
    plan.updated_at = datetime.now()
    db.commit()

    _audit(db, current_admin, "economy_update_plan", "plan", plan.id)
    db.commit()
    return {"success": True}


@admin_router.delete("/economy/plans/{plan_id}")
def economy_delete_plan(
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
def economy_list_packages(
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
def economy_create_package(
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
def economy_update_package(
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
def economy_delete_package(
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
def economy_list_exchange_codes(
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
def economy_create_exchange_codes(
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
def economy_update_exchange_code(
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
def economy_list_orders(
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
    from backend.api.economy import _fulfill_order, send_fulfill_notifications

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

    pending = await _fulfill_order(db, recharge_order=recharge_order,
                                   subscription_order=subscription_order)
    db.commit()

    # 先提交再发通知：履约事务里另开会话写站内信会撞 SQLite 写锁，通知会被静默丢掉
    await send_fulfill_notifications(pending)

    _audit(db, current_admin, "economy_mark_order_paid", "order", None,
           {"order_id": order_id})
    db.commit()
    return {"success": True, "message": "订单已标记支付并发货"}


# ==================== 导出 ====================

__all__ = ["admin_router"]
