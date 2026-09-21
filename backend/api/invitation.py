"""
邀请返利 API（统一后端）

端点（前缀 /api/user/invite）：
- GET  /config          邀请规则（开关/奖励点数）——公开
- GET  /my-code         我的邀请码（自动生成），含统计
- GET  /records         我邀请的记录
- GET  /rebates         我的返利台账（被邀请人充值产生的返利）
- apply_invitation      供注册流程调用的内部函数
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db
from backend.api.user import get_current_user
from backend.api.economy import _add_points

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user/invite", tags=["用户端-邀请返利"])

CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_invite_code(db: Session) -> str:
    """生成不冲突的邀请码（8 位）"""
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(models.InvitationCode).filter(
            models.InvitationCode.code == code
        ).first():
            return code


def _get_config(db: Session, key: str, default: str) -> str:
    config = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return config.value if config and config.value is not None else default


def _get_int_config(db: Session, key: str, default: int) -> int:
    try:
        return int(_get_config(db, key, str(default)))
    except (TypeError, ValueError):
        return default


def _get_bool_config(db: Session, key: str, default: bool) -> bool:
    return _get_config(db, key, "true" if default else "false").strip().lower() == "true"


def get_invite_config(db: Session) -> dict:
    """邀请配置（管理端 SystemConfig 可调）"""
    return {
        "enabled": _get_bool_config(db, "invitation_enabled", True),
        "reward_points": _get_int_config(db, "invitation_reward_points", 100),
        "invitee_reward_points": _get_int_config(db, "invitation_invitee_reward_points", 50),
        "rebate_percent": _get_int_config(db, "invitation_rebate_percent", 10),
    }


def apply_invitation(db: Session, user: models.WebUser, invite_code: str) -> dict:
    """注册流程调用：应用邀请码，双向发奖，写邀请记录。失败静默（不阻塞注册）"""
    config = get_invite_config(db)
    if not config["enabled"] or not invite_code:
        return {"applied": False}

    code_str = invite_code.strip().upper()
    code = db.query(models.InvitationCode).filter(
        models.InvitationCode.code == code_str,
        models.InvitationCode.is_active == True,  # noqa: E712
    ).first()
    if not code or code.user_id == user.id:
        return {"applied": False}
    if code.max_uses and code.use_count >= code.max_uses:
        return {"applied": False}

    now = datetime.now()
    if code.expires_at and code.expires_at < now:
        return {"applied": False}

    inviter = db.query(models.WebUser).filter(
        models.WebUser.id == code.user_id
    ).first()
    if not inviter:
        return {"applied": False}

    # 幂等：同一个被邀请人只能建立一次关系（重试/重复调用不得重复发奖）
    existing = db.query(models.InvitationRecord).filter(
        models.InvitationRecord.invitee_id == user.id
    ).first()
    if existing:
        logger.info("邀请关系已存在，跳过重复发奖: invitee=%s", user.id)
        return {"applied": False}

    # 记录邀请关系
    record = models.InvitationRecord(
        inviter_id=inviter.id,
        invitee_id=user.id,
        code_id=code.id,
        reward_points=config["reward_points"],
    )
    db.add(record)

    # 邀请者奖励
    inviter_balance = _add_points(
        db, inviter, config["reward_points"], "invite",
        f"成功邀请用户 {user.username}", f"invite:{user.id}",
    )
    # 被邀请者奖励
    invitee_balance = _add_points(
        db, user, config["invitee_reward_points"], "invitee",
        f"使用邀请码 {code_str} 注册", f"invited_by:{inviter.id}",
    )

    code.use_count = (code.use_count or 0) + 1
    try:
        # 唯一索引 invitee_id 兜底：并发重复调用时让冲突在此暴露并整体回滚，
        # 不会出现「发了奖但没有关系记录」
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("邀请关系并发重复，已回滚: invitee=%s", user.id)
        return {"applied": False}
    except OperationalError:
        # 数据库写锁竞争（SQLite 读写事务升级失败）：整体回滚，不留下半截发奖
        db.rollback()
        logger.warning("邀请发奖遇到写锁竞争，已回滚: invitee=%s", user.id)
        return {"applied": False}

    logger.info("邀请关系建立: inviter=%s invitee=%s code=%s",
                inviter.id, user.id, code_str)
    return {
        "applied": True,
        "inviter_id": inviter.id,
        "inviter_reward": config["reward_points"],
        "invitee_reward": config["invitee_reward_points"],
        "inviter_balance": inviter_balance,
        "invitee_balance": invitee_balance,
    }


def apply_rebate(db: Session, user: models.WebUser, amount: float, order_ref: str) -> int:
    """充值返利：被邀请人充值成功后，给邀请人发放返利积分（供支付履约调用）

    返回返利积分数量（无邀请关系或返利未开启时返回 0）
    """
    record = db.query(models.InvitationRecord).filter(
        models.InvitationRecord.invitee_id == user.id
    ).first()
    if not record:
        return 0

    inviter = db.query(models.WebUser).filter(
        models.WebUser.id == record.inviter_id
    ).first()
    if not inviter:
        return 0

    config = get_invite_config(db)
    if not config["enabled"] or config["rebate_percent"] <= 0:
        return 0

    rebate = max(1, int(amount * config["rebate_percent"] / 100))
    _add_points(
        db, inviter, rebate, "rebate",
        f"下级充值返利 {config['rebate_percent']}%（+{rebate} 积分）",
        f"rebate:{order_ref}",
    )
    logger.info("充值返利: inviter=%s invitee=%s order=%s rebate=%s",
                inviter.id, user.id, order_ref, rebate)
    return rebate


# ==================== Endpoints ====================

class InviteConfigResponse(BaseModel):
    enabled: bool
    reward_points: int
    invitee_reward_points: int
    rebate_percent: int


@router.get("/config", response_model=InviteConfigResponse)
async def invite_config(db: Session = Depends(get_db)):
    return InviteConfigResponse(**get_invite_config(db))


@router.get("/my-code")
async def my_code(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的邀请码（没有则自动生成）+ 邀请统计"""
    code = db.query(models.InvitationCode).filter(
        models.InvitationCode.user_id == current_user.id,
        models.InvitationCode.is_active == True,  # noqa: E712
    ).first()
    if not code:
        code = models.InvitationCode(
            code=_generate_invite_code(db),
            user_id=current_user.id,
            reward_points=get_invite_config(db)["reward_points"],
        )
        db.add(code)
        db.commit()
        db.refresh(code)

    invited_count = db.query(models.InvitationRecord).filter(
        models.InvitationRecord.inviter_id == current_user.id
    ).count()

    return {
        "code": code.code,
        "use_count": code.use_count or 0,
        "max_uses": code.max_uses,
        "invited_count": invited_count,
        "config": get_invite_config(db),
    }


@router.get("/records")
async def my_invitation_records(
    limit: int = 50,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我邀请的用户列表"""
    records = db.query(models.InvitationRecord).filter(
        models.InvitationRecord.inviter_id == current_user.id
    ).order_by(models.InvitationRecord.created_at.desc()).limit(min(limit, 200)).all()

    items = []
    for r in records:
        invitee = db.query(models.WebUser).filter(models.WebUser.id == r.invitee_id).first()
        items.append({
            "id": r.id,
            "invitee_username": invitee.username if invitee else "已注销",
            "reward_points": r.reward_points,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"total": len(items), "records": items}


@router.get("/rebates")
async def my_rebates(
    limit: int = 50,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的返利台账：被邀请人充值/购买产生的积分返利流水"""
    logs = db.query(models.PointsLog).filter(
        models.PointsLog.user_id == current_user.id,
        models.PointsLog.type == "rebate",
    ).order_by(models.PointsLog.created_at.desc()).limit(min(limit, 200)).all()

    total_rebate = sum(l.amount for l in logs if l.amount > 0)
    return {
        "total_rebate": total_rebate,
        "rebates": [
            {
                "id": l.id,
                "amount": l.amount,
                "description": l.description,
                "ref_id": l.ref_id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }
