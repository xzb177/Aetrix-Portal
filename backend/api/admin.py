"""
管理后台 API 路由
管理员操作会触发通知发送到用户前台，实现前后台联动
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from backend.database import get_db
from backend import models
from backend.notifications import (
    get_notification_service,
    notify_admin_event,
    notify_all_users,
    AdminEvent
)

logger = logging.getLogger(__name__)

# 创建路由
admin_router = APIRouter(prefix="/api/admin", tags=["管理后台"])

# 认证方案
security = HTTPBearer(auto_error=False)


# ==================== 依赖注入 ====================

async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.AdminUser:
    """获取当前登录管理员"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证"
        )

    # TODO: 实现 JWT 验证
    # 临时：使用 token 直接作为 admin_id（仅用于开发测试）
    try:
        admin_id = int(credentials.credentials)
        admin = db.query(models.AdminUser).filter(
            models.AdminUser.id == admin_id
        ).first()
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证"
        )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="管理员不存在"
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员已被禁用"
        )

    return admin


# ==================== 请求/响应模型 ====================

class AnnouncementCreateRequest(BaseModel):
    """创建公告请求"""
    title: str
    content: str
    type: str = "system"
    is_pinned: bool = False


class AnnouncementUpdateRequest(BaseModel):
    """更新公告请求"""
    title: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_active: Optional[bool] = None


class TicketUpdateRequest(BaseModel):
    """工单更新请求"""
    status: Optional[str] = None
    priority: Optional[str] = None
    admin_id: Optional[int] = None


class TicketReplyRequest(BaseModel):
    """工单回复请求"""
    message: str
    close_ticket: bool = False


class MediaSeekUpdateRequest(BaseModel):
    """求片更新请求"""
    status: str  # approved, rejected, completed
    admin_note: Optional[str] = None


class SubscriptionGrantRequest(BaseModel):
    """授予订阅请求"""
    user_id: int
    plan_id: int
    duration_days: int


class UserMessageSendRequest(BaseModel):
    """发送用户消息请求"""
    user_id: int
    title: str
    content: str
    message_type: str = "system"


class BroadcastMessageRequest(BaseModel):
    """广播消息请求"""
    title: str
    content: str


# ==================== 公告管理 API ====================

@admin_router.post("/announcements")
async def create_announcement(
    request: AnnouncementCreateRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """创建公告 - 联动：广播通知所有用户"""
    announcement = models.Announcement(
        title=request.title,
        content=request.content,
        type=request.type,
        is_pinned=request.is_pinned,
        is_active=True
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="create_announcement",
        target_type="announcement",
        target_id=announcement.id,
        details={"title": request.title}
    )
    db.add(log)
    db.commit()

    # 前后台联动：广播新公告给所有用户
    await notify_all_users(
        event_type=AdminEvent.ANNOUNCEMENT_PUBLISHED,
        title=f"📢 {request.title}",
        content=request.content,
        data={
            "announcement_id": announcement.id,
            "type": request.type
        }
    )

    logger.info(f"管理员 {current_admin.username} 创建了公告: {request.title}")

    return {
        "success": True,
        "announcement_id": announcement.id,
        "message": "公告创建成功并已推送给所有用户"
    }


@admin_router.put("/announcements/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    request: AnnouncementUpdateRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新公告"""
    announcement = db.query(models.Announcement).filter(
        models.Announcement.id == announcement_id
    ).first()

    if not announcement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公告不存在"
        )

    # 更新字段
    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(announcement, key, value)

    announcement.updated_at = datetime.now()
    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="update_announcement",
        target_type="announcement",
        target_id=announcement_id,
        details=update_data
    )
    db.add(log)
    db.commit()

    # 前后台联动：通知用户公告已更新
    await notify_all_users(
        event_type=AdminEvent.ANNOUNCEMENT_UPDATED,
        title="公告已更新",
        content=f"公告「{announcement.title}」已更新，请查看",
        data={"announcement_id": announcement_id}
    )

    return {"success": True, "message": "公告更新成功"}


