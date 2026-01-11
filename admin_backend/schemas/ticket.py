"""
工单相关数据模型
"""
from pydantic import BaseModel, Field


class TicketMessageRequest(BaseModel):
    """回复工单请求"""
    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="回复内容"
    )
    attachments: str = Field(
        None,
        max_length=1000,
        description="附件链接（可选）"
    )


class TicketStatusUpdateRequest(BaseModel):
    """更新工单状态请求"""
    status: str = Field(
        ...,
        pattern="^(open|replied|resolved|closed)$",
        description="工单状态: open, replied, resolved, closed"
    )


class AnnouncementCreateRequest(BaseModel):
    """创建公告请求"""
    title: str = Field(..., min_length=1, max_length=200, description="公告标题")
    content: str = Field(..., min_length=1, max_length=5000, description="公告内容")
    type: str = Field("system", pattern="^(system|maintenance|event)$", description="公告类型")
    is_active: bool = Field(True, description="是否启用")


class InvitationConfigUpdateRequest(BaseModel):
    """更新邀请配置请求"""
    invitation_enabled: bool = Field(None, description="是否启用邀请系统")
    invitation_reward_points: int = Field(None, ge=0, le=10000, description="邀请者奖励积分")
    invitation_invitee_reward_points: int = Field(None, ge=0, le=10000, description="被邀请者奖励积分")
