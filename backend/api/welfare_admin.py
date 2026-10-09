# -*- coding: utf-8 -*-
"""公益服管理后台 API

- GET  /welfare/users              公益用户列表
- POST /welfare/grant              开通/续期公益
- POST /welfare/revoke             取消公益资格
- POST /welfare/bulk-extend        批量延期
- GET/POST /welfare/lottery/prizes 奖品列表/新增
- PUT/DELETE /welfare/lottery/prizes/{id} 编辑/删除奖品
- GET  /welfare/lottery/logs       抽奖记录
- GET/PUT /welfare/config          公益配置读写
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.api.admin_core import admin_router, get_current_admin, _audit
from backend.database import get_db


# ==================== 公益用户管理 ====================

@admin_router.get("/welfare/users")
def welfare_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    only_welfare: bool = Query(True),
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """公益用户列表"""
    q = db.query(models.WebUser)
    if only_welfare:
        q = q.filter(models.WebUser.is_welfare == True)  # noqa: E712
    if keyword:
        q = q.filter(models.WebUser.username.like(f"%{keyword}%"))
    total = q.count()
    users = q.order_by(models.WebUser.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    from backend.emby_server import portal
    items = []
    for u in users:
        st = portal.get_welfare_status(db, u)
        items.append({
            "id": u.id,
            "username": u.username,
            "is_welfare": bool(getattr(u, "is_welfare", False)),
            "welfare_expires_at": u.welfare_expires_at.isoformat() if getattr(u, "welfare_expires_at", None) else None,
            "days_left": st["days_left"],
            "welfare_grant_channel": getattr(u, "welfare_grant_channel", None),
        })
    return {"total": total, "items": items}


class GrantRequest(BaseModel):
    user_id: int
    days: int = Field(30, description="天数，0=永不过期")
    channel: str = "admin"


@admin_router.post("/welfare/grant")
def welfare_grant(
    req: GrantRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """开通/续期公益资格"""
    user = db.query(models.WebUser).filter(models.WebUser.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    from backend.emby_server import portal
    expires = portal.grant_welfare(db, user, req.channel, req.days, granted_by=current_admin.id)
    _audit(db, current_admin.id, "welfare_grant", "user", user.id, {"days": req.days, "channel": req.channel})
    db.commit()
    return {"success": True, "expires_at": expires.isoformat() if expires else None}


class RevokeRequest(BaseModel):
    user_id: int


@admin_router.post("/welfare/revoke")
def welfare_revoke(
    req: RevokeRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """取消公益资格"""
    user = db.query(models.WebUser).filter(models.WebUser.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.is_welfare = False
    db.add(models.WelfareGrantLog(user_id=user.id, channel="admin_revoke", days=0, granted_by=current_admin.id))
    _audit(db, current_admin.id, "welfare_revoke", "user", user.id, {})
    db.commit()
    return {"success": True}


class BulkExtendRequest(BaseModel):
    min_expired_days: int = Field(0, description="过期天数下限")
    max_expired_days: int = Field(30, description="过期天数上限")
    add_days: int = Field(30, description="增加天数")


@admin_router.post("/welfare/bulk-extend")
def welfare_bulk_extend(
    req: BulkExtendRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """按过期天数范围批量延期"""
    now = datetime.now()
    users = db.query(models.WebUser).filter(models.WebUser.is_welfare == True).all()  # noqa: E712
    from backend.emby_server import portal
    affected = 0
    for u in users:
        exp = getattr(u, "welfare_expires_at", None)
        if exp is None:
            continue  # 永不过期跳过
        expired_days = (now - exp).days
        if expired_days < 0:
            continue  # 未过期跳过
        if req.min_expired_days <= expired_days <= req.max_expired_days:
            portal.grant_welfare(db, u, "bulk_extend", req.add_days, granted_by=current_admin.id)
            affected += 1
    _audit(db, current_admin.id, "welfare_bulk_extend", "system", None, {"affected": affected, "add_days": req.add_days})
    db.commit()
    return {"success": True, "affected": affected}


# ==================== 抽奖奖品管理 ====================

def _prize_to_dict(p):
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "value": p.value,
        "probability": p.probability,
        "enabled": bool(p.enabled),
    }


@admin_router.get("/welfare/lottery/prizes")
def lottery_prizes(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """奖品列表"""
    prizes = db.query(models.LotteryPrize).order_by(models.LotteryPrize.id).all()
    return [_prize_to_dict(p) for p in prizes]


class PrizeRequest(BaseModel):
    name: str
    type: str = "days"
    value: int = 0
    probability: float = 1.0
    enabled: bool = True


@admin_router.post("/welfare/lottery/prizes")
def lottery_prize_create(
    req: PrizeRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """新增奖品"""
    p = models.LotteryPrize(
        name=req.name, type=req.type, value=req.value,
        probability=req.probability, enabled=req.enabled,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    _audit(db, current_admin.id, "lottery_prize_create", "lottery_prize", p.id, {"name": req.name})
    db.commit()
    return _prize_to_dict(p)


class PrizeUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    value: Optional[int] = None
    probability: Optional[float] = None
    enabled: Optional[bool] = None


@admin_router.put("/welfare/lottery/prizes/{prize_id}")
def lottery_prize_update(
    prize_id: int,
    req: PrizeUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """编辑奖品"""
    p = db.query(models.LotteryPrize).filter(models.LotteryPrize.id == prize_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="奖品不存在")
    for field in ("name", "type", "value", "probability", "enabled"):
        v = getattr(req, field)
        if v is not None:
            setattr(p, field, v)
    _audit(db, current_admin.id, "lottery_prize_update", "lottery_prize", p.id, {})
    db.commit()
    return _prize_to_dict(p)


@admin_router.delete("/welfare/lottery/prizes/{prize_id}")
def lottery_prize_delete(
    prize_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除奖品"""
    p = db.query(models.LotteryPrize).filter(models.LotteryPrize.id == prize_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="奖品不存在")
    _audit(db, current_admin.id, "lottery_prize_delete", "lottery_prize", prize_id, {"name": p.name})
    db.delete(p)
    db.commit()
    return {"success": True}


