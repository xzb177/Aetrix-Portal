"""
求片管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from admin_database_user import get_user_db, MovieRequest, MovieRequestSubscriber, MovieRequestLog, WebUser
from admin_utils.auth import get_current_admin
from schemas.media_request import MovieRequestStatusUpdateRequest, MovieRequestUpdateRequest

router = APIRouter()


@router.get("/media-requests")
async def get_media_requests(
    status_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取求片列表"""
    try:
        query = db.query(MovieRequest)

        if status_filter:
            query = query.filter(MovieRequest.status == status_filter)
        if type_filter:
            query = query.filter(MovieRequest.type == type_filter)
        if search:
            query = query.filter(
                or_(
                    MovieRequest.movie_name.ilike(f"%{search}%"),
                    MovieRequest.note.ilike(f"%{search}%")
                )
            )

        total = query.count()
        requests = query.order_by(MovieRequest.created_at.desc()).offset(skip).limit(limit).all()

        result = []
        for req in requests:
            user = db.query(WebUser).filter(WebUser.id == req.user_id).first()
            # 获取同求人数
            subscriber_count = db.query(MovieRequestSubscriber).filter(
                MovieRequestSubscriber.request_id == req.id
            ).count()

            result.append({
                "id": req.id,
                "user_id": req.user_id,
                "username": user.username if user else "未知用户",
                "movie_name": req.movie_name,
                "year": req.year,
                "type": req.type,
                "note": req.note,
                "status": req.status,
                "status_remark": req.status_remark,
                "admin_note": req.admin_note,
                "emby_item_id": req.emby_item_id,
                "poster_url": req.poster_url,
                "tmdb_id": req.tmdb_id,
                "seek_count": req.seek_count or 1,
                "subscriber_count": subscriber_count,
                "created_at": req.created_at,
                "updated_at": req.updated_at,
                "completed_at": req.completed_at,
            })

        return {
            "total": total,
            "items": result
        }
    except Exception as e:
        logger.error(f"获取求片列表失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取求片列表失败: {str(e)}"
        )


