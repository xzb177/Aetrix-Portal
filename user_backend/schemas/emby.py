"""
Emby 相关 Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class EmbyServerResponse(BaseModel):
    """Emby 服务器响应"""
    id: int
    name: str
    url: str
    is_active: bool
    max_users: int
    current_users: int
    created_at: datetime

    class Config:
        from_attributes = True


class UserEmbyAccountResponse(BaseModel):
    """用户 Emby 账号响应"""
    id: int
    server_id: int
    server_name: str
    server_url: str
    username: str
    password: str
    expires_at: Optional[datetime] = None
    is_expired: bool = False

    class Config:
        from_attributes = True


class PlanServerRelationResponse(BaseModel):
    """套餐服务器关联响应"""
    id: int
    server_id: int
    server_name: str
    weight: int

    class Config:
        from_attributes = True


# 管理后台用
class CreateEmbyServer(BaseModel):
    """创建 Emby 服务器"""
    name: str = Field(..., min_length=1, max_length=100, description="服务器名称")
    url: str = Field(..., min_length=1, description="服务器地址（含端口）")
    api_key: str = Field(..., min_length=1, description="API Key")
    max_users: int = Field(0, ge=0, description="最大用户数（0为无限制）")


class UpdateEmbyServer(BaseModel):
    """更新 Emby 服务器"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None
    max_users: Optional[int] = Field(None, ge=0)


class AddServerToPlan(BaseModel):
    """添加服务器到套餐"""
    server_id: int
    weight: int = Field(1, ge=1, le=100, description="权重（1-100）")


class TestEmbyServer(BaseModel):
    """测试 Emby 服务器连接"""
    url: str
    api_key: str


class EmbyServerUserResponse(BaseModel):
    """Emby 服务器用户响应"""
    id: str
    name: str
    has_password: bool
    last_login: Optional[datetime] = None
    last_activity: Optional[datetime] = None


class ServerTestResponse(BaseModel):
    """服务器测试响应"""
    success: bool
    message: str
    info: Optional[dict] = None
