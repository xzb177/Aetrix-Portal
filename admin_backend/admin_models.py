"""
本地数据模型 - 匹配实际数据库结构
与主项目 models.py 解耦
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class UserBinding(Base):
    """用户绑定表 - 匹配实际数据库 schema"""
    __tablename__ = 'bindings'

    # 主键
    tg_id = Column(BigInteger, primary_key=True)

    # 基本信息
    emby_account = Column(String)
    is_vip = Column(Boolean)

    # 游戏数据
    win = Column(Integer)
    lost = Column(Integer)
    points = Column(Integer)
    bank_points = Column(Integer)
    weapon = Column(String)
    attack = Column(Integer)
    intimacy = Column(Integer)
    resonance_count = Column(Integer)

    # 签到相关
    last_checkin = Column(DateTime)
    last_tarot = Column(DateTime)
    total_checkin_days = Column(Integer, default=0)
    consecutive_checkin = Column(Integer, default=0)
    last_checkin_date = Column(DateTime)

    # 每日计数
    daily_chat_count = Column(Integer, default=0)
    daily_forge_count = Column(Integer, default=0)
    daily_tarot_count = Column(Integer, default=0)
    daily_box_count = Column(Integer, default=0)
    daily_gift_count = Column(Integer, default=0)
    daily_duel_count = Column(Integer, default=0)
    daily_presence_points = Column(Integer, default=0)

    # 时间相关
    last_chat_time = Column(DateTime)
    last_duel_date = Column(DateTime)
    last_box_buy_date = Column(DateTime)
    last_wheel_date = Column(DateTime)
    last_win_streak_date = Column(DateTime)
    last_active_time = Column(DateTime)
    last_interest_claimed = Column(DateTime)

    # 连击和幸运
    chat_combo = Column(Integer, default=0)
    lucky_boost = Column(Boolean, default=False)
    shield_active = Column(Boolean, default=False)
    lose_streak = Column(Integer, default=0)
    win_streak = Column(Integer)

    # 额外次数
    extra_tarot = Column(Integer, default=0)
    extra_gacha = Column(Integer, default=0)
    free_forges = Column(Integer, default=0)
    free_forges_big = Column(Integer, default=0)

    # 抽奖相关
    gacha_pity_counter = Column(Integer, default=0)
    forge_pity_counter = Column(Integer, default=0)

    # 成就和物品
    achievements = Column(Text, default='')
    items = Column(Text, default='')

    # 积分统计
    accumulated_interest = Column(Integer, default=0)
    total_earned = Column(Integer)
    total_spent = Column(Integer)
    total_presence_points = Column(Integer, default=0)

    # 任务相关
    daily_tasks = Column(String(100), default='')
    task_progress = Column(String(50), default='')
    task_date = Column(DateTime)
    presence_levels_claimed = Column(String(50), default='')
    wheel_spins_today = Column(Integer, default=0)

    # 塔楼相关
    tower_current_floor = Column(Integer, default=0)
    tower_max_floor = Column(Integer, default=0)
    tower_total_wins = Column(Integer, default=0)
    last_chest_open = Column(DateTime)

    # 突破相关
    breakthrough_level = Column(Integer, default=0)
    breakthrough_exp = Column(Integer, default=0)
    total_mp_spent_breakthrough = Column(Integer, default=0)

    # 观影相关
    daily_watch_minutes = Column(Integer, default=0)
    total_watch_minutes = Column(Integer, default=0)
    last_watch_claimed = Column(DateTime)
    early_bird_wins = Column(Integer, default=0)
    watch_streak = Column(Integer, default=0)
    last_watch_checkin_date = Column(DateTime)
    total_watch_checkin_days = Column(Integer, default=0)
    max_watch_streak = Column(Integer, default=0)
    watch_checkin_today = Column(Boolean, default=False)
    claimed_early_bird_items = Column(Text, default='')
    last_forge_date = Column(DateTime)


class MovieBookmark(Base):
    """电影收藏表"""
    __tablename__ = 'movie_bookmarks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    item_id = Column(String, nullable=False)
    item_name = Column(String)
    item_type = Column(String)
    bookmark_type = Column(String, default='favorite')
    rating = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime)


class ThemeActivity(Base):
    """主题观影活动"""
    __tablename__ = 'theme_activities'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    activity_type = Column(String, nullable=False)  # 实际是 activity_type 不是 theme_type
    filter_genre = Column(String)
    filter_director = Column(String)
    filter_series = Column(String)
    target_count = Column(Integer)
    reward_mp = Column(Integer)
    reward_title = Column(String)
    is_active = Column(Boolean)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    created_at = Column(DateTime)


class ThemeActivityProgress(Base):
    """活动进度"""
    __tablename__ = 'theme_activity_progress'

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    progress = Column(Integer, default=0)
    watched_items = Column(Text, default='')
    completed = Column(Boolean, default=False)
    reward_claimed = Column(Boolean, default=False)
    claimed_at = Column(DateTime)
    updated_at = Column(DateTime)
