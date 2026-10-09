# -*- coding: utf-8 -*-
"""会员经验核心模块：等级种子、经验自增、等级重算与用户端会员信息。"""

import json
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger(__name__)

# 默认 6 个等级的种子数据
DEFAULT_LEVELS = [
    {
        "level": 1,
        "name": "普通会员",
        "xp_threshold": 0,
        "badge_icon": "User",
        "badge_color": "#9ca3af",
        "benefits": ["基础观影权益", "每日签到"],
    },
    {
        "level": 2,
        "name": "铜牌会员",
        "xp_threshold": 100,
        "badge_icon": "Medal",
        "badge_color": "#cd7f32",
        "benefits": ["铜牌专属徽章", "邀请奖励加成"],
    },
    {
        "level": 3,
        "name": "白银会员",
        "xp_threshold": 500,
        "badge_icon": "Award",
        "badge_color": "#c0c0c0",
        "benefits": ["白银专属徽章", "优先客服"],
    },
    {
        "level": 4,
        "name": "黄金会员",
        "xp_threshold": 1500,
        "badge_icon": "Crown",
        "badge_color": "#ffd700",
        "benefits": ["黄金专属徽章", "专属客服通道"],
    },
    {
        "level": 5,
        "name": "铂金会员",
        "xp_threshold": 5000,
        "badge_icon": "Gem",
        "badge_color": "#e5e4e2",
        "benefits": ["铂金专属徽章", "新片优先通知"],
    },
    {
        "level": 6,
        "name": "钻石会员",
        "xp_threshold": 15000,
        "badge_icon": "Sparkles",
        "badge_color": "#b9f2ff",
        "benefits": ["钻石专属徽章", "专属活动邀请"],
    },
]


def _parse_benefits(benefits_json):
    """容错解析 benefits_json，失败时返回空列表。"""
    if not benefits_json:
        return []
    try:
        data = json.loads(benefits_json)
    except (ValueError, TypeError) as exc:
        logger.warning("benefits_json 解析失败: %s", exc)
        return []
    return data if isinstance(data, list) else []


def ensure_member_levels_seeded(db: Session) -> int:
    """幂等种子：member_levels 表为空时插入 DEFAULT_LEVELS，返回插入数量。"""
    count = db.query(models.MemberLevel).count()
    if count > 0:
        return 0
    for item in DEFAULT_LEVELS:
        db.add(
            models.MemberLevel(
                level=item["level"],
                name=item["name"],
                xp_threshold=item["xp_threshold"],
                badge_icon=item["badge_icon"],
                badge_color=item["badge_color"],
                benefits_json=json.dumps(item["benefits"], ensure_ascii=False),
                is_active=True,
            )
        )
    try:
        db.commit()
    except Exception:
        db.rollback()
        # 并发场景下可能已被其他进程播种
        if db.query(models.MemberLevel).count() > 0:
            return 0
        raise
    logger.info("会员等级种子写入完成，共 %d 条", len(DEFAULT_LEVELS))
    return len(DEFAULT_LEVELS)


def _recompute_level(db: Session, user: models.WebUser) -> int:
    """根据当前 member_xp 计算应属等级，仅在变化时用 SQL 级 update 写回。

    不提交事务：调用方负责 commit（履约等场景要求「更新与发货在同一事务里」）。
    """
    # 从库里重读真实 xp：调用方可能刚做了 SQL 级自增，ORM 对象未必已同步
    xp = int(
        db.query(models.WebUser.member_xp)
        .filter(models.WebUser.id == user.id)
        .scalar()
        or 0
    )
    levels = (
        db.query(models.MemberLevel)
        .filter(models.MemberLevel.is_active == True)  # noqa: E712
        .order_by(models.MemberLevel.xp_threshold.asc())
        .all()
    )
    # 取阈值 <= xp 的最大 level，没有则返回 1
    candidates = [lv.level for lv in levels if (lv.xp_threshold or 0) <= xp]
    target = max(candidates) if candidates else 1
    current = user.member_level or 1
    if current != target:
        db.query(models.WebUser).filter(models.WebUser.id == user.id).update(
            {models.WebUser.member_level: target},
            synchronize_session="fetch",
        )
        logger.info("用户 %s 等级变更: %s -> %s", user.id, current, target)
    return target


