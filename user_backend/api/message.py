"""
站内消息系统 API - 用户端
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from database import get_session
from database.models import Message, WebUser
from api.auth import get_current_user

router = APIRouter(tags=["站内消息"])


# ==================== Pydantic 模型 ====================

class MessageResponse(BaseModel):
    """消息响应模型"""
    id: int
    title: str
    content: str
    message_type: str
    related_id: Optional[int] = None
    is_read: bool
    created_at: str
    from_user: Optional[str] = None

    class Config:
        from_attributes = True


class MessagesListResponse(BaseModel):
    """消息列表响应"""
    data: List[MessageResponse]
    total: int
    unread_count: int


class UnreadCountResponse(BaseModel):
    """未读消息数响应"""
    unread_count: int


# ==================== API 端点 ====================

@router.get("")
async def get_messages(
    unread_only: bool = False,
    limit: int = 50,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    获取当前用户的站内消息列表

    参数:
    - unread_only: 只获取未读消息
    - limit: 返回数量限制
    """
    query = db.query(Message).filter(Message.user_id == current_user.id)

    if unread_only:
        query = query.filter(Message.is_read == False)

    messages = query.order_by(Message.created_at.desc()).limit(limit).all()

    # 统计未读数量
    unread_count = db.query(Message).filter(
        Message.user_id == current_user.id,
        Message.is_read == False
    ).count()

    return {
        "data": [
            {
                "id": msg.id,
                "title": msg.title,
                "content": msg.content,
                "message_type": msg.message_type,
                "related_id": msg.related_id,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "from_user": msg.from_user
            }
            for msg in messages
        ],
        "total": len(messages),
        "unread_count": unread_count
    }


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """获取当前用户未读消息数量"""
    count = db.query(Message).filter(
        Message.user_id == current_user.id,
        Message.is_read == False
    ).count()

    return {"unread_count": count}


@router.post("/{message_id}/read")
async def mark_as_read(
    message_id: int,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    标记消息为已读
    """
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.user_id == current_user.id
    ).first()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="消息不存在"
        )

    if not message.is_read:
        message.is_read = True
        from datetime import datetime
        message.read_at = datetime.now()
        db.commit()

    return {"success": True, "message": "已标记为已读"}


@router.post("/read-all")
async def mark_all_read(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    标记所有消息为已读
    """
    from datetime import datetime

    messages = db.query(Message).filter(
        Message.user_id == current_user.id,
        Message.is_read == False
    ).all()

    for msg in messages:
        msg.is_read = True
        msg.read_at = datetime.now()

    db.commit()

    return {"success": True, "message": f"已标记 {len(messages)} 条消息为已读"}


@router.delete("/{message_id}")
async def delete_message(
    message_id: int,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    删除消息
    """
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.user_id == current_user.id
    ).first()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="消息不存在"
        )

    db.delete(message)
    db.commit()

    return {"success": True, "message": "消息已删除"}
