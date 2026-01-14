"""
求片 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from database import get_session
from database.models import WebUser, MovieRequest, MovieRequestSubscriber
from schemas.request import (
    CreateMovieRequest,
    MovieRequestResponse,
    MovieRequestGalleryResponse,
    TmdbSearchResult,
    GalleryStatsResponse,
    UserRequestLimitResponse
)
from api.auth import get_current_user
from typing import List, Optional
import logging
from datetime import datetime, timedelta
import httpx

logger = logging.getLogger(__name__)
router = APIRouter()


def get_request_config():
    """从 admin backend 获取求片配置"""
    try:
        admin_backend_url = "http://royalbot_admin_backend:8080"
        response = httpx.get(
            f"{admin_backend_url}/api/settings/public/request-limit",
            timeout=5.0
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.warning(f"获取求片配置失败: {e}")

    # 默认配置
    return {
        "request_limit_per_user": 5,
        "request_limit_vip_bonus": 5,
        "request_limit_period": "total"
    }


def get_user_request_count(user_id: int, period: str, db: Session) -> int:
    """获取用户在指定周期内的求片数量"""
    query = db.query(func.count(MovieRequest.id)).filter(
        MovieRequest.user_id == user_id,
        MovieRequest.status.in_(['pending', 'approved'])  # 只计算有效的求片
    )

    if period == "monthly":
        # 本月
        from datetime import date
        today = date.today()
        start_of_month = today.replace(day=1)
        query = query.filter(MovieRequest.created_at >= start_of_month)
    elif period == "weekly":
        # 本周
        from datetime import date
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        query = query.filter(MovieRequest.created_at >= start_of_week)

    return query.scalar() or 0


def check_user_is_vip(user_id: int, db: Session) -> bool:
    """检查用户是否是有效的 VIP"""
    from database.models import UserSubscription
    from datetime import datetime

    subscription = db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id,
        UserSubscription.status == 'active',
        UserSubscription.end_date > datetime.now()
    ).first()

    return subscription is not None


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
    """提交求片请求（支持 TMDB 数据）"""
    # 获取求片配置
    config = get_request_config()
    limit_per_user = int(config.get("request_limit_per_user", 5))
    vip_bonus = int(config.get("request_limit_vip_bonus", 5))
    limit_period = config.get("request_limit_period", "total")

    # 检查求片限制
    if limit_per_user > 0:
        is_vip = check_user_is_vip(current_user.id, db)
        user_limit = limit_per_user + (vip_bonus if is_vip else 0)
        used_count = get_user_request_count(current_user.id, limit_period, db)

        logger.info(f"求片限制检查: user_id={current_user.id}, is_vip={is_vip}, user_limit={user_limit}, used_count={used_count}, limit_per_user={limit_per_user}")

        if used_count >= user_limit:
            period_text = {"total": "总计", "monthly": "本月", "weekly": "本周"}.get(limit_period, "总计")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"您的求片次数已用尽（{period_text}{user_limit}次）。VIP用户可获得额外{vip_bonus}次求片额度。"
            )

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
        tmdb_id=data.tmdb_id,
        poster_url=data.poster_url,
        status='pending',
        subscriber_count=1,  # 创建者自动订阅
        priority=0,
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    # 创建者自动订阅
    subscriber = MovieRequestSubscriber(
        request_id=request.id,
        user_id=current_user.id
    )
    db.add(subscriber)
    db.commit()

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


@router.get("/gallery", response_model=List[MovieRequestGalleryResponse])
async def get_gallery_requests(
    status_filter: Optional[str] = Query(None, description="状态筛选: pending, approved, completed"),
    type_filter: Optional[str] = Query(None, description="类型筛选: movie, series, anime, documentary"),
    sort_by: str = Query("hot", description="排序: hot=热度, latest=最新"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(50, ge=1, le=100, description="每页数量"),
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    获取海报墙求片列表（公共求片池）

    显示所有用户的求片请求，支持筛选和排序
    """
    query = db.query(MovieRequest).filter(
        MovieRequest.status.in_(['pending', 'approved', 'completed'])
    )

    # 状态筛选
    if status_filter:
        query = query.filter(MovieRequest.status == status_filter)

    # 类型筛选
    if type_filter:
        query = query.filter(MovieRequest.type == type_filter)

    # 排序
    if sort_by == "hot":
        # 按热度（订阅数 + 优先级）排序
        query = query.order_by(
            (MovieRequest.subscriber_count + MovieRequest.priority).desc(),
            MovieRequest.created_at.desc()
        )
    else:  # latest
        query = query.order_by(MovieRequest.created_at.desc())

    # 分页
    offset = (page - 1) * limit
    requests = query.offset(offset).limit(limit).all()

    return requests


