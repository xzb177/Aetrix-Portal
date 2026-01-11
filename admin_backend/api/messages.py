"""
站内消息管理 API - 管理后台
管理员可以发送消息给用户
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from admin_database_user import get_user_db, WebUser, Message
from admin_utils.auth import get_current_admin

router = APIRouter()


# ==================== Pydantic 模型 ====================

class SendMessageRequest(BaseModel):
    """发送消息请求"""
    user_id: int
    title: str
    content: str
    message_type: str = "system"  # system, ticket, announcement, subscription, media_seek, exchange_code
    related_id: Optional[int] = None


class BroadcastMessageRequest(BaseModel):
    """广播消息请求（发送给所有用户或VIP用户）"""
    title: str
    content: str
    message_type: str = "system"
    target: str = "all"  # all, vip, active
    related_id: Optional[int] = None


# ==================== API 端点 ====================

@router.get("/messages")
async def get_messages(
    skip: int = 0,
    limit: int = 50,
    user_id: Optional[int] = None,
    message_type: Optional[str] = None,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取消息列表"""
    query = db.query(Message)

    if user_id:
        query = query.filter(Message.user_id == user_id)
    if message_type:
        query = query.filter(Message.message_type == message_type)

    messages = query.order_by(Message.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for msg in messages:
        # 获取用户名
        user = db.query(WebUser).filter(WebUser.id == msg.user_id).first()
        result.append({
            "id": msg.id,
            "user_id": msg.user_id,
            "username": user.username if user else "未知用户",
            "title": msg.title,
            "content": msg.content,
            "message_type": msg.message_type,
            "related_id": msg.related_id,
            "is_read": msg.is_read,
            "from_user": msg.from_user,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "read_at": msg.read_at.isoformat() if msg.read_at else None,
        })

    return result


@router.get("/messages/stats")
async def get_message_stats(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取消息统计"""
    total_messages = db.query(Message).count()
    unread_messages = db.query(Message).filter(Message.is_read == False).count()

    # 按类型统计
    type_stats = {}
    for msg_type in ["system", "ticket", "announcement", "subscription", "media_seek", "exchange_code"]:
        count = db.query(Message).filter(Message.message_type == msg_type).count()
        type_stats[msg_type] = count

    return {
        "total_messages": total_messages,
        "unread_messages": unread_messages,
        "type_stats": type_stats
    }


@router.post("/messages/send")
async def send_message(
    data: SendMessageRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    发送消息给指定用户
    """
    # 验证用户存在
    user = db.query(WebUser).filter(WebUser.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    message = Message(
        user_id=data.user_id,
        title=data.title,
        content=data.content,
        message_type=data.message_type,
        related_id=data.related_id,
        is_read=False,
        from_user=admin.username if hasattr(admin, 'username') else "系统管理员",
        created_at=datetime.now()
    )

    db.add(message)
    db.commit()

    return {
        "success": True,
        "message": f"消息已发送给 {user.username}",
        "message_id": message.id
    }


@router.post("/messages/broadcast")
async def broadcast_message(
    data: BroadcastMessageRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    广播消息（发送给多个用户）

    target:
    - all: 所有用户
    - vip: VIP用户
    - active: 活跃用户
    """
    # 获取目标用户列表
    query = db.query(WebUser).filter(WebUser.is_active == True)

    if data.target == "vip":
        # VIP 用户需要从主数据库查询
        import sqlite3
        from admin_utils.config import settings

        vip_telegram_ids = set()
        try:
            conn = sqlite3.connect(settings.ROYALBOT_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT tg_id FROM bindings WHERE is_vip = 1")
            vip_telegram_ids = {row[0] for row in cursor.fetchall()}
            conn.close()
        except Exception:
            pass

        if vip_telegram_ids:
            query = query.filter(WebUser.telegram_id.in_(vip_telegram_ids))
        else:
            return {"success": True, "message": "没有找到VIP用户", "sent_count": 0}

    users = query.all()

    if not users:
        return {"success": True, "message": "没有找到目标用户", "sent_count": 0}

    # 批量创建消息
    from_user = admin.username if hasattr(admin, 'username') else "系统管理员"
    created_at = datetime.now()

    messages = []
    for user in users:
        msg = Message(
            user_id=user.id,
            title=data.title,
            content=data.content,
            message_type=data.message_type,
            related_id=data.related_id,
            is_read=False,
            from_user=from_user,
            created_at=created_at
        )
        messages.append(msg)

    db.bulk_save_objects(messages)
    db.commit()

    return {
        "success": True,
        "message": f"广播消息已发送给 {len(users)} 个用户",
        "sent_count": len(users)
    }


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """删除消息"""
    message = db.query(Message).filter(Message.id == message_id).first()

    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    db.delete(message)
    db.commit()

    return {"success": True, "message": "消息已删除"}


@router.post("/messages/{message_id}/read")
async def mark_message_read(
    message_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """标记消息为已读"""
    message = db.query(Message).filter(Message.id == message_id).first()

    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    message.is_read = True
    message.read_at = datetime.now()
    db.commit()

    return {"success": True, "message": "消息已标记为已读"}
