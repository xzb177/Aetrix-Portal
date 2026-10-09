"""群抽奖公开 API：公平核验（无需登录，纯只读）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lottery", tags=["群抽奖"])


def _lottery():
    """惰性导入 lottery 模块（G1 契约，并行任务尚未合入时返回 None）。"""
    try:
        from backend import lottery

        return lottery
    except ImportError:
        return None


@router.get("/rounds/{round_id}/fairness")
def round_fairness(round_id: int, db: Session = Depends(get_db)) -> dict:
    """公开公平核验：返回某轮抽奖的种子哈希/种子/算法/参与者/中奖者。

    无需登录，纯只读。开奖前仅暴露 seed_hash，开奖后才暴露 seed（由 lottery.verify_round 控制）。
    """
    lot = _lottery()
    if lot is None:
        raise HTTPException(status_code=503, detail="抽奖功能暂未开启")
    try:
        data = lot.verify_round(db, round_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify_round failed for round %s: %s", round_id, exc)
        raise HTTPException(status_code=404, detail="抽奖轮次不存在")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="核验数据异常")
    return data
