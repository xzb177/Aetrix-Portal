"""
认证相关 Schemas
"""
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class UserRegister(BaseModel):
    """用户注册"""
    username: str
    password: str
    email: Optional[str] = None
    invitation_code: Optional[str] = None  # 邀请码

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        """验证邮箱：空字符串转为 None，非空则验证格式"""
        if v is None or v.strip() == "":
            return None
        if "@" not in v:
            raise ValueError("无效的邮箱地址")
        return v.strip()


class TelegramCallback(BaseModel):
    """Telegram 登录回调"""
    query_string: str


class UserResponse(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    email: Optional[str] = None
    telegram_id: Optional[int] = None
    is_vip: bool = False
    emby_account: Optional[str] = None
    balance: Optional[int] = 0  # 余额，单位：分
    points: Optional[int] = 0  # @deprecated 旧字段，保留兼容性
    registered_date: Optional[datetime] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
