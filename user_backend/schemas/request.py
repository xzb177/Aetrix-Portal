"""
求片相关 Schemas
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CreateMovieRequest(BaseModel):
    """创建求片请求"""
    movie_name: str
    year: Optional[str] = None
    type: Optional[str] = "movie"
    note: Optional[str] = None


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
    created_at: datetime

    class Config:
        from_attributes = True
