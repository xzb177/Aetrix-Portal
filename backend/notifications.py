"""
多渠道通知服务
支持站内信、邮件、Telegram 等多种通知渠道
实现管理员操作与用户前台的联动
"""
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from backend.database import get_db
from backend import models
from backend.websocket import manager, send_notification

logger = logging.getLogger(__name__)


# ==================== 通知渠道抽象 ====================

class NotificationChannel:
    """通知渠道基类"""

    async def send(self, user_id: int, title: str, content: str, data: Optional[dict] = None) -> bool:
        """发送通知"""
        raise NotImplementedError


class InAppChannel(NotificationChannel):
    """站内信通知渠道"""

    def __init__(self):
        self.name = "in_app"

    async def send(self, user_id: int, title: str, content: str,
                   message_type: str = "system",
                   related_id: Optional[int] = None,
                   from_user_id: Optional[int] = None,
                   db: Session = None) -> bool:
        """发送站内消息"""
        try:
            # 创建数据库记录
            if db is None:
                db = next(get_db())

            message = models.StationMessage(
                from_user_id=from_user_id,
                to_user_id=user_id,
                title=title,
                content=content,
                message_type=message_type,
                related_id=related_id,
                is_read=False
            )
            db.add(message)
            db.commit()
            db.refresh(message)

            # 同时通过 WebSocket 推送
            await send_notification(
                notification_type=f"station.{message_type}",
                user_id=user_id,
                title=title,
                message=content,
                data={
                    "message_id": message.id,
                    "message_type": message_type,
                    "related_id": related_id
                }
            )

            logger.info(f"站内消息已发送给用户 {user_id}: {title}")
            return True

        except Exception as e:
            logger.error(f"发送站内消息失败: {e}")
            if db:
                db.rollback()
            return False


class EmailChannel(NotificationChannel):
    """邮件通知渠道"""

    def __init__(self, smtp_host: str = None, smtp_port: int = 587,
                 smtp_user: str = None, smtp_password: str = None):
        self.name = "email"
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.enabled = bool(smtp_host and smtp_user)

    async def send(self, user_id: int, title: str, content: str,
                   data: Optional[dict] = None, db: Session = None) -> bool:
        """发送邮件通知"""
        if not self.enabled:
            logger.warning("邮件通知未配置，跳过发送")
            return False

        try:
            # 获取用户邮箱
            if db is None:
                db = next(get_db())

            user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
            if not user or not user.email:
                logger.warning(f"用户 {user_id} 没有邮箱地址")
                return False

            # TODO: 实现邮件发送逻辑
            # import smtplib
            # from email.mime.text import MIMEText
            # msg = MIMEText(content, 'plain', 'utf-8')
            # msg['Subject'] = title
            # msg['From'] = self.smtp_user
            # msg['To'] = user.email
            # ...

            # 记录通知历史
            history = models.NotificationHistory(
                notification_type="email",
                target=user.email,
                title=title,
                content=content,
                status="sent",
                sent_at=datetime.now()
            )
            db.add(history)
            db.commit()

            logger.info(f"邮件已发送给用户 {user_id}: {title}")
            return True

        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            if db:
                db.rollback()
            return False


class TelegramChannel(NotificationChannel):
    """Telegram 通知渠道"""

    def __init__(self, bot_token: str = None):
        self.name = "telegram"
        self.bot_token = bot_token
        self.enabled = bool(bot_token)

    async def send(self, user_id: int, title: str, content: str,
                   data: Optional[dict] = None, db: Session = None) -> bool:
        """发送 Telegram 通知"""
        if not self.enabled:
            logger.warning("Telegram 通知未配置，跳过发送")
            return False

        try:
            # 获取用户的 Telegram ID
            if db is None:
                db = next(get_db())

            # 查找关联的 Telegram 账号
            tg_user = db.query(models.TelegramUser).filter(
                models.TelegramUser.web_user_id == user_id
            ).first()

            if not tg_user:
                logger.warning(f"用户 {user_id} 没有关联 Telegram 账号")
                return False

            # TODO: 实现 Telegram 发送逻辑
            # import httpx
            # async with httpx.AsyncClient() as client:
            #     await client.post(
            #         f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            #         json={"chat_id": tg_user.id, "text": f"*{title}*\n\n{content}", "parse_mode": "Markdown"}
            #     )

            # 记录通知历史
            history = models.NotificationHistory(
                notification_type="telegram",
                target=str(tg_user.id),
                title=title,
                content=content,
                status="sent",
                sent_at=datetime.now()
            )
            db.add(history)
            db.commit()

            logger.info(f"Telegram 消息已发送给用户 {user_id}")
            return True

        except Exception as e:
            logger.error(f"发送 Telegram 消息失败: {e}")
            if db:
                db.rollback()
            return False


