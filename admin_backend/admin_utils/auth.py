"""
认证和授权工具
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from admin_database import AdminSessionLocal as SessionLocal
from admin_utils.models_loader import AdminUser, Permission
from admin_utils.config import settings

# HTTP Bearer 认证
security = HTTPBearer(auto_error=False)  # 设置 auto_error=False 以支持 cookie 认证


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT 访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """解码 JWT 访问令牌"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def get_token_from_request(request: Request) -> Optional[str]:
    """从请求中获取 token（支持 Authorization 头和 cookie）"""
    # 先尝试从 Authorization 头获取
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    # 再尝试从 cookie 获取
    return request.cookies.get("admin_access_token")


def get_current_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> AdminUser:
    """获取当前登录的管理员"""
    # 先尝试从 Authorization 头获取 token
    token = None
    if credentials:
        token = credentials.credentials

    # 如果没有从 Authorization 头获取到，尝试从 cookie 获取
    if not token:
        token = request.cookies.get("admin_access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据",
        )

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
        )

    admin_id = payload.get("sub")
    if admin_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
        )

    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
        if admin is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="管理员不存在",
            )
        if not admin.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="管理员账号已被禁用",
            )
        return admin
    finally:
        db.close()


def require_permission(permission: str):
    """权限检查装饰器"""
    def permission_checker(current_admin: AdminUser = Depends(get_current_admin)):
        if not Permission.has_permission(current_admin.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要权限: {Permission.PERMISSION_DESCRIPTIONS.get(permission, permission)}",
            )
        return current_admin
    return permission_checker


def is_super_admin(current_admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    """检查是否为超级管理员"""
    if current_admin.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此操作仅超级管理员可执行",
        )
    return current_admin
