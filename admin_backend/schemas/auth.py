"""
认证相关数据模型
"""
from pydantic import BaseModel, Field


class AdminInfo(BaseModel):
    """管理员信息"""
    id: int
    username: str
    role: str
    role_display: str
    permissions: list
    is_active: bool
    last_login: str | None = None


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, description="用户名")
    password: str = Field(..., min_length=1, description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field("Bearer", description="令牌类型")
    expires_in: int = Field(..., description="过期时间（秒）")
    admin_info: AdminInfo = Field(..., description="管理员信息")
    csrf_token: str | None = Field(None, description="CSRF 令牌 (用于 Cookie 认证)")


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., min_length=1, description="旧密码")
    new_password: str = Field(..., min_length=6, description="新密码")