@router.get("/media-requests/stats")
async def get_media_request_stats(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取求片统计"""
    try:
        total = db.query(MovieRequest).count()
        pending = db.query(MovieRequest).filter(MovieRequest.status == "pending").count()
        approved = db.query(MovieRequest).filter(MovieRequest.status == "approved").count()
        completed = db.query(MovieRequest).filter(MovieRequest.status == "completed").count()
        rejected = db.query(MovieRequest).filter(MovieRequest.status == "rejected").count()

        # 今日新增
        from datetime import date
        today = date.today()
        today_count = db.query(MovieRequest).filter(
            MovieRequest.created_at >= datetime.combine(today, datetime.min.time())
        ).count()

        return {
            "total": total,
            "pending": pending,
            "approved": approved,
            "completed": completed,
            "rejected": rejected,
            "today": today_count
        }
    except Exception as e:
        logger.error(f"获取求片统计失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取求片统计失败: {str(e)}"
        )


@router.get("/media-requests/{request_id}")
async def get_media_request_detail(
    request_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取求片详情"""
    req = db.query(MovieRequest).filter(MovieRequest.id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求片请求不存在"
        )

    user = db.query(WebUser).filter(WebUser.id == req.user_id).first()

    # 获取同求用户
    subscribers = db.query(MovieRequestSubscriber).filter(
        MovieRequestSubscriber.request_id == request_id
    ).all()

    subscriber_list = []
    for sub in subscribers:
        sub_user = db.query(WebUser).filter(WebUser.id == sub.user_id).first()
        subscriber_list.append({
            "id": sub.id,
            "user_id": sub.user_id,
            "username": sub_user.username if sub_user else "未知用户",
            "created_at": sub.created_at,
            "notified": sub.notified
        })

    # 获取操作日志
    logs = db.query(MovieRequestLog).filter(
        MovieRequestLog.request_id == request_id
    ).order_by(MovieRequestLog.created_at.desc()).limit(20).all()

    log_list = []
    for log in logs:
        log_user = None
        if log.user_id:
            log_user = db.query(WebUser).filter(WebUser.id == log.user_id).first()

        log_list.append({
            "id": log.id,
            "log_type": log.log_type,
            "content": log.content,
            "extra_data": log.extra_data,
            "username": log_user.username if log_user else "系统",
            "created_at": log.created_at
        })

    return {
        "id": req.id,
        "user_id": req.user_id,
        "username": user.username if user else "未知用户",
        "movie_name": req.movie_name,
        "year": req.year,
        "type": req.type,
        "note": req.note,
        "status": req.status,
        "status_remark": req.status_remark,
        "admin_note": req.admin_note,
        "emby_item_id": req.emby_item_id,
        "poster_url": req.poster_url,
        "tmdb_id": req.tmdb_id,
        "download_id": req.download_id,
        "seek_count": req.seek_count or 1,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
        "completed_at": req.completed_at,
        "subscribers": subscriber_list,
        "logs": log_list
    }


@router.put("/media-requests/{request_id}")
async def update_media_request(
    request_id: int,
    data: MovieRequestUpdateRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新求片信息"""
    req = db.query(MovieRequest).filter(MovieRequest.id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求片请求不存在"
        )

    # 更新字段
    if data.movie_name is not None:
        req.movie_name = data.movie_name
    if data.year is not None:
        req.year = data.year
    if data.type is not None:
        req.type = data.type
    if data.note is not None:
        req.note = data.note

    req.updated_at = datetime.now()
    db.commit()

    # 记录日志
    _log_action(db, request_id, admin.id, "updated", f"管理员更新了求片信息")

    return {"message": "更新成功"}


@router.put("/media-requests/{request_id}/status")
async def update_media_request_status(
    request_id: int,
    data: MovieRequestStatusUpdateRequest,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新求片状态"""
    req = db.query(MovieRequest).filter(MovieRequest.id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求片请求不存在"
        )

    old_status = req.status

    # 更新状态
    req.status = data.status
    req.updated_at = datetime.now()

    if data.admin_note is not None:
        req.admin_note = data.admin_note
    if data.status_remark is not None:
        req.status_remark = data.status_remark
    if data.emby_item_id is not None:
        req.emby_item_id = data.emby_item_id
    if data.poster_url is not None:
        req.poster_url = data.poster_url
    if data.tmdb_id is not None:
        req.tmdb_id = data.tmdb_id

    # 如果是完成状态，记录完成时间并更新用户统计
    if data.status == "completed" and old_status != "completed":
        req.completed_at = datetime.now()
        # 更新用户成功求片统计
        user = db.query(WebUser).filter(WebUser.id == req.user_id).first()
        if user:
            user.completed_requests_count = (user.completed_requests_count or 0) + 1

    # 更新用户总求片数（只增加一次）
    if old_status == "pending" and data.status != "pending":
        user = db.query(WebUser).filter(WebUser.id == req.user_id).first()
        if user:
            user.total_requests_count = (user.total_requests_count or 0) + 1

    db.commit()

    # 记录日志
    status_text = {
        "pending": "待处理",
        "approved": "已批准",
        "completed": "已完成",
        "rejected": "已拒绝"
    }.get(data.status, data.status)

    _log_action(db, request_id, admin.id, "status_changed",
                f"状态从 {old_status} 变更为 {status_text}")

    # 如果状态变为完成，通知所有订阅用户
    if data.status == "completed":
        _notify_subscribers(db, request_id)

    return {"message": "状态更新成功"}


@router.delete("/media-requests/{request_id}")
async def delete_media_request(
    request_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """删除求片请求"""
    req = db.query(MovieRequest).filter(MovieRequest.id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求片请求不存在"
        )

    # 删除关联数据
    db.query(MovieRequestSubscriber).filter(
        MovieRequestSubscriber.request_id == request_id
    ).delete()
    db.query(MovieRequestLog).filter(
        MovieRequestLog.request_id == request_id
    ).delete()

    db.delete(req)
    db.commit()

    return {"message": "删除成功"}


@router.get("/media-requests/{request_id}/subscribers")
async def get_request_subscribers(
    request_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取求片的订阅用户列表"""
    req = db.query(MovieRequest).filter(MovieRequest.id == request_id).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求片请求不存在"
        )

    subscribers = db.query(MovieRequestSubscriber).filter(
        MovieRequestSubscriber.request_id == request_id
    ).all()

    result = []
    for sub in subscribers:
        user = db.query(WebUser).filter(WebUser.id == sub.user_id).first()
        result.append({
            "id": sub.id,
            "user_id": sub.user_id,
            "username": user.username if user else "未知用户",
            "email": user.email if user else None,
            "created_at": sub.created_at,
            "notified": sub.notified
        })

    return result


def _log_action(db: Session, request_id: int, user_id: int, log_type: str, content: str, extra_data: dict = None):
    """记录操作日志"""
    log = MovieRequestLog(
        request_id=request_id,
        user_id=user_id,
        log_type=log_type,
        content=content,
        extra_data=extra_data
    )
    db.add(log)
    db.commit()


def _notify_subscribers(db: Session, request_id: int):
    """标记所有订阅者为已通知"""
    db.query(MovieRequestSubscriber).filter(
        and_(
            MovieRequestSubscriber.request_id == request_id,
            MovieRequestSubscriber.notified == False
        )
    ).update({"notified": True})
    db.commit()
