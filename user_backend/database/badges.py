"""
徽章系统数据模型
彩蛋功能：身份签名卡 + 徽章系统
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, DateTime, Index, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


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
