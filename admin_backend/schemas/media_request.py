"""
求片管理相关数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional


class MovieRequestStatusUpdateRequest(BaseModel):
    """更新求片状态请求"""
    status: str = Field(
        ...,
        pattern="^(pending|approved|completed|rejected)$",
        description="求片状态: pending-待处理, approved-已批准, completed-已完成, rejected-已拒绝"
    )
    admin_note: Optional[str] = Field(None, max_length=1000, description="管理员备注")
    status_remark: Optional[str] = Field(None, max_length=500, description="状态说明")
    emby_item_id: Optional[str] = Field(None, max_length=100, description="Emby 媒体 ID")
    poster_url: Optional[str] = Field(None, max_length=500, description="海报 URL")
    tmdb_id: Optional[str] = Field(None, max_length=50, description="TMDB ID")


class MovieRequestUpdateRequest(BaseModel):
    """更新求片请求"""
    movie_name: Optional[str] = Field(None, min_length=1, max_length=255, description="影片名称")
    year: Optional[str] = Field(None, max_length=10, description="年份")
    type: Optional[str] = Field(None, max_length=50, description="类型")
    note: Optional[str] = Field(None, max_length=1000, description="用户备注")
