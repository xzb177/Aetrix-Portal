"""
统一数据模型
整合用户端、管理后台和主项目的所有数据模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, DateTime, Text, Numeric, Index, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from backend.database import Base


# ==================== 系统管理相关 ====================

class AdminUser(Base):
    """管理员用户表"""
    __tablename__ = 'admin_users'

    __table_args__ = (
        Index('idx_admin_username', 'username'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255))
    role = Column(String(50), default='admin')  # super_admin, admin, operator
    permissions = Column(JSON)  # 权限列表
    is_active = Column(Boolean, default=True)
    failed_login_count = Column(Integer, default=0)
    locked_until = Column(DateTime)
    last_login_at = Column(DateTime)
    last_login_ip = Column(String(50))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AdminRole(Base):
    """管理员角色表"""
    __tablename__ = 'admin_roles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    permissions = Column(JSON)  # 权限列表
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class AdminLog(Base):
    """管理员操作日志表"""
    __tablename__ = 'admin_logs'

    __table_args__ = (
        Index('idx_admin_log_user', 'admin_user_id'),
        Index('idx_admin_log_action', 'action'),
        Index('idx_admin_log_time', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey('admin_users.id'))
    action = Column(String(100), nullable=False)  # 操作类型
    target_type = Column(String(50))  # 操作目标类型
    target_id = Column(Integer)  # 操作目标ID
    details = Column(JSON)  # 操作详情
    ip_address = Column(String(50))
    user_agent = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)

    admin_user = relationship("AdminUser")


class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = 'system_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    value = Column(Text)
    description = Column(String(255))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class NotificationHistory(Base):
    """通知历史表"""
    __tablename__ = 'notification_history'

    __table_args__ = (
        Index('idx_notif_type', 'notification_type'),
        Index('idx_notif_time', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_type = Column(String(50), nullable=False)  # telegram, email, system
    target = Column(String(255))  # 接收者
    title = Column(String(255))
    content = Column(Text)
    status = Column(String(20), default='pending')  # pending, sent, failed
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    sent_at = Column(DateTime)


class StationMessage(Base):
    """站内消息表 - 前后台联动核心"""
    __tablename__ = 'station_messages'

    __table_args__ = (
        Index('idx_station_from', 'from_user_id'),
        Index('idx_station_to', 'to_user_id'),
        Index('idx_station_read', 'is_read'),
        Index('idx_station_type', 'message_type'),
        Index('idx_station_time', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_user_id = Column(Integer, ForeignKey('admin_users.id'))  # 发送者（管理员），系统消息为空
    to_user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)  # 接收者
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(20), default='system')  # system, ticket, announcement, subscription, media_seek
    related_id = Column(Integer)  # 关联ID（如工单ID、公告ID）
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    from_user = relationship("AdminUser")
    to_user = relationship("WebUser", backref="station_messages")


# ==================== 用户相关 ====================

class WebUser(Base):
    """Web 用户表（网站登录用户）"""
    __tablename__ = 'web_users'

    __table_args__ = (
        Index('idx_web_username', 'username'),
        Index('idx_web_telegram_id', 'telegram_id'),
        Index('idx_web_email', 'email'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255))
    telegram_id = Column(BigInteger, unique=True)
    is_active = Column(Boolean, default=True)
    is_staff = Column(Boolean, default=False)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TelegramUser(Base):
    """Telegram 用户表（从主项目迁移）"""
    __tablename__ = 'telegram_users'

    __table_args__ = (
        Index('idx_tg_id', 'telegram_id'),
        Index('idx_tg_username', 'username'),
    )

    id = Column(BigInteger, primary_key=True)  # Telegram ID
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    language_code = Column(String(10))
    is_bot = Column(Boolean, default=False)
    is_premium = Column(Boolean, default=False)

    # Emby 相关
    emby_account = Column(String)  # Emby 账号
    emby_password = Column(String)  # Emby 密码
    emby_url = Column(String)  # Emby 服务器地址
    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(DateTime)

    # 积分系统
    points = Column(Integer, default=0)
    bank_points = Column(Integer, default=0)
    total_earned = Column(Integer, default=0)
    total_spent = Column(Integer, default=0)

    # 签到相关
    last_checkin = Column(DateTime)
    last_checkin_date = Column(DateTime)
    total_checkin_days = Column(Integer, default=0)
    consecutive_checkin = Column(Integer, default=0)

    # 观影相关
    daily_watch_minutes = Column(Integer, default=0)
    total_watch_minutes = Column(Integer, default=0)
    last_watch_claimed = Column(DateTime)
    watch_streak = Column(Integer, default=0)
    last_watch_checkin_date = Column(DateTime)
    total_watch_checkin_days = Column(Integer, default=0)
    watch_checkin_today = Column(Boolean, default=False)

    # 游戏数据（兼容原有功能）
    win = Column(Integer, default=0)
    lost = Column(Integer, default=0)
    weapon = Column(String)
    attack = Column(Integer, default=0)
    intimacy = Column(Integer, default=0)
    resonance_count = Column(Integer, default=0)

    # 时间相关
    last_active_time = Column(DateTime)
    last_chat_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    web_user_id = Column(Integer, ForeignKey('web_users.id'))
    web_user = relationship("WebUser", backref="telegram_accounts")


# ==================== 订阅和支付相关 ====================

class SubscriptionPlan(Base):
    """订阅套餐表"""
    __tablename__ = 'subscription_plans'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    price = Column(Numeric(10, 2), nullable=False)
    duration_days = Column(Integer, nullable=False)
    features = Column(JSON)  # 特性列表
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class UserSubscription(Base):
    """用户订阅表"""
    __tablename__ = 'user_subscriptions'

    __table_args__ = (
        Index('idx_sub_user', 'user_id'),
        Index('idx_sub_status', 'status'),
        Index('idx_sub_expiry', 'end_date'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    start_date = Column(DateTime, default=datetime.now)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(20), default='active')  # active, expired, cancelled
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    plan = relationship("SubscriptionPlan")
    user = relationship("WebUser")


class RechargePackage(Base):
    """充值套餐表"""
    __tablename__ = 'recharge_packages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    amount = Column(Integer, nullable=False)  # 积分数量
    price = Column(Numeric(10, 2), nullable=False)
    bonus = Column(Integer, default=0)  # 赠送积分
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class RechargeOrder(Base):
    """充值订单表"""
    __tablename__ = 'recharge_orders'

    __table_args__ = (
        Index('idx_recharge_user', 'user_id'),
        Index('idx_recharge_status', 'status'),
        Index('idx_recharge_order_id', 'order_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    package_id = Column(Integer, ForeignKey('recharge_packages.id'), nullable=False)
    amount = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(50))
    status = Column(String(20), default='pending')
    payment_url = Column(String(500))
    paid_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    package = relationship("RechargePackage")
    user = relationship("WebUser")


class SubscriptionOrder(Base):
    """订阅订单表"""
    __tablename__ = 'subscription_orders'

    __table_args__ = (
        Index('idx_suborder_user', 'user_id'),
        Index('idx_suborder_status', 'status'),
        Index('idx_suborder_order_id', 'order_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    item_name = Column(String(255))
    amount = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(50))
    status = Column(String(20), default='pending')
    payment_url = Column(String(500))
    paid_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    plan = relationship("SubscriptionPlan")
    user = relationship("WebUser")


# ==================== Emby 相关 ====================

class EmbyServer(Base):
    """Emby 服务器表"""
    __tablename__ = 'emby_servers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    url = Column(String(255), nullable=False)
    api_key = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    max_users = Column(Integer, default=0)
    current_users = Column(Integer, default=0)
    priority = Column(Integer, default=0)  # 优先级
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 监控数据
    last_check_at = Column(DateTime)
    status = Column(String(20), default='unknown')  # online, offline, unknown
    response_time = Column(Integer)  # 响应时间（毫秒）


class PlanServerRelation(Base):
    """套餐服务器关联表（负载均衡）"""
    __tablename__ = 'plan_server_relations'

    __table_args__ = (
        Index('idx_psr_plan', 'plan_id'),
        Index('idx_psr_server', 'server_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    server_id = Column(Integer, ForeignKey('emby_servers.id'), nullable=False)
    weight = Column(Integer, default=1)  # 权重
    created_at = Column(DateTime, default=datetime.now)

    plan = relationship("SubscriptionPlan")
    server = relationship("EmbyServer")


class UserEmbyAccount(Base):
    """用户 Emby 账号表"""
    __tablename__ = 'user_emby_accounts'

    __table_args__ = (
        Index('idx_emby_user', 'user_id'),
        Index('idx_emby_server', 'server_id'),
        Index('idx_emby_sub', 'subscription_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    server_id = Column(Integer, ForeignKey('emby_servers.id'), nullable=False)
    subscription_id = Column(Integer, ForeignKey('user_subscriptions.id'), nullable=False)
    emby_user_id = Column(String(100))
    username = Column(String(100))
    password = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)

    server = relationship("EmbyServer")
    user = relationship("WebUser")
    subscription = relationship("UserSubscription")


class EmbySession(Base):
    """Emby 会话监控表"""
    __tablename__ = 'emby_sessions'

    __table_args__ = (
        Index('idx_session_user', 'user_id'),
        Index('idx_session_server', 'server_id'),
        Index('idx_session_time', 'start_time'),
    )

    id = Column(String(100), primary_key=True)  # Emby Session ID
    server_id = Column(Integer, ForeignKey('emby_servers.id'))
    user_id = Column(Integer, ForeignKey('web_users.id'))
    username = Column(String(100))
    item_name = Column(String(255))
    item_type = Column(String(50))  # movie, series, episode
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    play_duration = Column(Integer, default=0)  # 播放时长（秒）
    device_name = Column(String(100))
    client_name = Column(String(100))

    server = relationship("EmbyServer")
    user = relationship("WebUser")


class MovieBookmark(Base):
    """电影收藏表"""
    __tablename__ = 'movie_bookmarks'

    __table_args__ = (
        Index('idx_bookmark_user', 'user_id'),
        Index('idx_bookmark_item', 'item_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    item_id = Column(String, nullable=False)
    item_name = Column(String)
    item_type = Column(String)
    bookmark_type = Column(String, default='favorite')  # favorite, watchlist
    rating = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


# ==================== 工单系统 ====================

class Ticket(Base):
    """工单表"""
    __tablename__ = 'tickets'

    __table_args__ = (
        Index('idx_ticket_user', 'user_id'),
        Index('idx_ticket_status', 'status'),
        Index('idx_ticket_priority', 'priority'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    category = Column(String(50), default='other')
    priority = Column(String(20), default='medium')
    status = Column(String(20), default='open')
    admin_id = Column(Integer, ForeignKey('admin_users.id'))  # 处理管理员
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("WebUser")
    admin = relationship("AdminUser")


class TicketMessage(Base):
    """工单消息表"""
    __tablename__ = 'ticket_messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey('tickets.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'))
    admin_id = Column(Integer, ForeignKey('admin_users.id'))
    message = Column(Text, nullable=False)
    attachments = Column(JSON)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    ticket = relationship("Ticket")
    user = relationship("WebUser")
    admin = relationship("AdminUser")


# ==================== 公告和活动 ====================

class Announcement(Base):
    """公告表"""
    __tablename__ = 'announcements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(20), default='system')
    is_active = Column(Boolean, default=True)
    is_pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ThemeActivity(Base):
    """主题观影活动表"""
    __tablename__ = 'theme_activities'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    activity_type = Column(String(50), nullable=False)
    filter_genre = Column(String)
    filter_director = Column(String)
    filter_series = Column(String)
    target_count = Column(Integer)
    reward_mp = Column(Integer)
    reward_title = Column(String)
    is_active = Column(Boolean, default=True)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class ThemeActivityProgress(Base):
    """活动进度表"""
    __tablename__ = 'theme_activity_progress'

    __table_args__ = (
        Index('idx_actprog_user', 'user_id'),
        Index('idx_actprog_activity', 'activity_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, ForeignKey('theme_activities.id'), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    progress = Column(Integer, default=0)
    watched_items = Column(Text, default='')
    completed = Column(Boolean, default=False)
    reward_claimed = Column(Boolean, default=False)
    claimed_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==================== 邀请系统 ====================

class InvitationCode(Base):
    """邀请码表"""
    __tablename__ = 'invitation_codes'

    __table_args__ = (
        Index('idx_inv_code', 'code'),
        Index('idx_inv_user', 'user_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    max_uses = Column(Integer, default=100)
    use_count = Column(Integer, default=0)
    reward_points = Column(Integer, default=0)
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser")


class InvitationRecord(Base):
    """邀请记录表"""
    __tablename__ = 'invitation_records'

    __table_args__ = (
        Index('idx_inv_inviter', 'inviter_id'),
        Index('idx_inv_invitee', 'invitee_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    inviter_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    invitee_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    code_id = Column(Integer, ForeignKey('invitation_codes.id'), nullable=False)
    reward_points = Column(Integer, default=0)
    reward_claimed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    inviter = relationship("WebUser", foreign_keys=[inviter_id])
    invitee = relationship("WebUser", foreign_keys=[invitee_id])
    code = relationship("InvitationCode")


# ==================== 求片系统 ====================

class MovieRequest(Base):
    """求片请求表"""
    __tablename__ = 'movie_requests'

    __table_args__ = (
        Index('idx_req_user', 'user_id'),
        Index('idx_req_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    movie_name = Column(String(255), nullable=False)
    year = Column(String(10))
    type = Column(String(50))
    note = Column(Text)
    status = Column(String(20), default='pending')
    admin_note = Column(Text)
    emby_item_id = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("WebUser")


# ==================== 系统监控 ====================

class SystemMetric(Base):
    """系统指标表"""
    __tablename__ = 'system_metrics'

    __table_args__ = (
        Index('idx_metric_name', 'metric_name'),
        Index('idx_metric_time', 'timestamp'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float)
    tags = Column(JSON)  # 标签，如 {server_id: 1}
    timestamp = Column(DateTime, default=datetime.now)


class AlertRule(Base):
    """告警规则表"""
    __tablename__ = 'alert_rules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    metric_name = Column(String(100), nullable=False)
    condition = Column(String(20))  # gt, lt, eq
    threshold = Column(Float)
    severity = Column(String(20), default='warning')  # info, warning, critical
    notification_channels = Column(JSON)  # ['telegram', 'email']
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Alert(Base):
    """告警记录表"""
    __tablename__ = 'alerts'

    __table_args__ = (
        Index('idx_alert_rule', 'rule_id'),
        Index('idx_alert_status', 'status'),
        Index('idx_alert_time', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey('alert_rules.id'))
    severity = Column(String(20), default='warning')
    title = Column(String(255))
    message = Column(Text)
    status = Column(String(20), default='open')  # open, acknowledged, resolved
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    rule = relationship("AlertRule")


# ==================== 导出所有模型 ====================
__all__ = [
    # 系统管理
    "AdminUser", "AdminRole", "AdminLog", "SystemConfig", "NotificationHistory", "StationMessage",
    # 用户
    "WebUser", "TelegramUser",
    # 订阅和支付
    "SubscriptionPlan", "UserSubscription", "RechargePackage", "RechargeOrder", "SubscriptionOrder",
    # Emby
    "EmbyServer", "PlanServerRelation", "UserEmbyAccount", "EmbySession", "MovieBookmark",
    # 工单
    "Ticket", "TicketMessage",
    # 公告和活动
    "Announcement", "ThemeActivity", "ThemeActivityProgress",
    # 邀请
    "InvitationCode", "InvitationRecord",
    # 求片
    "MovieRequest",
    # 监控
    "SystemMetric", "AlertRule", "Alert",
]
