"""
审计日志服务

记录用户关键操作，用于：
- 安全审计
- 问题排查
- 用户行为分析
- 合规要求
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from database.models import UserAuditLog, WebUser

logger = logging.getLogger(__name__)


# ==================== 操作类型定义 ====================

class AuditAction:
    """审计操作类型常量"""

    # 认证相关
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"

    # 订阅相关
    SUBSCRIPTION_CREATED = "subscription_created"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    SUBSCRIPTION_EXPIRED = "subscription_expired"

    # Emby 账号相关
    ACCOUNT_CLAIMED = "account_claimed"
    ACCOUNT_RESET = "account_reset"
    ACCOUNT_DISABLED = "account_disabled"

    # 订单相关
    ORDER_CREATED = "order_created"
    ORDER_PAID = "order_paid"
    ORDER_CANCELLED = "order_cancelled"

    # 求片相关
    REQUEST_CREATED = "request_created"
    REQUEST_APPROVED = "request_approved"
    REQUEST_COMPLETED = "request_completed"

    # 工单相关
    TICKET_CREATED = "ticket_created"
    TICKET_CLOSED = "ticket_closed"

    # 兑换码相关
    CODE_REDEEMED = "code_redeemed"

    # 风控相关
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    ACCOUNT_LOCKED = "account_locked"


# ==================== 审计日志记录 ====================

def log_action(
    db: Session,
    user_id: int,
    action: str,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None
) -> UserAuditLog:
    """
    记录用户操作日志

    Args:
        db: 数据库会话
        user_id: 用户ID
        action: 操作类型
        details: 操作详情（JSON）
        ip_address: IP地址
        user_agent: User-Agent
        target_type: 目标类型
        target_id: 目标ID

    Returns:
        创建的审计日志对象
    """
    try:
        log = UserAuditLog(
            user_id=user_id,
            action=action,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            target_type=target_type,
            target_id=target_id,
            created_at=datetime.now()
        )
        db.add(log)
        db.commit()

        logger.debug(f"记录审计日志: 用户={user_id}, 操作={action}")
        return log

    except Exception as e:
        logger.error(f"记录审计日志失败: {e}")
        db.rollback()
        raise


# ==================== 便捷函数 ====================

def log_login(
    db: Session,
    user_id: int,
    ip_address: str,
    user_agent: str,
    success: bool = True
):
    """记录登录操作"""
    action = AuditAction.LOGIN if success else AuditAction.LOGIN_FAILED
    log_action(
        db=db,
        user_id=user_id,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent
    )


def log_subscription_action(
    db: Session,
    user_id: int,
    action: str,
    subscription_id: int,
    plan_name: Optional[str] = None
):
    """记录订阅相关操作"""
    details = {}
    if plan_name:
        details['plan_name'] = plan_name
    details['subscription_id'] = subscription_id

    log_action(
        db=db,
        user_id=user_id,
        action=action,
        details=details,
        target_type='subscription',
        target_id=subscription_id
    )


def log_account_action(
    db: Session,
    user_id: int,
    action: str,
    server_name: Optional[str] = None,
    emby_username: Optional[str] = None
):
    """记录 Emby 账号相关操作"""
    details = {}
    if server_name:
        details['server_name'] = server_name
    if emby_username:
        details['emby_username'] = emby_username

    log_action(
        db=db,
        user_id=user_id,
        action=action,
        details=details,
        target_type='emby_account'
    )


def log_order_action(
    db: Session,
    user_id: int,
    action: str,
    order_id: str,
    amount: Optional[float] = None,
    payment_method: Optional[str] = None
):
    """记录订单相关操作"""
    details = {'order_id': order_id}
    if amount:
        details['amount'] = amount
    if payment_method:
        details['payment_method'] = payment_method

    log_action(
        db=db,
        user_id=user_id,
        action=action,
        details=details,
        target_type='order'
    )


def log_suspicious_activity(
    db: Session,
    user_id: int,
    activity_type: str,
    details: Dict[str, Any],
    ip_address: Optional[str] = None
):
    """记录可疑活动"""
    log_action(
        db=db,
        user_id=user_id,
        action=f"{AuditAction.SUSPICIOUS_ACTIVITY}:{activity_type}",
        details=details,
        ip_address=ip_address,
        target_type='security'
    )


# ==================== 查询功能 ====================

def get_user_logs(
    db: Session,
    user_id: int,
    limit: int = 100,
    action: Optional[str] = None
) -> List[UserAuditLog]:
    """
    获取用户审计日志

    Args:
        db: 数据库会话
        user_id: 用户ID
        limit: 返回数量限制
        action: 过滤操作类型

    Returns:
        审计日志列表
    """
    try:
        query = db.query(UserAuditLog).filter(
            UserAuditLog.user_id == user_id
        )

        if action:
            query = query.filter(UserAuditLog.action == action)

        return query.order_by(
            UserAuditLog.created_at.desc()
        ).limit(limit).all()

    except Exception as e:
        logger.error(f"查询用户审计日志失败: {e}")
        return []


def get_recent_logins(
    db: Session,
    user_id: int,
    hours: int = 24
) -> List[UserAuditLog]:
    """
    获取用户最近的登录记录

    Args:
        db: 数据库会话
        user_id: 用户ID
        hours: 查询小时数

    Returns:
        登录记录列表
    """
    try:
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(hours=hours)

        return db.query(UserAuditLog).filter(
            UserAuditLog.user_id == user_id,
            UserAuditLog.action.in_([AuditAction.LOGIN, AuditAction.LOGIN_FAILED]),
            UserAuditLog.created_at >= cutoff
        ).order_by(
            UserAuditLog.created_at.desc()
        ).all()

    except Exception as e:
        logger.error(f"查询登录记录失败: {e}")
        return []


def get_failed_logins(
    db: Session,
    user_id: Optional[int] = None,
    hours: int = 24
) -> List[UserAuditLog]:
    """
    获取失败登录记录

    Args:
        db: 数据库会话
        user_id: 用户ID（None 表示查询所有用户）
        hours: 查询小时数

    Returns:
        失败登录记录列表
    """
    try:
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(hours=hours)

        query = db.query(UserAuditLog).filter(
            UserAuditLog.action == AuditAction.LOGIN_FAILED,
            UserAuditLog.created_at >= cutoff
        )

        if user_id:
            query = query.filter(UserAuditLog.user_id == user_id)

        return query.order_by(
            UserAuditLog.created_at.desc()
        ).all()

    except Exception as e:
        logger.error(f"查询失败登录记录失败: {e}")
        return []


def get_security_events(
    db: Session,
    hours: int = 24,
    limit: int = 100
) -> List[UserAuditLog]:
    """
    获取安全相关事件

    Args:
        db: 数据库会话
        hours: 查询小时数
        limit: 返回数量限制

    Returns:
        安全事件列表
    """
    try:
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(hours=hours)
        security_actions = [
            AuditAction.LOGIN_FAILED,
            AuditAction.PASSWORD_RESET,
            AuditAction.ACCOUNT_RESET,
            AuditAction.SUSPICIOUS_ACTIVITY,
            AuditAction.ACCOUNT_LOCKED,
        ]

        return db.query(UserAuditLog).filter(
            UserAuditLog.created_at >= cutoff,
            UserAuditLog.action.in_(security_actions)
        ).order_by(
            UserAuditLog.created_at.desc()
        ).limit(limit).all()

    except Exception as e:
        logger.error(f"查询安全事件失败: {e}")
        return []


# ==================== 统计分析 ====================

def get_user_activity_summary(
    db: Session,
    user_id: int,
    days: int = 30
) -> Dict[str, Any]:
    """
    获取用户活动摘要

    Args:
        db: 数据库会话
        user_id: 用户ID
        days: 统计天数

    Returns:
        活动摘要字典
    """
    try:
        from datetime import timedelta
        from sqlalchemy import func

        cutoff = datetime.now() - timedelta(days=days)

        # 总操作数
        total_actions = db.query(func.count(UserAuditLog.id)).filter(
            UserAuditLog.user_id == user_id,
            UserAuditLog.created_at >= cutoff
        ).scalar()

        # 最后活跃时间
        last_activity = db.query(UserAuditLog.created_at).filter(
            UserAuditLog.user_id == user_id
        ).order_by(
            UserAuditLog.created_at.desc()
        ).first()

        # 操作分布
        action_distribution = db.query(
            UserAuditLog.action,
            func.count(UserAuditLog.id)
        ).filter(
            UserAuditLog.user_id == user_id,
            UserAuditLog.created_at >= cutoff
        ).group_by(UserAuditLog.action).all()

        return {
            'user_id': user_id,
            'days': days,
            'total_actions': total_actions or 0,
            'last_activity': last_activity[0] if last_activity else None,
            'action_distribution': {action: count for action, count in action_distribution}
        }

    except Exception as e:
        logger.error(f"获取用户活动摘要失败: {e}")
        return {
            'user_id': user_id,
            'days': days,
            'total_actions': 0,
            'last_activity': None,
            'action_distribution': {}
        }
