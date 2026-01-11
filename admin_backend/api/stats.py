"""
统计分析 API
"""
from datetime import datetime, timedelta, date
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, text
import httpx

from admin_database import get_main_db, get_admin_db, main_engine, UserBinding
from admin_utils.models_loader import AdminLog
from admin_utils.models_loader import Permission
from admin_utils.logging_config import get_logger
from schemas.stats import OverviewStats, RankingList, TrendData, StatPoint, AdminLogItem, TopUser
from schemas.common import Response
from admin_utils.auth import require_permission
from admin_utils.config import settings

router = APIRouter()
logger = get_logger(__name__)


def check_main_db_available() -> bool:
    """检查主项目 SQLite 数据库是否可用（bindings 表是否存在）"""
    try:
        with main_engine.connect() as conn:
            conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='bindings'"))
            result = conn.fetchone()
            return result is not None
    except Exception:
        return False


async def fetch_emby_sessions():
    """获取 Emby 活跃会话（包括转码状态）"""
    if not settings.EMBY_URL or not settings.EMBY_API_KEY:
        return []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.EMBY_URL}/Sessions",
                headers={"X-Emby-Token": settings.EMBY_API_KEY},
                timeout=10.0
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning(f"获取 Emby 会话失败: {e}", exc_info=True)
    return []


async def fetch_emby_items(limit: int = 50, sort_by: str = "PlayCount"):
    """获取 Emby 媒体列表"""
    if not settings.EMBY_URL or not settings.EMBY_API_KEY:
        return []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.EMBY_URL}/Items",
                params={
                    "SortBy": sort_by,
                    "SortOrder": "Descending",
                    "Limit": limit,
                    "IncludeItemTypes": "Movie,Episode,Series",
                },
                headers={"X-Emby-Token": settings.EMBY_API_KEY},
                timeout=30.0
            )
            if response.status_code == 200:
                return response.json().get("Items", [])
    except Exception as e:
        logger.warning(f"获取 Emby 媒体列表失败: {e}", exc_info=True)
    return []


async def fetch_emby_users_activity(days: int = 7):
    """获取 Emby 用户活动统计"""
    if not settings.EMBY_URL or not settings.EMBY_API_KEY:
        return {}

    try:
        async with httpx.AsyncClient() as client:
            # 获取用户列表
            users_response = await client.get(
                f"{settings.EMBY_URL}/Users",
                headers={"X-Emby-Token": settings.EMBY_API_KEY},
                timeout=10.0
            )
            if users_response.status_code != 200:
                return {}

            users = users_response.json()
            activity_data = {}

            for user in users:
                user_id = user.get("Id")
                user_name = user.get("Name")

                # 获取用户最近播放
                played_response = await client.get(
                    f"{settings.EMBY_URL}/Users/{user_id}/Items",
                    params={
                        "Limit": 20,
                        "SortBy": "DatePlayed",
                        "SortOrder": "Descending",
                        "IncludeItemTypes": "Movie,Episode",
                    },
                    headers={"X-Emby-Token": settings.EMBY_API_KEY},
                    timeout=10.0
                )

                if played_response.status_code == 200:
                    played_items = played_response.json().get("Items", [])
                    activity_data[user_name] = {
                        "recent_played": len(played_items),
                        "items": played_items[:10]
                    }

            return activity_data
    except Exception as e:
        logger.warning(f"获取 Emby 用户活动失败: {e}", exc_info=True)
    return {}