def add_xp(
    db: Session,
    user: models.WebUser,
    delta: int,
    source: str,
    ref_id: str | None = None,
) -> dict:
    """累加会员经验并写流水、重算等级。

    约定与 ``_add_points`` 一致：**不提交事务**，只做 SQL 级自增 + 添流水对象，
    由调用方统一 commit（履约场景要求积分/经验/订单状态在同一事务里）。
    """
    if delta <= 0:
        return {"added": False}

    old_level = user.member_level or 1

    # SQL 级自增 member_xp，防并发丢更新
    db.query(models.WebUser).filter(models.WebUser.id == user.id).update(
        {models.WebUser.member_xp: func.coalesce(models.WebUser.member_xp, 0) + delta},
        synchronize_session="fetch",
    )

    # 查回真实 xp_after（读自己事务内的写入）
    xp_after = int(
        db.query(models.WebUser.member_xp)
        .filter(models.WebUser.id == user.id)
        .scalar()
        or 0
    )

    # 写经验流水
    db.add(
        models.MemberXpLog(
            user_id=user.id,
            xp_delta=delta,
            xp_after=xp_after,
            source=source,
            ref_id=ref_id,
        )
    )

    # 重算等级并检测是否升级
    level = _recompute_level(db, user)
    leveled_up = level > old_level
    if leveled_up:
        logger.info("用户 %s 升级: %s -> %s", user.id, old_level, level)

    return {
        "added": True,
        "xp_after": xp_after,
        "level": level,
        "leveled_up": leveled_up,
        "old_level": old_level,
    }


def get_member_info(db: Session, user: models.WebUser) -> dict:
    """用户端 /api/user/member 使用：等级列表 + 当前等级 + 进度。"""
    # 确保种子存在
    ensure_member_levels_seeded(db)

    rows = (
        db.query(models.MemberLevel)
        .filter(models.MemberLevel.is_active == True)  # noqa: E712
        .order_by(models.MemberLevel.level.asc())
        .all()
    )
    levels = []
    for lv in rows:
        levels.append(
            {
                "level": lv.level,
                "name": lv.name,
                "xp_threshold": lv.xp_threshold or 0,
                "benefits": _parse_benefits(lv.benefits_json),
                "badge_icon": lv.badge_icon,
                "badge_color": lv.badge_color,
            }
        )

    xp = user.member_xp or 0
    level = user.member_level or 1

    # 当前等级信息
    current = next((item for item in levels if item["level"] == level), None)
    if current is None:
        # 兜底：取不超过当前经验的最高等级，否则用第一级
        fallback = [item for item in levels if item["xp_threshold"] <= xp]
        current = fallback[-1] if fallback else (levels[0] if levels else None)
        level = current["level"] if current else 1

    level_name = current["name"] if current else "普通会员"
    badge_icon = current["badge_icon"] if current else "User"
    badge_color = current["badge_color"] if current else "#9ca3af"
    cur_threshold = current["xp_threshold"] if current else 0

    # 下一级阈值与进度
    higher = [item for item in levels if item["level"] > level]
    if higher:
        nxt = higher[0]
        next_level = nxt["level"]
        next_threshold = nxt["xp_threshold"]
        xp_to_next = max(0, next_threshold - xp)
        span = next_threshold - cur_threshold
        if span <= 0:
            progress_pct = 100.0
        else:
            progress_pct = min(
                100.0, max(0.0, (xp - cur_threshold) / span * 100.0)
            )
    else:
        # 满级
        next_level = None
        next_threshold = None
        xp_to_next = None
        progress_pct = 100.0

    return {
        "level": level,
        "level_name": level_name,
        "xp": xp,
        "badge_icon": badge_icon,
        "badge_color": badge_color,
        "next_level": next_level,
        "next_threshold": next_threshold,
        "xp_to_next": xp_to_next,
        "progress_pct": round(progress_pct, 2),
        "levels": levels,
    }

