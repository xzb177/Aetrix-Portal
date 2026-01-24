"""
数据埋点和统计 API
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime, timedelta
from typing import List, Optional
import logging

from database import get_session, SessionLocal
from database.models import (
    AnalyticsEvent, DailyStats, WebUser, UserSubscription,
    SubscriptionOrder, InvitationRecord, Message
)
from api.auth import get_current_user, get_current_user_optional
from schemas.auth import UserResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["数据埋点与统计"])


# ==================== Schemas ====================

class TrackEventRequest(BaseModel):
    """事件埋点请求"""
    event_name: str  # 事件名称：invite_open, register_success, payment_success, subscribe_success 等
    event_category: Optional[str] = None  # 事件分类
    properties: Optional[dict] = None  # 事件属性
    page_url: Optional[str] = None  # 页面URL
    referrer: Optional[str] = None  # 来源页面


class DailyStatsResponse(BaseModel):
    """每日统计响应"""
    date: str
    new_users: int
    active_users: int
    new_subscriptions: int
    active_subscriptions: int
    total_orders: int
    paid_orders: int
    total_revenue: float
    total_invitations: int
    conversion_rate: float


class ConversionStatsResponse(BaseModel):
    """转化统计响应"""
    total_invitations: int
    registered: int
    paid: int
    subscribed: int
    conversion_rate: float


# ==================== 事件埋点 ====================

@router.post("/track")
async def track_event(
    data: TrackEventRequest,
    request: Request,
    db: Session = Depends(get_session),
    current_user: Optional[UserResponse] = Depends(get_current_user_optional)
):
    """
    记录事件埋点

    支持的事件类型：
    - invite_open: 打开邀请页面
    - invite_copy: 复制邀请链接
    - invite_qrcode: 显示二维码
    - register_success: 注册成功
    - payment_initiate: 发起支付
    - payment_success: 支付成功
    - payment_fail: 支付失败
    - subscribe_success: 订阅成功
    - page_view: 页面浏览
    """
    try:
        # 获取客户端信息
        user_agent = request.headers.get("user-agent", "")[:500]
        ip_address = request.client.host if request.client else None
        session_id = request.headers.get("x-session-id", "")[:64]

        event = AnalyticsEvent(
            user_id=current_user.id if current_user else None,
            session_id=session_id,
            event_name=data.event_name,
            event_category=data.event_category,
            properties=data.properties or {},
            page_url=data.page_url,
            referrer=data.referrer,
            user_agent=user_agent,
            ip_address=ip_address
        )
        db.add(event)
        db.commit()

        return {"status": "success", "event_id": event.id}

    except Exception as e:
        logger.error(f"记录事件埋点失败: {e}")
        raise HTTPException(status_code=500, detail="记录事件失败")


# ==================== 统计接口 ====================

@router.get("/stats/today")
async def get_today_stats(
    db: Session = Depends(get_session)
):
    """
    获取今日统计

    返回今日新增、付费人数、订阅人数、转化率等关键指标
    """
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # 新增用户
        new_users = db.query(WebUser).filter(
            WebUser.created_at >= today
        ).count()

        # 活跃用户（有事件记录的去重用户数）
        active_users = db.query(AnalyticsEvent).filter(
            AnalyticsEvent.created_at >= today
        ).distinct(AnalyticsEvent.user_id).count()

        # 新增订阅（今日创建的订阅）
        new_subscriptions = db.query(UserSubscription).filter(
            UserSubscription.created_at >= today
        ).count()

        # 活跃订阅
        active_subscriptions = db.query(UserSubscription).filter(
            UserSubscription.status == 'active',
            UserSubscription.end_date >= datetime.now()
        ).count()

        # 订单统计
        total_orders = db.query(SubscriptionOrder).filter(
            SubscriptionOrder.created_at >= today
        ).count()

        paid_orders = db.query(SubscriptionOrder).filter(
            SubscriptionOrder.status == 'paid',
            SubscriptionOrder.paid_at >= today
        ).count()

        # 总收入
        revenue_result = db.query(
            func.sum(SubscriptionOrder.amount)
        ).filter(
            SubscriptionOrder.status == 'paid',
            SubscriptionOrder.paid_at >= today
        ).first()
        total_revenue = float(revenue_result[0] or 0)

        # 邀请统计
        total_invitations = db.query(InvitationRecord).filter(
            InvitationRecord.created_at >= today
        ).count()

        # 转化邀请（已付费或订阅）
        converted_invitations = db.query(InvitationRecord).filter(
            InvitationRecord.created_at >= today,
            InvitationRecord.conversion_status.in_(['paid', 'subscribed'])
        ).count()

        conversion_rate = round(
            (converted_invitations / total_invitations * 100) if total_invitations > 0 else 0,
            1
        )

        return {
            "date": today.strftime("%Y-%m-%d"),
            "new_users": new_users,
            "active_users": active_users,
            "new_subscriptions": new_subscriptions,
            "active_subscriptions": active_subscriptions,
            "total_orders": total_orders,
            "paid_orders": paid_orders,
            "total_revenue": total_revenue,
            "total_invitations": total_invitations,
            "conversion_rate": conversion_rate
        }

    except Exception as e:
        logger.error(f"获取今日统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取统计失败")


@router.get("/stats/weekly")
async def get_weekly_stats(
    db: Session = Depends(get_session)
):
    """
    获取近7天统计趋势
    """
    try:
        stats = []
        for i in range(7):
            date = datetime.now() - timedelta(days=i)
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)

            # 新增用户
            new_users = db.query(WebUser).filter(
                WebUser.created_at >= start_of_day,
                WebUser.created_at <= end_of_day
            ).count()

            # 已支付订单
            paid_orders = db.query(SubscriptionOrder).filter(
                SubscriptionOrder.status == 'paid',
                SubscriptionOrder.paid_at >= start_of_day,
                SubscriptionOrder.paid_at <= end_of_day
            ).count()

            # 总收入
            revenue_result = db.query(
                func.sum(SubscriptionOrder.amount)
            ).filter(
                SubscriptionOrder.status == 'paid',
                SubscriptionOrder.paid_at >= start_of_day,
                SubscriptionOrder.paid_at <= end_of_day
            ).first()
            total_revenue = float(revenue_result[0] or 0)

            stats.append({
                "date": date.strftime("%Y-%m-%d"),
                "new_users": new_users,
                "paid_orders": paid_orders,
                "total_revenue": total_revenue
            })

        return list(reversed(stats))

    except Exception as e:
        logger.error(f"获取周统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取统计失败")


@router.get("/stats/conversion")
async def get_conversion_stats(
    db: Session = Depends(get_session),
    days: int = 30
):
    """
    获取转化漏斗统计

    Args:
        days: 统计天数，默认30天
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=days)

        # 邀请记录总数
        total_invitations = db.query(InvitationRecord).filter(
            InvitationRecord.created_at >= cutoff_date
        ).count()

        # 各状态统计
        registered = total_invitations  # 所有邀请记录都是已注册
        paid = db.query(InvitationRecord).filter(
            InvitationRecord.created_at >= cutoff_date,
            InvitationRecord.conversion_status == 'paid'
        ).count()

        subscribed = db.query(InvitationRecord).filter(
            InvitationRecord.created_at >= cutoff_date,
            InvitationRecord.conversion_status == 'subscribed'
        ).count()

        # 转化率
        conversion_rate = round(
            ((paid + subscribed) / total_invitations * 100) if total_invitations > 0 else 0,
            1
        )

        return {
            "period_days": days,
            "total_invitations": total_invitations,
            "registered": registered,
            "paid": paid,
            "subscribed": subscribed,
            "conversion_rate": conversion_rate,
            "funnel": {
                "invite_to_register": 100,  # 邀请到注册（邀请记录本身就是注册成功）
                "register_to_paid": round((paid / registered * 100) if registered > 0 else 0, 1),
                "paid_to_subscribe": round((subscribed / paid * 100) if paid > 0 else 0, 1)
            }
        }

    except Exception as e:
        logger.error(f"获取转化统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取统计失败")