@admin_router.delete("/announcements/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """删除公告"""
    announcement = db.query(models.Announcement).filter(
        models.Announcement.id == announcement_id
    ).first()

    if not announcement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公告不存在"
        )

    title = announcement.title
    db.delete(announcement)
    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="delete_announcement",
        target_type="announcement",
        target_id=announcement_id,
        details={"title": title}
    )
    db.add(log)
    db.commit()

    return {"success": True, "message": "公告删除成功"}


# ==================== 工单管理 API ====================

@admin_router.get("/tickets")
async def get_tickets(
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取工单列表"""
    query = db.query(models.Ticket)

    if status_filter:
        query = query.filter(models.Ticket.status == status_filter)
    if category_filter:
        query = query.filter(models.Ticket.category == category_filter)

    tickets = query.order_by(
        models.Ticket.created_at.desc()
    ).all()

    result = []
    for ticket in tickets:
        user = db.query(models.WebUser).filter(
            models.WebUser.id == ticket.user_id
        ).first()

        # 获取最新消息
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
            "created_at": ticket.created_at.isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
            "latest_message": latest_message.message[:100] if latest_message else ""
        })

    return result


@admin_router.put("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    request: TicketUpdateRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新工单状态"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    # 更新字段
    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ticket, key, value)

    ticket.updated_at = datetime.now()
    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="update_ticket",
        target_type="ticket",
        target_id=ticket_id,
        details=update_data
    )
    db.add(log)
    db.commit()

    # 前后台联动：通知用户工单状态已更新
    await notify_admin_event(
        event_type=AdminEvent.TICKET_REPLIED,
        user_id=ticket.user_id,
        title="工单状态已更新",
        content=f"您的工单「{ticket.title}」状态已变更为：{ticket.status}",
        related_id=ticket_id,
        from_admin_id=current_admin.id
    )

    return {"success": True, "message": "工单更新成功"}


@admin_router.post("/tickets/{ticket_id}/reply")
async def reply_ticket(
    ticket_id: int,
    request: TicketReplyRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """回复工单 - 联动：通知用户"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    # 创建管理员回复
    message = models.TicketMessage(
        ticket_id=ticket.id,
        admin_id=current_admin.id,
        message=request.message,
        is_admin=True
    )
    db.add(message)

    # 更新工单状态
    ticket.status = "closed" if request.close_ticket else "open"
    ticket.admin_id = current_admin.id
    ticket.updated_at = datetime.now()

    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="reply_ticket",
        target_type="ticket",
        target_id=ticket_id,
        details={"message": request.message, "closed": request.close_ticket}
    )
    db.add(log)
    db.commit()

    # 前后台联动：通知用户工单有新回复
    await notify_admin_event(
        event_type=AdminEvent.TICKET_REPLIED if not request.close_ticket else AdminEvent.TICKET_CLOSED,
        user_id=ticket.user_id,
        title="工单有新回复" if not request.close_ticket else "工单已关闭",
        content=request.message,
        related_id=ticket_id,
        from_admin_id=current_admin.id
    )

    logger.info(f"管理员 {current_admin.username} 回复了工单 {ticket_id}")

    return {"success": True, "message": "回复成功"}


@admin_router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: int,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """关闭工单 - 联动：通知用户"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    ticket.status = "closed"
    ticket.updated_at = datetime.now()
    db.commit()

    # 前后台联动：通知用户工单已关闭
    await notify_admin_event(
        event_type=AdminEvent.TICKET_CLOSED,
        user_id=ticket.user_id,
        title="工单已关闭",
        content=f"您的工单「{ticket.title}」已被管理员关闭",
        related_id=ticket_id,
        from_admin_id=current_admin.id
    )

    return {"success": True, "message": "工单已关闭"}


# ==================== 求片管理 API ====================

@admin_router.get("/media-seek")
async def get_media_seeks(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取求片列表"""
    query = db.query(models.MovieRequest)

    if status_filter:
        query = query.filter(models.MovieRequest.status == status_filter)

    requests = query.order_by(models.MovieRequest.created_at.desc()).all()

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
            "created_at": req.created_at.isoformat()
        })

    return result


@admin_router.put("/media-seek/{request_id}")
async def update_media_seek(
    request_id: int,
    request: MediaSeekUpdateRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新求片状态 - 联动：通知用户"""
    media_request = db.query(models.MovieRequest).filter(
        models.MovieRequest.id == request_id
    ).first()

    if not media_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求片请求不存在"
        )

    # 更新状态
    media_request.status = request.status
    media_request.admin_note = request.admin_note
    media_request.updated_at = datetime.now()
    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="update_media_seek",
        target_type="media_seek",
        target_id=request_id,
        details={"status": request.status}
    )
    db.add(log)
    db.commit()

    # 前后台联动：通知用户求片状态已更新
    event_map = {
        "approved": AdminEvent.MEDIA_SEEK_APPROVED,
        "rejected": AdminEvent.MEDIA_SEEK_REJECTED,
        "completed": AdminEvent.MEDIA_SEEK_COMPLETED
    }

    title_map = {
        "approved": "求片请求已批准",
        "rejected": "求片请求已拒绝",
        "completed": "求片请求已完成"
    }

    await notify_admin_event(
        event_type=event_map.get(request.status, "media_seek.updated"),
        user_id=media_request.user_id,
        title=title_map.get(request.status, "求片状态已更新"),
        content=f"您的求片《{media_request.movie_name}》状态已更新为：{request.status}"
                  + (f"\n备注：{request.admin_note}" if request.admin_note else ""),
        related_id=request_id,
        from_admin_id=current_admin.id
    )

    logger.info(f"管理员 {current_admin.username} 更新了求片 {request_id} 状态为 {request.status}")

    return {"success": True, "message": "求片状态更新成功"}


