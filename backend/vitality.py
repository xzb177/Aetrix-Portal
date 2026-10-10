from __future__ import annotations
import logging
import threading
from datetime import date
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models
from backend.integrations import store

logger = logging.getLogger(__name__)

CONFIG_ENABLED = "vitality_enabled"
CONFIG_MAX = "vitality_max"
CONFIG_DAILY_COST = "vitality_daily_cost"
CONFIG_LIMIT_THRESHOLD = "vitality_limit_threshold"
CONFIG_POINT_COST = "vitality_point_cost"

VITALITY_DEFAULTS = {
    CONFIG_ENABLED: "true",
    CONFIG_MAX: "14",
    CONFIG_DAILY_COST: "1",
    CONFIG_LIMIT_THRESHOLD: "3",
    CONFIG_POINT_COST: "10",
}

def _raw(db: Session, key: str) -> str:
    return store.get_value(db, key, "")

def _cfg_bool(db, key, default):
    raw = _raw(db, key)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() == "true"

def _cfg_int(db, key, default):
    raw = _raw(db, key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default

def get_vitality_config(db: Session) -> dict:
    return {
        "enabled": _cfg_bool(db, CONFIG_ENABLED, True),
        "max": _cfg_int(db, CONFIG_MAX, 14),
        "daily_cost": _cfg_int(db, CONFIG_DAILY_COST, 1),
        "limit_threshold": _cfg_int(db, CONFIG_LIMIT_THRESHOLD, 3),
        "point_cost": _cfg_int(db, CONFIG_POINT_COST, 10),
    }

def vitality_status(db: Session, user) -> dict:
    cfg = get_vitality_config(db)
    v = int(getattr(user, "vitality", None) or 0)
    return {
        "vitality": v,
        "max": cfg["max"],
        "limit_threshold": cfg["limit_threshold"],
        "can_play": (not cfg["enabled"]) or (not getattr(user, "is_welfare", False)) or v >= cfg["limit_threshold"],
        "suspended": v <= 0,
    }

def ensure_can_play(db: Session, user) -> None:
    cfg = get_vitality_config(db)
    if not cfg["enabled"]:
        return
    if not getattr(user, "is_welfare", False):
        return
    if getattr(user, "is_staff", False):
        return
    v = int(getattr(user, "vitality", None) or 0)
    if v >= cfg["limit_threshold"]:
        return
    raise HTTPException(status_code=403, detail=f"活力值不足（{v}/{cfg['limit_threshold']}），签到或用积分续活力后可继续观影")

def _add_vitality(db: Session, user_id: int, delta: int, reason: str) -> int:
    cfg = get_vitality_config(db)
    max_vitality = int(cfg.get("max", VITALITY_DEFAULTS[CONFIG_MAX]))
    db.query(models.WebUser).filter(models.WebUser.id == user_id).update(
        {models.WebUser.vitality: func.coalesce(models.WebUser.vitality, 0) + delta},
        synchronize_session="fetch",
    )
    row = db.query(models.WebUser.vitality).filter(models.WebUser.id == user_id).first()
    current = int(row[0]) if row and row[0] is not None else 0
    final = max(0, min(max_vitality, current))
    if final != current:
        db.query(models.WebUser).filter(models.WebUser.id == user_id).update(
            {models.WebUser.vitality: final},
            synchronize_session="fetch",
        )
    db.add(models.VitalityLog(user_id=user_id, delta=delta, balance_after=final, reason=reason))
    return final

_DEDUCT_BATCH = 500


def daily_deduct(db: Session) -> dict:
    """每日 00:00 扣减公益服用户活力值"""
    cfg = get_vitality_config(db)
    if not cfg["enabled"]:
        return {"deducted": 0, "suspended": 0, "skipped": True}
    cost = cfg["daily_cost"]
    deducted = 0
    suspended = 0
    last_id = 0
    # 键集分页（id > last_id）而不是 offset：过滤条件是 vitality > 0，本批扣到 0 的用户
    # 会从结果集里消失，offset 继续往后跳就会整批漏扣后面的用户
    while True:
        rows = (db.query(models.WebUser.id)
                .filter(models.WebUser.is_welfare == True, models.WebUser.vitality > 0,
                        models.WebUser.id > last_id)
                .order_by(models.WebUser.id).limit(_DEDUCT_BATCH).all())
        if not rows:
            break
        for (uid,) in rows:
            try:
                new_v = _add_vitality(db, uid, -cost, "daily_deduct")
                deducted += 1
                if new_v <= 0:
                    suspended += 1
            except Exception:
                logger.exception("vitality daily_deduct failed for user %s", uid)
        db.commit()
        last_id = rows[-1][0]
    return {"deducted": deducted, "suspended": suspended}

_SCHEDULER_STARTED = False
_SCHEDULER_LOCK = threading.Lock()
CONFIG_LAST_DEDUCT_DATE = "vitality_last_deduct_date"

def _today_str() -> str:
    return date.today().isoformat()

def claim_daily_deduct(db: Session, today: str) -> bool:
    """原子认领「今天的活力值扣减」：认领成功返回 True（本进程负责扣减），否则 False。

    旧实现是「读上次日期 → 扣减 → 再写日期」：多个 worker 进程/实例各有一个调度线程，
    会同时读到旧日期、各扣一遍（公益服用户活力被双倍扣减，提前停播）；扣减中途崩溃
    重启也会再扣一遍。现在先用 UPDATE ... WHERE value != today（无行时 INSERT，唯一键兜底）
    认领并提交，再扣减。代价：认领后扣减中途崩溃，当天少扣（对用户有利，不会重复扣）。
    """
    from sqlalchemy import or_
    from sqlalchemy.exc import IntegrityError

    claimed = (
        db.query(models.SystemConfig)
        .filter(
            models.SystemConfig.key == CONFIG_LAST_DEDUCT_DATE,
            or_(models.SystemConfig.value.is_(None), models.SystemConfig.value != today),
        )
        .update({"value": today}, synchronize_session=False)
    )
    if claimed:
        db.commit()
        return True
    exists = db.query(models.SystemConfig.id).filter(
        models.SystemConfig.key == CONFIG_LAST_DEDUCT_DATE).first()
    if exists:
        db.rollback()
        return False
    db.add(models.SystemConfig(key=CONFIG_LAST_DEDUCT_DATE, value=today))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def start_vitality_scheduler() -> bool:
    """启动每日活力值扣减调度（daemon 线程，同一进程只启动一次）

    上次执行日期持久化在 SystemConfig(vitality_last_deduct_date)：worker 重启
    当天不再重复扣减。
    """
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return False
        _SCHEDULER_STARTED = True

    def _tick():
        try:
            from backend.database import SessionLocal
            db = SessionLocal()
            try:
                today = _today_str()
                if store.get_value(db, CONFIG_LAST_DEDUCT_DATE, "") == today:
                    return
                # 先原子认领当天，再扣减：多进程/多实例同时跑调度时只有一个能扣
                if not claim_daily_deduct(db, today):
                    return
                store.invalidate(CONFIG_LAST_DEDUCT_DATE)
                result = daily_deduct(db)
                logger.info("活力值每日扣减完成: %s", result)
            finally:
                db.close()
        except Exception:
            logger.exception("vitality scheduler tick failed")

    def _loop():
        while True:
            threading.Event().wait(60)
            _tick()

    threading.Thread(target=_loop, daemon=True, name="vitality-scheduler").start()
    logger.info("活力值调度已启动（每 60 秒检查一次，每日 00:00 扣减）")
    return True

__all__ = [
    "VITALITY_DEFAULTS", "get_vitality_config", "vitality_status",
    "ensure_can_play", "daily_deduct", "claim_daily_deduct", "start_vitality_scheduler",
]
