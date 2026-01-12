"""
求片 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_session
from database.models import WebUser, MovieRequest
from schemas.request import CreateMovieRequest, MovieRequestResponse
from api.auth import get_current_user
from typing import List
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


async def send_new_request_notification(request: MovieRequest, username: str):
    """发送新求片通知（异步，不阻塞主流程）"""
    try:
        from utils.telegram import notify_new_media_request
        await notify_new_media_request(
            movie_name=request.movie_name,
            username=username,
            year=request.year,
            media_type=request.type or "movie",
            note=request.note,
            request_id=request.id,
        )
    except Exception as e:
        logger.error(f"发送求片通知失败: {e}")


@router.post("", response_model=MovieRequestResponse)
async def create_movie_request(
    data: CreateMovieRequest,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """提交求片请求"""
    # 检查是否有重复的待处理请求
    existing = db.query(MovieRequest).filter(
        MovieRequest.user_id == current_user.id,
        MovieRequest.movie_name == data.movie_name,
        MovieRequest.year == data.year,
        MovieRequest.status.in_(['pending', 'approved'])
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="您已提交过相同的求片请求"
        )

    request = MovieRequest(
        user_id=current_user.id,
        movie_name=data.movie_name,
        year=data.year,
        type=data.type,
        note=data.note,
        status='pending',
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    # 发送 Telegram 通知给管理员（异步，不阻塞响应）
    import asyncio
    asyncio.create_task(send_new_request_notification(request, current_user.username))

    return request


@router.get("/my", response_model=List[MovieRequestResponse])
async def get_my_requests(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """获取我的求片列表"""
    requests = db.query(MovieRequest).filter(
        MovieRequest.user_id == current_user.id
    ).order_by(MovieRequest.created_at.desc()).all()

    return requests


@router.get("/{request_id}", response_model=MovieRequestResponse)
async def get_request_detail(
    request_id: int,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """获取求片详情"""
    request = db.query(MovieRequest).filter(
        MovieRequest.id == request_id,
        MovieRequest.user_id == current_user.id
    ).first()

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    return request
