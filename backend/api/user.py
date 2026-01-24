"""
用户端 API 路由
与管理后台联动，用户可接收管理员操作的通知
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import logging

from backend.database import get_db
from backend import models
from backend.notifications import get_notification_service, AdminEvent

logger = logging.getLogger(__name__)

# 创建路由
user_router = APIRouter(prefix="/api/user", tags=["用户端"])

# 认证方案
security = HTTPBearer(auto_error=False)


# ==================== 依赖注入 ====================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.WebUser:
    """获取当前登录用户"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证"
        )

    # 处理 Bearer 前缀
    token = credentials.credentials
    if token.startswith("Bearer "):
        token = token[7:]  # 去掉 "Bearer " 前缀

    # 临时：使用 token 直接作为 user_id（仅用于开发测试）
    try:
        user_id = int(token)
        user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证"
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )

    return user


# ==================== 请求/响应模型 ====================

class MessageResponse(BaseModel):
    """站内消息响应"""
    id: int
    title: str
    content: str
    message_type: str
    related_id: Optional[int]
    is_read: bool
    created_at: str
    from_user: Optional[str] = None

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    """未读消息数响应"""
    unread_count: int


class ExchangeCodeRedeemRequest(BaseModel):
    """兑换码兑换请求"""
    code: str


class UserMeResponse(BaseModel):
    """当前用户信息响应"""
    id: int
    username: str
    email: Optional[str] = None
    is_vip: bool
    points: Optional[int] = None
    balance: Optional[int] = None
    telegram_id: Optional[int] = None
    avatar_url: Optional[str] = None
    completed_requests_count: int = 0
    total_requests_count: int = 0
    registered_date: Optional[str] = None

    class Config:
        from_attributes = True


class ExchangeCodeRedeemResponse(BaseModel):
    """兑换码兑换响应"""
    success: bool
    message: str
    reward_type: Optional[str] = None
    reward_amount: Optional[int] = None


class TicketCreateRequest(BaseModel):
    """工单创建请求"""
    title: str
    category: str = "other"
    message: str


class TicketCreateResponse(BaseModel):
    """工单创建响应"""
    success: bool
    ticket_id: int
    message: str


class TicketResponse(BaseModel):
    """工单响应"""
    id: int
    title: str
    category: str
    status: str
    priority: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TicketMessageResponse(BaseModel):
    """工单消息响应"""
    id: int
    message: str
    is_admin: bool
    created_at: str
    admin_name: Optional[str] = None

    class Config:
        from_attributes = True


class AnnouncementResponse(BaseModel):
    """公告响应"""
    id: int
    title: str
    content: str
    type: str
    is_pinned: bool
    created_at: str

    class Config:
        from_attributes = True


# ==================== 认证/用户信息 API ====================

