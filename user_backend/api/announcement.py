"""
公告系统 API - 用户端
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from database import get_session
from database.models import Announcement
from schemas.announcement import AnnouncementResponse

router = APIRouter(tags=["公告"])


@router.get("", response_model=List[AnnouncementResponse])
async def get_announcements(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_session)
):
    """
    获取公告列表

    只返回已激活的公告，按创建时间倒序排列
    """
    announcements = db.query(Announcement).filter(
        Announcement.is_active == True
    ).order_by(
        Announcement.created_at.desc()
    ).offset(skip).limit(limit).all()

    return announcements


@router.get("/{announcement_id}", response_model=AnnouncementResponse)
async def get_announcement(
    announcement_id: int,
    db: Session = Depends(get_session)
):
    """
    获取公告详情
    """
    announcement = db.query(Announcement).filter(
        Announcement.id == announcement_id,
        Announcement.is_active == True
    ).first()

    if not announcement:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公告不存在"
        )

    return announcement
