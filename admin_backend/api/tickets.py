"""
工单管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from admin_database_user import get_user_db, Ticket, TicketMessage, WebUser
from admin_utils.auth import get_current_admin
from schemas.ticket import TicketMessageRequest, TicketStatusUpdateRequest

router = APIRouter()


@router.get("/tickets")
async def get_tickets(
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取工单列表"""
    query = db.query(Ticket)

    if status_filter:
        query = query.filter(Ticket.status == status_filter)
    if category_filter:
        query = query.filter(Ticket.category == category_filter)
    if priority_filter:
        query = query.filter(Ticket.priority == priority_filter)

    tickets = query.order_by(Ticket.updated_at.desc()).offset(skip).limit(limit).all()

    result = []
    for ticket in tickets:
        user = db.query(WebUser).filter(WebUser.id == ticket.user_id).first()
        result.append({
            "id": ticket.id,
            "user_id": ticket.user_id,
            "username": user.username if user else "未知用户",
            "title": ticket.title,
            "category": ticket.category,
            "priority": ticket.priority,
            "status": ticket.status,
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at
        })

    return result


@router.get("/tickets/stats")
async def get_ticket_stats(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取工单统计"""
    total = db.query(Ticket).count()
    open_count = db.query(Ticket).filter(Ticket.status == "open").count()
    replied_count = db.query(Ticket).filter(Ticket.status == "replied").count()
    resolved_count = db.query(Ticket).filter(Ticket.status == "resolved").count()
    closed_count = db.query(Ticket).filter(Ticket.status == "closed").count()

    return {
        "total": total,
        "open": open_count,
        "replied": replied_count,
        "resolved": resolved_count,
        "closed": closed_count
    }


@router.get("/tickets/{ticket_id}")
async def get_ticket_detail(
    ticket_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取工单详情"""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    user = db.query(WebUser).filter(WebUser.id == ticket.user_id).first()

    # 获取消息
    messages = db.query(TicketMessage).filter(
        TicketMessage.ticket_id == ticket_id
    ).order_by(TicketMessage.created_at.asc()).all()

    message_list = []
    for msg in messages:
        msg_user = None
        if msg.user_id and not msg.is_admin:
            msg_user = db.query(WebUser).filter(WebUser.id == msg.user_id).first()

        message_list.append({
            "id": msg.id,
            "message": msg.message,
            "attachments": msg.attachments,
            "is_admin": msg.is_admin,
            "username": "管理员" if msg.is_admin else (msg_user.username if msg_user else "未知用户"),
            "created_at": msg.created_at
        })

    return {
        "id": ticket.id,
        "user_id": ticket.user_id,
        "username": user.username if user else "未知用户",
        "title": ticket.title,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "messages": message_list
    }


@router.post("/tickets/{ticket_id}/messages")
async def send_message(
    ticket_id: int,
    data: TicketMessageRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """回复工单"""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    message = TicketMessage(
        ticket_id=ticket_id,
        user_id=None,  # 管理员消息
        message=data.message,
        attachments=data.attachments,
        is_admin=True,
        created_at=datetime.now()
    )
    db.add(message)

    # 更新工单状态
    ticket.status = "replied"
    ticket.updated_at = datetime.now()

    db.commit()

    return {"message": "回复成功"}


@router.put("/tickets/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: int,
    data: TicketStatusUpdateRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新工单状态"""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    ticket.status = data.status
    ticket.updated_at = datetime.now()

    db.commit()

    return {"message": "状态更新成功"}
