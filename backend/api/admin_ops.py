"""
管理后台运营 API（卡码体系 / 设备风控 / 登录与安全日志）

借鉴 twilight-kotomi 的运营面板核心运营能力，与 `backend/api/admin.py`
（用户、套餐、经济、审计等既有管理面）分文件维护，避免单文件继续膨胀。

- 卡码：类型化生成（注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码）、总览统计、停用与回收
- 设备：跨用户设备审查、封禁（同时吊销该设备令牌）、移除（踢下线）
- 日志：登录成功/失败、设备超限、诱饵码触发等风控事件筛选与清理

鉴权与管理端完全一致：复用 `get_current_admin`（is_staff 的 WebUser）+ JWT。
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend import authlog, codes, devices, models, realms, share_guard
from backend.api.admin_core import _audit, get_current_admin
from backend.database import get_db

logger = logging.getLogger(__name__)

admin_ops_router = APIRouter(prefix="/api/admin", tags=["管理后台·运营"])


# ==================== 卡码体系 ====================


def _code_state(code: models.RegistrationCode, now: datetime) -> str:
    if not code.is_active:
        return "disabled"
    if code.expires_at and code.expires_at < now:
        return "expired"
    if code.max_uses and (code.use_count or 0) >= code.max_uses:
        return "used_up"
    return "active"


def _code_usernames(db: Session, code: models.RegistrationCode) -> list:
    ids = [int(i) for i in str(code.used_by or "").split(",") if str(i).strip().isdigit()]
    if not ids:
        return []
    rows = db.query(models.WebUser.id, models.WebUser.username).filter(
        models.WebUser.id.in_(ids)
    ).all()
    return [{"id": r[0], "username": r[1]} for r in rows]


def code_dto(db: Session, code: models.RegistrationCode, now: Optional[datetime] = None,
             realm_names: Optional[dict] = None) -> dict:
    now = now or datetime.now()
    code_type = int(code.code_type or codes.CODE_TYPE_REGISTER)
    days = code.days if code.days is not None else codes.DEFAULT_DAYS
    if realm_names is None:
        realm_names = {r.id: r.name for r in realms.list_realms(db)}
    return {
        "id": code.id,
        "code": code.code,
        # 卡码是一个服一个的：它开的是哪个服的会员，列表里得看得出来
        "realm_id": code.realm_id,
        "realm_name": realm_names.get(code.realm_id, "") if code.realm_id else "",
        "code_type": code_type,
        "code_type_name": codes.CODE_TYPE_NAMES.get(code_type, "卡码"),
        "days": days,
        "days_text": codes.format_days(days),
        "is_permanent": days < 0,
        "is_decoy": codes.is_honeypot(code),
        "target_username": code.target_username or "",
        "source": code.source or "admin",
        "max_uses": code.max_uses,
        "use_count": code.use_count or 0,
        "is_active": bool(code.is_active),
        "state": _code_state(code, now),
        "note": code.note,
        "expires_at": code.expires_at.isoformat() if code.expires_at else None,
        "used_by": _code_usernames(db, code),
        "created_at": code.created_at.isoformat() if code.created_at else None,
    }


@admin_ops_router.get("/registration-codes/list")
def list_codes(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    code_type: Optional[int] = None,
    state: str = "",
    keyword: str = "",
    realm_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
):
    """卡码列表（类型 / 状态 / 关键字 / 归属服筛选 + 分页）

    卡码是一个服一个的：``realm_id=0`` 看全部服，不传看当前服。
    """
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope(db.query(models.RegistrationCode),
                         models.RegistrationCode.realm_id, scope_id)
    if code_type:
        query = query.filter(models.RegistrationCode.code_type == code_type)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(
            models.RegistrationCode.code.ilike(like),
            models.RegistrationCode.note.ilike(like),
            models.RegistrationCode.target_username.ilike(like),
        ))

    now = datetime.now()
    rows = query.order_by(models.RegistrationCode.created_at.desc()).all()
    if state:
        rows = [r for r in rows if _code_state(r, now) == state]
    total = len(rows)
    page = rows[max(offset, 0):max(offset, 0) + min(max(limit, 1), 300)]
    realm_names = {r.id: r.name for r in realms.list_realms(db)}
    return {
        "total": total,
        "realm_id": scope_id,
        "realm_name": realms.get_realm(db, scope_id).name if scope_id else "全部服",
        "realms": [{"id": r.id, "name": r.name} for r in realms.list_realms(db)],
        "codes": [code_dto(db, c, now, realm_names) for c in page],
    }


@admin_ops_router.get("/registration-codes/stats")
def code_stats(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    realm_id: Optional[int] = None,
):
    """卡码总览：按类型统计 + 诱饵命中 + 累计授予天数（按服；``realm_id=0`` 为全部服）"""
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    rows = realms.scope(db.query(models.RegistrationCode),
                        models.RegistrationCode.realm_id, scope_id).all()
    now = datetime.now()
    by_type: dict = {}
    counters = {"active": 0, "disabled": 0, "expired": 0, "used_up": 0}
    decoy_total = decoy_triggered = 0
    days_granted = 0

    for c in rows:
        code_type = int(c.code_type or codes.CODE_TYPE_REGISTER)
        days = c.days if c.days is not None else codes.DEFAULT_DAYS
        used = c.use_count or 0
        counters[_code_state(c, now)] += 1

        if codes.is_honeypot(c):
            decoy_total += 1
            if used:
                decoy_triggered += 1
        elif days > 0:
            days_granted += days * used

        bucket = by_type.setdefault(code_type, {
            "code_type": code_type,
            "code_type_name": codes.CODE_TYPE_NAMES.get(code_type, "卡码"),
            "total": 0,
            "used": 0,
            "available": 0,
        })
        bucket["total"] += 1
        bucket["used"] += used
        if _code_state(c, now) == "active":
            bucket["available"] += 1

    return {
        "total": len(rows),
        "active": counters["active"],
        "disabled": counters["disabled"],
        "expired": counters["expired"],
        "used_up": counters["used_up"],
        "decoy": {"total": decoy_total, "triggered": decoy_triggered},
        "days_granted": days_granted,
        "realm_id": scope_id,
        "realm_name": realms.get_realm(db, scope_id).name if scope_id else "全部服",
        "by_type": sorted(by_type.values(), key=lambda x: x["code_type"]),
    }


class CodeGenerateRequest(BaseModel):
    """类型化卡码生成"""
    code_type: int = Field(default=codes.CODE_TYPE_REGISTER, ge=1, le=3)
    count: int = Field(default=1, ge=1, le=200)
    days: Optional[int] = Field(default=None, ge=-1, le=36500)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_days: int = Field(default=30, ge=1, le=3650)
    algorithm: str = codes.DEFAULT_ALGORITHM
    is_decoy: bool = False
    target_username: str = ""
    note: str = ""
    # 这张卡码开通哪个服的会员（留空 = 当前服）
    realm_id: Optional[int] = None


@admin_ops_router.post("/registration-codes/generate")
def generate_codes(
    request: CodeGenerateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量生成类型化卡码"""
    if request.algorithm not in codes.RANDOM_ALGORITHMS:
        raise HTTPException(status_code=400, detail="随机算法不支持")

    days = request.days if request.days is not None else codes.DEFAULT_DAYS
    if request.code_type == codes.CODE_TYPE_WHITELIST:
        days = -1  # 白名单码语义即长期有效（与 codes.grant_days_for 口径一致）

    target_username = (request.target_username or "").strip()
    if target_username:
        exists = db.query(models.WebUser).filter(
            func.lower(models.WebUser.username) == target_username.lower()
        ).first()
        if not exists:
            raise HTTPException(status_code=400, detail=f"指名账号不存在：{target_username}")

    target_realm = realms.claim(db, request.realm_id)
    if not realms.get_realm(db, target_realm):
        raise HTTPException(status_code=400, detail=f"服不存在: #{target_realm}")

    expires_at = datetime.now() + timedelta(days=request.expires_days)
    created = []
    for index in range(1, request.count + 1):
        raw = ""
        for _attempt in range(20):
            raw = codes.render_code(
                code_type=request.code_type, days=days, index=index,
                algorithm=request.algorithm, decoy=bool(request.is_decoy),
            )
            if not db.query(models.RegistrationCode).filter(
                models.RegistrationCode.code == raw
            ).first():
                break
        else:
            raise HTTPException(status_code=500, detail="卡码生成冲突，请重试")

        code = models.RegistrationCode(
            code=raw,
            max_uses=request.max_uses,
            use_count=0,
            is_active=True,
            note=request.note or None,
            expires_at=expires_at,
            created_by=current_admin.id,
            code_type=request.code_type,
            days=days,
            target_username=target_username or None,
            source="admin",
            realm_id=target_realm,
        )
        db.add(code)
        created.append(code)

    db.commit()
    for c in created:
        db.refresh(c)

    type_name = codes.CODE_TYPE_NAMES.get(request.code_type, "卡码")
    realm_name = codes.realm_label(db, target_realm)
    _audit(db, current_admin, "generate_registration_codes", "registration_code",
           created[0].id if created else None,
           {"count": request.count, "code_type": request.code_type, "days": days,
            "is_decoy": request.is_decoy, "target_username": target_username or None,
            "realm_id": target_realm})
    db.commit()

    return {
        "success": True,
        "message": f"已生成 {len(created)} 个{type_name}（「{realm_name}」的会员）",
        "realm_id": target_realm,
        "realm_name": realm_name,
        "codes": [
            {"id": c.id, "code": c.code, "days_text": codes.format_days(days),
             "expires_at": c.expires_at.isoformat()}
            for c in created
        ],
    }


class CodeUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    note: Optional[str] = None
    # 改归属服：改之前先确认（这张码还没被用过才安全）
    realm_id: Optional[int] = None


@admin_ops_router.patch("/registration-codes/{code_id}")
def update_code(
    code_id: int,
    request: CodeUpdateRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改卡码：启用 / 停用 / 备注"""
    code = db.query(models.RegistrationCode).filter(
        models.RegistrationCode.id == code_id
    ).first()
    if not code:
        raise HTTPException(status_code=404, detail="卡码不存在")

    if request.is_active is not None:
        code.is_active = request.is_active
    if request.note is not None:
        code.note = request.note or None
    if request.realm_id is not None and int(request.realm_id) != int(code.realm_id or 0):
        if not realms.get_realm(db, request.realm_id):
            raise HTTPException(status_code=400, detail=f"服不存在: #{request.realm_id}")
        if code.use_count:
            # 已核销的卡码换服会让「开通的是哪个服的会员」对不上账
            raise HTTPException(status_code=400, detail="该卡码已被使用，不能改归属服")
        code.realm_id = int(request.realm_id)
    db.commit()

    _audit(db, current_admin, "update_registration_code", "registration_code", code.id,
           {"is_active": code.is_active, "note": code.note, "realm_id": code.realm_id})
    db.commit()
    return {"success": True, "code": code_dto(db, code)}


@admin_ops_router.delete("/registration-codes/{code_id}")
def delete_code(
    code_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除卡码：已核销的保留审计只允许停用"""
    code = db.query(models.RegistrationCode).filter(
        models.RegistrationCode.id == code_id
    ).first()
    if not code:
        raise HTTPException(status_code=404, detail="卡码不存在")
    if code.use_count:
        raise HTTPException(status_code=400, detail="该卡码已被使用，只能停用不能删除")

    raw = code.code
    db.delete(code)
    db.commit()
    _audit(db, current_admin, "delete_registration_code", "registration_code", code_id,
           {"code": raw})
    db.commit()
    return {"success": True, "message": "卡码已删除"}


# ==================== 设备风控 ====================


@admin_ops_router.get("/devices/stats")
def device_stats(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now() - timedelta(days=devices.ACTIVE_DEVICE_DAYS)
    total = db.query(func.count(models.UserDevice.id)).scalar() or 0
    active = db.query(func.count(models.UserDevice.id)).filter(
        models.UserDevice.is_blocked.is_(False),
        models.UserDevice.last_seen_at >= cutoff,
    ).scalar() or 0
    blocked = db.query(func.count(models.UserDevice.id)).filter(
        models.UserDevice.is_blocked.is_(True)
    ).scalar() or 0
    users = db.query(func.count(func.distinct(models.UserDevice.user_id))).scalar() or 0
    return {
        "total": int(total),
        "active_30d": int(active),
        "blocked": int(blocked),
        "users": int(users),
        "limit_per_user": devices.device_limit(db),
        "auto_evict": devices.device_auto_evict(db),
        "active_days": devices.ACTIVE_DEVICE_DAYS,
    }


@admin_ops_router.get("/devices")
def list_all_devices(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    user_id: Optional[int] = None,
    keyword: str = "",
    only_blocked: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    """跨用户设备审查"""
    query = db.query(models.UserDevice, models.WebUser).outerjoin(
        models.WebUser, models.WebUser.id == models.UserDevice.user_id
    )
    if user_id:
        query = query.filter(models.UserDevice.user_id == user_id)
    if only_blocked:
        query = query.filter(models.UserDevice.is_blocked.is_(True))

    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(
            models.UserDevice.device_id.ilike(like),
            models.UserDevice.name.ilike(like),
            models.UserDevice.client.ilike(like),
            models.UserDevice.ip.ilike(like),
            models.WebUser.username.ilike(like),
        ))

    total = query.count()
    rows = query.order_by(models.UserDevice.last_seen_at.desc()).offset(
        max(offset, 0)
    ).limit(min(max(limit, 1), 300)).all()

    cutoff = datetime.now() - timedelta(days=devices.ACTIVE_DEVICE_DAYS)
    items = []
    for device, user in rows:
        dto = devices.device_dto(device)
        dto["user_id"] = device.user_id
        dto["username"] = user.username if user else f"用户 #{device.user_id}"
        dto["is_user_active"] = bool(user.is_active) if user else False
        dto["is_online_recent"] = bool(
            device.last_seen_at is None or device.last_seen_at >= cutoff
        )
        items.append(dto)
    return {"total": total, "devices": items}


class DeviceBlockRequest(BaseModel):
    is_blocked: bool


@admin_ops_router.put("/devices/{device_id}")
def update_device(
    device_id: str,
    request: DeviceBlockRequest,
    user_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """封禁 / 解封设备（封禁同时吊销该设备令牌）"""
    device = db.query(models.UserDevice).filter(
        models.UserDevice.user_id == user_id,
        models.UserDevice.device_id == device_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    device.is_blocked = request.is_blocked
    db.commit()
    if request.is_blocked:
        devices.revoke_device_tokens(db, user_id, device_id)

    _audit(db, current_admin, "update_device", "user_device", device.id,
           {"device_id": device_id, "user_id": user_id, "is_blocked": request.is_blocked})
    db.commit()
    return {
        "success": True,
        "message": "设备已封禁，该设备需重新登录且会被拒绝" if request.is_blocked else "设备已解封",
    }


@admin_ops_router.delete("/devices/{device_id}")
def delete_device(
    device_id: str,
    user_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """移除设备并吊销令牌（踢下线）"""
    ok = devices.remove_device(db, user_id, device_id, revoke_tokens=True)
    if not ok:
        raise HTTPException(status_code=404, detail="设备不存在")
    _audit(db, current_admin, "remove_device", "user_device", None,
           {"device_id": device_id, "user_id": user_id})
    db.commit()
    return {"success": True, "message": "设备已移除，对应客户端需重新登录"}


# ==================== 登录 / 安全日志 ====================


@admin_ops_router.get("/login-logs")
def list_login_logs(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    username: str = "",
    ip: str = "",
    reason: str = "",
    success: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
):
    """登录与风控事件日志"""
    query = db.query(models.LoginLog)
    kw = (username or "").strip()
    if kw:
        query = query.filter(models.LoginLog.username.ilike(f"%{kw}%"))
    ip_kw = (ip or "").strip()
    if ip_kw:
        query = query.filter(models.LoginLog.ip.ilike(f"%{ip_kw}%"))
    if reason:
        query = query.filter(models.LoginLog.reason == reason)
    if success is not None:
        query = query.filter(models.LoginLog.success.is_(success))

    total = query.count()
    rows = query.order_by(models.LoginLog.created_at.desc()).offset(
        max(offset, 0)
    ).limit(min(max(limit, 1), 300)).all()

    day_ago = datetime.now() - timedelta(hours=24)
    failed_24h = db.query(func.count(models.LoginLog.id)).filter(
        models.LoginLog.success.is_(False),
        models.LoginLog.created_at >= day_ago,
    ).scalar() or 0
    risk_24h = db.query(func.count(models.LoginLog.id)).filter(
        models.LoginLog.reason.in_(["device_limit", "decoy_code"]),
        models.LoginLog.created_at >= day_ago,
    ).scalar() or 0

    return {
        "total": total,
        "summary": {"failed_24h": int(failed_24h), "risk_24h": int(risk_24h)},
        "reasons": [{"value": k, "label": v} for k, v in authlog.REASONS.items()],
        "logs": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": r.username,
                "ip": r.ip,
                "region": r.region or "",
                "user_agent": r.user_agent,
                "success": bool(r.success),
                "reason": r.reason,
                "reason_label": authlog.REASONS.get(r.reason or "", r.reason or "-"),
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


class LogPurgeRequest(BaseModel):
    days: Optional[int] = Field(default=None, ge=0, le=3650)


@admin_ops_router.post("/login-logs/purge")
def purge_login_logs(
    request: LogPurgeRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """按保留天数清理日志（days=0 清空）"""
    if request.days == 0:
        deleted = int(db.query(models.LoginLog).delete(synchronize_session=False) or 0)
        db.commit()
    else:
        deleted = authlog.purge_old(db, request.days)

    _audit(db, current_admin, "purge_login_logs", "login_log", None,
           {"days": request.days, "deleted": deleted})
    db.commit()
    return {"success": True, "message": f"已清理 {deleted} 条日志", "deleted": deleted}


# ==================== 防共享：跨城市轨迹 + 同播检测（v2.43.0） ====================
#
# 判定与处置逻辑都在 ``backend/share_guard.py``；这里只做三件事：读策略与事件、
# 写策略、清理事件。两处写端点都写审计——「谁把自动停用打开了」必须是可追溯的，
# 否则一个被误伤的用户没地方说理。


@admin_ops_router.get("/share-guard")
def get_share_guard(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
    kind: str = "",
    limit: int = 100,
    offset: int = 0,
):
    """防共享策略 + 事件流水 + 近 24h 概览（只读，运营与只读角色都能看）

    只列**判定**：基线行（``is_baseline``，只是「这个账号现在在 X 城」）是判定算法
    自己的记忆，不是异常。它留在库里（判定要靠它记住上一次的城市），但不进这一页——
    否则列表里绝大多数是「用户还在原地」，概览数字也会被它冲高到失去意义。
    """
    query = db.query(models.ShareGuardEvent).filter(
        models.ShareGuardEvent.is_baseline.is_(False)
    )
    if kind in (share_guard.KIND_TRAVEL, share_guard.KIND_CONCURRENT):
        query = query.filter(models.ShareGuardEvent.kind == kind)

    total = query.count()
    rows = (
        query.order_by(models.ShareGuardEvent.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 300))
        .all()
    )
    day_ago = datetime.now() - timedelta(hours=24)
    _recent = (
        models.ShareGuardEvent.created_at >= day_ago,
        models.ShareGuardEvent.is_baseline.is_(False),
    )
    travel_24h = db.query(func.count(models.ShareGuardEvent.id)).filter(
        *_recent, models.ShareGuardEvent.kind == share_guard.KIND_TRAVEL,
    ).scalar() or 0
    concurrent_24h = db.query(func.count(models.ShareGuardEvent.id)).filter(
        *_recent, models.ShareGuardEvent.kind == share_guard.KIND_CONCURRENT,
    ).scalar() or 0
    enforced_24h = db.query(func.count(models.ShareGuardEvent.id)).filter(
        *_recent, models.ShareGuardEvent.action == "enforce",
    ).scalar() or 0

    return {
        "success": True,
        "policy": share_guard.policy_payload(db),
        "summary": {
            "total": int(total),
            "travel_24h": int(travel_24h),
            "concurrent_24h": int(concurrent_24h),
            "enforced_24h": int(enforced_24h),
        },
        "kinds": [
            {"value": "", "label": "全部"},
            {"value": share_guard.KIND_TRAVEL, "label": share_guard.KIND_LABELS[share_guard.KIND_TRAVEL]},
            {"value": share_guard.KIND_CONCURRENT, "label": share_guard.KIND_LABELS[share_guard.KIND_CONCURRENT]},
        ],
        "events": [share_guard.event_dto(row) for row in rows],
    }


class ShareGuardPolicyRequest(BaseModel):
    policy: dict


@admin_ops_router.put("/share-guard/policy")
def update_share_guard_policy(
    payload: ShareGuardPolicyRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """写回防共享策略（只认白名单里的键，非法值保持原值不动）

    不静默降级：写入后返回**真实生效值**，前端照它回填，不自己猜。
    """
    applied = share_guard.write_policy(db, payload.policy)
    _audit(db, current_admin, "share_guard_policy_update", "system", None, applied)
    db.commit()
    return {
        "success": True,
        "applied": applied,
        "policy": share_guard.policy_payload(db),
    }


class ShareGuardPurgeRequest(BaseModel):
    days: Optional[int] = Field(default=None, ge=0, le=3650)


@admin_ops_router.post("/share-guard/purge")
def purge_share_guard_events(
    payload: ShareGuardPurgeRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """清理防共享事件（days=0 = 清空全部）"""
    if payload.days == 0:
        deleted = int(db.query(models.ShareGuardEvent).delete(synchronize_session=False) or 0)
        db.commit()
    else:
        deleted = share_guard.purge_old(db, payload.days)

    _audit(db, current_admin, "purge_share_guard_events", "share_guard_event", None,
           {"days": payload.days, "deleted": deleted})
    db.commit()
    return {"success": True, "message": f"已清理 {deleted} 条防共享事件", "deleted": deleted}


__all__ = ["admin_ops_router"]