# ==================== 订阅管理 API ====================

@admin_router.post("/subscriptions/grant")
async def grant_subscription(
    request: SubscriptionGrantRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """授予用户订阅 - 联动：通知用户"""
    # 验证用户和套餐
    user = db.query(models.WebUser).filter(
        models.WebUser.id == request.user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == request.plan_id
    ).first()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="套餐不存在"
        )

    # 创建订阅
    end_date = datetime.now() + timedelta(days=request.duration_days)

    subscription = models.UserSubscription(
        user_id=request.user_id,
        plan_id=request.plan_id,
        start_date=datetime.now(),
        end_date=end_date,
        status="active"
    )
    db.add(subscription)
    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="grant_subscription",
        target_type="subscription",
        target_id=subscription.id,
        details={
            "user_id": request.user_id,
            "plan_id": request.plan_id,
            "duration_days": request.duration_days
        }
    )
    db.add(log)
    db.commit()

    # 前后台联动：通知用户已获得订阅
    await notify_admin_event(
        event_type=AdminEvent.SUBSCRIPTION_MANUAL,
        user_id=request.user_id,
        title="🎉 恭喜获得订阅",
        content=f"管理员已为您开通「{plan.name}」订阅，有效期 {request.duration_days} 天"
                  f"\n到期时间：{end_date.strftime('%Y-%m-%d')}",
        related_id=subscription.id,
        from_admin_id=current_admin.id
    )

    logger.info(f"管理员 {current_admin.username} 为用户 {request.user_id} 授予了订阅")

    return {"success": True, "message": "订阅授予成功"}


@admin_router.post("/subscriptions/{subscription_id}/extend")
async def extend_subscription(
    subscription_id: int,
    days: int,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """延长订阅有效期 - 联动：通知用户"""
    subscription = db.query(models.UserSubscription).filter(
        models.UserSubscription.id == subscription_id
    ).first()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="订阅不存在"
        )

    # 延长订阅
    old_end_date = subscription.end_date
    subscription.end_date = max(
        subscription.end_date,
        datetime.now()
    ) + timedelta(days=days)
    subscription.updated_at = datetime.now()
    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="extend_subscription",
        target_type="subscription",
        target_id=subscription_id,
        details={"days": days, "old_end": old_end_date.isoformat()}
    )
    db.add(log)
    db.commit()

    # 前后台联动：通知用户订阅已延长
    await notify_admin_event(
        event_type=AdminEvent.SUBSCRIPTION_EXTENDED,
        user_id=subscription.user_id,
        title="订阅已延长",
        content=f"您的订阅已延长 {days} 天，新到期时间：{subscription.end_date.strftime('%Y-%m-%d')}",
        related_id=subscription_id,
        from_admin_id=current_admin.id
    )

    return {"success": True, "message": "订阅延长成功"}


# ==================== 用户消息 API ====================

