"""
管理后台 API · 经济、邀请与统计

从 `admin.py` 拆出的「后段」：邀请与返利、积分台账、经济系统设置、经济统计，
以及 v2.4.0 补的用户详情 / 趋势 / 订阅总览。

**这里的端点一律写成同步 ``def``**：项目用的是同步 SQLAlchemy，``async def``
端点会在事件循环上直接跑查询，一个管理员点开「经济统计」就会把全站请求按住。
``def`` 端点由 FastAPI 自动丢到线程池，语义不变（HTTP 契约、依赖注入、返回类型
都一样），但不再占住事件循环。唯一保留 ``async def`` 的是
``economy_adjust_points``——它真的要 ``await notify_admin_event``。

路由对象与其它后台模块共用 ``admin_core.admin_router``，导入即注册。
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend import models
from backend.api.admin_core import (
    _audit,
    admin_router,
    get_current_admin,
)
from backend.database import get_db
from backend.notifications import notify_admin_event


# ---------- 邀请与返利管理 ----------

@admin_router.get("/economy/invitations")
def economy_list_invitations(
    limit: int = 100,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """邀请记录列表（谁邀请了谁、奖励多少）"""
    records = db.query(models.InvitationRecord).order_by(
        models.InvitationRecord.created_at.desc()
    ).limit(min(limit, 200)).all()

    user_ids = {r.inviter_id for r in records} | {r.invitee_id for r in records}
    users = {u.id: u.username for u in db.query(models.WebUser).filter(
        models.WebUser.id.in_(user_ids)).all()} if user_ids else {}

    return {"records": [
        {
            "id": r.id,
            "inviter": users.get(r.inviter_id, "未知"),
            "invitee": users.get(r.invitee_id, "未知"),
            "reward_points": r.reward_points,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]}


@admin_router.get("/economy/points-logs")
def economy_points_logs(
    user_id: Optional[int] = None,
    type_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """全站积分流水台账"""
    q = db.query(models.PointsLog)
    if user_id:
        q = q.filter(models.PointsLog.user_id == user_id)
    if type_filter:
        q = q.filter(models.PointsLog.type == type_filter)

    total = q.count()
    logs = q.order_by(models.PointsLog.created_at.desc()).offset(offset).limit(min(limit, 200)).all()

    user_ids = {l.user_id for l in logs}
    users = {u.id: u.username for u in db.query(models.WebUser).filter(
        models.WebUser.id.in_(user_ids)).all()} if user_ids else {}

    return {
        "total": total,
        "logs": [
            {
                "id": l.id, "user_id": l.user_id,
                "username": users.get(l.user_id, "未知"),
                "amount": l.amount, "balance_after": l.balance_after,
                "type": l.type, "description": l.description,
                "ref_id": l.ref_id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


class PointsAdjustRequest(BaseModel):
    amount: int  # 正数发放 / 负数扣除
    reason: str = ""


@admin_router.post("/economy/users/{user_id}/points")
async def economy_adjust_points(
    user_id: int,
    request: PointsAdjustRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员手动调整用户积分（记账，留审计）—— 写库整段下放线程池

    同步 SQLAlchemy 跑在事件循环上时，一次提交 = 全站排队；这里只需要等通知（WebSocket）。
    """
    from backend.api.economy import _add_points

    admin_id = current_admin.id
    reason = request.reason

    def _adjust() -> int:
        user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if request.amount == 0:
            raise HTTPException(status_code=400, detail="调整数量不能为 0")

        balance = _add_points(
            db, user, request.amount,
            "admin_grant" if request.amount > 0 else "admin_deduct",
            reason or f"管理员调整（{request.amount:+d}）",
            f"admin:{admin_id}",
        )
        db.commit()

        _audit(db, admin_id, "economy_adjust_points", "user", user_id,
               {"amount": request.amount, "reason": reason})
        db.commit()
        return balance

    balance = await run_in_threadpool(_adjust)

    await notify_admin_event(
        event_type="economy.admin_adjust",
        user_id=user_id,
        title=f"💰 积分变动 {request.amount:+d}",
        content=f"{reason or '管理员调整'}\n当前余额：{balance} 积分",
        from_admin_id=admin_id,
    )
    return {"success": True, "balance": balance}


# ---------- 经济系统设置 ----------

