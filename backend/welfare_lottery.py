# -*- coding: utf-8 -*-
"""抽奖业务逻辑（公益服模块3-娱乐板块）

手动编写（OpenRouter 免费模型 429 限流，按 backend/points.py 模式手写）。

规则：
- 每次抽奖消耗 lottery_cost 积分（默认 10，SystemConfig 可调）
- 按奖品 probability 权重随机
- 中奖后自动发放：
  - days: 调用 portal.grant_welfare 续公益天数（channel="lottery"）
  - points: 直接加积分
  - whitelist: grant_welfare(days=0) 永不过期
- 默认奖品在首次抽奖时自动初始化（幂等）

SystemConfig 键：
- lottery_cost=10
"""

from __future__ import annotations

import logging
import random

from sqlalchemy.orm import Session

from backend import models
from backend.api import economy

logger = logging.getLogger(__name__)

# 默认奖品：(name, type, value, probability 权重)
DEFAULT_PRIZES = [
    ("7天公益", "days", 7, 40.0),
    ("30天公益", "days", 30, 10.0),
    ("50积分", "points", 50, 30.0),
    ("100积分", "points", 100, 15.0),
    ("白名单（永久）", "whitelist", 0, 1.0),
]


def _get_int(db: Session, key: str, default: int) -> int:
    return economy._get_int_config(db, key, default)


def ensure_default_prizes(db: Session) -> None:
    """幂等初始化默认奖品"""
    exists = db.query(models.LotteryPrize).count()
    if exists:
        return
    for name, ptype, value, prob in DEFAULT_PRIZES:
        db.add(models.LotteryPrize(
            name=name, type=ptype, value=value,
            probability=prob, enabled=True,
        ))
    db.commit()
    logger.info("抽奖默认奖品已初始化")


def list_prizes(db: Session) -> list:
    """奖品列表（启用的）"""
    ensure_default_prizes(db)
    prizes = db.query(models.LotteryPrize).filter(
        models.LotteryPrize.enabled == True  # noqa: E712
    ).order_by(models.LotteryPrize.id).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "type": p.type,
            "value": p.value,
        }
        for p in prizes
    ]


def draw(db: Session, user: models.WebUser) -> dict:
    """抽奖一次

    流程：检查积分 → 扣分 → 权重随机 → 发放奖品 → 写记录
    """
    ensure_default_prizes(db)

    cost = _get_int(db, "lottery_cost", 10)
    balance = int(user.points or 0)
    if balance < cost:
        raise ValueError(f"积分不足，抽奖需要 {cost} 分，当前 {balance} 分")

    prizes = db.query(models.LotteryPrize).filter(
        models.LotteryPrize.enabled == True  # noqa: E712
    ).all()
    if not prizes:
        raise ValueError("暂无可用奖品")

    # 权重随机
    total = sum(p.probability for p in prizes)
    if total <= 0:
        raise ValueError("奖品概率配置错误")
    r = random.uniform(0, total)
    acc = 0.0
    prize = prizes[-1]
    for p in prizes:
        acc += p.probability
        if r <= acc:
            prize = p
            break

    # 扣分
    economy._add_points(db, user, -cost, "lottery", f"抽奖消耗 {cost} 分")

    # 发放奖品
    grant_info = _grant_prize(db, user, prize)

    # 写抽奖记录
    db.add(models.LotteryLog(user_id=user.id, prize_id=prize.id))
    db.commit()

    logger.info("抽奖: user=%s prize=%s", user.id, prize.name)
    return {
        "prize": {"id": prize.id, "name": prize.name, "type": prize.type, "value": prize.value},
        "grant": grant_info,
        "cost": cost,
    }


def _grant_prize(db: Session, user: models.WebUser, prize: models.LotteryPrize) -> dict:
    """发放奖品"""
    # 延迟导入，避免循环依赖
    from backend.emby_server import portal

    if prize.type == "days":
        portal.grant_welfare(db, user, "lottery", prize.value)
        db.commit()
        return {"type": "days", "days": prize.value}
    elif prize.type == "points":
        new_balance = economy._add_points(
            db, user, prize.value, "lottery", f"抽奖获得 {prize.value} 分")
        db.commit()
        return {"type": "points", "points": prize.value, "balance": new_balance}
    elif prize.type == "whitelist":
        portal.grant_welfare(db, user, "lottery", 0)  # days=0 永不过期
        db.commit()
        return {"type": "whitelist", "days": 0}
    else:
        raise ValueError(f"未知奖品类型：{prize.type}")


def my_logs(db: Session, user: models.WebUser, page: int = 1, page_size: int = 20) -> dict:
    """我的抽奖记录"""
    q = db.query(models.LotteryLog).filter(
        models.LotteryLog.user_id == user.id
    ).order_by(models.LotteryLog.id.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    prize_ids = {l.prize_id for l in items}
    prizes = {p.id: p.name for p in db.query(models.LotteryPrize).filter(
        models.LotteryPrize.id.in_(prize_ids)).all()} if prize_ids else {}

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": l.id,
                "prize_id": l.prize_id,
                "prize_name": prizes.get(l.prize_id, "未知"),
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in items
        ],
    }
