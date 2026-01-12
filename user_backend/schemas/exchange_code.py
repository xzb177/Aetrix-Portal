"""
兑换码相关 Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import IntEnum


class ExchangeCodeType(IntEnum):
    """兑换码类型"""
    ACTIVATE_TRIAL = 1  # 激活试用
    EXTEND_DAYS = 2  # 按天续期
    EXTEND_MONTHS = 3  # 按月续期
    RECHARGE_POINTS = 4  # 充值积分


class ExchangeCodeStatus(IntEnum):
    """兑换码状态"""
    UNUSED = 0  # 未使用
    USED = 1  # 已使用
    DISABLED = -1  # 已禁用


class RedeemExchangeCodeRequest(BaseModel):
    """兑换兑换码请求"""
    code: str = Field(..., min_length=1, max_length=64, description="兑换码")


class RedeemExchangeCodeResponse(BaseModel):
    """兑换兑换码响应"""
    message: str
    type: int
    result: dict


class ExchangeCodeRecordResponse(BaseModel):
    """兑换记录响应"""
    id: int
    code: str
    type: int
    type_name: str
    exchange_count: int
    note: str
    used_at: datetime

    class Config:
        from_attributes = True


# ============ 管理后台用 ============

class CreateExchangeCodeRequest(BaseModel):
    """创建兑换码请求"""
    code: Optional[str] = Field(None, min_length=1, max_length=64, description="兑换码（留空自动生成）")
    type: int = Field(..., ge=1, le=4, description="兑换码类型：1激活试用 2按天续期 3按月续期 4充值积分")
    exchange_count: int = Field(1, ge=1, description="兑换数量/天数")
    note: Optional[str] = Field(None, description="备注")


class BatchCreateExchangeCodeRequest(BaseModel):
    """批量创建兑换码请求"""
    count: int = Field(..., ge=1, le=100, description="生成数量")
    type: int = Field(..., ge=1, le=4, description="兑换码类型")
    exchange_count: int = Field(1, ge=1, description="兑换数量/天数")
    note: Optional[str] = Field(None, description="备注")


class UpdateExchangeCodeStatusRequest(BaseModel):
    """更新兑换码状态请求"""
    status: int = Field(..., ge=-1, le=1, description="状态：-1禁用 0未使用 1已使用")


class ExchangeCodeResponse(BaseModel):
    """兑换码响应"""
    id: int
    code: str
    type: int
    type_name: str
    exchange_count: int
    status: int
    status_name: str
    used_by_user_id: Optional[int]
    used_by_username: Optional[str]
    used_at: Optional[datetime]
    created_by_admin_id: Optional[int]
    created_by_admin_username: Optional[str]
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ExchangeCodeListResponse(BaseModel):
    """兑换码列表响应"""
    total: int
    items: list[ExchangeCodeResponse]


class ExchangeCodeStatsResponse(BaseModel):
    """兑换码统计响应"""
    total: int
    unused: int
    used: int
    disabled: int
    by_type: dict[str, int]
