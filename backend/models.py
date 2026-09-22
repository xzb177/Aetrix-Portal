"""
统一数据模型
整合用户端、管理后台和主项目的所有数据模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, DateTime, Text, Numeric, Index, ForeignKey, JSON, Float, UniqueConstraint
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


class ServerRealm(Base):
    """服（一个可独立运营的服务单元）—— 面板可以同时运营多个服

    一个服 = 一套独立对外提供播放的服务：

    - **内容**：该服的媒体库（``emby_libraries.realm_id``）与存储挂载（``storage_mounts.realm_id``）；
    - **卖什么**：该服的套餐（``subscription_plans.realm_id``）；
    - **卖给谁**：该服的订阅（``user_subscriptions.realm_id``）——同一个用户可以在多个服各有一份订阅；
    - **谁来放**：该服的服务器记录（``remote_servers.realm_id``，kind=ea）。
      同一个服可以部署到多台机器上（每台一个 EA，各有自己的 ``node_key``）同时出流。

    面板顶部的「当前服」决定后台各页默认在看哪个服（``SystemConfig["active_realm_id"]``）。
    升级上来的老部署会自动回填出一个默认服（``slug='main'``），行为与单服时完全一致。

    **接入方式（``access_mode``）**：一个面板可以同时运营两种服——

    - ``paid``（付费服，缺省）：需要生效中的订阅才能播放，卖套餐、走付费墙；
    - ``free``（公益服）：免费开放，**不需要订阅**即可播放全库内容。公益服一般靠
      注册/邀请引流，用 ``access_note`` 写清规则（限设备、禁止下载、禁止转卖…），
      并用 ``allow_download`` 关掉下载以保护资源与带宽。

    两种服的判定统一收口在 ``backend/subscriptions.py``（``can_play`` /
    ``ensure_download_allowed``）：升级上来的老服没有这个字段值时按 ``paid`` 处理，
    行为与升级前完全一致。
    """

    __tablename__ = 'server_realms'

    __table_args__ = (
        Index('idx_realm_slug', 'slug'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), unique=True, nullable=False)
    # 稳定标识：写进 EA 的 REALM 环境变量、也用于排查（改名不影响它）
    slug = Column(String(40), unique=True, nullable=False)
    # 该服对外的 Emby 地址（用户端账号卡用；留空则回退全局 EMBY_PUBLIC_URL）
    url = Column(String(500), default='')
    description = Column(String(300), default='')
    # v2.7.0 公益服：paid（需要订阅）/ free（免费开放）；空值按 paid 处理
    access_mode = Column(String(10), default='paid')
    # 公益服规则/说明（用户端展示，也作为付费墙与下载拦截的提示文案）
    access_note = Column(String(500), default='')
    # 该服下载策略：None=跟随全局（公益服默认禁止）/ True=允许 / False=禁止
    allow_download = Column(Boolean, nullable=True, default=None)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class RemoteServer(Base):
    """已添加的服务器（面板可以加多台，每类里挑一台作为「当前使用」）

    四类：

    - ``ea``：本项目自带的 Emby API（EA，分离部署的后端服）。激活后同步写回
      ``emby_managed_*`` 配置，现有的网关闸门 / 挂载体检 / 客户端指引全部照旧生效。
    - ``emby``：已有的第三方 Emby / Jellyfin。激活后同步写回 ``emby_external_*``。
    - ``moviepilot``：MoviePilot。求片批准后可一键提交为它的订阅（它自己去搜索与下载）。
    - ``qbittorrent``：qBittorrent。有磁力/种子链接时可直接交给它下载。

    ``config`` 存类型相关字段（JSON 文本），密钥类字段永不出接口（见 ``servers.mask_config``）。
    同一类型只能有一行 ``is_active``：由激活接口保证，避免出现「谁是当前入口」的歧义。
    **同一类型 + 同一个服** 只能有一行 ``is_active``（见 ``servers.activate``）。
    """

    __tablename__ = 'remote_servers'

    __table_args__ = (
        Index('idx_remote_server_kind', 'kind'),
        Index('idx_remote_server_realm', 'realm_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), unique=True, nullable=False)
    kind = Column(String(20), nullable=False)  # ea / emby / moviepilot / qbittorrent
    # 属于哪个服：每台 EA 只服务它所属服的内容与订阅（见 backend/realms.py）
    realm_id = Column(Integer, ForeignKey('server_realms.id'), nullable=True)
    # 节点标识：EA 启动时用环境变量 NODE_KEY 认领这条记录（见 emby_server/nodes.py）。
    # 只有 EA 需要它——它决定「这台机器负责哪些媒体库、只提供哪些内容」。
    node_key = Column(String(60), unique=True, nullable=True)
    url = Column(String(500), nullable=False)
    # 类型相关配置（JSON 文本）：api_key / username / password / savepath 等
    config = Column(Text, default='{}')
    is_enabled = Column(Boolean, default=True)
    # 同一类型里的「当前使用」：EA / Emby 会同步到 emby_active_mode 等旧配置键
    is_active = Column(Boolean, default=False)
    remark = Column(String(300), default='')
    # 最近一次连接测试结果（仅展示，不参与鉴权判断）
    last_checked_at = Column(DateTime)
    last_check_ok = Column(Boolean)
    last_check_message = Column(String(300))
    created_at = Column(DateTime, default=datetime.now)
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
    points = Column(Integer, default=0)  # 积分余额（签到/邀请返利/兑换/充值）

    # 自建 Emby 凭据（完全自建模式下，Emby 客户端用此账号密码登录）
    emby_username = Column(String(64), unique=True, nullable=True)
    emby_password = Column(String(128), nullable=True)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TelegramUser(Base):
    """Telegram 用户表（从主项目迁移）"""
    __tablename__ = 'telegram_users'

    __table_args__ = (
        Index('idx_tg_id', 'id'),
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
    # 属于哪个服：套餐一个服一个（见 ServerRealm）。同一套餐只卖给该服的用户。
    realm_id = Column(Integer, ForeignKey('server_realms.id'), nullable=True)
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    realm = relationship("ServerRealm")


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
    # 订阅属于哪个服：决定它能在哪个服的 EA 上播放（见 backend/subscriptions.py）。
    # 同一个用户可以在多个服各有一份互不影响的订阅。
    realm_id = Column(Integer, ForeignKey('server_realms.id'), nullable=True)
    start_date = Column(DateTime, default=datetime.now)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(20), default='active')  # active, expired, cancelled
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    plan = relationship("SubscriptionPlan")
    user = relationship("WebUser")
    realm = relationship("ServerRealm")


class SubscriptionReminder(Base):
    """订阅到期提醒的发送记录（去重表）

    「到期前 7/3/1 天提醒续费」这个任务会周期性重复执行，**没有这张表就会反复提醒同一个人**。
    每条（订阅 × 档位）只允许一行：``kind`` 是 ``7d`` / ``3d`` / ``1d``，
    以及到期那一刻的一次 ``expired``。写入成功即代表已发过，不再重发。
    """
    __tablename__ = 'subscription_reminders'

    __table_args__ = (
        UniqueConstraint('subscription_id', 'kind', name='uq_sub_reminder_kind'),
        Index('idx_sub_reminder_sub', 'subscription_id'),
        Index('idx_sub_reminder_time', 'sent_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey('user_subscriptions.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    # 冗余存一份归属服：结算/排查时不必再回查订阅行
    realm_id = Column(Integer, ForeignKey('server_realms.id'), nullable=True)
    kind = Column(String(20), nullable=False)  # 7d / 3d / 1d / expired
    sent_at = Column(DateTime, default=datetime.now)


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
    status = Column(String(20), default='pending')  # pending / paid / refunded / closed
    payment_url = Column(String(500))
    paid_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    # 关单（未支付订单作废）与退款（已支付订单冲正）的留痕。
    # 退款必须留下原因与冲正额度：客服对账、争议时这是唯一的依据。
    closed_at = Column(DateTime)
    refunded_at = Column(DateTime)
    refund_reason = Column(String(255))
    refunded_points = Column(Integer, default=0)  # 实际冲正给该用户的积分数（正数=扣回）
    # 用优惠券时的快照：列表价、优惠金额、核销记录（退款时要把额度还回去）
    list_price = Column(Numeric(10, 2), default=0)
    discount_amount = Column(Numeric(10, 2), default=0)
    coupon_usage_id = Column(Integer, ForeignKey('coupon_usages.id'), nullable=True)

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
    status = Column(String(20), default='pending')  # pending / paid / refunded / closed
    payment_url = Column(String(500))
    paid_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    # 履约时记下「这条订单开出了哪份订阅、发了多少天」：退款要按这笔回滚天数。
    # 不记就只能猜（用户可能同时有别的来源的天数），退款就会多扣或少扣。
    subscription_id = Column(Integer, ForeignKey('user_subscriptions.id'), nullable=True)
    days_granted = Column(Integer, default=0)
    closed_at = Column(DateTime)
    refunded_at = Column(DateTime)
    refund_reason = Column(String(255))
    list_price = Column(Numeric(10, 2), default=0)
    discount_amount = Column(Numeric(10, 2), default=0)
    coupon_usage_id = Column(Integer, ForeignKey('coupon_usages.id'), nullable=True)

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
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=True)
    admin_id = Column(Integer, ForeignKey('admin_users.id'), nullable=True)
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


# ==================== 经济系统（签到/积分/兑换码） ====================

class CheckinRecord(Base):
    """每日签到记录表"""
    __tablename__ = 'checkin_records'

    __table_args__ = (
        Index('idx_checkin_user_date', 'user_id', 'checkin_date', unique=True),
        Index('idx_checkin_date', 'checkin_date'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False, index=True)
    checkin_date = Column(DateTime, nullable=False)  # 签到日期（零点）
    points_awarded = Column(Integer, default=0)
    streak = Column(Integer, default=1)  # 连续签到天数
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser")


class PointsLog(Base):
    """积分流水表（收入/支出台账）"""
    __tablename__ = 'points_logs'

    __table_args__ = (
        Index('idx_points_user', 'user_id'),
        Index('idx_points_type', 'type'),
        Index('idx_points_time', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # 正数收入 / 负数支出
    balance_after = Column(Integer, default=0)  # 变动后余额
    type = Column(String(30), default='system')  # checkin, invite, invitee, rebate, exchange, recharge, admin_grant, admin_deduct
    description = Column(String(255))
    ref_id = Column(String(64))  # 关联对象（订单号/兑换码等）
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser")


class ExchangeCode(Base):
    """兑换码表（积分兑换 / 订阅兑换）"""
    __tablename__ = 'exchange_codes'

    __table_args__ = (
        Index('idx_exchange_code', 'code'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    type = Column(String(20), default='points')  # points 积分 / subscription 订阅
    points_value = Column(Integer, default=0)  # points 型：兑换积分数
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=True)  # subscription 型：套餐
    duration_days = Column(Integer, default=0)  # subscription 型：时长
    max_uses = Column(Integer, default=1)
    use_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    note = Column(String(255))
    used_by = Column(String(500))  # 逗号分隔的 WebUser.id 审计
    expires_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey('web_users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    plan = relationship("SubscriptionPlan")


# ==================== 邀请系统 ====================

class RegistrationCode(Base):
    """卡码表（注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码）

    借鉴 twilight-kotomi 的 RegCode：一份数据结构靠 code_type 区分用途，
    days 表示授予或叠加的会员天数，is_decoy 为蜜罐码，target_username 为指名码。
    本项目的会员口径以 UserSubscription(end_date) 为单一事实来源，
    因此卡码的「天数」最终落到订阅上（无生效订阅则新建，有则叠加）。
    """
    __tablename__ = 'registration_codes'

    __table_args__ = (
        Index('idx_reg_code', 'code'),
        Index('idx_reg_code_type', 'code_type'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    max_uses = Column(Integer, default=1)
    use_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    note = Column(String(255))
    used_by = Column(String(500))  # 逗号分隔的 WebUser.id 审计
    expires_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey('web_users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    # 属于哪个服：这张卡码开出来的是那个服的会员（见 economy.redeem_registration_code）
    realm_id = Column(Integer, ForeignKey('server_realms.id'), nullable=True)
    # ===== 卡码体系（借鉴 twilight-kotomi 的 RegCode）=====
    code_type = Column(Integer, default=1)  # 1 注册码 / 2 续期码 / 3 白名单码
    days = Column(Integer, default=30)  # 授予或叠加的会员天数；-1 表示永久
    is_decoy = Column(Boolean, default=False)  # 诱饵码（蜜罐：使用即封禁账号）
    target_username = Column(String(50))  # 指名码：非空时仅限该用户名使用
    source = Column(String(20), default='admin')  # admin 管理员发放 / invite 邀请体系生成


class UserDevice(Base):
    """用户设备（第三方播放器登录设备，用于设备上限与设备审查）

    借鉴 twilight-kotomi 的设备限制：按 user_id + device_id 唯一，
    记录客户端名称/版本/IP 与首末次出现时间，超限时可拒绝新设备或踢最久未使用者。
    """
    __tablename__ = 'user_devices'

    __table_args__ = (
        UniqueConstraint('user_id', 'device_id', name='uq_device_user_device'),
        Index('idx_device_user', 'user_id'),
        Index('idx_device_last_seen', 'last_seen_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    device_id = Column(String(128), nullable=False)
    name = Column(String(100))  # 设备名（X-Emby-Authorization Device）
    client = Column(String(100))  # 客户端（Infuse / Forward / SenPlayer ...）
    app_version = Column(String(50))
    ip = Column(String(64))
    first_seen_at = Column(DateTime, default=datetime.now)
    last_seen_at = Column(DateTime, default=datetime.now)
    is_blocked = Column(Boolean, default=False)

    user = relationship("WebUser")


class LoginLog(Base):
    """登录与账号安全日志

    记录登录成功/失败、设备超限被拒、诱饵码触发封禁等事件，
    供管理后台风控审查（reason 区分事件类型）。
    """
    __tablename__ = 'login_logs'

    __table_args__ = (
        Index('idx_loginlog_user', 'user_id'),
        Index('idx_loginlog_time', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=True)
    username = Column(String(64))
    ip = Column(String(64))
    user_agent = Column(String(300))
    success = Column(Boolean, default=True)
    reason = Column(String(100))  # portal_login / emby_login / device_limit / decoy_code ...
    detail = Column(String(255))
    # IP 归属地（能力：IP 与地理位置）；未配置提供方时为空——由 authlog 在写入时填
    region = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)


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
        # 一个被邀请人只能有一条关系记录：并发重复发奖的最后一道门
        Index('idx_inv_invitee', 'invitee_id', unique=True),
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


# ==================== 优惠券 ====================

class CouponCode(Base):
    """优惠券（购买时抵扣，v2.10.0）

    与兑换码（`ExchangeCode`）不是一回事：兑换码是「不花钱直接拿东西」，
    优惠券是「付费时打折 / 减钱」——钱还是要走支付网关，只是单价变了。

    **使用次数是预订制的**：下单时就占额度（`CouponUsage.status='reserved'`），
    支付成功转 `consumed`，订单被关掉/退款则 `released` 并把额度还回去。
    只在付款成功时计数的话，一串未支付订单会同时绕过限额，付完款全都拿到折扣。
    """
    __tablename__ = 'coupon_codes'

    __table_args__ = (
        UniqueConstraint('code', name='uq_coupon_code'),
        Index('idx_coupon_kind', 'kind'),
        Index('idx_coupon_active', 'is_active'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    # 适用范围：subscription 只能买会员 / recharge 只能充值 / all 两者皆可
    kind = Column(String(20), default='all')
    # percent 百分比（value=85 即 85 折、实付 85%）；fixed 直接减免（value=单位元）
    discount_type = Column(String(20), default='percent')
    value = Column(Integer, default=0)
    # 满多少可用（0 = 不设门槛）；百分比券的封顶减免（0 = 不封顶）
    min_amount = Column(Numeric(10, 2), default=0)
    max_discount = Column(Numeric(10, 2), default=0)
    # 只对某个服的套餐可用（多服运营下避免 A 服的券在 B 服用）
    realm_id = Column(Integer, ForeignKey('server_realms.id'), nullable=True)
    max_uses = Column(Integer, default=0)      # 总次数上限，0 = 不限
    use_count = Column(Integer, default=0)     # 当前占用（reserved + consumed）
    per_user_limit = Column(Integer, default=1)  # 每人最多用几次，0 = 不限
    valid_from = Column(DateTime)
    valid_until = Column(DateTime)
    is_active = Column(Boolean, default=True)
    note = Column(String(255))
    created_by = Column(Integer, ForeignKey('web_users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    realm = relationship("ServerRealm")


class CouponUsage(Base):
    """优惠券核销记录：一笔优惠订单一行（预订 → 消费 / 释放）

    `paid_amount` / `list_price` 快照下来：套餐改价后，历史订单仍要能解释「当时到底按多少钱算的」。
    """
    __tablename__ = 'coupon_usages'

    __table_args__ = (
        UniqueConstraint('order_id', name='uq_coupon_usage_order'),
        Index('idx_coupon_usage_user', 'user_id'),
        Index('idx_coupon_usage_coupon', 'coupon_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    coupon_id = Column(Integer, ForeignKey('coupon_codes.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    order_id = Column(String(64), nullable=False)
    kind = Column(String(20))
    # reserved 占了额度但还没付 / consumed 已付款 / released 订单关掉或退款、额度已还
    status = Column(String(20), default='reserved')
    list_price = Column(Numeric(10, 2), default=0)
    discount_amount = Column(Numeric(10, 2), default=0)
    paid_amount = Column(Numeric(10, 2), default=0)
    created_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime)

    coupon = relationship("CouponCode")
    user = relationship("WebUser")


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
    # 求的是哪个服的片：入库后进的是该服的媒体库
    realm_id = Column(Integer, ForeignKey('server_realms.id'), nullable=True)
    # 转交外部服务的结果：moviepilot（已提交订阅）/ qbittorrent（已交给下载器加种）
    push_target = Column(String(20))
    push_status = Column(String(20))  # ok / failed
    push_message = Column(String(300))
    pushed_at = Column(DateTime)
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
    # 多服运营
    "ServerRealm",
    # 用户
    "WebUser", "TelegramUser",
    # 订阅和支付
    "SubscriptionPlan", "UserSubscription", "SubscriptionReminder",
    "RechargePackage", "RechargeOrder", "SubscriptionOrder",
    # Emby
    "EmbyServer", "PlanServerRelation", "UserEmbyAccount", "EmbySession", "MovieBookmark",
    # 工单
    "Ticket", "TicketMessage",
    # 公告和活动
    "Announcement", "ThemeActivity", "ThemeActivityProgress",
    # 经济系统
    "CheckinRecord", "PointsLog", "ExchangeCode",
    # 邀请
    "InvitationCode", "InvitationRecord",
    # 优惠券
    "CouponCode", "CouponUsage",
    # 求片
    "MovieRequest",
    # 监控
    "SystemMetric", "AlertRule", "Alert",
]
