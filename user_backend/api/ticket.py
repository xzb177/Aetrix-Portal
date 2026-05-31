"""
工单系统 API - 用户端
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import os
import uuid
from datetime import datetime

from database import get_session
from database.models import Ticket, TicketMessage, WebUser
from schemas.ticket import (
    TicketResponse,
    TicketDetailResponse,
    TicketMessageResponse,
    CreateTicket,
    CreateTicketMessage,
    UploadAttachmentResponse
)
from api.auth import get_current_user
from schemas.auth import UserResponse

router = APIRouter(tags=["工单"])

# 附件上传目录
UPLOAD_DIR = "uploads/tickets"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("", response_model=List[TicketResponse])
async def get_my_tickets(
    status_filter: str = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取我的工单列表
    """
    query = db.query(Ticket).filter(Ticket.user_id == current_user.id)

    if status_filter:
        query = query.filter(Ticket.status == status_filter)

    tickets = query.order_by(Ticket.updated_at.desc()).offset(skip).limit(limit).all()

    # 转换为响应格式，添加未读消息数
    result = []
    for ticket in tickets:
        result.append(TicketResponse(
            id=ticket.id,
            title=ticket.title,
            category=ticket.category,
            priority=ticket.priority,
            status=ticket.status,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at
        ))

    return result


@router.post("", response_model=TicketResponse)
async def create_ticket(
    ticket_data: CreateTicket,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    创建新工单
    """
    # 创建工单
    ticket = Ticket(
        user_id=current_user.id,
        title=ticket_data.title,
        category=ticket_data.category,
        priority=ticket_data.priority,
        status="open"
    )
    db.add(ticket)
    db.flush()

    # 创建初始消息
    message = TicketMessage(
        ticket_id=ticket.id,
        user_id=current_user.id,
        message=ticket_data.message,
        attachments=ticket_data.attachments,
        is_admin=False
    )
    db.add(message)
    db.commit()

    return TicketResponse(
        id=ticket.id,
        title=ticket.title,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at
    )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket_detail(
    ticket_id: int,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取工单详情
    """
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    # 获取消息列表
    messages = db.query(TicketMessage).filter(
        TicketMessage.ticket_id == ticket_id
    ).order_by(TicketMessage.created_at.asc()).all()

    message_responses = []
    for msg in messages:
        message_responses.append(TicketMessageResponse(
            id=msg.id,
            message=msg.message,
            attachments=msg.attachments,
            is_admin=msg.is_admin,
            created_at=msg.created_at
        ))

    return TicketDetailResponse(
        id=ticket.id,
        title=ticket.title,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        messages=message_responses
    )


@router.post("/{ticket_id}/messages", response_model=TicketMessageResponse)
async def send_message(
    ticket_id: int,
    message_data: CreateTicketMessage,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    发送工单消息
    """
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    if ticket.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="工单已关闭，无法发送消息"
        )

    # 创建消息
    message = TicketMessage(
        ticket_id=ticket_id,
        user_id=current_user.id,
        message=message_data.message,
        attachments=message_data.attachments,
        is_admin=False
    )
    db.add(message)

    # 更新工单状态
    ticket.status = "open"
    ticket.updated_at = datetime.now()

    db.commit()
    db.refresh(message)

    return TicketMessageResponse(
        id=message.id,
        message=message.message,
        attachments=message.attachments,
        is_admin=message.is_admin,
        created_at=message.created_at
    )


@router.post("/{ticket_id}/close", response_model=TicketResponse)
async def close_ticket(
    ticket_id: int,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    关闭工单
    """
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    ticket.status = "closed"
    ticket.updated_at = datetime.now()
    db.commit()

    return TicketResponse(
        id=ticket.id,
        title=ticket.title,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at
    )


@router.post("/upload", response_model=UploadAttachmentResponse)
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    上传工单附件

    支持图片和常见文档格式
    """
    # 验证文件类型
    allowed_types = [
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "application/pdf",
        "text/plain"
    ]

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型。支持的类型: {', '.join(allowed_types)}"
        )

    # 验证文件大小（5MB）
    MAX_SIZE = 5 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件大小不能超过 5MB"
        )

    # 生成唯一文件名
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # 保存文件
    with open(filepath, "wb") as f:
        f.write(content)

    # 返回访问 URL
    url = f"/api/user/tickets/attachments/{filename}"

    return UploadAttachmentResponse(
        url=url,
        filename=file.filename
    )


@router.get("/attachments/{filename}")
async def get_attachment(filename: str):
    """
    获取附件文件
    """
    # 防止路径遍历攻击：只允许纯文件名，拒绝任何路径分隔符
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法文件名"
        )

    filepath = os.path.join(UPLOAD_DIR, filename)

    # 二次校验：确保解析后的路径确实在 UPLOAD_DIR 内
    real_upload = os.path.realpath(UPLOAD_DIR)
    real_file = os.path.realpath(filepath)
    if not real_file.startswith(real_upload + os.sep):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="禁止访问"
        )

    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在"
        )

    from fastapi.responses import FileResponse
    return FileResponse(filepath)
