"""
公告管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from admin_database_user import get_user_db, Announcement
from admin_utils.auth import get_current_admin

router = APIRouter()


@router.get("/announcements")
async def get_announcements(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取公告列表"""
    announcements = db.query(Announcement).order_by(
        Announcement.created_at.desc()
    ).offset(skip).limit(limit).all()

    result = []
    for ann in announcements:
        result.append({
            "id": ann.id,
            "title": ann.title,
            "content": ann.content,
            "type": ann.type,
            "is_active": ann.is_active,
            "created_at": ann.created_at,
            "updated_at": ann.updated_at
        })

    return result


@router.post("/announcements")
async def create_announcement(
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """创建公告"""
    announcement = Announcement(
        title=data.get('title'),
        content=data.get('content'),
        type=data.get('type', 'system'),
        is_active=data.get('is_active', True),
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)

    return {
        "id": announcement.id,
        "message": "公告创建成功"
    }


@router.put("/announcements/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新公告"""
    announcement = db.query(Announcement).filter(
        Announcement.id == announcement_id
    ).first()

    if not announcement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公告不存在"
        )

    if 'title' in data:
        announcement.title = data['title']
    if 'content' in data:
        announcement.content = data['content']
    if 'type' in data:
        announcement.type = data['type']
    if 'is_active' in data:
        announcement.is_active = data['is_active']

    announcement.updated_at = datetime.now()
    db.commit()

    return {"message": "公告更新成功"}


@router.delete("/announcements/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """删除公告"""
    announcement = db.query(Announcement).filter(
        Announcement.id == announcement_id
    ).first()

    if not announcement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公告不存在"
        )

    db.delete(announcement)
    db.commit()

    return {"message": "公告删除成功"}
