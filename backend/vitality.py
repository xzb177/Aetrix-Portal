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

def daily_deduct(db: Session) -> dict:
    """每日 00:00 扣减公益服用户活力值"""
    cfg = get_vitality_config(db)
    if not cfg["enabled"]:
        return {"deducted": 0, "suspended": 0, "skipped": True}
    cost = cfg["daily_cost"]
    deducted = 0
    suspended = 0
    offset = 0
    batch = 500
    while True:
        rows = (db.query(models.WebUser.id)
                .filter(models.WebUser.is_welfare == True, models.WebUser.vitality > 0)
                .order_by(models.WebUser.id).offset(offset).limit(batch).all())
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
        offset += batch
    return {"deducted": deducted, "suspended": suspended}

_SCHEDULER_STARTED = False
_SCHEDULER_LOCK = threading.Lock()
CONFIG_LAST_DEDUCT_DATE = "vitality_last_deduct_date"

def _today_str() -> str:
    return date.today().isoformat()

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
                last = store.get_value(db, CONFIG_LAST_DEDUCT_DATE, "")
                today = _today_str()
                if last == today:
                    return
                result = daily_deduct(db)
                # 记录执行日期（daily_deduct 内部已 commit，这里再写一行）
                row = db.query(models.SystemConfig).filter(
                    models.SystemConfig.key == CONFIG_LAST_DEDUCT_DATE).first()
                if row:
                    row.value = today
                else:
                    db.add(models.SystemConfig(key=CONFIG_LAST_DEDUCT_DATE, value=today))
                db.commit()
                store.invalidate(CONFIG_LAST_DEDUCT_DATE)
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
    "ensure_can_play", "daily_deduct", "start_vitality_scheduler",
]
