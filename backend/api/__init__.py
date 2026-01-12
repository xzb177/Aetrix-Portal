"""
API 路由包
包含用户端和管理后台的所有路由
"""
from backend.api.user import user_router
from backend.api.admin import admin_router

__all__ = ["user_router", "admin_router"]