@router.get("/overview", response_model=Response[OverviewStats])
async def get_overview_stats(
    current_admin = Depends(require_permission("stats.view")),
    db: Session = Depends(get_main_db)
):
    """获取概览统计数据"""
    # 检查主数据库是否可用
    if not check_main_db_available():
        return Response(data=OverviewStats(
            total_users=0, vip_users=0, new_users_today=0, active_users_week=0,
            total_watch_minutes=0, total_watch_hours=0, avg_daily_watch_minutes=0,
            watch_streak_users=0, total_checkin_days=0, checkin_today=0,
            consecutive_checkin_top=0, total_mp_issued=0, total_mp_in_bank=0,
            total_mp_in_wallet=0,
        ))

    # 用户统计
    total_users = db.query(func.count(UserBinding.tg_id)).scalar() or 0
    vip_users = db.query(func.count(UserBinding.tg_id)).filter(UserBinding.is_vip == True).scalar() or 0

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # 使用首次签到作为新用户代理
    new_users_today = db.query(func.count(UserBinding.tg_id)).filter(
        UserBinding.last_checkin_date >= today_start,
        UserBinding.total_checkin_days <= 1
    ).scalar() or 0

    week_ago = datetime.now() - timedelta(days=7)
    active_users_week = db.query(func.count(UserBinding.tg_id)).filter(
        UserBinding.last_active_time >= week_ago
    ).scalar() or 0

    # 观影统计
    total_watch_minutes = db.query(func.sum(UserBinding.total_watch_minutes)).scalar() or 0
    total_watch_hours = total_watch_minutes // 60

    # 计算平均每日观影分钟数
    users_with_watch = db.query(func.count(UserBinding.tg_id)).filter(
        UserBinding.total_watch_minutes > 0
    ).scalar() or 0
    avg_daily_watch_minutes = int(total_watch_minutes / users_with_watch) if users_with_watch > 0 else 0

    # 观影打卡用户
    watch_streak_users = db.query(func.count(UserBinding.tg_id)).filter(
        UserBinding.watch_streak >= 3
    ).scalar() or 0

    # 签到统计
    total_checkin_days = db.query(func.sum(UserBinding.total_checkin_days)).scalar() or 0
    checkin_today = db.query(func.count(UserBinding.tg_id)).filter(
        UserBinding.last_checkin_date >= today_start
    ).scalar() or 0

    # 最高连续签到
    max_consecutive = db.query(func.max(UserBinding.consecutive_checkin)).scalar() or 0

    # 经济统计
    total_mp_in_bank = db.query(func.sum(UserBinding.bank_points)).scalar() or 0
    total_mp_in_wallet = db.query(func.sum(UserBinding.points)).scalar() or 0
    total_mp_issued = db.query(func.sum(UserBinding.total_earned)).scalar() or 0

    return Response(data=OverviewStats(
        total_users=total_users,
        vip_users=vip_users,
        new_users_today=new_users_today,
        active_users_week=active_users_week,
        total_watch_minutes=total_watch_minutes,
        total_watch_hours=total_watch_hours,
        avg_daily_watch_minutes=avg_daily_watch_minutes,
        watch_streak_users=watch_streak_users,
        total_checkin_days=total_checkin_days,
        checkin_today=checkin_today,
        consecutive_checkin_top=max_consecutive,
        total_mp_issued=total_mp_issued,
        total_mp_in_bank=total_mp_in_bank,
        total_mp_in_wallet=total_mp_in_wallet,
    ))


@router.get("/ranking", response_model=Response[RankingList])
async def get_ranking(
    limit: int = Query(10, ge=1, le=50),
    current_admin = Depends(require_permission("stats.view")),
    db: Session = Depends(get_main_db)
):
    """获取排行榜"""
    # 检查主数据库是否可用
    if not check_main_db_available():
        return Response(data=RankingList(
            watch_users=[], checkin_users=[], power_users=[], wealth_users=[]
        ))

    # 观影时长排行
    watch_users = db.query(UserBinding.tg_id, UserBinding.emby_account, UserBinding.total_watch_minutes).filter(
        UserBinding.total_watch_minutes > 0
    ).order_by(desc(UserBinding.total_watch_minutes)).limit(limit).all()

    # 签到天数排行
    checkin_users = db.query(UserBinding.tg_id, UserBinding.emby_account, UserBinding.total_checkin_days).filter(
        UserBinding.total_checkin_days > 0
    ).order_by(desc(UserBinding.total_checkin_days)).limit(limit).all()

    # 战力排行
    power_users = db.query(UserBinding.tg_id, UserBinding.emby_account, UserBinding.attack).filter(
        UserBinding.attack > 0
    ).order_by(desc(UserBinding.attack)).limit(limit).all()

    # 财富排行
    wealth_users = db.query(UserBinding.tg_id, UserBinding.emby_account, UserBinding.bank_points).filter(
        UserBinding.bank_points > 0
    ).order_by(desc(UserBinding.bank_points)).limit(limit).all()

    def to_top_user(items, value_index):
        return [
            TopUser(
                tg_id=item[0],
                emby_account=item[1],
                value=item[value_index],
            )
            for item in items
        ]

    return Response(data=RankingList(
        watch_users=to_top_user(watch_users, 2),
        checkin_users=to_top_user(checkin_users, 2),
        power_users=to_top_user(power_users, 2),
        wealth_users=to_top_user(wealth_users, 2),
    ))


