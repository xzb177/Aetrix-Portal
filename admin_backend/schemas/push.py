"""
推送管理数据模型
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PushHistoryItem(BaseModel):
    """推送历史项"""
    id: int
    item_id: str
    item_name: str
    poster_url: Optional[str] = None
    pushed_at: datetime

    class Config:
        from_attributes = True


class PushConfig(BaseModel):
    """推送配置"""
    high_quality_push_hour: int = Field(20, ge=0, le=23, description="推送时间（小时）")
    high_quality_rating_threshold: float = Field(6.0, ge=0, le=10, description="评分阈值")
    high_quality_bitrate_threshold: int = Field(20000000, ge=0, description="码率阈值")
    high_quality_min_width: int = Field(1920, ge=0, description="最低分辨率宽度")
    check_interval_minutes: int = Field(30, ge=5, description="检查间隔（分钟）")
    notification_chats: str = Field("", description="通知群组ID（逗号分隔）")


class PushConfigUpdate(BaseModel):
    """推送配置更新"""
    high_quality_push_hour: Optional[int] = None
    high_quality_rating_threshold: Optional[float] = None
    high_quality_bitrate_threshold: Optional[int] = None
    high_quality_min_width: Optional[int] = None
    check_interval_minutes: Optional[int] = None
    notification_chats: Optional[str] = None


class NewReleaseItem(BaseModel):
    """新发布影片"""
    item_id: str
    name: str
    year: Optional[str] = None
    poster_url: Optional[str] = None
    rating: Optional[float] = None
    added_date: Optional[datetime] = None