ECONOMY_CONFIG_KEYS = {
    "checkin_enabled": "bool", "checkin_base_points": "int", "checkin_streak_bonus": "int",
    "checkin_streak_max_bonus": "int",
    "media_seek_daily_limit": "int",  # 用户每日求片上限（用户端硬性校验）
    "exchange_enabled": "bool",
    "recharge_enabled": "bool", "subscription_purchase_enabled": "bool",
    "payment_gateway_url": "str", "payment_partner_id": "str",
    "payment_partner_key": "secret", "payment_qqpay_enabled": "bool",
    "site_url": "str",
    # 付费墙：是否要求有效订阅才能播放 + 自定义拦截文案
    "subscription_required": "bool", "subscription_gate_message": "str",
    # 下载开关与设备/日志风控（借鉴 twilight-kotomi 的运营策略）
    "allow_download": "bool",
    "device_limit_per_user": "int", "device_limit_auto_evict": "bool",
    "login_log_retention_days": "int",
    "invitation_enabled": "bool", "invitation_reward_points": "int",
    "invitation_invitee_reward_points": "int", "invitation_rebate_percent": "int",
}


class EconomySettingsRequest(BaseModel):
    settings: dict


@admin_router.get("/economy/settings")
def economy_get_settings(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    result = {}
    for key, value_type in ECONOMY_CONFIG_KEYS.items():
        config = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if value_type == "secret":
            result[key] = "******" if (config and config.value) else ""
        else:
            result[key] = config.value if config else ""
    return {"settings": result}


@admin_router.put("/economy/settings")
def economy_update_settings(
    request: EconomySettingsRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新经济系统配置（secret 值为 ****** 时保持不变）"""
    changed = {}
    for key, value in request.settings.items():
        if key not in ECONOMY_CONFIG_KEYS:
            continue
        if ECONOMY_CONFIG_KEYS[key] == "secret" and (not value or value == "******"):
            continue
        config = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if config:
            config.value = str(value)
        else:
            db.add(models.SystemConfig(key=key, value=str(value)))
        changed[key] = str(value) if ECONOMY_CONFIG_KEYS[key] != "secret" else "(已更新)"

    db.commit()
    _audit(db, current_admin, "economy_update_settings", "system", None, changed)
    db.commit()
    return {"success": True, "changed": list(changed.keys())}


# ---------- 经济统计 ----------

@admin_router.get("/economy/stats")
def economy_stats(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """经济系统概览：用户/积分/订单/兑换/邀请"""
    from sqlalchemy import func as _func

    total_points = db.query(_func.coalesce(_func.sum(models.WebUser.points), 0)).scalar() or 0
    pending_recharge = db.query(models.RechargeOrder).filter(
        models.RechargeOrder.status == "pending").count()
    paid_recharge = db.query(_func.coalesce(_func.sum(models.RechargeOrder.price), 0)).filter(
        models.RechargeOrder.status == "paid").scalar() or 0
    paid_sub = db.query(_func.coalesce(_func.sum(models.SubscriptionOrder.amount), 0)).filter(
        models.SubscriptionOrder.status == "paid").scalar() or 0

    return {
        "total_points": int(total_points),
        "checkins_today": db.query(models.CheckinRecord).filter(
            models.CheckinRecord.checkin_date >= datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0)).count(),
        "orders": {"pending": pending_recharge,
                   "revenue": round(float(paid_recharge) + float(paid_sub), 2)},
        "exchange_codes": {
            "total": db.query(models.ExchangeCode).count(),
            "used": db.query(models.ExchangeCode).filter(
                models.ExchangeCode.use_count > 0).count(),
        },
        "invitations": db.query(models.InvitationRecord).count(),
    }


# ==================== 用户详情 / 趋势 / 订阅总览（v2.4.0 补齐） ====================


def _days_left(end_date: Optional[datetime], now: datetime) -> int:
    if not end_date:
        return 0
    return max(0, (end_date - now).days)


@admin_router.get("/users/{user_id}")
def get_user_detail(
    user_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """用户 360° 详情：资料 / 订阅 / 积分 / 订单 / 邀请 / 签到 / 观看"""
    from backend.emby_server import models as em

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    now = datetime.now()

    # ---------- 订阅 ----------
    subs = (
        db.query(models.UserSubscription)
        .filter(models.UserSubscription.user_id == user_id)
        .order_by(models.UserSubscription.end_date.desc())
        .limit(10)
        .all()
    )
    active_sub = next(
        (s for s in subs if s.status == "active" and s.end_date and s.end_date > now), None
    )

    def _sub_row(s: models.UserSubscription) -> dict:
        return {
            "id": s.id,
            "plan_name": s.plan.name if s.plan else f"套餐 #{s.plan_id}",
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "days_left": _days_left(s.end_date, now),
            "status": s.status,
        }

    # ---------- 积分 ----------
    income = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user_id, models.PointsLog.amount > 0
    ).scalar() or 0
    expense = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user_id, models.PointsLog.amount < 0
    ).scalar() or 0
    recent_logs = (
        db.query(models.PointsLog)
        .filter(models.PointsLog.user_id == user_id)
        .order_by(models.PointsLog.created_at.desc())
        .limit(10)
        .all()
    )

    # ---------- 订单 ----------
    recharge_orders = (
        db.query(models.RechargeOrder)
        .filter(models.RechargeOrder.user_id == user_id)
        .order_by(models.RechargeOrder.created_at.desc())
        .limit(10)
        .all()
    )
    sub_orders = (
        db.query(models.SubscriptionOrder)
        .filter(models.SubscriptionOrder.user_id == user_id)
        .order_by(models.SubscriptionOrder.created_at.desc())
        .limit(10)
        .all()
    )
    paid_total = float(
        db.query(func.coalesce(func.sum(models.RechargeOrder.price), 0)).filter(
            models.RechargeOrder.user_id == user_id,
            models.RechargeOrder.status == "paid",
        ).scalar() or 0
    ) + float(
        db.query(func.coalesce(func.sum(models.SubscriptionOrder.amount), 0)).filter(
            models.SubscriptionOrder.user_id == user_id,
            models.SubscriptionOrder.status == "paid",
        ).scalar() or 0
    )

    # ---------- 邀请 ----------
    invite_records = (
        db.query(models.InvitationRecord)
        .filter(models.InvitationRecord.inviter_id == user_id)
        .order_by(models.InvitationRecord.created_at.desc())
        .limit(10)
        .all()
    )
    invitee_ids = [r.invitee_id for r in invite_records]
    invitee_names = {
        u.id: u.username
        for u in db.query(models.WebUser).filter(models.WebUser.id.in_(invitee_ids)).all()
    } if invitee_ids else {}
    rebate_total = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user_id, models.PointsLog.type == "rebate"
    ).scalar() or 0

    # ---------- 签到 ----------
    checkin_count = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == user_id
    ).count()
    last_checkin = (
        db.query(models.CheckinRecord)
        .filter(models.CheckinRecord.user_id == user_id)
        .order_by(models.CheckinRecord.checkin_date.desc())
        .first()
    )

    # ---------- 观看 ----------
    plays = db.query(em.PlaybackSession).filter(em.PlaybackSession.user_id == user_id).count()
    watched_items = db.query(em.UserMediaData).filter(
        em.UserMediaData.user_id == user_id,
        em.UserMediaData.played == True,  # noqa: E712
    ).count()

    return {
        "profile": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "emby_username": user.emby_username,
            "points": user.points or 0,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "subscription": {
            "active": _sub_row(active_sub) if active_sub else None,
            "history": [_sub_row(s) for s in subs],
        },
        "points": {
            "balance": user.points or 0,
            "income": int(income),
            "expense": abs(int(expense)),
            "recent": [
                {
                    "id": l.id,
                    "amount": l.amount,
                    "balance_after": l.balance_after,
                    "type": l.type,
                    "description": l.description,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                }
                for l in recent_logs
            ],
        },
        "orders": {
            "paid_total": round(paid_total, 2),
            "recharge": [
                {
                    "order_id": o.order_id,
                    "item_name": o.package.name if o.package else f"套餐 #{o.package_id}",
                    "amount": float(o.price),
                    "points": o.amount,
                    "status": o.status,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in recharge_orders
            ],
            "subscription": [
                {
                    "order_id": o.order_id,
                    "item_name": o.item_name or (o.plan.name if o.plan else f"套餐 #{o.plan_id}"),
                    "amount": float(o.amount),
                    "status": o.status,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in sub_orders
            ],
        },
        "invitation": {
            "count": db.query(models.InvitationRecord).filter(
                models.InvitationRecord.inviter_id == user_id
            ).count(),
            "rebate_total": int(rebate_total),
            "invitees": [
                {
                    "username": invitee_names.get(r.invitee_id, "未知"),
                    "reward_points": r.reward_points,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in invite_records
            ],
        },
        "checkin": {
            "total": checkin_count,
            "last_date": last_checkin.checkin_date.isoformat() if last_checkin else None,
            "streak": last_checkin.streak if last_checkin else 0,
        },
        "watch": {
            "plays": plays,
            "watched_items": watched_items,
        },
    }


@admin_router.get("/stats/trend")
def get_stats_trend(
    days: int = 14,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """趋势统计（默认近 14 天）：新增用户 / 播放次数 / 营收 / 签到

    单次聚合查询后按日补零，保证折线图连续。
    """
    from backend.emby_server import models as em

    days = max(1, min(days, 90))
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)

    def _series(rows) -> dict:
        out: dict = {}
        for day, value in rows:
            key = str(day)[:10]
            out[key] = out.get(key, 0) + (value or 0)
        return out

    user_rows = db.query(
        func.date(models.WebUser.created_at), func.count(models.WebUser.id)
    ).filter(models.WebUser.created_at >= start).group_by(
        func.date(models.WebUser.created_at)
    ).all()

    play_rows = db.query(
        func.date(em.PlaybackSession.start_time), func.count(em.PlaybackSession.id)
    ).filter(em.PlaybackSession.start_time >= start).group_by(
        func.date(em.PlaybackSession.start_time)
    ).all()

    recharge_rows = db.query(
        func.date(models.RechargeOrder.paid_at), func.coalesce(func.sum(models.RechargeOrder.price), 0)
    ).filter(
        models.RechargeOrder.status == "paid", models.RechargeOrder.paid_at >= start
    ).group_by(func.date(models.RechargeOrder.paid_at)).all()

    sub_rows = db.query(
        func.date(models.SubscriptionOrder.paid_at), func.coalesce(func.sum(models.SubscriptionOrder.amount), 0)
    ).filter(
        models.SubscriptionOrder.status == "paid", models.SubscriptionOrder.paid_at >= start
    ).group_by(func.date(models.SubscriptionOrder.paid_at)).all()

    checkin_rows = db.query(
        func.date(models.CheckinRecord.checkin_date), func.count(models.CheckinRecord.id)
    ).filter(models.CheckinRecord.checkin_date >= start).group_by(
        func.date(models.CheckinRecord.checkin_date)
    ).all()

    users_map = _series(user_rows)
    plays_map = _series(play_rows)
    recharge_map = _series(recharge_rows)
    sub_map = _series(sub_rows)
    checkin_map = _series(checkin_rows)

    series = []
    for i in range(days):
        day = start + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        series.append({
            "date": key,
            "new_users": int(users_map.get(key, 0)),
            "plays": int(plays_map.get(key, 0)),
            "revenue": round(float(recharge_map.get(key, 0)) + float(sub_map.get(key, 0)), 2),
            "checkins": int(checkin_map.get(key, 0)),
        })

    return {
        "days": days,
        "series": series,
        "totals": {
            "new_users": sum(p["new_users"] for p in series),
            "plays": sum(p["plays"] for p in series),
            "revenue": round(sum(p["revenue"] for p in series), 2),
            "checkins": sum(p["checkins"] for p in series),
        },
    }


@admin_router.get("/economy/subscriptions")
def economy_list_subscriptions(
    status_filter: str = "",
    limit: int = 50,
    offset: int = 0,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """订阅总览：全部订阅记录 + 状态筛选 + 到期概览

    status_filter: active（生效中）/ expiring（7 天内到期）/ expired（已过期）
    """
    now = datetime.now()
    week_later = now + timedelta(days=7)

    q = db.query(models.UserSubscription)
    if status_filter == "active":
        q = q.filter(models.UserSubscription.status == "active",
                     models.UserSubscription.end_date > now)
    elif status_filter == "expiring":
        q = q.filter(models.UserSubscription.status == "active",
                     models.UserSubscription.end_date > now,
                     models.UserSubscription.end_date <= week_later)
    elif status_filter == "expired":
        q = q.filter(or_(models.UserSubscription.status == "expired",
                         models.UserSubscription.end_date <= now))

    total = q.count()
    rows = q.order_by(models.UserSubscription.end_date.asc()).offset(offset).limit(min(limit, 200)).all()

    user_ids = {r.user_id for r in rows}
    users = {
        u.id: u.username
        for u in db.query(models.WebUser).filter(models.WebUser.id.in_(user_ids)).all()
    } if user_ids else {}

    active_count = db.query(models.UserSubscription).filter(
        models.UserSubscription.status == "active", models.UserSubscription.end_date > now
    ).count()
    expiring_count = db.query(models.UserSubscription).filter(
        models.UserSubscription.status == "active",
        models.UserSubscription.end_date > now,
        models.UserSubscription.end_date <= week_later,
    ).count()
    expired_count = db.query(models.UserSubscription).filter(
        or_(models.UserSubscription.status == "expired",
            models.UserSubscription.end_date <= now)
    ).count()

    return {
        "total": total,
        "summary": {
            "active": active_count,
            "expiring_7d": expiring_count,
            "expired": expired_count,
        },
        "subscriptions": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": users.get(r.user_id, "未知"),
                "plan_name": r.plan.name if r.plan else f"套餐 #{r.plan_id}",
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "days_left": _days_left(r.end_date, now),
                "status": "active" if (r.status == "active" and r.end_date and r.end_date > now) else "expired",
            }
            for r in rows
        ],
    }
