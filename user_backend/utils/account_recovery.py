"""
账号恢复工具函数

用于在续费后恢复被禁用的 Emby 账号
"""
import logging
from datetime import timedelta
from sqlalchemy.orm import Session

from database.models import UserEmbyAccount, UserSubscription, EmbyServer, WebUser, Message
from utils.emby_client import EmbyClient

logger = logging.getLogger(__name__)


async def reactivate_subscription_accounts(db: Session, subscription: UserSubscription) -> dict:
    """
    恢复订阅下所有被禁用的 Emby 账号

    Args:
        db: 数据库会话
        subscription: 订阅对象

    Returns:
        dict: {'success': bool, 'reactivated': int, 'failed': int, 'messages': list}
    """
    result = {
        'success': True,
        'reactivated': 0,
        'failed': 0,
        'messages': []
    }

    try:
        # 查找该订阅下被禁用的账号
        disabled_accounts = db.query(UserEmbyAccount).filter(
            UserEmbyAccount.subscription_id == subscription.id,
            UserEmbyAccount.is_active == False
        ).all()

        if not disabled_accounts:
            result['messages'].append('没有需要恢复的账号')
            return result

        logger.info(f"订阅 {subscription.id} 有 {len(disabled_accounts)} 个待恢复账号")

        for account in disabled_accounts:
            server = db.query(EmbyServer).filter(
                EmbyServer.id == account.server_id
            ).first()

            if not server or not server.is_active:
                msg = f"服务器 {account.server_id} 不可用，跳过账号恢复"
                logger.warning(msg)
                result['messages'].append(msg)
                result['failed'] += 1
                continue

            try:
                emby_client = EmbyClient(server.url, server.api_key)

                # 生成新密码
                new_password = EmbyClient.generate_password(12)

                # 更新 Emby 密码
                emby_result = emby_client.update_user_password(
                    account.emby_user_id,
                    new_password
                )

                if emby_result.get('success'):
                    # 更新数据库
                    account.password = new_password
                    account.is_active = True
                    # 更新过期时间
                    account.expires_at = subscription.end_date + timedelta(days=7)
                    db.add(account)

                    logger.info(f"已恢复账号 {account.username}@{server.name}")

                    # 发送站内消息通知用户
                    user = db.query(WebUser).filter(WebUser.id == subscription.user_id).first()
                    if user:
                        message = Message(
                            user_id=user.id,
                            title="Emby 账号已恢复",
                            content=f"您的订阅已续费，Emby 账号已恢复使用！\n\n服务器: {server.name}\n地址: {server.url}\n用户名: {account.username}\n密码: {new_password}\n\n过期时间: {account.expires_at.strftime('%Y-%m-%d')}",
                            message_type="subscription",
                            related_id=subscription.id
                        )
                        db.add(message)

                    result['reactivated'] += 1
                    result['messages'].append(f"已恢复账号 {account.username}@{server.name}")
                else:
                    msg = f"恢复 Emby 密码失败: {emby_result.get('message')}"
                    logger.error(msg)
                    result['messages'].append(msg)
                    result['failed'] += 1

            except Exception as e:
                msg = f"恢复账号 {account.id} 时出错: {e}"
                logger.error(msg)
                result['messages'].append(msg)
                result['failed'] += 1

        db.commit()

        if result['failed'] > 0:
            result['success'] = False

    except Exception as e:
        logger.error(f"账号恢复过程出错: {e}")
        result['success'] = False
        result['messages'].append(f"账号恢复过程出错: {e}")

    return result


def get_account_recovery_info(db: Session, user_id: int) -> dict:
    """
    获取用户账号恢复信息

    检查用户是否有被禁用的账号以及对应的订阅状态

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        dict: 账号恢复信息
    """
    # 查找用户被禁用的账号
    disabled_accounts = db.query(UserEmbyAccount).filter(
        UserEmbyAccount.user_id == user_id,
        UserEmbyAccount.is_active == False
    ).all()

    if not disabled_accounts:
        return {
            'has_disabled_accounts': False,
            'accounts': []
        }

    accounts_info = []
    for account in disabled_accounts:
        subscription = db.query(UserSubscription).filter(
            UserSubscription.id == account.subscription_id
        ).first()

        server = db.query(EmbyServer).filter(
            EmbyServer.id == account.server_id
        ).first()

        accounts_info.append({
            'id': account.id,
            'username': account.username,
            'server_name': server.name if server else '未知',
            'subscription_status': subscription.status if subscription else None,
            'subscription_end_date': subscription.end_date.isoformat() if subscription and subscription.end_date else None,
            'can_reactivate': subscription and subscription.status == 'active' and subscription.end_date and subscription.end_date > None
        })

    return {
        'has_disabled_accounts': True,
        'accounts': accounts_info
    }
