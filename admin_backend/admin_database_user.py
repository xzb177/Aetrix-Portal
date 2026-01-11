"""
用户端网站数据库连接
订阅套餐、充值套餐等数据存储在用户端数据库中
使用 PostgreSQL（与 admin_database 共享同一个数据库）
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, BigInteger, DateTime, Text, Numeric, ForeignKey, Index, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
import os

# 用户端数据库 - 使用 PostgreSQL
USER_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://royalbot:royalbot_prod_2026_secure@127.0.0.1:5432/royalbot"
)

# 创建引擎
user_engine = create_engine(
    USER_DB_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# 创建会话工厂
UserSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=user_engine)

# Base
UserBase = declarative_base()


class WebUser(UserBase):
    """Web 用户表"""
    __tablename__ = 'web_users'

    __table_args__ = (
        Index('idx_web_username', 'username'),
        Index('idx_web_telegram_id', 'telegram_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255))
    telegram_id = Column(BigInteger, unique=True)
    is_active = Column(Boolean, default=True)
    is_staff = Column(Boolean, default=False)
    created_at = Column(DateTime)


class SubscriptionPlan(UserBase):
    """订阅套餐表"""
    __tablename__ = 'subscription_plans'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    price = Column(Numeric(10, 2), nullable=False)
    duration_days = Column(Integer, nullable=False)
    features = Column(Text)
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime)


class UserSubscription(UserBase):
    """用户订阅表"""
    __tablename__ = 'user_subscriptions'

    __table_args__ = (
        Index('idx_sub_user', 'user_id'),
        Index('idx_sub_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    start_date = Column(DateTime)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(20), default='active')
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime)

    plan = relationship("SubscriptionPlan")
    user = relationship("WebUser")


class SubscriptionOrder(UserBase):
    """订阅订单表"""
    __tablename__ = 'subscription_orders'

    __table_args__ = (
        Index('idx_suborder_user', 'user_id'),
        Index('idx_suborder_status', 'status'),
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
    created_at = Column(DateTime)

    plan = relationship("SubscriptionPlan")
    user = relationship("WebUser")


class RechargePackage(UserBase):
    """充值套餐表"""
    __tablename__ = 'recharge_packages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    amount = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    bonus = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime)


class RechargeOrder(UserBase):
    """充值订单表"""
    __tablename__ = 'recharge_orders'

    __table_args__ = (
        Index('idx_recharge_user', 'user_id'),
        Index('idx_recharge_status', 'status'),
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
    created_at = Column(DateTime)

    package = relationship("RechargePackage")
    user = relationship("WebUser")


class MovieRequest(UserBase):
    """求片请求表"""
    __tablename__ = 'movie_requests'

    __table_args__ = (
        Index('idx_req_user', 'user_id'),
        Index('idx_req_status', 'status'),
        Index('idx_req_created', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    movie_name = Column(String(255), nullable=False)
    year = Column(String(10))
    type = Column(String(50))
    note = Column(Text)
    status = Column(String(20), default='pending')  # pending, approved, completed, rejected
    status_remark = Column(Text)  # 状态说明
    admin_note = Column(Text)
    emby_item_id = Column(String(100))
    download_id = Column(String(255))  # 下载任务ID
    poster_url = Column(String(500))  # 海报URL
    tmdb_id = Column(String(50))  # TMDB ID
    seek_count = Column(Integer, default=1)  # 同求人数
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    completed_at = Column(DateTime)  # 完成时间

    user = relationship("WebUser")
    subscribers = relationship("MovieRequestSubscriber", back_populates="request", cascade="all, delete-orphan")
    logs = relationship("MovieRequestLog", back_populates="request", cascade="all, delete-orphan")


class MovieRequestSubscriber(UserBase):
    """求片同求表 - 用户订阅某个求片"""
    __tablename__ = 'movie_request_subscribers'

    __table_args__ = (
        Index('idx_sub_req', 'request_id'),
        Index('idx_sub_user', 'user_id'),
        Index('idx_sub_unique', 'request_id', 'user_id', unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey('movie_requests.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    notified = Column(Boolean, default=False)  # 是否已通知完成

    request = relationship("MovieRequest", back_populates="subscribers")
    user = relationship("WebUser")


class MovieRequestLog(UserBase):
    """求片操作日志表"""
    __tablename__ = 'movie_request_logs'

    __table_args__ = (
        Index('idx_log_req', 'request_id'),
        Index('idx_log_type', 'log_type'),
        Index('idx_log_created', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey('movie_requests.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'))  # 操作用户
    log_type = Column(String(20), nullable=False)  # created, subscribed, status_changed, completed
    content = Column(Text)  # 日志内容
    extra_data = Column(JSON)  # 额外数据
    created_at = Column(DateTime, default=datetime.now)

    request = relationship("MovieRequest", back_populates="logs")


# ==================== 新增模型 ====================

class EmbyServer(UserBase):
    """Emby 服务器表"""
    __tablename__ = 'emby_servers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    url = Column(String(255), nullable=False)
    api_key = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    max_users = Column(Integer, default=0)
    current_users = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class PlanServerRelation(UserBase):
    """套餐服务器关联表"""
    __tablename__ = 'plan_server_relations'

    __table_args__ = (
        Index('idx_psr_plan', 'plan_id'),
        Index('idx_psr_server', 'server_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=False)
    server_id = Column(Integer, ForeignKey('emby_servers.id'), nullable=False)
    weight = Column(Integer, default=1)
    created_at = Column(DateTime)

    plan = relationship("SubscriptionPlan")
    server = relationship("EmbyServer")


class UserEmbyAccount(UserBase):
    """用户 Emby 账号表"""
    __tablename__ = 'user_emby_accounts'

    __table_args__ = (
        Index('idx_emby_user', 'user_id'),
        Index('idx_emby_server', 'server_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    server_id = Column(Integer, ForeignKey('emby_servers.id'), nullable=False)
    emby_user_id = Column(String(100))
    username = Column(String(100), nullable=False)
    password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    server = relationship("EmbyServer")
    user = relationship("WebUser")


class Announcement(UserBase):
    """公告表"""
    __tablename__ = 'announcements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(20), default='system')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class Ticket(UserBase):
    """工单表"""
    __tablename__ = 'tickets'

    __table_args__ = (
        Index('idx_ticket_user', 'user_id'),
        Index('idx_ticket_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    title = Column(String(255), nullable=False)
    category = Column(String(50))
    priority = Column(String(20), default='normal')
    status = Column(String(20), default='open')
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    user = relationship("WebUser")


class TicketMessage(UserBase):
    """工单消息表"""
    __tablename__ = 'ticket_messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey('tickets.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'))
    message = Column(Text, nullable=False)
    attachments = Column(JSON)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime)

    ticket = relationship("Ticket")
    user = relationship("WebUser")


class InvitationCode(UserBase):
    """邀请码表"""
    __tablename__ = 'invitation_codes'

    __table_args__ = (
        Index('idx_inv_code', 'code'),
        Index('idx_inv_user', 'user_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime)

    user = relationship("WebUser")


class InvitationRecord(UserBase):
    """邀请记录表"""
    __tablename__ = 'invitation_records'

    __table_args__ = (
        Index('idx_inv_inviter', 'inviter_id'),
        Index('idx_inv_invitee', 'invitee_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    inviter_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    invitee_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    code = Column(String(20))  # 邀请码
    reward_points = Column(Integer, default=0)
    created_at = Column(DateTime)

    inviter = relationship("WebUser", foreign_keys="InvitationRecord.inviter_id")
    invitee = relationship("WebUser", foreign_keys="InvitationRecord.invitee_id")


class Message(UserBase):
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
    message_type = Column(String(50), default='system')
    related_id = Column(Integer)
    is_read = Column(Boolean, default=False)
    from_user = Column(String(100))
    created_at = Column(DateTime)
    read_at = Column(DateTime)

    user = relationship("WebUser")


class SystemConfig(UserBase):
    """系统配置表"""
    __tablename__ = 'system_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    value = Column(Text)
    description = Column(String(255))
    updated_at = Column(DateTime)


class ExchangeCode(UserBase):
    """兑换码表"""
    __tablename__ = 'exchange_codes'

    __table_args__ = (
        Index('idx_exchange_code', 'code'),
        Index('idx_exchange_status', 'status'),
        Index('idx_exchange_user', 'used_by_user_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    type = Column(Integer, nullable=False, default=1)
    exchange_count = Column(Integer, nullable=False, default=1)
    status = Column(Integer, nullable=False, default=0)
    used_by_user_id = Column(Integer, ForeignKey('web_users.id'), nullable=True)
    used_at = Column(DateTime)
    created_by_admin_id = Column(Integer)
    note = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


def get_user_db() -> Session:
    """获取用户端数据库会话"""
    db = UserSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_user_db():
    """初始化用户端数据库表（创建所有用户相关的表）"""
    UserBase.metadata.create_all(bind=user_engine)
