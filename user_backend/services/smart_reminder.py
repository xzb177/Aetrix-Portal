"""
智能续费提醒服务
根据用户观影习惯，在最佳时机发送续费提醒
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from database.models import (
    WebUser, UserSubscription, UserEmbyAccount, EmbyServer,
    Message, MovieRequest
)

logger = logging.getLogger(__name__)


class SmartReminderService:
    """智能续费提醒"""

    # 追剧提醒：订阅到期前 N 天，如果有在追的剧，提前提醒
    CONTENT_REMIND_DAYS = 2

    @staticmethod
    def check_and_remind(db: Session) -> Dict[str, int]:
        """
        检查并发送智能续费提醒

        策略：
        1. 追剧提醒：订阅快到期 + 有活跃求片/观看 → "你追的 XX 马上更新，续费不错过"
        2. 到期提醒：3天/1天 → 标准到期提醒
        3. 过期挽留：过期后1天 → "你的 Emby 账号已暂停，续费立刻恢复"
        """
        stats = {"content_remind": 0, "expiry_remind": 0, "post_expiry": 0}
        now = datetime.now()

        # 查找即将过期的活跃订阅
        upcoming = db.query(UserSubscription).filter(
            UserSubscription.status == 'active',
            UserSubscription.end_date <= now + timedelta(days=3),
            UserSubscription.end_date > now
        ).all()

        for sub in upcoming:
            user = db.query(WebUser).filter(WebUser.id == sub.user_id).first()
            if not user:
                continue

            days_left = (sub.end_date - now).days

            # 检查是否有追剧/求片活动
            recent_requests = db.query(MovieRequest).filter(
                MovieRequest.user_id == user.id,
                MovieRequest.created_at >= now - timedelta(days=7)
            ).count()

            # 策略1：追剧提醒
            if recent_requests > 0 and days_left <= SmartReminderService.CONTENT_REMIND_DAYS:
                # 检查是否已发送过
                if not SmartReminderService._already_sent(db, user.id, "content_remind", sub.id):
                    SmartReminderService._send_message(
                        db, user.id, sub.id,
                        title="🎬 追剧提醒",
                        content=f"你最近有 {recent_requests} 个求片请求正在处理中，"
                                f"订阅将于 {days_left} 天后到期。续费即可不错过任何更新！",
                        msg_type="subscription"
                    )
                    stats["content_remind"] += 1

            # 策略2：标准到期提醒
            if days_left in [3, 1]:
                if not SmartReminderService._already_sent(db, user.id, f"expiry_{days_left}d", sub.id):
                    SmartReminderService._send_message(
                        db, user.id, sub.id,
                        title=f"⏰ 订阅将于 {days_left} 天后到期",
                        content=f"你的订阅将于 {sub.end_date.strftime('%Y-%m-%d')} 到期，"
                                f"请及时续费以避免 Emby 账号被暂停。",
                        msg_type="subscription"
                    )
                    stats["expiry_remind"] += 1

        # 策略3：过期挽留
        recently_expired = db.query(UserSubscription).filter(
            UserSubscription.status == 'expired',
            UserSubscription.end_date >= now - timedelta(days=1),
            UserSubscription.end_date < now
        ).all()

        for sub in recently_expired:
            if not SmartReminderService._already_sent(db, sub.user_id, "post_expiry", sub.id):
                SmartReminderService._send_message(
                    db, sub.user_id, sub.id,
                    title="😢 你的 Emby 账号已暂停",
                    content="订阅已过期，Emby 账号已被暂停。续费后将自动恢复，无需重新领取账号。",
                    msg_type="subscription"
                )
                stats["post_expiry"] += 1

        return stats

    @staticmethod
    def _already_sent(db: Session, user_id: int, remind_type: str, sub_id: int) -> bool:
        """检查是否已发送过该类型的提醒"""
        existing = db.query(Message).filter(
            Message.user_id == user_id,
            Message.message_type == "subscription",
            Message.related_id == sub_id,
            Message.title.like(f"%{remind_type}%")
        ).first()
        return existing is not None

    @staticmethod
    def _send_message(db: Session, user_id: int, sub_id: int,
                      title: str, content: str, msg_type: str):
        """发送站内消息"""
        msg = Message(
            user_id=user_id,
            title=title,
            content=content,
            message_type=msg_type,
            related_id=sub_id
        )
        db.add(msg)
        db.commit()
        logger.info(f"智能提醒已发送: user={user_id}, type={title}")