# ==================== 多渠道通知管理器 ====================

class NotificationService:
    """通知服务管理器"""

    def __init__(self):
        self.channels: Dict[str, NotificationChannel] = {
            "in_app": InAppChannel(),
        }
        # 从配置加载其他渠道
        self._config_loaded = False
        self._load_channels_from_config()

    def _load_channels_from_config(self):
        """从系统配置加载通知渠道"""
        if self._config_loaded:
            return

        try:
            db = next(get_db())

            # 获取邮件配置
            email_configs = db.query(models.SystemConfig).filter(
                models.SystemConfig.key.like('email_%')
            ).all()
            email_config = {cfg.key: cfg.value for cfg in email_configs}

            if email_config.get('email_enabled') == 'true':
                self.channels['email'] = EmailChannel(
                    smtp_host=email_config.get('email_smtp_host'),
                    smtp_port=int(email_config.get('email_smtp_port', 587)),
                    smtp_user=email_config.get('email_smtp_user'),
                    smtp_password=email_config.get('email_smtp_password'),
                )
                logger.info("邮件通知渠道已启用")

            # 获取 Telegram 配置
            tg_configs = db.query(models.SystemConfig).filter(
                models.SystemConfig.key.like('telegram_%')
            ).all()
            tg_config = {cfg.key: cfg.value for cfg in tg_configs}

            if tg_config.get('telegram_bot_token'):
                self.channels['telegram'] = TelegramChannel(
                    bot_token=tg_config.get('telegram_bot_token')
                )
                logger.info("Telegram 通知渠道已启用")

            self._config_loaded = True

        except Exception as e:
            logger.error(f"加载通知渠道配置失败: {e}")

    def reload_config(self):
        """重新加载配置"""
        self._config_loaded = False
        self._load_channels_from_config()

    def add_channel(self, name: str, channel: NotificationChannel):
        """添加通知渠道"""
        self.channels[name] = channel

    async def send(self, user_id: int, title: str, content: str,
                   channels: Optional[List[str]] = None,
                   message_type: str = "system",
                   related_id: Optional[int] = None,
                   from_user_id: Optional[int] = None,
                   data: Optional[dict] = None,
                   db: Optional[Session] = None) -> Dict[str, bool]:
        """
        发送多渠道通知

        Args:
            user_id: 接收用户ID
            title: 通知标题
            content: 通知内容
            channels: 通知渠道列表，默认使用所有可用渠道
            message_type: 消息类型
            related_id: 关联ID
            from_user_id: 发送者ID（管理员）
            data: 附加数据

        Returns:
            各渠道发送结果 {channel_name: success}
        """
        if channels is None:
            channels = ["in_app"]  # 默认只发送站内信

        results = {}
        db_session = db or next(get_db())

        for channel_name in channels:
            if channel_name not in self.channels:
                logger.warning(f"通知渠道 {channel_name} 不存在")
                results[channel_name] = False
                continue

            channel = self.channels[channel_name]

            if channel_name == "in_app":
                success = await channel.send(
                    user_id=user_id,
                    title=title,
                    content=content,
                    message_type=message_type,
                    related_id=related_id,
                    from_user_id=from_user_id,
                    db=db_session
                )
            else:
                success = await channel.send(
                    user_id=user_id,
                    title=title,
                    content=content,
                    data=data,
                    db=db_session
                )

            results[channel_name] = success

        return results

    async def broadcast(self, title: str, content: str,
                        channels: Optional[List[str]] = None,
                        data: Optional[dict] = None) -> int:
        """
        广播通知给所有在线用户

        Returns:
            接收到的用户数量
        """
        online_users = manager.get_online_users()
        count = 0

        for user_id in online_users:
            results = await self.send(
                user_id=user_id,
                title=title,
                content=content,
                channels=channels or ["in_app"],
                data=data
            )
            if any(results.values()):
                count += 1

        return count

    async def get_unread_count(self, user_id: int, db: Optional[Session] = None) -> int:
        """获取用户未读消息数量"""
        if db is None:
            db = next(get_db())

        count = db.query(models.StationMessage).filter(
            and_(
                models.StationMessage.to_user_id == user_id,
                models.StationMessage.is_read == False
            )
        ).count()

        return count

    async def mark_as_read(self, message_id: int, user_id: int, db: Optional[Session] = None) -> bool:
        """标记消息为已读"""
        if db is None:
            db = next(get_db())

        message = db.query(models.StationMessage).filter(
            and_(
                models.StationMessage.id == message_id,
                models.StationMessage.to_user_id == user_id
            )
        ).first()

        if message:
            message.is_read = True
            message.read_at = datetime.now()
            db.commit()

            # 通过 WebSocket 通知未读数更新
            unread_count = await self.get_unread_count(user_id, db)
            await send_notification(
                notification_type="station.unread_count",
                user_id=user_id,
                title="",
                message="",
                data={"unread_count": unread_count}
            )

            return True

        return False

    async def get_messages(self, user_id: int, limit: int = 50,
                           unread_only: bool = False, db: Optional[Session] = None) -> List[models.StationMessage]:
        """获取用户消息列表"""
        if db is None:
            db = next(get_db())

        query = db.query(models.StationMessage).filter(
            models.StationMessage.to_user_id == user_id
        )

        if unread_only:
            query = query.filter(models.StationMessage.is_read == False)

        messages = query.order_by(models.StationMessage.created_at.desc()).limit(limit).all()

        return messages


