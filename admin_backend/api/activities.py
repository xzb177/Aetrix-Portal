"""
活动管理 API
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from admin_database import get_main_db, ThemeActivity, ThemeActivityProgress, MovieBookmark, UserBinding
from admin_utils.models_loader import AdminLog
from schemas.activity import (
    ActivityCreate,
    ActivityUpdate,
    ActivityListItem,
    ActivityDetail,
    ActivityProgressItem,
)
from schemas.common import Response, PaginatedResponse
from admin_utils.auth import require_permission

router = APIRouter()


@router.get("", response_model=Response[PaginatedResponse[ActivityListItem]])
async def get_activities(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    current_admin = Depends(require_permission("activities.view")),
    db: Session = Depends(get_main_db)
):
    """获取活动列表"""
    query = db.query(ThemeActivity)

    if is_active is not None:
        query = query.filter(ThemeActivity.is_active == is_active)

    query = query.order_by(ThemeActivity.created_at.desc())
    total = query.count()
    offset = (page - 1) * page_size
    activities = query.offset(offset).limit(page_size).all()

    # 获取每个活动的参与人数和完成人数
    items = []
    for activity in activities:
        participant_count = db.query(func.count(ThemeActivityProgress.id)).filter(
            ThemeActivityProgress.activity_id == activity.id
        ).scalar() or 0

        completed_count = db.query(func.count(ThemeActivityProgress.id)).filter(
            ThemeActivityProgress.activity_id == activity.id,
            ThemeActivityProgress.completed == True
        ).scalar() or 0

        items.append(ActivityListItem(
            id=activity.id,
            name=activity.name,
            description=activity.description,
            activity_type=activity.activity_type,
            target_count=activity.target_count,
            reward_mp=activity.reward_mp,
            reward_title=activity.reward_title,
            is_active=activity.is_active,
            start_date=activity.start_date,
            end_date=activity.end_date,
            participant_count=participant_count,
            completed_count=completed_count,
        ))

    return Response(data=PaginatedResponse.create(items, total, page, page_size))


@router.get("/{activity_id}", response_model=Response[ActivityDetail])
async def get_activity_detail(
    activity_id: int,
    current_admin = Depends(require_permission("activities.view")),
    db: Session = Depends(get_main_db)
):
    """获取活动详情"""
    activity = db.query(ThemeActivity).filter(ThemeActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    return Response(data=ActivityDetail(
        id=activity.id,
        name=activity.name,
        description=activity.description,
        activity_type=activity.activity_type,
        filter_genre=activity.filter_genre,
        filter_director=activity.filter_director,
        filter_series=activity.filter_series,
        target_count=activity.target_count,
        reward_mp=activity.reward_mp,
        reward_title=activity.reward_title,
        is_active=activity.is_active,
        start_date=activity.start_date,
        end_date=activity.end_date,
        participant_count=0,
        completed_count=0,
    ))


@router.post("", response_model=Response[dict])
async def create_activity(
    data: ActivityCreate,
    request: Request,
    current_admin = Depends(require_permission("activities.create")),
    db: Session = Depends(get_main_db)
):
    """创建活动"""
    activity = ThemeActivity(**data.model_dump())
    db.add(activity)
    db.commit()
    db.refresh(activity)

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="create_activity",
        resource="activity",
        resource_id=str(activity.id),
        details={"name": activity.name, "activity_type": activity.activity_type},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "活动创建成功", "activity_id": activity.id})


@router.put("/{activity_id}", response_model=Response[dict])
async def update_activity(
    activity_id: int,
    data: ActivityUpdate,
    request: Request,
    current_admin = Depends(require_permission("activities.edit")),
    db: Session = Depends(get_main_db)
):
    """更新活动"""
    activity = db.query(ThemeActivity).filter(ThemeActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(activity, field, value)

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="update_activity",
        resource="activity",
        resource_id=str(activity_id),
        details=update_data,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "活动更新成功"})


@router.delete("/{activity_id}", response_model=Response[dict])
async def delete_activity(
    activity_id: int,
    request: Request,
    current_admin = Depends(require_permission("activities.delete")),
    db: Session = Depends(get_main_db)
):
    """删除活动"""
    activity = db.query(ThemeActivity).filter(ThemeActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    # 删除活动进度
    db.query(ThemeActivityProgress).filter(
        ThemeActivityProgress.activity_id == activity_id
    ).delete()

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="delete_activity",
        resource="activity",
        resource_id=str(activity_id),
        details={"name": activity.name},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)

    db.delete(activity)
    db.commit()

    return Response(data={"message": "活动删除成功"})


@router.get("/{activity_id}/progress", response_model=Response[PaginatedResponse[ActivityProgressItem]])
async def get_activity_progress(
    activity_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin = Depends(require_permission("activities.view")),
    db: Session = Depends(get_main_db)
):
    """获取活动进度列表"""
    # 检查活动是否存在
    activity = db.query(ThemeActivity).filter(ThemeActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    query = db.query(ThemeActivityProgress).filter(
        ThemeActivityProgress.activity_id == activity_id
    ).order_by(desc(ThemeActivityProgress.progress))

    total = query.count()
    offset = (page - 1) * page_size
    progresses = query.offset(offset).limit(page_size).all()

    items = [ActivityProgressItem.model_validate(p) for p in progresses]

    return Response(data=PaginatedResponse.create(items, total, page, page_size))


@router.post("/{activity_id}/toggle", response_model=Response[dict])
async def toggle_activity_status(
    activity_id: int,
    request: Request,
    current_admin = Depends(require_permission("activities.edit")),
    db: Session = Depends(get_main_db)
):
    """切换活动启用状态"""
    activity = db.query(ThemeActivity).filter(ThemeActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    activity.is_active = not activity.is_active

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="toggle_activity",
        resource="activity",
        resource_id=str(activity_id),
        details={"is_active": activity.is_active},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    status_text = "启用" if activity.is_active else "禁用"
    return Response(data={"message": f"活动已{status_text}", "is_active": activity.is_active})
