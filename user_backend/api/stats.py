"""
用户端统计 API - 提供首页统计数据
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_session
from database.models import WebUser

router = APIRouter()


@router.get("/stats")
async def get_user_stats(db: Session = Depends(get_session)):
    """
    获取用户端统计数据 - 用于首页展示

    Returns:
        total_users: 总用户数
        active_users: 活跃用户数
    """
    total_users = db.query(WebUser).count()
    active_users = db.query(WebUser).filter(WebUser.is_active == True).count()

    return {
        "totalUsers": total_users,
        "activeUsers": active_users
    }