@router.get("/trend", response_model=Response[TrendData])
async def get_trend_data(
    days: int = Query(7, ge=1, le=30, description="查询天数"),
    current_admin = Depends(require_permission("stats.view")),
    db: Session = Depends(get_main_db)
):
    """获取趋势数据"""
    # 检查主数据库是否可用
    if not check_main_db_available():
        # 返回空趋势数据
        empty_trend = [StatPoint(date=(datetime.now() - timedelta(days=days - i - 1)).strftime("%m-%d"), value=0) for i in range(days)]
        return Response(data=TrendData(
            watch_trend=empty_trend.copy(),
            checkin_trend=empty_trend.copy(),
            new_user_trend=empty_trend.copy(),
        ))

    watch_trend = []
    checkin_trend = []
    new_user_trend = []

    for i in range(days):
        target_date = datetime.now() - timedelta(days=days - i - 1)
        date_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        date_str = target_date.strftime("%m-%d")

        # 观影趋势（这里用总观影分钟数的简化统计）
        watch_trend.append(StatPoint(date=date_str, value=0))

        # 签到趋势
        checkin_count = db.query(func.count(UserBinding.tg_id)).filter(
            and_(UserBinding.last_checkin_date >= date_start, UserBinding.last_checkin_date <= date_end)
        ).scalar() or 0
        checkin_trend.append(StatPoint(date=date_str, value=checkin_count))

        # 新用户趋势（使用首次签到作为代理）
        new_user_count = db.query(func.count(UserBinding.tg_id)).filter(
            and_(UserBinding.last_checkin_date >= date_start, UserBinding.last_checkin_date <= date_end),
            UserBinding.total_checkin_days <= 1
        ).scalar() or 0
        new_user_trend.append(StatPoint(date=date_str, value=new_user_count))

    return Response(data=TrendData(
        watch_trend=watch_trend,
        checkin_trend=checkin_trend,
        new_user_trend=new_user_trend,
    ))


@router.get("/logs", response_model=Response[List[AdminLogItem]])
async def get_admin_logs(
    limit: int = Query(50, ge=1, le=200),
    current_admin = Depends(require_permission("system.logs")),
    db: Session = Depends(get_admin_db)  # 修复：AdminLog 在管理后台数据库中
):
    """获取管理操作日志"""
    logs = db.query(AdminLog).order_by(desc(AdminLog.created_at)).limit(limit).all()

    items = [
        AdminLogItem(
            id=log.id,
            admin_username=log.admin_username,
            action=log.action,
            resource=log.resource,
            resource_id=log.resource_id,
            details=log.details,
            ip_address=log.ip_address,
            created_at=log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
        )
        for log in logs
    ]

    return Response(data=items)


