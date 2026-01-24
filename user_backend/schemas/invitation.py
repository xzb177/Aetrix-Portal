"""
邀请相关 Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class InvitationCodeResponse(BaseModel):
    """邀请码响应"""
    id: int
    code: str
    use_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class InvitationStatsResponse(BaseModel):
    """邀请统计响应"""
    total_invitations: int
    total_rewards: int
    my_code: str
    use_count: int = 0  # 邀请码使用次数


class InvitationRecordResponse(BaseModel):
    """邀请记录响应"""
    id: int
    invitee_username: str
    reward_points: int
    conversion_status: str = 'registered'  # registered/paid/subscribed
    first_payment_at: Optional[datetime] = None
    first_subscription_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CreateInvitationCode(BaseModel):
    """创建邀请码"""
    code: Optional[str] = Field(None, min_length=4, max_length=20, description="邀请码（留空自动生成）")


class ApplyInvitationCode(BaseModel):
    """使用邀请码"""
    code: str = Field(..., min_length=4, max_length=20, description="邀请码")


class InvitationConfigResponse(BaseModel):
    """邀请配置响应"""
    invitation_enabled: bool
    invitation_reward_points: int
    invitation_invitee_reward_points: int


class UpdateInvitationConfig(BaseModel):
    """更新邀请配置"""
    invitation_enabled: Optional[bool] = None
    invitation_reward_points: Optional[int] = Field(None, ge=0)
    invitation_invitee_reward_points: Optional[int] = Field(None, ge=0)


# 管理后台用
class AdminInvitationRecordResponse(BaseModel):
    """管理员邀请记录响应"""
    id: int
    inviter_username: str
    invitee_username: str
    code: str
    reward_points: int
    created_at: datetime

    class Config:
        from_attributes = True
