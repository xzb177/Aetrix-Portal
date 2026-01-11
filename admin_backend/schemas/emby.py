"""
Emby 数据管理模型
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class EmbyBookmarkItem(BaseModel):
    """Emby 收藏项"""
    id: int
    user_id: int
    item_id: str
    item_name: str
    item_type: str
    bookmark_type: str
    rating: Optional[int] = None
    notes: str
    created_at: datetime

    class Config:
        from_attributes = True


class EmbyBookmarkCreate(BaseModel):
    """创建收藏"""
    user_id: int
    item_id: str
    item_name: str
    item_type: str = "Movie"
    bookmark_type: str  # want/watched/favorite


class WatchStats(BaseModel):
    """观影统计"""
    total_users: int
    users_with_emby: int
    total_watch_minutes: int
    avg_watch_minutes: int
    daily_active_users: int
    weekly_active_users: int
    top_watchers: list


class EmbyItem(BaseModel):
    """Emby 媒体项"""
    item_id: str
    name: str
    year: Optional[str] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    genres: list = []
    rating: Optional[float] = None
    runtime: Optional[int] = None
    premiere_date: Optional[str] = None


class RecentPlayItem(BaseModel):
    """最近播放项"""
    item_id: str
    name: str
    type: str
    series_name: Optional[str] = None
    season_id: Optional[str] = None
    primary_image_tag: Optional[str] = None
    thumb_image_tag: Optional[str] = None
    backdrop_image_tag: Optional[str] = None
    production_year: Optional[int] = None
    community_rating: Optional[float] = None
    run_time_ticks: Optional[int] = None
    date_created: Optional[str] = None
    played_percentage: Optional[float] = None
    last_played_date: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None


class ManualPushRequest(BaseModel):
    """手动推送请求"""
    item_id: str = Field(..., description="Emby 媒体 ID")
    message: Optional[str] = Field(None, description="自定义推送消息")


class UnbindEmbyRequest(BaseModel):
    """解绑 Emby 请求"""
    user_id: int = Field(..., description="用户 Telegram ID")