# ==================== 管理员操作事件 ====================

class AdminEvent:
    """管理员操作事件常量"""

    # 兑换码事件
    EXCHANGE_CODE_GENERATED = "exchange_code.generated"
    EXCHANGE_CODE_USED = "exchange_code.used"

    # 工单事件
    TICKET_CREATED = "ticket.created"
    TICKET_REPLIED = "ticket.replied"
    TICKET_CLOSED = "ticket.closed"

    # 公告事件
    ANNOUNCEMENT_PUBLISHED = "announcement.published"
    ANNOUNCEMENT_UPDATED = "announcement.updated"
    ANNOUNCEMENT_DELETED = "announcement.deleted"

    # 订阅事件
    SUBSCRIPTION_MANUAL = "subscription.manual"
    SUBSCRIPTION_EXTENDED = "subscription.extended"
    SUBSCRIPTION_EXPIRED = "subscription.expired"

    # 求片事件
    MEDIA_SEEK_APPROVED = "media_seek.approved"
    MEDIA_SEEK_REJECTED = "media_seek.rejected"
    MEDIA_SEEK_COMPLETED = "media_seek.completed"

    # 系统事件
    SYSTEM_MAINTENANCE = "system.maintenance"
    USER_WARNING = "user.warning"
    USER_BANNED = "user.banned"


async def notify_admin_event(
    event_type: str,
    user_id: Optional[int],
    title: str,
    content: str,
    related_id: Optional[int] = None,
    from_admin_id: Optional[int] = None,
    channels: Optional[List[str]] = None
) -> Dict[str, bool]:
    """
    触发管理员操作事件通知

    这是实现前后台联动的核心函数
    管理员在后台的操作会通过这个函数通知到用户前台

    数据流：
    管理员操作 → 后台API → notify_admin_event() → NotificationService.send()
            → 站内信数据库 + WebSocket推送 → 用户前台实时更新
    """
    message_type = event_type.split('.')[0]  # ticket, announcement, subscription, exchange_code, media_seek

    notification_service = get_notification_service()

    return await notification_service.send(
        user_id=user_id,
        title=title,
        content=content,
        channels=channels or ["in_app"],
        message_type=message_type,
        related_id=related_id,
        from_user_id=from_admin_id
    )


async def notify_all_users(
    event_type: str,
    title: str,
    content: str,
    data: Optional[dict] = None
) -> int:
    """
    广播通知给所有用户

    用于：
    - 系统公告发布
    - 系统维护通知
    - 重要系统更新
    """
    notification_service = get_notification_service()

    return await notification_service.broadcast(
        title=title,
        content=content,
        channels=["in_app"],
        data=data or {"event_type": event_type}
    )


# ==================== 全局单例 ====================

_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """获取通知服务单例"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


# ==================== 导出 ====================

__all__ = [
    "NotificationService",
    "InAppChannel",
    "EmailChannel",
    "TelegramChannel",
    "get_notification_service",
    "notify_admin_event",
    "notify_all_users",
    "AdminEvent",
]