@router.get("/transcode")
async def get_transcode_queue(
    current_admin = Depends(require_permission("system.view"))
):
    """获取转码队列（基于 Emby Sessions API）"""
    sessions = await fetch_emby_sessions()

    transcode_items = []
    for session in sessions:
        # 检查是否有转码活动
        if session.get("NowPlayingItem") and session.get("TranscodingInfo"):
            transcode_info = session.get("TranscodingInfo", {})
            now_playing = session.get("NowPlayingItem", {})

            transcode_items.append({
                "user": session.get("UserName", "Unknown"),
                "item_name": now_playing.get("Name", "Unknown"),
                "item_type": now_playing.get("Type", "Unknown"),
                "container": transcode_info.get("Container", "N/A"),
                "video_codec": transcode_info.get("VideoCodec", "N/A"),
                "audio_codec": transcode_info.get("AudioCodec", "N/A"),
                "width": transcode_info.get("Width", 0),
                "height": transcode_info.get("Height", 0),
                "bitrate": transcode_info.get("Bitrate", 0),
                "framerate": transcode_info.get("Framerate", "N/A"),
                "is_video_direct": transcode_info.get("IsVideoDirect", False),
                "is_audio_direct": transcode_info.get("IsAudioDirect", False),
                "progress": session.get("PlaybackPosition", 0),
                "duration": now_playing.get("RunTimeTicks", 0) / 10000000,  # 转换为秒
                "percent_complete": int((session.get("PlaybackPosition", 0) / (now_playing.get("RunTimeTicks", 1) / 10000000)) * 100) if now_playing.get("RunTimeTicks") else 0,
            })

    return Response(data={
        "active_transcodes": len(transcode_items),
        "items": transcode_items
    })


@router.get("/heatmap")
async def get_playback_heatmap(
    days: int = Query(30, ge=7, le=90, description="统计天数"),
    current_admin = Depends(require_permission("stats.view"))
):
    """
    获取播放热力图数据

    注意：当前版本暂不支持播放热力图功能，因为播放记录数据存储在旧系统中。
    未来版本将从 Emby 服务器获取播放统计。
    """
    # 返回空数据结构（避免前端错误）
    hourly_data = [0] * 24  # 24小时
    weekly_data = [[0] * 24 for _ in range(7)]  # 7天 x 24小时

    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    return Response(data={
        "hourly": hourly_data,
        "weekly": weekly_data,
        "weekday_names": weekday_names,
        "total_plays": 0,
        "peak_hour": "--:--",
        "peak_count": 0
    })


@router.get("/popular-content")
async def get_popular_content(
    limit: int = Query(20, ge=5, le=100),
    content_type: str = Query("all", regex="^(all|movie|series|episode)$"),
    current_admin = Depends(require_permission("stats.view"))
):
    """获取热门内容（基于 Emby 播放次数）"""
    # 从 Emby 获取按播放次数排序的内容
    sort_by = "PlayCount"

    # 根据 content_type 过滤
    include_types = "Movie,Episode,Series"
    if content_type == "movie":
        include_types = "Movie"
    elif content_type == "series":
        include_types = "Series"
    elif content_type == "episode":
        include_types = "Episode"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.EMBY_URL}/Items",
                params={
                    "SortBy": sort_by,
                    "SortOrder": "Descending",
                    "Limit": limit,
                    "IncludeItemTypes": include_types,
                    "Fields": "PlayCount,UserDataRating,Genres,ProductionYear",
                },
                headers={"X-Emby-Token": settings.EMBY_API_KEY},
                timeout=30.0
            )
            if response.status_code == 200:
                items = response.json().get("Items", [])

                popular_items = []
                for item in items[:limit]:
                    popular_items.append({
                        "id": item.get("Id"),
                        "name": item.get("Name"),
                        "type": item.get("Type"),
                        "year": item.get("ProductionYear"),
                        "play_count": item.get("UserData", {}).get("PlayCount", 0),
                        "rating": item.get("CommunityRating"),
                        "genres": [g.get("Name") for g in item.get("Genres", [])],
                        "primary_image": f"{settings.EMBY_URL}/Items/{item.get('Id')}/Images/Primary" if item.get("Id") else None,
                    })

                return Response(data={
                    "items": popular_items,
                    "total": len(popular_items)
                })
                return Response(data={"items": [], "total": 0})
    except Exception as e:
        logger.error(f"获取热门内容失败: {e}", exc_info=True)

    return Response(data={"items": [], "total": 0})


