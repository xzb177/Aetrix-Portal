"""
通知服务

统一处理各种通知消息的发送：
- Telegram 通知
- 站内消息
- 邮件通知（预留）
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session

from database.models import WebUser, Message
from utils.config import settings
from utils.telegram import send_telegram_message

logger = logging.getLogger(__name__)


# ==================== 站内消息 ====================

def create_inbox_message(
    db: Session,
    user_id: int,
    title: str,
    content: str,
    message_type: str = "system",
    related_id: Optional[int] = None
) -> Message:
    """
    创建站内消息

    Args:
        db: 数据库会话
        user_id: 用户ID
        title: 消息标题
        content: 消息内容
        message_type: 消息类型
        related_id: 关联ID

    Returns:
        创建的消息对象
    """
    message = Message(
        user_id=user_id,
        title=title,
        content=content,
        message_type=message_type,
        related_id=related_id
    )
    db.add(message)
    db.commit()
    return message


async def send_expiring_reminder_message(
    user_id: int,
    username: str,
    days: int,
    end_date,
    subscription_id: int,
    db: Session
):
    """
    发送订阅即将过期提醒

    Args:
        user_id: 用户ID
        username: 用户名
        days: 距离过期的天数
        end_date: 过期日期
        subscription_id: 订阅ID
        db: 数据库会话
    """
    title = f"订阅将在 {days} 天后过期"
    content = f"""亲爱的 {username}：

您的订阅将在 {days} 天后过期（{end_date.strftime('%Y-%m-%d')}）。

为避免影响使用，请及时续费。感谢您的支持！

如已续费，请忽略此消息。
"""

    create_inbox_message(
        db=db,
        user_id=user_id,
        title=title,
        content=content,
        message_type="subscription",
        related_id=subscription_id
    )


async def send_welcome_message(
    user_id: int,
    username: str,
    plan_name: str,
    end_date,
    db: Session
):
    """
    发送订阅成功欢迎消息

    Args:
        user_id: 用户ID
        username: 用户名
        plan_name: 套餐名称
        end_date: 过期日期
        db: 数据库会话
    """
    title = "欢迎订阅 RoyalBot！"
    content = f"""亲爱的 {username}：

感谢您订阅 {plan_name}！

您的订阅有效期至：{end_date.strftime('%Y-%m-%d')}

请在「我的订阅」页面领取您的 Emby 账号。

祝您观影愉快！
"""

    create_inbox_message(
        db=db,
        user_id=user_id,
        title=title,
        content=content,
        message_type="subscription"
    )


async def send_subscription_renewed_message(
    user_id: int,
    username: str,
    new_end_date,
    db: Session
):
    """
    发送订阅续费成功消息

    Args:
        user_id: 用户ID
        username: 用户名
        new_end_date: 新的过期日期
        db: 数据库会话
    """
    title = "续费成功！"
    content = f"""亲爱的 {username}：

您的订阅已成功续费！

新的有效期至：{new_end_date.strftime('%Y-%m-%d')}

感谢您的继续支持！
"""

    create_inbox_message(
        db=db,
        user_id=user_id,
        title=title,
        content=content,
        message_type="subscription"
    )


# ==================== 系统告警 ====================

async def send_system_alert_message(message: str):
    """
    发送系统告警消息到管理员

    Args:
        message: 告警内容
    """
    try:
        # 解析管理员聊天ID
        chat_ids = settings.TELEGRAM_ADMIN_CHAT_IDS
        if not chat_ids:
            logger.warning("未配置管理员聊天ID，跳过告警发送")
            return

        for chat_id_str in chat_ids.split(','):
            chat_id = chat_id_str.strip()
            if chat_id:
                await send_telegram_message(chat_id, message)
                logger.info(f"已发送告警到管理员 {chat_id}")

    except Exception as e:
        logger.error(f"发送系统告警失败: {e}")


# ==================== 风控告警 ====================

async def send_risk_alert_message(
    user_id: int,
    username: str,
    risk_type: str,
    details: str
):
    """
    发送风控告警消息

    Args:
        user_id: 用户ID
        username: 用户名
        risk_type: 风险类型
        details: 详细信息
    """
    message = f"""🚨 风控告警

用户: {username} (ID: {user_id})
风险类型: {risk_type}

详细信息:
{details}

请及时处理。
"""

    await send_system_alert_message(message)


# ==================== 求片通知 ====================

async def send_movie_request_completed_notification(
    user_id: int,
    movie_name: str,
    db: Session
):
    """
    发送求片完成通知

    Args:
        user_id: 用户ID
        movie_name: 电影名称
        db: 数据库会话
    """
    title = "您求片的内容已上架！"
    content = f"""您求片的《{movie_name}》已上架！

快去 Emby 观看吧！

感谢您的支持！
"""

    create_inbox_message(
        db=db,
        user_id=user_id,
        title=title,
        content=content,
        message_type="media_seek"
    )


async def notify_all_subscribers(
    request_id: int,
    movie_name: str,
    subscriber_ids: list,
    db: Session
):
    """
    通知所有订阅该求片的用户

    Args:
        request_id: 求片ID
        movie_name: 电影名称
        subscriber_ids: 订阅用户ID列表
        db: 数据库会话
    """
    for user_id in subscriber_ids:
        try:
            await send_movie_request_completed_notification(
                user_id=user_id,
                movie_name=movie_name,
                db=db
            )
        except Exception as e:
            logger.error(f"通知用户 {user_id} 失败: {e}")


# ==================== 登录异常告警 ====================

async def send_login_alert(
    user_id: int,
    username: str,
    ip_address: str,
    user_agent: str,
    is_new_location: bool = False
):
    """
    发送登录异常告警

    Args:
        user_id: 用户ID
        username: 用户名
        ip_address: IP地址
        user_agent: User-Agent
        is_new_location: 是否为新位置登录
    """
    title = "新的登录活动"
    content = f"""检测到您的账号有新的登录活动：

IP 地址: {ip_address}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

如果这不是您本人操作，请及时修改密码并联系客服。
"""

    from database.models import Message
    from database import SessionLocal

    db = SessionLocal()
    try:
        create_inbox_message(
            db=db,
            user_id=user_id,
            title=title,
            content=content,
            message_type="security"
        )
    finally:
        db.close()

    # 同时通知管理员
    if is_new_location:
        await send_system_alert_message(
            f"🚨 可疑登录活动\n\n用户: {username} (ID: {user_id})\nIP: {ip_address}\nUser-Agent: {user_agent[:100]}"
        )