@router.post("/stats/daily", response_model=DailyStatsResponse)
async def generate_daily_stats(
    date: Optional[str] = None,
    db: Session = Depends(get_session)
):
    """
    生成或获取指定日期的统计

    Args:
        date: 日期字符串 (YYYY-MM-DD)，默认为今天
    """
    try:
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            target_date = datetime.now()

        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        # 检查是否已存在
        existing = db.query(DailyStats).filter(
            DailyStats.stat_date == start_of_day
        ).first()

        if existing:
            return DailyStatsResponse(
                date=existing.stat_date.strftime("%Y-%m-%d"),
                new_users=existing.new_users,
                active_users=existing.active_users,
                new_subscriptions=existing.new_subscriptions,
                active_subscriptions=existing.active_subscriptions,
                total_orders=existing.total_orders,
                paid_orders=existing.paid_orders,
                total_revenue=float(existing.total_revenue),
                total_invitations=existing.total_invitations,
                conversion_rate=float(existing.conversion_rate)
            )

        # 计算统计数据
        new_users = db.query(WebUser).filter(
            WebUser.created_at >= start_of_day,
            WebUser.created_at <= end_of_day
        ).count()

        active_subscriptions = db.query(UserSubscription).filter(
            UserSubscription.status == 'active',
            UserSubscription.end_date >= datetime.now()
        ).count()

        new_subscriptions = db.query(UserSubscription).filter(
            UserSubscription.created_at >= start_of_day,
            UserSubscription.created_at <= end_of_day
        ).count()

        total_orders = db.query(SubscriptionOrder).filter(
            SubscriptionOrder.created_at >= start_of_day,
            SubscriptionOrder.created_at <= end_of_day
        ).count()

        paid_orders = db.query(SubscriptionOrder).filter(
            SubscriptionOrder.status == 'paid',
            SubscriptionOrder.paid_at >= start_of_day,
            SubscriptionOrder.paid_at <= end_of_day
        ).all()

        total_revenue = sum(float(order.amount) for order in paid_orders)
        paid_orders_count = len(paid_orders)

        # 邀请统计
        total_invitations = db.query(InvitationRecord).filter(
            InvitationRecord.created_at >= start_of_day,
            InvitationRecord.created_at <= end_of_day
        ).count()

        converted_invitations = db.query(InvitationRecord).filter(
            InvitationRecord.created_at >= start_of_day,
            InvitationRecord.created_at <= end_of_day,
            InvitationRecord.conversion_status.in_(['paid', 'subscribed'])
        ).count()

        conversion_rate = round(
            (converted_invitations / total_invitations * 100) if total_invitations > 0 else 0,
            1
        )

        # 创建记录
        stats = DailyStats(
            stat_date=start_of_day,
            new_users=new_users,
            active_users=0,  # 暂时设为0
            new_subscriptions=new_subscriptions,
            active_subscriptions=active_subscriptions,
            total_orders=total_orders,
            paid_orders=paid_orders_count,
            total_revenue=total_revenue,
            total_invitations=total_invitations,
            converted_invitations=converted_invitations,
            conversion_rate=conversion_rate
        )
        db.add(stats)
        db.commit()

        return DailyStatsResponse(
            date=start_of_day.strftime("%Y-%m-%d"),
            new_users=new_users,
            active_users=0,
            new_subscriptions=new_subscriptions,
            active_subscriptions=active_subscriptions,
            total_orders=total_orders,
            paid_orders=paid_orders_count,
            total_revenue=total_revenue,
            total_invitations=total_invitations,
            conversion_rate=conversion_rate
        )

    except Exception as e:
        logger.error(f"生成每日统计失败: {e}")
        raise HTTPException(status_code=500, detail="生成统计失败")
