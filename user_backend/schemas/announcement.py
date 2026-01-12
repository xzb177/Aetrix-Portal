"""
公告相关 Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AnnouncementResponse(BaseModel):
    """公告响应"""
    id: int
    title: str
    content: str
    type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreateAnnouncement(BaseModel):
    """创建公告"""
    title: str = Field(..., min_length=1, max_length=200, description="公告标题")
    content: str = Field(..., min_length=1, description="公告内容")
    type: str = Field("system", description="公告类型: system, activity, urgent")


class UpdateAnnouncement(BaseModel):
    """更新公告"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = None
    type: Optional[str] = None
    is_active: Optional[bool] = None
