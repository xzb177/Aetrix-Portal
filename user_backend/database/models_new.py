"""
创新功能数据库模型
家庭席位 / 观影画像 / 权益包 / 阶梯邀请 / 流失预测 / 智能提醒
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, Float
)
from sqlalchemy.orm import relationship


# ==================== 家庭席位系统 ====================

class FamilySeat(Base):
    """家庭席位主账号"""
    __tablename__ = 'family_seats'

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey('web_users.id'), nullable=False, unique=True)
    plan_type = Column(String(20), default='standard')  # standard(3人) / premium(5人) / elite(8人)
    max_members = Column(Integer, default=3)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    owner = relationship("WebUser")
    members = relationship("FamilyMember", back_populates="family", cascade="all, delete-orphan")


class FamilyMember(Base):
    """家庭子账号"""
    __tablename__ = 'family_members'

    __table_args__ = (
        Index('idx_fm_family', 'family_id'),
        Index('idx_fm_user', 'user_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    family_id = Column(Integer, ForeignKey('family_seats.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    nickname = Column(String(50))
    role = Column(String(20), default='member')  # member / child
    is_active = Column(Boolean, default=True)
    joined_at = Column(DateTime, default=datetime.now)

    family = relationship("FamilySeat", back_populates="members")
    user = relationship("WebUser")


# ==================== 观影旅程画像 ====================

class ViewingProfile(Base):
    """用户观影画像（聚合数据）"""
    __tablename__ = 'viewing_profiles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False, unique=True)

    # 类型偏好 (JSON: {"movie": 45, "series": 30, "anime": 15, ...})
    genre_preferences = Column(JSON, default=dict)
    # 活跃时段 (JSON: {"weekday_evening": 60, "weekend_afternoon": 25, ...})
    active_periods = Column(JSON, default=dict)
    # 设备分布 (JSON: {"android_tv": 50, "ios": 30, "web": 20, ...})
    device_distribution = Column(JSON, default=dict)
    # 弃剧点分析 (JSON: {"avg_drop_episode": 3, "common_drop_reason": "too_slow", ...})
    drop_off_patterns = Column(JSON, default=dict)

    # 统计数据
    total_watch_hours = Column(Float, default=0)
    total_items = Column(Integer, default=0)
    avg_session_minutes = Column(Float, default=0)
    favorite_genres = Column(JSON, default=list)  # ["科幻", "悬疑", "动作"]
    last_active_at = Column(DateTime)

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("WebUser")


# ==================== 权益包系统 ====================

class AddOnPackage(Base):
    """可选叠加权益包"""
    __tablename__ = 'add_on_packages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    package_type = Column(String(50), nullable=False)  # priority_request / exclusive_route / 4k_quality / family_seat
    price = Column(Float, nullable=False)  # 价格（元/月）
    duration_days = Column(Integer, default=30)
    features = Column(JSON, default=dict)  # {"max_priority": 5, "route_ids": [1,2]}
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class UserAddOn(Base):
    """用户已购买的权益包"""
    __tablename__ = 'user_add_ons'

    __table_args__ = (
        Index('idx_uao_user', 'user_id'),
        Index('idx_uao_status', 'status'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    package_id = Column(Integer, ForeignKey('add_on_packages.id'), nullable=False)
    status = Column(String(20), default='active')  # active / expired / cancelled
    start_date = Column(DateTime, default=datetime.now)
    end_date = Column(DateTime, nullable=False)
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser")
    package = relationship("AddOnPackage")


# ==================== 阶梯邀请系统 ====================

class TieredInviteReward(Base):
    """阶梯邀请奖励配置"""
    __tablename__ = 'tiered_invite_rewards'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tier = Column(Integer, nullable=False, unique=True)  # 阶梯等级 1/2/3
    required_invites = Column(Integer, nullable=False)  # 需要邀请人数
    reward_type = Column(String(50), nullable=False)  # badge / subscription_days / priority_boost
    reward_value = Column(JSON, nullable=False)  # {"days": 7} / {"badge_id": "super_inviter"}
    description = Column(String(200))
    is_active = Column(Boolean, default=True)


class UserInviteProgress(Base):
    """用户邀请进度"""
    __tablename__ = 'user_invite_progress'

    user_id = Column(Integer, ForeignKey('web_users.id'), primary_key=True)
    total_invites = Column(Integer, default=0)
    completed_tiers = Column(JSON, default=list)  # [1, 2] 已完成的阶梯
    last_invite_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("WebUser")


# ==================== 流失预测 ====================

class ChurnRisk(Base):
    """用户流失风险记录"""
    __tablename__ = 'churn_risks'

    __table_args__ = (
        Index('idx_churn_user', 'user_id'),
        Index('idx_churn_risk', 'risk_level'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    risk_level = Column(String(20), default='low')  # low / medium / high / critical
    risk_score = Column(Integer, default=0)  # 0-100
    factors = Column(JSON, default=list)  # ["inactive_7days", "no_login_3days", ...]
    action_taken = Column(String(100))  # "sent_trial_day" / "sent_discount" / null
    action_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("WebUser")


# ==================== 智能续费提醒 ====================

class SmartReminder(Base):
    """智能续费提醒配置"""
    __tablename__ = 'smart_reminders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    reminder_type = Column(String(50), nullable=False)  # content_update / expiry_approaching / viewing_streak
    trigger_condition = Column(JSON, nullable=False)  # {"days_before_expiry": 1, "content_series": "xxx"}
    message_template = Column(Text)
    is_active = Column(Boolean, default=True)
    last_sent_at = Column(DateTime)
    send_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("WebUser")


# ==================== Emby 服务器健康记录 ====================

class EmbyHealthLog(Base):
    """Emby 服务器健康检查日志"""
    __tablename__ = 'emby_health_logs'

    __table_args__ = (
        Index('idx_ehl_server', 'server_id'),
        Index('idx_ehl_time', 'checked_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey('emby_servers.id'), nullable=False)
    status = Column(String(20), nullable=False)  # healthy / degraded / down
    response_time_ms = Column(Integer)
    active_sessions = Column(Integer, default=0)
    error_message = Column(Text)
    checked_at = Column(DateTime, default=datetime.now)

    server = relationship("EmbyServer")


class FailoverEvent(Base):
    """故障转移事件记录"""
    __tablename__ = 'failover_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_server_id = Column(Integer, ForeignKey('emby_servers.id'))
    to_server_id = Column(Integer, ForeignKey('emby_servers.id'))
    reason = Column(String(200))
    affected_users = Column(Integer, default=0)
    auto_resolved = Column(Boolean, default=False)
    compensation_days = Column(Integer, default=0)  # 补偿天数
    created_at = Column(DateTime, default=datetime.now)

    from_server = relationship("EmbyServer", foreign_keys=[from_server_id])
    to_server = relationship("EmbyServer", foreign_keys=[to_server_id])