@admin_router.post("/messages/send")
async def send_user_message(
    request: UserMessageSendRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """发送消息给指定用户 - 联动：站内信"""
    # 验证用户存在
    user = db.query(models.WebUser).filter(
        models.WebUser.id == request.user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="send_user_message",
        target_type="user",
        target_id=request.user_id,
        details={"title": request.title, "type": request.message_type}
    )
    db.add(log)
    db.commit()

    # 前后台联动：发送站内消息
    await notify_admin_event(
        event_type=f"station.{request.message_type}",
        user_id=request.user_id,
        title=request.title,
        content=request.content,
        message_type=request.message_type,
        from_admin_id=current_admin.id
    )

    logger.info(f"管理员 {current_admin.username} 向用户 {request.user_id} 发送了消息")

    return {"success": True, "message": "消息发送成功"}


@admin_router.post("/messages/broadcast")
async def broadcast_message(
    request: BroadcastMessageRequest,
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """广播消息给所有用户 - 联动：全站广播"""
    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="broadcast_message",
        target_type="all_users",
        details={"title": request.title}
    )
    db.add(log)
    db.commit()

    # 前后台联动：广播给所有用户
    count = await notify_all_users(
        event_type="system.broadcast",
        title=request.title,
        content=request.content
    )

    logger.info(f"管理员 {current_admin.username} 广播了消息，接收用户数：{count}")

    return {
        "success": True,
        "message": f"广播已发送，预计接收 {count} 位在线用户"
    }


# ==================== 系统管理 API ====================

@admin_router.post("/system/maintenance")
async def set_maintenance_mode(
    enabled: bool,
    message: str = "系统维护中，请稍后访问",
    current_admin: models.AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """设置维护模式 - 联动：通知所有用户"""
    # 保存配置
    config = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "maintenance_mode"
    ).first()

    if config:
        config.value = "true" if enabled else "false"
    else:
        config = models.SystemConfig(
            key="maintenance_mode",
            value="true" if enabled else "false"
        )
        db.add(config)

    # 保存维护消息
    msg_config = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "maintenance_message"
    ).first()

    if msg_config:
        msg_config.value = message
    else:
        msg_config = models.SystemConfig(
            key="maintenance_message",
            value=message
        )
        db.add(msg_config)

    db.commit()

    # 记录操作日志
    log = models.AdminLog(
        admin_user_id=current_admin.id,
        action="set_maintenance",
        target_type="system",
        details={"enabled": enabled}
    )
    db.add(log)
    db.commit()

    # 前后台联动：通知所有用户系统维护
    if enabled:
        await notify_all_users(
            event_type=AdminEvent.SYSTEM_MAINTENANCE,
            title="⚠️ 系统维护通知",
            content=message
        )

    return {"success": True, "message": f"维护模式已{'开启' if enabled else '关闭'}"}


# ==================== 操作日志 API ====================

@admin_router.get("/logs")
async def get_admin_logs(
    action_filter: Optional[str] = None,
    target_type_filter: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取管理员操作日志"""
    query = db.query(models.AdminLog)

    if action_filter:
        query = query.filter(models.AdminLog.action == action_filter)
    if target_type_filter:
        query = query.filter(models.AdminLog.target_type == target_type_filter)

    logs = query.order_by(models.AdminLog.created_at.desc()).limit(limit).all()

    result = []
    for log in logs:
        admin = db.query(models.AdminUser).filter(
            models.AdminUser.id == log.admin_user_id
        ).first()

        result.append({
            "id": log.id,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat(),
            "admin_name": admin.username if admin else "未知"
        })

    return result


# ==================== 统计数据 API ====================

@admin_router.get("/stats/overview")
async def get_stats_overview(
    db: Session = Depends(get_db)
):
    """获取系统概览统计"""
    # 用户统计
    total_users = db.query(models.WebUser).count()
    active_users = db.query(models.WebUser).filter(
        models.WebUser.is_active == True
    ).count()

    # 订阅统计
    active_subscriptions = db.query(models.UserSubscription).filter(
        models.UserSubscription.status == "active",
        models.UserSubscription.end_date > datetime.now()
    ).count()

    # 工单统计
    open_tickets = db.query(models.Ticket).filter(
        models.Ticket.status == "open"
    ).count()

    # 求片统计
    pending_requests = db.query(models.MovieRequest).filter(
        models.MovieRequest.status == "pending"
    ).count()

    return {
        "users": {
            "total": total_users,
            "active": active_users
        },
        "subscriptions": {
            "active": active_subscriptions
        },
        "tickets": {
            "open": open_tickets
        },
        "media_seeks": {
            "pending": pending_requests
        }
    }


# ==================== 导出 ====================

__all__ = ["admin_router"]