@router.get("/stats", response_model=GalleryStatsResponse)
async def get_gallery_stats(
    db: Session = Depends(get_session)
):
    """获取海报墙统计数据"""
    # 统计各状态数量
    total = db.query(func.count(MovieRequest.id)).filter(
        MovieRequest.status.in_(['pending', 'approved', 'completed'])
    ).scalar()

    pending = db.query(func.count(MovieRequest.id)).filter(
        MovieRequest.status == 'pending'
    ).scalar()

    approved = db.query(func.count(MovieRequest.id)).filter(
        MovieRequest.status == 'approved'
    ).scalar()

    completed = db.query(func.count(MovieRequest.id)).filter(
        MovieRequest.status == 'completed'
    ).scalar()

    # 按类型统计
    type_stats = db.query(
        MovieRequest.type,
        func.count(MovieRequest.id).label('count')
    ).filter(
        MovieRequest.status.in_(['pending', 'approved', 'completed'])
    ).group_by(MovieRequest.type).all()

    by_type = {type_: count for type_, count in type_stats}

    return GalleryStatsResponse(
        total=total or 0,
        pending=pending or 0,
        approved=approved or 0,
        completed=completed or 0,
        by_type=by_type
    )


@router.get("/tmdb-search", response_model=List[TmdbSearchResult])
async def search_tmdb(
    query: str = Query(..., min_length=2, description="搜索关键词"),
    media_type: Optional[str] = Query(None, description="媒体类型: movie, series"),
    current_user: WebUser = Depends(get_current_user),
):
    """
    搜索 TMDB 影片

    返回匹配的影片列表，包含海报 URL 和元数据
    """
    from services.tmdb import get_tmdb_service

    tmdb = get_tmdb_service()

    try:
        if media_type == "movie":
            results = await tmdb.search_movie(query)
        elif media_type == "series":
            results = await tmdb.search_tv(query)
        else:
            results = await tmdb.search_multi(query)

        return [TmdbSearchResult(**r) for r in results]
    except Exception as e:
        logger.error(f"TMDB 搜索失败: {e}")
        return []


@router.post("/{request_id}/subscribe", response_model=MovieRequestResponse)
async def subscribe_request(
    request_id: int,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    订阅/投票求片请求

    增加订阅数，表示用户也想要这个影片
    """
    request = db.query(MovieRequest).filter(
        MovieRequest.id == request_id
    ).first()

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="求片请求不存在"
        )

    # 检查是否已订阅
    existing = db.query(MovieRequestSubscriber).filter(
        MovieRequestSubscriber.request_id == request_id,
        MovieRequestSubscriber.user_id == current_user.id
    ).first()

    if existing:
        # 已订阅，取消订阅
        db.delete(existing)
        if request.subscriber_count > 0:
            request.subscriber_count -= 1
        db.commit()
        # 更新优先级
        request.priority = max(0, request.priority - 1)
    else:
        # 新订阅
        subscriber = MovieRequestSubscriber(
            request_id=request_id,
            user_id=current_user.id
        )
        db.add(subscriber)
        request.subscriber_count += 1
        request.priority += 1
        db.commit()

    db.refresh(request)
    return request


@router.get("/{request_id}", response_model=MovieRequestResponse)
async def get_request_detail(
    request_id: int,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """获取求片详情"""
    request = db.query(MovieRequest).filter(
        MovieRequest.id == request_id
    ).first()

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    # 检查用户是否订阅
    is_subscribed = db.query(MovieRequestSubscriber).filter(
        MovieRequestSubscriber.request_id == request_id,
        MovieRequestSubscriber.user_id == current_user.id
    ).first() is not None

    # 添加到响应（不修改数据库）
    request_dict = MovieRequestResponse.model_validate(request).model_dump()
    request_dict['is_subscribed'] = is_subscribed

    return request_dict


@router.get("/my/limit", response_model=UserRequestLimitResponse)
async def get_my_request_limit(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    获取当前用户的求片限制状态

    返回用户的求片配额、已使用次数、剩余次数等信息
    """
    # 获取求片配置
    config = get_request_config()
    limit_per_user = int(config.get("request_limit_per_user", 5))
    vip_bonus = int(config.get("request_limit_vip_bonus", 5))
    limit_period = config.get("request_limit_period", "total")

    # 检查 VIP 状态
    is_vip = check_user_is_vip(current_user.id, db)

    # 计算用户限制
    user_limit = limit_per_user + (vip_bonus if is_vip else 0)

    # 获取已使用次数
    used_count = get_user_request_count(current_user.id, limit_period, db)

    # 计算剩余次数
    remaining = max(0, user_limit - used_count) if limit_per_user > 0 else 999

    return UserRequestLimitResponse(
        limit=user_limit if limit_per_user > 0 else 0,
        used=used_count,
        remaining=remaining,
        period=limit_period,
        is_vip=is_vip,
        vip_bonus=vip_bonus
    )
