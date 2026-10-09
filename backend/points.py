# -*- coding: utf-8 -*-
"""公益服积分模块（模块2）

定位：公益服的"货币"层。复用 economy.py 的基础设施
（WebUser.points 余额 + PointsLog 流水 + _add_points 原子更新），
只提供公益服专用的业务逻辑：

- award_chat_points：发言奖励（每日上限）
- get_points_summary：积分概览
- redeem_welfare：积分兑换公益天数
- welfare_signin：公益服签到（Foam 风格：随机 1-3 分、连签奖励、15% 惩罚）

SystemConfig 键（backend/api/economy._get_int_config 读取）：
- points_signin_min=1, points_signin_max=3
- points_signin_streak_bonus=2, points_signin_streak_days=7
- points_signin_penalty_pct=15, points_signin_penalty_min=1, points_signin_penalty_max=3
- points_chat_daily_cap=20, points_chat_per_msg=1
- points_redeem_7d=100, points_redeem_30d=300
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models
from backend.api import economy

logger = logging.getLogger(__name__)


def _today_start() -> datetime:
    """今日零点"""
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _get_int(db: Session, key: str, default: int) -> int:
    """读整数配置"""
    return economy._get_int_config(db, key, default)


def award_chat_points(db: Session, user_id: int) -> int:
    """发言奖励（供聊天/评论模块调用）

    每条发言奖励 points_chat_per_msg 分，每日上限 points_chat_daily_cap 分。
    达到上限后返回 0，不再奖励。
    """
    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if user is None:
        return 0

    cap = _get_int(db, "points_chat_daily_cap", 20)
    per_msg = _get_int(db, "points_chat_per_msg", 1)

    today = _today_start()
    earned_today = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user_id,
        models.PointsLog.type == "chat",
        models.PointsLog.amount > 0,
        models.PointsLog.created_at >= today,
    ).scalar() or 0

    if earned_today >= cap:
        return 0

    # 避免单次奖励超过上限
    award = min(per_msg, cap - earned_today)
    economy._add_points(db, user, award, "chat", "发言奖励")
    db.commit()
    return award


def get_points_summary(db: Session, user: models.WebUser) -> dict:
    """积分概览：余额 / 今日获得 / 累计获得"""
    balance = int(user.points or 0)
    today = _today_start()

    today_earned = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user.id,
        models.PointsLog.amount > 0,
        models.PointsLog.created_at >= today,
    ).scalar() or 0

    total_earned = db.query(func.coalesce(func.sum(models.PointsLog.amount), 0)).filter(
        models.PointsLog.user_id == user.id,
        models.PointsLog.amount > 0,
    ).scalar() or 0

    return {
        "balance": balance,
        "today_earned": int(today_earned),
        "total_earned": int(total_earned),
    }


def redeem_welfare(db: Session, user: models.WebUser, days_option: int) -> dict:
    """积分兑换公益天数

    days_option: 只能是 7 或 30
    流程：扣分 → 调 portal.grant_welfare 开通/续期
    注意：grant_welfare 内部会 db.commit()，所以扣分后不再单独 commit
    """
    if days_option not in (7, 30):
        raise ValueError("仅支持兑换 7 天或 30 天")

    cost_key = "points_redeem_7d" if days_option == 7 else "points_redeem_30d"
    default_cost = 100 if days_option == 7 else 300
    cost = _get_int(db, cost_key, default_cost)

    balance = int(user.points or 0)
    if balance < cost:
        raise ValueError(f"积分不足，需要 {cost} 分，当前 {balance} 分")

    # 先扣分
    new_balance = economy._add_points(
        db, user, -cost, "redeem", f"积分兑换公益{days_option}天"
    )

    # 再开通（内部 commit）
    from backend.emby_server import portal
    expires_at = portal.grant_welfare(
        db, user, channel="points_redeem", days=days_option
    )

    return {
        "days": days_option,
        "cost": cost,
        "balance": new_balance,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def welfare_signin(db: Session, user: models.WebUser) -> dict:
    """公益服签到（Foam 风格）

    - 每日 1 次，随机 points_signin_min ~ points_signin_max 分
    - 连续 points_signin_streak_days 天奖励 points_signin_streak_bonus 分
    - points_signin_penalty_pct% 概率触发惩罚，扣 points_signin_penalty_min ~ max 分
    - 复用 CheckinRecord 防重（唯一索引是最后一道门）

    返回：{'points': 实际得分（可为负）, 'streak': 连签天数,
           'balance': 余额, 'penalty': 是否触发惩罚}
    """
    user_id = user.id
    today = _today_start()

    # 防重：今日已签到
    exists = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == user_id,
        models.CheckinRecord.checkin_date >= today,
    ).first()
    if exists:
        raise ValueError("今天已经签到过啦")

    # 连签：昨天有记录则 +1，否则重置为 1
    yesterday_record = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == user_id,
        models.CheckinRecord.checkin_date >= today - timedelta(days=1),
        models.CheckinRecord.checkin_date < today,
    ).order_by(models.CheckinRecord.checkin_date.desc()).first()
    streak = (yesterday_record.streak + 1) if yesterday_record else 1

    # 基础随机分
    p_min = _get_int(db, "points_signin_min", 1)
    p_max = _get_int(db, "points_signin_max", 3)
    if p_min > p_max:
        p_min, p_max = p_max, p_min
    base = random.randint(p_min, p_max)

    # 连签奖励
    streak_days = _get_int(db, "points_signin_streak_days", 7)
    streak_bonus_cfg = _get_int(db, "points_signin_streak_bonus", 2)
    bonus = streak_bonus_cfg if streak >= streak_days else 0

    # 惩罚（Foam 的点睛之笔）
    penalty_pct = _get_int(db, "points_signin_penalty_pct", 15)
    penalty = False
    penalty_amount = 0
    if random.random() * 100 < penalty_pct:
        pen_min = _get_int(db, "points_signin_penalty_min", 1)
        pen_max = _get_int(db, "points_signin_penalty_max", 3)
        if pen_min > pen_max:
            pen_min, pen_max = pen_max, pen_min
        penalty_amount = random.randint(pen_min, pen_max)
        penalty = True

    total = base + bonus - penalty_amount

    # 落库（CheckinRecord 唯一索引防并发重复）
    record = models.CheckinRecord(
        user_id=user_id,
        checkin_date=today,
        points_awarded=total,
        streak=streak,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        # 唯一索引冲突：并发重复签到
        db.rollback()
        raise ValueError("今天已经签到过啦")

    # 发分
    new_balance = economy._add_points(db, user, total, "signin", "公益签到")
    db.commit()

    return {
        "points": total,
        "streak": streak,
        "balance": new_balance,
        "penalty": penalty,
    }