@user_router.get("/auth/me", response_model=UserMeResponse)
async def get_me(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户信息"""
    # 获取求片统计
    completed_count = db.query(models.MediaRequest).filter(
        models.MediaRequest.user_id == current_user.id,
        models.MediaRequest.status == "completed"
    ).count()

    total_count = db.query(models.MediaRequest).filter(
        models.MediaRequest.user_id == current_user.id
    ).count()

    return UserMeResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_vip=current_user.is_vip,
        points=current_user.points,
        balance=current_user.balance,
        telegram_id=current_user.telegram_id,
        avatar_url=current_user.avatar_url,
        completed_requests_count=completed_count,
        total_requests_count=total_count,
        registered_date=current_user.created_at.isoformat() if current_user.created_at else None
    )


# ==================== 站内消息 API ====================

@user_router.get("/messages", response_model=List[MessageResponse])
async def get_messages(
    unread_only: bool = False,
    limit: int = 50,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取站内消息列表"""
    notification_service = get_notification_service()

    messages = await notification_service.get_messages(
        user_id=current_user.id,
        limit=limit,
        unread_only=unread_only,
        db=db
    )

    result = []
    for msg in messages:
        from_name = None
        if msg.from_user:
            from_name = msg.from_user.username

        result.append(MessageResponse(
            id=msg.id,
            title=msg.title,
            content=msg.content,
            message_type=msg.message_type,
            related_id=msg.related_id,
            is_read=msg.is_read,
            created_at=msg.created_at.isoformat(),
            from_user=from_name
        ))

    return result


@user_router.get("/messages/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取未读消息数量"""
    notification_service = get_notification_service()

    count = await notification_service.get_unread_count(
        user_id=current_user.id,
        db=db
    )

    return UnreadCountResponse(unread_count=count)


@user_router.post("/messages/{message_id}/read")
async def mark_message_read(
    message_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """标记消息为已读"""
    notification_service = get_notification_service()

    success = await notification_service.mark_as_read(
        message_id=message_id,
        user_id=current_user.id,
        db=db
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="消息不存在"
        )

    return {"success": True, "message": "消息已标记为已读"}


@user_router.post("/messages/read-all")
async def mark_all_read(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """标记所有消息为已读"""
    # 批量更新未读消息
    db.query(models.StationMessage).filter(
        models.StationMessage.to_user_id == current_user.id,
        models.StationMessage.is_read == False
    ).update({
        "is_read": True,
        "read_at": datetime.now()
    })

    db.commit()

    # 通知 WebSocket
    from backend.websocket import send_notification
    await send_notification(
        notification_type="station.unread_count",
        user_id=current_user.id,
        title="",
        message="",
        data={"unread_count": 0}
    )

    return {"success": True, "message": "所有消息已标记为已读"}


# ==================== 兑换码 API ====================

@user_router.post("/exchange-codes/redeem", response_model=ExchangeCodeRedeemResponse)
async def redeem_exchange_code(
    request: ExchangeCodeRedeemRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """兑换兑换码 - 与后台兑换码管理联动"""
    # TODO: 实现 ExchangeCode 模型
    # code = db.query(models.ExchangeCode).filter(
    #     models.ExchangeCode.code == request.code.upper()
    # ).first()

    # 模拟实现
    return ExchangeCodeRedeemResponse(
        success=True,
        message="兑换成功！",
        reward_type="rcoin",
        reward_amount=100
    )


# ==================== 工单 API ====================

@user_router.get("/tickets", response_model=List[TicketResponse])
async def get_my_tickets(
    status_filter: Optional[str] = None,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取我的工单列表"""
    query = db.query(models.Ticket).filter(
        models.Ticket.user_id == current_user.id
    )

    if status_filter:
        query = query.filter(models.Ticket.status == status_filter)

    tickets = query.order_by(models.Ticket.updated_at.desc()).all()

    return [
        TicketResponse(
            id=t.id,
            title=t.title,
            category=t.category,
            status=t.status,
            priority=t.priority,
            created_at=t.created_at.isoformat(),
            updated_at=t.updated_at.isoformat()
        )
        for t in tickets
    ]


@user_router.post("/tickets", response_model=TicketCreateResponse)
async def create_ticket(
    request: TicketCreateRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新工单 - 与后台工单系统联动"""
    ticket = models.Ticket(
        user_id=current_user.id,
        title=request.title,
        category=request.category,
        status="open",
        priority="medium"
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # 创建工单消息
    message = models.TicketMessage(
        ticket_id=ticket.id,
        user_id=current_user.id,
        message=request.message,
        is_admin=False
    )
    db.add(message)
    db.commit()

    # 通知管理员有新工单
    # TODO: 获取在线管理员列表并通知
    # await notify_admins_new_ticket(ticket.id)

    return TicketCreateResponse(
        success=True,
        ticket_id=ticket.id,
        message="工单创建成功"
    )


@user_router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket_detail(
    ticket_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取工单详情"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id,
        models.Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    return TicketResponse(
        id=ticket.id,
        title=ticket.title,
        category=ticket.category,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at.isoformat(),
        updated_at=ticket.updated_at.isoformat()
    )


@user_router.get("/tickets/{ticket_id}/messages", response_model=List[TicketMessageResponse])
async def get_ticket_messages(
    ticket_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取工单消息列表"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id,
        models.Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    messages = db.query(models.TicketMessage).filter(
        models.TicketMessage.ticket_id == ticket_id
    ).order_by(models.TicketMessage.created_at.asc()).all()

    result = []
    for msg in messages:
        admin_name = None
        if msg.is_admin and msg.admin:
            admin_name = msg.admin.username

        result.append(TicketMessageResponse(
            id=msg.id,
            message=msg.message,
            is_admin=msg.is_admin,
            created_at=msg.created_at.isoformat(),
            admin_name=admin_name
        ))

    return result


@user_router.post("/tickets/{ticket_id}/messages")
async def reply_ticket(
    ticket_id: int,
    request: TicketCreateRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """回复工单"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id,
        models.Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    if ticket.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="工单已关闭，无法回复"
        )

    # 创建消息
    message = models.TicketMessage(
        ticket_id=ticket.id,
        user_id=current_user.id,
        message=request.message,
        is_admin=False
    )
    db.add(message)

    # 更新工单状态和时间
    ticket.status = "open"
    ticket.updated_at = datetime.now()

    db.commit()

    # 通知管理员工单有新回复
    # TODO: 通过 WebSocket 通知管理员

    return {"success": True, "message": "回复成功"}


@user_router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """关闭工单"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id,
        models.Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    ticket.status = "closed"
    ticket.updated_at = datetime.now()
    db.commit()

    return {"success": True, "message": "工单已关闭"}


# ==================== 公告 API ====================

@user_router.get("/announcements", response_model=List[AnnouncementResponse])
async def get_announcements(
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    """获取系统公告 - 与后台公告管理联动"""
    query = db.query(models.Announcement)

    if active_only:
        query = query.filter(models.Announcement.is_active == True)

    announcements = query.order_by(
        models.Announcement.is_pinned.desc(),
        models.Announcement.created_at.desc()
    ).limit(20).all()

    return [
        AnnouncementResponse(
            id=a.id,
            title=a.title,
            content=a.content,
            type=a.type,
            is_pinned=a.is_pinned,
            created_at=a.created_at.isoformat()
        )
        for a in announcements
    ]


# ==================== 求片 API ====================

class MediaSeekRequest(BaseModel):
    """求片请求"""
    movie_name: str
    year: Optional[str] = None
    type: Optional[str] = None
    note: Optional[str] = None


@user_router.post("/media-seek")
async def create_media_seek(
    request: MediaSeekRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建求片请求 - 与后台求片管理联动"""
    # TODO: 检查用户今日求片次数限制

    media_request = models.MovieRequest(
        user_id=current_user.id,
        movie_name=request.movie_name,
        year=request.year,
        type=request.type,
        note=request.note,
        status="pending"
    )
    db.add(media_request)
    db.commit()

    # 通知管理员有新求片请求
    # TODO: 通过 WebSocket 通知管理员

    return {"success": True, "message": "求片请求已提交"}


@user_router.get("/media-seek")
async def get_my_media_seeks(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取我的求片列表"""
    requests = db.query(models.MovieRequest).filter(
        models.MovieRequest.user_id == current_user.id
    ).order_by(models.MovieRequest.created_at.desc()).all()

    return [
        {
            "id": r.id,
            "movie_name": r.movie_name,
            "year": r.year,
            "type": r.type,
            "note": r.note,
            "status": r.status,
            "admin_note": r.admin_note,
            "created_at": r.created_at.isoformat()
        }
        for r in requests
    ]


# ==================== 订阅 API ====================

@user_router.get("/subscriptions")
async def get_my_subscriptions(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取我的订阅列表 - 与后台订阅管理联动"""
    subscriptions = db.query(models.UserSubscription).filter(
        models.UserSubscription.user_id == current_user.id
    ).order_by(models.UserSubscription.created_at.desc()).all()

    result = []
    for sub in subscriptions:
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == sub.plan_id
        ).first()

        result.append({
            "id": sub.id,
            "plan_name": plan.name if plan else "未知套餐",
            "start_date": sub.start_date.isoformat(),
            "end_date": sub.end_date.isoformat(),
            "status": sub.status,
            "auto_renew": sub.auto_renew,
            "days_left": (sub.end_date - datetime.now()).days if sub.end_date > datetime.now() else 0
        })

    return result


@user_router.get("/subscription-plans")
async def get_subscription_plans(
    db: Session = Depends(get_db)
):
    """获取可用订阅套餐 - 与后台套餐管理联动"""
    plans = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.is_active == True
    ).order_by(models.SubscriptionPlan.sort_order).all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": float(p.price),
            "duration_days": p.duration_days,
            "features": p.features,
            "is_popular": p.is_popular
        }
        for p in plans
    ]


# ==================== Emby 服务器 API ====================

@user_router.get("/emby-servers")
async def get_available_servers(
    db: Session = Depends(get_db)
):
    """获取可用的 Emby 服务器列表 - 与后台服务器管理联动"""
    servers = db.query(models.EmbyServer).filter(
        models.EmbyServer.is_active == True
    ).order_by(models.EmbyServer.priority.desc()).all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "status": s.status,
            "current_users": s.current_users,
            "max_users": s.max_users
        }
        for s in servers
    ]


@user_router.get("/emby-account")
async def get_my_emby_account(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取我的 Emby 账号信息"""
    account = db.query(models.UserEmbyAccount).filter(
        models.UserEmbyAccount.user_id == current_user.id,
        models.UserEmbyAccount.is_active == True
    ).first()

    if not account:
        return {"has_account": False}

    server = db.query(models.EmbyServer).filter(
        models.EmbyServer.id == account.server_id
    ).first()

    return {
        "has_account": True,
        "username": account.username,
        "server_name": server.name if server else "未知",
        "server_url": server.url if server else "",
        "expires_at": account.expires_at.isoformat() if account.expires_at else None,
        "is_active": account.is_active
    }


# ==================== 导出 ====================

__all__ = ["user_router"]
