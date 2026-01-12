"""
统计分析数据模型
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class StatPoint(BaseModel):
    """统计点"""
    date: str
    value: int


class OverviewStats(BaseModel):
    """概览统计"""
    # 用户统计
    total_users: int
    vip_users: int
    new_users_today: int
    active_users_week: int

    # 观影统计
    total_watch_minutes: int
    total_watch_hours: int
    avg_daily_watch_minutes: int
    watch_streak_users: int

    # 签到统计
    total_checkin_days: int
    checkin_today: int
    consecutive_checkin_top: int

    # 经济统计
    total_mp_issued: int
    total_mp_in_bank: int
    total_mp_in_wallet: int


class TopUser(BaseModel):
    """排行榜用户"""
    tg_id: int
    username: Optional[str] = None
    emby_account: Optional[str] = None
    value: int


class RankingList(BaseModel):
    """排行榜"""
    watch_users: List[TopUser]  # 观影时长排行
    checkin_users: List[TopUser]  # 签到天数排行
    power_users: List[TopUser]  # 战力排行
    wealth_users: List[TopUser]  # 财富排行


class TrendData(BaseModel):
    """趋势数据"""
    watch_trend: List[StatPoint]  # 观影趋势（最近7天）
    checkin_trend: List[StatPoint]  # 签到趋势（最近7天）
    new_user_trend: List[StatPoint]  # 新用户趋势（最近7天)


class AdminLogItem(BaseModel):
    """管理日志项"""
    id: int
    admin_username: str
    action: str
    resource: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True