@router.get("/user-behavior")
async def get_user_behavior(
    days: int = Query(7, ge=1, le=30),
    current_admin = Depends(require_permission("stats.view")),
    db: Session = Depends(get_main_db)
):
    """获取用户行为分析"""
    # 检查主数据库是否可用
    if not check_main_db_available():
        # 返回空行为数据
        empty_trend = [{"date": (datetime.now() - timedelta(days=days - i - 1)).strftime("%Y-%m-%d"), "count": 0} for i in range(days)]
        return Response(data={
            "active_users_trend": empty_trend,
            "hour_distribution": [0] * 24,
            "watch_distribution": {"0-1小时": 0, "1-10小时": 0, "10-50小时": 0, "50-100小时": 0, "100+小时": 0},
            "vip_vs_non_vip": {"vip_active": 0, "non_vip_active": 0, "vip_avg_watch_minutes": 0, "non_vip_avg_watch_minutes": 0},
            "total_active_users": 0,
            "period_days": days
        })

    # 从数据库获取用户行为数据
    start_date = datetime.now() - timedelta(days=days)

    # 活跃用户趋势
    active_users_by_day = []
    for i in range(days):
        day_start = start_date + timedelta(days=i)
        day_end = day_start.replace(hour=23, minute=59, second=59)
        day_start = day_start.replace(hour=0, minute=0, second=0)

        count = db.query(func.count(UserBinding.tg_id)).filter(
            UserBinding.last_watch_claimed >= day_start,
            UserBinding.last_watch_claimed <= day_end
        ).scalar() or 0

        active_users_by_day.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "count": count
        })

    # 观影时段分布
    hour_distribution = [0] * 24
    users = db.query(UserBinding).filter(
        UserBinding.total_watch_minutes > 0,
        UserBinding.last_watch_claimed >= start_date
    ).all()

    for user in users:
        if user.last_watch_claimed:
            hour = user.last_watch_claimed.hour
            if 0 <= hour < 24:
                hour_distribution[hour] += 1

    # 用户观看时长分布
    watch_distribution = {
        "0-1小时": 0,
        "1-10小时": 0,
        "10-50小时": 0,
        "50-100小时": 0,
        "100+小时": 0
    }

    for user in users:
        hours = user.total_watch_minutes / 60
        if hours < 1:
            watch_distribution["0-1小时"] += 1
        elif hours < 10:
            watch_distribution["1-10小时"] += 1
        elif hours < 50:
            watch_distribution["10-50小时"] += 1
        elif hours < 100:
            watch_distribution["50-100小时"] += 1
        else:
            watch_distribution["100+小时"] += 1

    # VIP 用户行为
    vip_users = db.query(UserBinding).filter(
        UserBinding.is_vip == True,
        UserBinding.last_watch_claimed >= start_date
    ).count()

    non_vip_users = db.query(UserBinding).filter(
        UserBinding.is_vip == False,
        UserBinding.last_watch_claimed >= start_date
    ).count()

    # 平均观看时长
    avg_watch_vip = db.query(func.avg(UserBinding.total_watch_minutes)).filter(
        UserBinding.is_vip == True
    ).scalar() or 0

    avg_watch_non_vip = db.query(func.avg(UserBinding.total_watch_minutes)).filter(
        UserBinding.is_vip == False
    ).scalar() or 0

    return Response(data={
        "active_users_trend": active_users_by_day,
        "hour_distribution": hour_distribution,
        "watch_distribution": watch_distribution,
        "vip_vs_non_vip": {
            "vip_active": vip_users,
            "non_vip_active": non_vip_users,
            "vip_avg_watch_minutes": round(avg_watch_vip, 1),
            "non_vip_avg_watch_minutes": round(avg_watch_non_vip, 1)
        },
        "total_active_users": len(users),
        "period_days": days
    })
