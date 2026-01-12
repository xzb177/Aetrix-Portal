"""
活动管理数据模型
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ActivityCreate(BaseModel):
    """创建活动"""
    name: str = Field(..., min_length=1, description="活动名称")
    description: Optional[str] = Field(None, description="活动描述")
    activity_type: str = Field(..., description="活动类型: genre/director/series/custom")
    filter_genre: Optional[str] = Field(None, description="类型过滤")
    filter_director: Optional[str] = Field(None, description="导演过滤")
    filter_series: Optional[str] = Field(None, description="系列过滤")
    target_count: int = Field(5, ge=1, description="目标数量")
    reward_mp: int = Field(100, ge=0, description="奖励MP")
    reward_title: Optional[str] = Field(None, description="奖励称号")
    start_date: Optional[datetime] = Field(None, description="开始时间")
    end_date: Optional[datetime] = Field(None, description="结束时间")


class ActivityUpdate(BaseModel):
    """更新活动"""
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    target_count: Optional[int] = None
    reward_mp: Optional[int] = None
    reward_title: Optional[str] = None
    end_date: Optional[datetime] = None


class ActivityListItem(BaseModel):
    """活动列表项"""
    id: int
    name: str
    description: Optional[str] = None
    activity_type: str
    target_count: int
    reward_mp: int
    reward_title: Optional[str] = None
    is_active: bool
    start_date: datetime
    end_date: Optional[datetime] = None
    participant_count: int = 0
    completed_count: int = 0

    class Config:
        from_attributes = True


class ActivityDetail(ActivityListItem):
    """活动详情"""
    filter_genre: Optional[str] = None
    filter_director: Optional[str] = None
    filter_series: Optional[str] = None


class ActivityProgressItem(BaseModel):
    """活动进度项"""
    id: int
    activity_id: int
    user_id: int
    progress: int
    watched_items: str
    completed: bool
    reward_claimed: bool
    updated_at: datetime

    class Config:
        from_attributes = True