@admin_router.get("/welfare/lottery/logs")
def lottery_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """抽奖记录"""
    q = db.query(models.LotteryLog).order_by(models.LotteryLog.id.desc())
    total = q.count()
    logs = q.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for log in logs:
        items.append({
            "id": log.id,
            "username": log.user.username if log.user else "",
            "prize_name": log.prize.name if log.prize else "",
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })
    return {"total": total, "items": items}


# ==================== 求片审核 ====================

def _request_to_dict(r):
    return {
        "id": r.id,
        "title": r.title,
        "media_type": r.media_type,
        "tmdb_id": r.tmdb_id,
        "username": r.user.username if r.user else "",
        "status": r.status,
        "admin_note": r.admin_note or "",
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@admin_router.get("/welfare/requests")
def welfare_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """求片审核列表"""
    q = db.query(models.MediaRequest).order_by(models.MediaRequest.id.desc())
    if status:
        q = q.filter(models.MediaRequest.status == status)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_request_to_dict(r) for r in items]}


class RequestNote(BaseModel):
    admin_note: str = ""


@admin_router.post("/welfare/requests/{request_id}/approve")
def welfare_request_approve(
    request_id: int,
    req: RequestNote,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """通过求片"""
    r = db.query(models.MediaRequest).filter(models.MediaRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="求片记录不存在")
    r.status = "approved"
    r.admin_note = req.admin_note
    _audit(db, current_admin.id, "welfare_request_approve", "media_request", r.id, {"title": r.title})
    db.commit()
    return {"success": True}


@admin_router.post("/welfare/requests/{request_id}/reject")
def welfare_request_reject(
    request_id: int,
    req: RequestNote,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """拒绝求片"""
    r = db.query(models.MediaRequest).filter(models.MediaRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="求片记录不存在")
    r.status = "rejected"
    r.admin_note = req.admin_note
    _audit(db, current_admin.id, "welfare_request_reject", "media_request", r.id, {"title": r.title})
    db.commit()
    return {"success": True}


@admin_router.post("/welfare/requests/{request_id}/done")
def welfare_request_done(
    request_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """标记求片已入库"""
    r = db.query(models.MediaRequest).filter(models.MediaRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="求片记录不存在")
    r.status = "done"
    _audit(db, current_admin.id, "welfare_request_done", "media_request", r.id, {"title": r.title})
    db.commit()
    return {"success": True}


# ==================== 公益配置 ====================

WELFARE_CONFIG_KEYS = {
    "points_signin_min": "1",
    "points_signin_max": "3",
    "points_signin_streak_bonus": "2",
    "points_chat_daily_cap": "20",
    "points_redeem_7d": "100",
    "points_redeem_30d": "300",
    "welfare_grace_days": "7",
    "welfare_inactive_days": "30",
    "welfare_request_monthly": "3",
    "lottery_cost": "10",
    # P0 统一货币体系：充值比例与红包规则
    "recharge_ratio": "1.2",
    "redpacket_fee_pct": "5",
    "redpacket_send_limit_7d": "20",
    "redpacket_recv_limit_7d": "10",
    # TG 门禁：公益服能力（签到/积分/红包/抽奖）是否要求绑定 Telegram
    "welfare_require_tg_bind": "1",
    # 注册后 TG 绑定引导页总开关
    "tg_bind_guide_enabled": "1",
# M1 群发言积分：总开关默认关闭，服主手动开启
    "chat_points_enabled": "false",
    "chat_points_group_ids": "",
    "chat_points_per_message": "1",
    "chat_points_min_len": "2",
    "chat_points_minute_window": "60",
    "chat_points_daily_cap": "20",
    "chat_points_points_per_day": "100",
}


@admin_router.get("/welfare/config")
def welfare_config_get(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """读取公益配置"""
    result = {}
    for key, default in WELFARE_CONFIG_KEYS.items():
        cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        result[key] = cfg.value if cfg else default
    return result


@admin_router.put("/welfare/config")
def welfare_config_set(
    data: dict,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """保存公益配置"""
    updated = []
    for key, value in data.items():
        if key not in WELFARE_CONFIG_KEYS:
            continue
        cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if cfg:
            cfg.value = str(value)
        else:
            db.add(models.SystemConfig(key=key, value=str(value)))
        updated.append(key)
    _audit(db, current_admin.id, "welfare_config_update", "system", None, {"updated": updated})
    db.commit()
    return {"success": True, "updated": updated}
