"""
Emby 数据管理 API
"""
import httpx
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from admin_database import get_main_db, UserBinding, MovieBookmark
from admin_utils.models_loader import AdminLog
from admin_utils.logging_config import get_logger
from schemas.emby import EmbyBookmarkItem, WatchStats, EmbyItem, ManualPushRequest, UnbindEmbyRequest, RecentPlayItem
from schemas.common import Response, PaginatedResponse
from admin_utils.auth import require_permission
from admin_utils.config import settings

router = APIRouter()
logger = get_logger(__name__)


async def fetch_emby_item(item_id: str) -> Optional[dict]:
    """从 Emby 获取媒体信息"""
    if not settings.EMBY_URL or not settings.EMBY_API_KEY:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.EMBY_URL}/Users/{settings.EMBY_API_KEY}/Items/{item_id}",
                headers={"X-Emby-Token": settings.EMBY_API_KEY},
                timeout=10.0
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning(f"获取 Emby 信息失败: {e}", exc_info=True)
    return None


@router.get("/stats", response_model=Response[WatchStats])
async def get_emby_stats(
    current_admin = Depends(require_permission("emby.view")),
    db: Session = Depends(get_main_db)
):
    """获取 Emby 观影统计"""
    try:
        # 总用户数
        total_users = db.query(func.count(UserBinding.tg_id)).scalar()

        # 已绑定 Emby 的用户数
        users_with_emby = db.query(func.count(UserBinding.tg_id)).filter(
            UserBinding.emby_account != None,
            UserBinding.emby_account != ""
        ).scalar()

        # 总观影分钟数
        total_watch_minutes = db.query(func.sum(UserBinding.total_watch_minutes)).scalar() or 0

        # 平均观影分钟数
        avg_watch_minutes = int(total_watch_minutes / users_with_emby) if users_with_emby and users_with_emby > 0 else 0

        # 今日有观影的用户
        from datetime import datetime, timedelta
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_active_users = db.query(func.count(UserBinding.tg_id)).filter(
            UserBinding.daily_watch_minutes > 0
        ).scalar() or 0

        # 周活跃用户
        week_ago = datetime.now() - timedelta(days=7)
        weekly_active_users = db.query(func.count(UserBinding.tg_id)).filter(
            UserBinding.last_watch_claimed >= week_ago
        ).scalar() or 0

        # 观影排行榜 Top 10
        top_watchers = db.query(UserBinding).filter(
            UserBinding.total_watch_minutes > 0
        ).order_by(desc(UserBinding.total_watch_minutes)).limit(10).all()

        top_watchers_data = [
            {
                "tg_id": u.tg_id,
                "emby_account": u.emby_account,
                "total_watch_minutes": u.total_watch_minutes,
                "total_watch_hours": round(u.total_watch_minutes / 60, 1),
            }
            for u in top_watchers
        ]

        return Response(data=WatchStats(
            total_users=total_users or 0,
            users_with_emby=users_with_emby or 0,
            total_watch_minutes=total_watch_minutes,
            avg_watch_minutes=avg_watch_minutes,
            daily_active_users=daily_active_users,
            weekly_active_users=weekly_active_users,
            top_watchers=top_watchers_data,
        ))
    except Exception as e:
        logger.warning(f"Error querying Emby stats: {e}")
        # 返回空统计数据
        return Response(data=WatchStats(
            total_users=0,
            users_with_emby=0,
            total_watch_minutes=0,
            avg_watch_minutes=0,
            daily_active_users=0,
            weekly_active_users=0,
            top_watchers=[],
        ))


@router.get("/bookmarks", response_model=Response[PaginatedResponse[EmbyBookmarkItem]])
async def get_bookmarks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = None,
    bookmark_type: Optional[str] = None,
    current_admin = Depends(require_permission("emby.view")),
    db: Session = Depends(get_main_db)
):
    """获取收藏列表"""
    query = db.query(MovieBookmark)

    # 用户筛选
    if user_id:
        query = query.filter(MovieBookmark.user_id == user_id)

    # 类型筛选
    if bookmark_type:
        query = query.filter(MovieBookmark.bookmark_type == bookmark_type)

    # 排序和分页
    query = query.order_by(desc(MovieBookmark.created_at))
    total = query.count()
    offset = (page - 1) * page_size
    bookmarks = query.offset(offset).limit(page_size).all()

    items = [EmbyBookmarkItem.model_validate(b) for b in bookmarks]

    return Response(data=PaginatedResponse.create(items, total, page, page_size))


@router.get("/item/{item_id}", response_model=Response[EmbyItem])
async def get_emby_item_info(
    item_id: str,
    current_admin = Depends(require_permission("emby.view"))
):
    """获取 Emby 媒体详情"""
    item_data = await fetch_emby_item(item_id)
    if not item_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="媒体不存在或 Emby 连接失败",
        )

    # 处理海报 URL
    poster_url = None
    if item_data.get("ImageTags"):
        poster_url = f"{settings.EMBY_URL}/Items/{item_id}/Images/Primary"

    # 提取类型
    genres = [g.get("Name") for g in item_data.get("Genres", [])] if item_data.get("Genres") else []

    return Response(data=EmbyItem(
        item_id=item_data.get("Id", ""),
        name=item_data.get("Name", ""),
        year=item_data.get("ProductionYear", ""),
        poster_url=poster_url,
        overview=item_data.get("Overview"),
        genres=genres,
        rating=item_data.get("CommunityRating"),
        runtime=item_data.get("RunTimeTicks"),
        premiere_date=item_data.get("PremiereDate"),
    ))


@router.post("/unbind", response_model=Response[dict])
async def unbind_emby(
    data: UnbindEmbyRequest,
    request: Request,
    current_admin = Depends(require_permission("emby.unbind")),
    db: Session = Depends(get_main_db)
):
    """解绑用户 Emby 账号"""
    user = db.query(UserBinding).filter(UserBinding.tg_id == data.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    old_emby_account = user.emby_account
    user.emby_account = None

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="unbind_emby",
        resource="user",
        resource_id=str(data.user_id),
        details={"old_emby_account": old_emby_account},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "Emby 账号解绑成功"})


@router.get("/users/{user_id}/bookmarks", response_model=Response[list])
async def get_user_bookmarks(
    user_id: int,
    current_admin = Depends(require_permission("emby.view")),
    db: Session = Depends(get_main_db)
):
    """获取用户收藏列表"""
    bookmarks = db.query(MovieBookmark).filter(
        MovieBookmark.user_id == user_id
    ).order_by(MovieBookmark.created_at.desc()).all()

    items = [
        {
            "id": b.id,
            "item_id": b.item_id,
            "item_name": b.item_name,
            "item_type": b.item_type,
            "bookmark_type": b.bookmark_type,
            "rating": b.rating,
            "notes": b.notes,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in bookmarks
    ]

    return Response(data=items)


@router.get("/recent-plays", response_model=Response[list[RecentPlayItem]])
async def get_recent_plays(
    limit: int = Query(10, ge=1, le=50),
    current_admin = Depends(require_permission("emby.view"))
):
    """
    获取最近播放的媒体列表

    从 Emby 服务器获取最近添加/播放的媒体项
    """
    if not settings.EMBY_URL or not settings.EMBY_API_KEY:
        return Response(data=[])

    try:
        from admin_utils.utils.emby_client import EmbyClient

        client = EmbyClient(settings.EMBY_URL, settings.EMBY_API_KEY)
        items = client.get_latest_items(limit=limit)

        # 添加图片 URL
        for item in items:
            if item.get('primary_image_tag'):
                item['poster_url'] = client.get_item_image_url(
                    item['id'],
                    item['primary_image_tag'],
                    'Primary'
                )
            if item.get('backdrop_image_tag'):
                item['backdrop_url'] = client.get_item_image_url(
                    item['id'],
                    item['backdrop_image_tag'],
                    'Backdrop'
                )

        return Response(data=[RecentPlayItem(**item) for item in items])

    except Exception as e:
        logger.warning(f"获取最近播放失败: {e}", exc_info=True)
        return Response(data=[])


@router.get("/activity-feed", response_model=Response[list])
async def get_activity_feed(
    limit: int = Query(20, ge=1, le=100),
    current_admin = Depends(require_permission("emby.view"))
):
    """
    获取综合活动动态

    返回最近播放 + 用户观影活动的综合数据
    """
    activities = []

    # 获取 Emby 最近媒体
    try:
        from admin_utils.utils.emby_client import EmbyClient

        client = EmbyClient(settings.EMBY_URL, settings.EMBY_API_KEY)
        items = client.get_latest_items(limit=limit)

        for item in items:
            poster_url = None
            if item.get('primary_image_tag'):
                poster_url = client.get_item_image_url(
                    item['id'],
                    item['primary_image_tag'],
                    'Primary'
                )

            activities.append({
                "type": "media_added",
                "item_id": item['id'],
                "item_name": item['name'],
                "item_type": item['type'],
                "series_name": item.get('series_name'),
                "poster_url": poster_url,
                "production_year": item.get('production_year'),
                "timestamp": item.get('date_created')
            })
    except Exception as e:
        logger.warning(f"获取 Emby 媒体失败: {e}")

    # 按时间排序
    activities.sort(key=lambda x: x.get('timestamp') or '', reverse=True)

    return Response(data=activities[:limit])
