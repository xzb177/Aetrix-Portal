"""
求片相关 Schemas
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class CreateMovieRequest(BaseModel):
    """创建求片请求"""
    movie_name: str
    year: Optional[str] = None
    type: Optional[str] = "movie"
    note: Optional[str] = None
    tmdb_id: Optional[str] = None
    poster_url: Optional[str] = None


class MovieRequestResponse(BaseModel):
    """求片请求响应"""
    id: int
    movie_name: str
    year: Optional[str] = None
    type: Optional[str] = None
    note: Optional[str] = None
    status: str
    admin_note: Optional[str] = None
    emby_item_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    poster_url: Optional[str] = None
    subscriber_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class MovieRequestGalleryResponse(BaseModel):
    """海报墙求片响应"""
    id: int
    movie_name: str
    year: Optional[str] = None
    type: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    subscriber_count: int = 0
    priority: int = 0
    status: str
    tmdb_id: Optional[str] = None
    overview: Optional[str] = None
    vote_average: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TmdbSearchResult(BaseModel):
    """TMDB 搜索结果"""
    id: int
    tmdb_id: int
    media_type: str  # movie, series
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    poster_url_large: Optional[str] = None
    backdrop_url: Optional[str] = None
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
    genre_ids: List[int] = []


class GalleryStatsResponse(BaseModel):
    """海报墙统计响应"""
    total: int
    pending: int
    approved: int
    completed: int
    by_type: dict


class UserRequestLimitResponse(BaseModel):
    """用户求片限制响应"""
    limit: int  # 用户可提交的求片总数
    used: int  # 已使用的次数
    remaining: int  # 剩余次数
    period: str  # 限制周期: total, monthly, weekly
    is_vip: bool  # 是否是 VIP
    vip_bonus: int  # VIP 额外次数
