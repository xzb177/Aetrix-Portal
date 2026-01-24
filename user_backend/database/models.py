"""
用户端网站数据库模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, DateTime, Text, Numeric, Index, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


# ==================== Emby 服务器相关 ====================

class EmbyServer(Base):
    """Emby 服务器表"""
    __tablename__ = 'emby_servers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # 服务器名称
    url = Column(String(255), nullable=False)  # 服务器地址（含端口）
    api_key = Column(String(255), nullable=False)  # API Key
    is_active = Column(Boolean, default=True)  # 是否启用
    max_users = Column(Integer, default=0)  # 最大用户数（0为无限制）
    current_users = Column(Integer, default=0)  # 当前用户数
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


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
    weight = Column(Integer, default=1)  # 权重（用于负载均衡）
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
    emby_user_id = Column(String(100))  # Emby 中的用户 ID
    username = Column(String(100))  # Emby 账号用户名
    password = Column(String(255))  # Emby 账号密码
    is_active = Column(Boolean, default=True)  # 账号是否激活
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime)  # 与订阅同步过期

    server = relationship("EmbyServer")
    user = relationship("WebUser")
    subscription = relationship("UserSubscription")


# ==================== 站内消息系统 ====================

class Message(Base):
    """站内消息表"""
    __tablename__ = 'messages'

    __table_args__ = (
        Index('idx_msg_user', 'user_id'),
        Index('idx_msg_read', 'is_read'),
        Index('idx_msg_type', 'message_type'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(50), default='system')  # system, ticket, announcement, subscription, media_seek, exchange_code
    related_id = Column(Integer)  # 关联 ID（如工单 ID、订阅 ID 等）
    is_read = Column(Boolean, default=False)
    from_user = Column(String(100))  # 发送者名称（管理员）
    created_at = Column(DateTime, default=datetime.now)
    read_at = Column(DateTime)  # 已读时间

    user = relationship("WebUser")


# ==================== 公告系统 ====================

class Announcement(Base):
    """公告表"""
    __tablename__ = 'announcements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(20), default='system')  # system, activity, urgent
    priority_level = Column(Integer, default=2)  # P0=强制弹窗, P1=消息中心置顶, P2=普通
    is_active = Column(Boolean, default=True)
    start_at = Column(DateTime)  # 生效时间
    end_at = Column(DateTime)  # 过期时间
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==================== 工单系统 ====================

class Ticket(Base):
    """工单表"""
    __tablename__ = 'tickets'

    __table_args__ = (
        Index('idx_ticket_user', 'user_id'),
        Index('idx_ticket_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    category = Column(String(50), default='other')  # technical, billing, feature, other
    priority = Column(String(20), default='medium')  # low, medium, high, urgent
    status = Column(String(20), default='open')  # open, replied, resolved, closed
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("WebUser")


class TicketMessage(Base):
    """工单消息表"""
    __tablename__ = 'ticket_messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey('tickets.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'))  # NULL 表示管理员回复
    message = Column(Text, nullable=False)
    attachments = Column(JSON)  # JSON 数组，存储附件 URL
    is_admin = Column(Boolean, default=False)  # 是否为管理员消息
    created_at = Column(DateTime, default=datetime.now)

    ticket = relationship("Ticket")
    user = relationship("WebUser")


# ==================== 兑换码系统 ====================

class ExchangeCode(Base):
    """兑换码表"""
    __tablename__ = 'exchange_codes'

    __table_args__ = (
        Index('idx_exchange_code', 'code'),
        Index('idx_exchange_status', 'status'),
        Index('idx_exchange_user', 'used_by_user_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    type = Column(Integer, nullable=False, default=1)  # 1:激活试用 2:按天续期 3:按月续期 4:充值积分
    exchange_count = Column(Integer, nullable=False, default=1)  # 兑换数量/天数
    status = Column(Integer, nullable=False, default=0)  # 0:未使用 1:已使用 -1:已禁用
    used_by_user_id = Column(Integer, ForeignKey('web_users.id'), nullable=True)
    used_at = Column(DateTime)
    created_by_admin_id = Column(Integer)  # 管理员 ID（引用 admin_users）
    note = Column(Text)  # 备注
    created_at = Column(DateTime, default=datetime.now)
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
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)  # 生成者
    use_count = Column(Integer, default=0)  # 使用次数
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser")


class InvitationRecord(Base):
    """邀请记录表"""
    __tablename__ = 'invitation_records'

    __table_args__ = (
        Index('idx_inv_inviter', 'inviter_id'),
        Index('idx_inv_invitee', 'invitee_id'),
        Index('idx_inv_conversion', 'conversion_status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    inviter_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)  # 邀请者
    invitee_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)  # 被邀请者
    code = Column(String(20), nullable=False)  # 邀请码
    reward_points = Column(Integer, default=0)  # 总奖励积分
    # 转化状态追踪
    conversion_status = Column(String(20), default='registered')  # registered/paid/subscribed
    first_payment_at = Column(DateTime)  # 首次支付时间
    first_subscription_at = Column(DateTime)  # 首次订阅时间
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    inviter = relationship("WebUser", foreign_keys=[inviter_id])
    invitee = relationship("WebUser", foreign_keys=[invitee_id])


# ==================== 系统配置 ====================

class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = 'system_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    value = Column(Text)  # JSON 或纯文本
    description = Column(String(255))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PointsTransaction(Base):
    """积分交易记录表"""
    __tablename__ = 'points_transactions'

    __table_args__ = (
        Index('idx_pt_user', 'user_id'),
        Index('idx_pt_type', 'transaction_type'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    amount = Column(Integer, nullable=False)  # 变动数量（正数为增加，负数为减少）
    transaction_type = Column(String(50), nullable=False)  # recharge, invite_reward, exchange, subscription, admin_adjust
    description = Column(String(255))  # 描述
    related_id = Column(Integer)  # 关联 ID（如兑换码 ID、邀请记录 ID 等）
    balance_after = Column(Integer, nullable=False)  # 交易后余额
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser", back_populates="point_transactions")


class BalanceTransaction(Base):
    """充值余额交易记录表"""
    __tablename__ = 'balance_transactions'

    __table_args__ = (
        Index('idx_bt_user', 'user_id'),
        Index('idx_bt_type', 'transaction_type'),
        Index('idx_bt_source', 'source_type'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    amount = Column(Integer, nullable=False)  # 变动数量（单位：分，正数为增加，负数为减少）
    balance_before = Column(Integer, nullable=False)  # 交易前余额（分）
    balance_after = Column(Integer, nullable=False)  # 交易后余额（分）
    transaction_type = Column(String(50), nullable=False)  # recharge, exchange, payment, admin_adjust, refund
    source_type = Column(String(50))  # 来源类型：exchange_code, recharge_package, invitation 等
    source_id = Column(Integer)  # 来源 ID（如兑换码 ID）
    description = Column(String(255))  # 描述
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser", back_populates="balance_transactions")


class ExchangeCodeRecord(Base):
    """兑换码使用记录表"""
    __tablename__ = 'exchange_code_records'

    __table_args__ = (
        Index('idx_ecr_user', 'user_id'),
        Index('idx_ecr_code', 'exchange_code_id'),
        Index('idx_ecr_created', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    exchange_code_id = Column(Integer, ForeignKey('exchange_codes.id'), nullable=False)
    code_type = Column(Integer, nullable=False)  # 兑换码类型：1激活试用 2按天续期 3按月续期 4充值余额
    code_display = Column(String(100))  # 兑换码显示（脱敏）
    effect = Column(JSON)  # 兑换效果（JSON 格式记录）
    description = Column(String(500))  # 效果描述
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser")
    exchange_code = relationship("ExchangeCode")


class WebUser(Base):
    """Web 用户表（账号密码登录）"""
    __tablename__ = 'web_users'

    __table_args__ = (
        Index('idx_web_username', 'username'),
        Index('idx_web_telegram_id', 'telegram_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255))
    telegram_id = Column(BigInteger, unique=True)  # 关联 Telegram 账号
    is_active = Column(Boolean, default=True)
    is_staff = Column(Boolean, default=False)
    points = Column(Integer, default=0)  # MP 积分余额（已废弃，兼容旧数据）
    balance = Column(Integer, default=0)  # 充值余额（单位：分）
    completed_requests_count = Column(Integer, default=0)  # 成功求片入库数量
    total_requests_count = Column(Integer, default=0)  # 总求片数量
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 交易记录关联
    point_transactions = relationship("PointsTransaction", back_populates="user", cascade="all, delete-orphan")
    balance_transactions = relationship("BalanceTransaction", back_populates="user", cascade="all, delete-orphan")


class SubscriptionPlan(Base):
    """订阅套餐表"""
    __tablename__ = 'subscription_plans'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    price = Column(Numeric(10, 2), nullable=False)  # 价格（元）
    duration_days = Column(Integer, nullable=False)  # 有效期（天）
    features = Column(Text)  # 特性列表（JSON）
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class UserSubscription(Base):
    """用户订阅表"""
    __tablename__ = 'user_subscriptions'

    __table_args__ = (
        Index('idx_sub_user', 'user_id'),
        Index('idx_sub_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    start_date = Column(DateTime, default=datetime.now)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(20), default='active')  # active, expired, cancelled
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    plan = relationship("SubscriptionPlan")
    user = relationship("WebUser")


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
    type = Column(String(50))  # movie, series, anime, documentary, other
    note = Column(Text)
    status = Column(String(20), default='pending')  # pending, approved, rejected, completed
    priority = Column(Integer, default=0)  # 优先级（投票数或管理员设置）
    admin_note = Column(Text)
    emby_item_id = Column(String(100))  # 添加到 Emby 后的媒体 ID
    tmdb_id = Column(String(50))  # TMDB ID
    poster_url = Column(String(500))  # 海报URL
    subscriber_count = Column(Integer, default=1)  # 订阅该求片的用户数
    completed_at = Column(DateTime)  # 完成时间
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("WebUser")


class RechargePackage(Base):
    """充值套餐表"""
    __tablename__ = 'recharge_packages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    amount = Column(Integer, nullable=False)  # MP 积分数量
    price = Column(Numeric(10, 2), nullable=False)  # 价格（元）
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
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False, index=True)  # 外部订单号
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    package_id = Column(Integer, ForeignKey('recharge_packages.id'), nullable=False)
    amount = Column(Integer, nullable=False)  # MP 积分数量
    price = Column(Numeric(10, 2), nullable=False)  # 价格（元）
    payment_method = Column(String(50))  # xunhu, alipay, wechat
    status = Column(String(20), default='pending')  # pending, paid, failed, cancelled
    payment_url = Column(String(500))  # 支付链接
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
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False, index=True)  # 外部订单号
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    item_name = Column(String(255))  # 商品名称
    amount = Column(Numeric(10, 2), nullable=False)  # 价格（元）
    payment_method = Column(String(50))
    status = Column(String(20), default='pending')  # pending, paid, failed, cancelled
    payment_url = Column(String(500))
    paid_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    plan = relationship("SubscriptionPlan")
    user = relationship("WebUser")


# ==================== 审计日志系统 ====================

class UserAuditLog(Base):
    """用户操作审计日志表"""
    __tablename__ = 'user_audit_logs'

    __table_args__ = (
        Index('idx_audit_user', 'user_id'),
        Index('idx_audit_action', 'action'),
        Index('idx_audit_created', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    action = Column(String(100), nullable=False, index=True)  # 操作类型
    target_type = Column(String(50))  # 操作目标类型
    target_id = Column(Integer)  # 操作目标ID
    details = Column(JSON)  # 操作详情
    ip_address = Column(String(50))  # IP地址
    user_agent = Column(String(500))  # User-Agent
    created_at = Column(DateTime, default=datetime.now, index=True)

    user = relationship("WebUser")


# ==================== 求片订阅系统 ====================

class MovieRequestSubscriber(Base):
    """求片订阅表（用户订阅求片通知）"""
    __tablename__ = 'movie_request_subscribers'

    __table_args__ = (
        Index('idx_mr_sub_request', 'request_id'),
        Index('idx_mr_sub_user', 'user_id'),
        Index('idx_mr_sub_unique', 'request_id', 'user_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey('movie_requests.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    request = relationship("MovieRequest")
    user = relationship("WebUser")


# ==================== 账号发放重试队列 ====================

class AccountDeliveryQueue(Base):
    """账号发放重试队列表"""
    __tablename__ = 'account_delivery_queue'

    __table_args__ = (
        Index('idx_delivery_user', 'user_id'),
        Index('idx_delivery_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    subscription_id = Column(Integer, ForeignKey('user_subscriptions.id'), nullable=False)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    status = Column(String(20), default='pending')  # pending, processing, completed, failed
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    last_error = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    processed_at = Column(DateTime)  # 处理完成时间

    user = relationship("WebUser")
    subscription = relationship("UserSubscription")
    plan = relationship("SubscriptionPlan")


# ==================== 数据埋点 ====================

class AnalyticsEvent(Base):
    """事件埋点表"""
    __tablename__ = 'analytics_events'

    __table_args__ = (
        Index('idx_event_user', 'user_id'),
        Index('idx_event_name', 'event_name'),
        Index('idx_event_time', 'created_at'),
        Index('idx_event_session', 'session_id'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=True)  # 可为空（未登录用户）
    session_id = Column(String(64), nullable=True)  # 会话ID
    event_name = Column(String(50), nullable=False, index=True)  # 事件名称
    event_category = Column(String(50))  # 事件分类：invite/payment/subscription等
    properties = Column(JSON)  # 事件属性（JSON格式）
    page_url = Column(String(500))  # 页面URL
    referrer = Column(String(500))  # 来源页面
    user_agent = Column(String(500))  # 用户代理
    ip_address = Column(String(64))  # IP地址
    created_at = Column(DateTime, default=datetime.now, index=True)

    user = relationship("WebUser")


class DailyStats(Base):
    """每日统计表"""
    __tablename__ = 'daily_stats'

    __table_args__ = (
        Index('idx_stats_date', 'stat_date'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(DateTime, nullable=False, unique=True)  # 统计日期
    # 用户数据
    new_users = Column(Integer, default=0)  # 新增用户
    active_users = Column(Integer, default=0)  # 活跃用户
    # 订阅数据
    new_subscriptions = Column(Integer, default=0)  # 新增订阅
    active_subscriptions = Column(Integer, default=0)  # 活跃订阅
    expired_subscriptions = Column(Integer, default=0)  # 过期订阅
    # 订单数据
    total_orders = Column(Integer, default=0)  # 总订单数
    paid_orders = Column(Integer, default=0)  # 已支付订单
    total_revenue = Column(Numeric(10, 2), default=0)  # 总收入
    # 邀请数据
    total_invitations = Column(Integer, default=0)  # 总邀请数
    converted_invitations = Column(Integer, default=0)  # 转化邀请数（已付费/订阅）
    conversion_rate = Column(Numeric(5, 2), default=0)  # 转化率（百分比）
    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==================== 徽章系统 ====================

class Badge(Base):
    """徽章定义表"""
    __tablename__ = 'badges'

    __table_args__ = (
        Index('idx_badge_code', 'code'),
        Index('idx_badge_active', 'is_active'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)  # 徽章代码（如：bridge_operator）
    name = Column(String(100), nullable=False)  # 徽章名称
    name_en = Column(String(100))  # 英文名称
    description = Column(Text)  # 描述
    icon = Column(String(100))  # 图标（emoji 或图标名）
    color = Column(String(20), default='#673AB7')  # 主题色
    rarity = Column(String(20), default='common')  # 稀有度: common, rare, epic, legendary
    category = Column(String(50), default='achievement')  # 分类: achievement, milestone, special
    requirement_type = Column(String(50))  # 要求类型: first_bind, request_count, recharge_amount
    requirement_value = Column(Integer, default=0)  # 要求值
    is_active = Column(Boolean, default=True)  # 是否启用
    sort_order = Column(Integer, default=0)  # 排序
    created_at = Column(DateTime, default=datetime.now)


class UserBadge(Base):
    """用户徽章关联表"""
    __tablename__ = 'user_badges'

    __table_args__ = (
        Index('idx_ub_user', 'user_id'),
        Index('idx_ub_badge', 'badge_id'),
        Index('idx_ub_unlocked', 'unlocked_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    badge_id = Column(Integer, ForeignKey('badges.id'), nullable=False)
    progress = Column(Integer, default=0)  # 进度（如：已求片次数）
    unlocked_at = Column(DateTime)  # 解锁时间
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    badge = relationship("Badge")


# 初始化徽章数据
INITIAL_BADGES = [
    {
        'code': 'bridge_operator',
        'name': 'BRIDGE OPERATOR',
        'name_en': 'Bridge Operator',
        'description': '完成首次登船，连接到 Aetrix',
        'icon': '🌉',
        'color': '#4CAF50',
        'rarity': 'common',
        'category': 'milestone',
        'requirement_type': 'first_bind',
        'requirement_value': 1,
        'sort_order': 1,
    },
    {
        'code': 'signal_runner',
        'name': 'SIGNAL RUNNER',
        'name_en': 'Signal Runner',
        'description': '累计求片达到 10 次',
        'icon': '📡',
        'color': '#2196F3',
        'rarity': 'rare',
        'category': 'achievement',
        'requirement_type': 'request_count',
        'requirement_value': 10,
        'sort_order': 2,
    },
    {
        'code': 'vault_member',
        'name': 'VAULT MEMBER',
        'name_en': 'Vault Member',
        'description': '累计充值达到 100 元',
        'icon': '💎',
        'color': '#FF9800',
        'rarity': 'rare',
        'category': 'achievement',
        'requirement_type': 'recharge_amount',
        'requirement_value': 10000,  # 单位：分
        'sort_order': 3,
    },
    {
        'code': 'elite_runner',
        'name': 'ELITE RUNNER',
        'name_en': 'Elite Runner',
        'description': '累计求片达到 50 次',
        'icon': '🚀',
        'color': '#9C27B0',
        'rarity': 'epic',
        'category': 'achievement',
        'requirement_type': 'request_count',
        'requirement_value': 50,
        'sort_order': 4,
    },
    {
        'code': 'prime_vault',
        'name': 'PRIME VAULT',
        'name_en': 'Prime Vault',
        'description': '累计充值达到 500 元',
        'icon': '👑',
        'color': '#FFD700',
        'rarity': 'legendary',
        'category': 'achievement',
        'requirement_type': 'recharge_amount',
        'requirement_value': 50000,
        'sort_order': 5,
    },
]


class PaymentConfig(Base):
    """支付配置表"""
    __tablename__ = 'payment_config'

    id = Column(Integer, primary_key=True)
    gateway_url = Column(String(255), nullable=False)  # 支付网关地址
    partner_id = Column(String(100), nullable=False)  # 商户ID
    key = Column(String(255), nullable=False)  # 商户密钥
    notify_url = Column(String(500))  # 异步回调地址
    return_url = Column(String(500))  # 同步跳转地址
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
