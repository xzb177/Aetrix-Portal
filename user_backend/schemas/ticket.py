"""
工单相关 Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class TicketResponse(BaseModel):
    """工单响应"""
    id: int
    title: str
    category: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TicketDetailResponse(BaseModel):
    """工单详情响应"""
    id: int
    title: str
    category: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: List['TicketMessageResponse'] = []

    class Config:
        from_attributes = True


class TicketMessageResponse(BaseModel):
    """工单消息响应"""
    id: int
    message: str
    attachments: Optional[List[str]] = None
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CreateTicket(BaseModel):
    """创建工单"""
    title: str = Field(..., min_length=1, max_length=200, description="工单标题")
    category: str = Field("other", description="分类: technical, billing, feature, other")
    priority: str = Field("medium", description="优先级: low, medium, high, urgent")
    message: str = Field(..., min_length=1, description="问题描述")
    attachments: Optional[List[str]] = Field(None, description="附件 URL 列表")


class CreateTicketMessage(BaseModel):
    """创建工单消息"""
    message: str = Field(..., min_length=1, description="消息内容")
    attachments: Optional[List[str]] = None


class UpdateTicketStatus(BaseModel):
    """更新工单状态"""
    status: str = Field(..., description="状态: open, replied, resolved, closed")


class UploadAttachmentResponse(BaseModel):
    """上传附件响应"""
    url: str
    filename: str


# 管理后台用
class AdminTicketListResponse(BaseModel):
    """管理员工单列表响应"""
    id: int
    user_id: int
    username: str
    title: str
    category: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
