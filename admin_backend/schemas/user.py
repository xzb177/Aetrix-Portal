"""
用户管理数据模型
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class UserListItem(BaseModel):
    """用户列表项"""
    tg_id: int
    username: Optional[str] = None
    emby_account: Optional[str] = None
    is_vip: bool
    points: Optional[int] = 0
    bank_points: Optional[int] = 0
    attack: Optional[int] = 0
    total_watch_minutes: int = 0
    total_checkin_days: int = 0
    last_checkin_date: Optional[datetime] = None
    watch_streak: int = 0

    class Config:
        from_attributes = True


class UserDetail(BaseModel):
    """用户详情"""
    # 基本信息
    tg_id: int
    username: Optional[str] = None
    emby_account: Optional[str] = None
    is_vip: bool

    # 魔力系统
    points: Optional[int] = 0
    bank_points: Optional[int] = 0
    accumulated_interest: Optional[int] = 0
    total_earned: Optional[int] = 0
    total_spent: Optional[int] = 0

    # 战力系统
    attack: Optional[int] = 0
    weapon: Optional[str] = None
    breakthrough_level: Optional[int] = 0

    # 签到系统
    consecutive_checkin: Optional[int] = 0
    total_checkin_days: Optional[int] = 0
    last_checkin_date: Optional[datetime] = None

    # Emby 观影
    daily_watch_minutes: Optional[int] = 0
    total_watch_minutes: Optional[int] = 0
    watch_streak: Optional[int] = 0
    total_watch_checkin_days: Optional[int] = 0
    max_watch_streak: Optional[int] = 0
    watch_checkin_today: Optional[bool] = False

    # 观影宝箱
    early_bird_wins: Optional[int] = 0

    # 成就
    achievements: Optional[str] = ""

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """用户更新"""
    emby_account: Optional[str] = None
    is_vip: Optional[bool] = None
    points: Optional[int] = None
    bank_points: Optional[int] = None
    attack: Optional[int] = None
    total_watch_minutes: Optional[int] = None
    watch_streak: Optional[int] = None


class UserStats(BaseModel):
    """用户统计"""
    total_users: int
    vip_users: int
    new_users_today: int
    active_users_week: int
    total_watch_minutes: int
    total_checkin_days: int


class UserSearchRequest(BaseModel):
    """用户搜索请求"""
    keyword: Optional[str] = None
    is_vip: Optional[bool] = None
    has_emby: Optional[bool] = None
    sort_by: Optional[str] = "tg_id"
    sort_order: Optional[str] = "desc"
