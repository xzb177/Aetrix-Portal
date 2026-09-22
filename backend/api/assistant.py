"""用户端 · AI 助手（能力：AI 模型设置）

只提供能力：模型、端点、密钥都由管理员在后台「系统设置 → AI 模型设置」里自己填，
项目不内置任何 key。没配好或没启用时，前端据 ``/status`` 直接不显示入口——不会出现
「点了之后报 500」这种半成品状态。

- ``GET  /api/user/ai/status``：是否可用 + 今日剩余次数（用户端据此显示/隐藏入口）
- ``POST /api/user/ai/ask``  ：提问（登录用户，按 ``ai_daily_limit`` 限流，默认 20 次/天）
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.api.emby_portal import get_current_user_jwt
from backend.database import get_db
from backend.integrations import ai as ai_capability

logger = logging.getLogger(__name__)

assistant_router = APIRouter(prefix="/api/user/ai", tags=["用户端-AI 助手"])

MAX_QUESTION_CHARS = 1000


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)
    history: Optional[List[dict]] = None


def _quota(db: Session, user_id: int) -> dict:
    """当日配额快照：limit / used / remaining（limit<=0 表示不限）"""
    limit = ai_capability.daily_limit(db)
    used = ai_capability.used_today(user_id)
    remaining = None if limit <= 0 else max(0, limit - used)
    return {"daily_limit": limit, "used": used, "remaining": remaining}


@assistant_router.get("/status")
async def assistant_status(
    current_user: models.WebUser = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
):
    """助手是否可用 + 今日剩余次数（前端据此显示/隐藏入口与提示）"""
    if not ai_capability.available(db):
        return {"enabled": False, "reason": "管理员尚未配置 AI 模型（在「系统设置 → AI 模型设置」里填写端点、模型与密钥）",
                "daily_limit": 0, "remaining": None}
    return {"enabled": True, "reason": "", **_quota(db, current_user.id)}


@assistant_router.post("/ask")
async def assistant_ask(
    req: AskRequest,
    current_user: models.WebUser = Depends(get_current_user_jwt),
    db: Session = Depends(get_db),
):
    """向配置好的模型提一个问题（多把密钥轮换；上游失败原因原样透出）"""
    if not ai_capability.available(db):
        raise HTTPException(status_code=503, detail="AI 助手未启用或尚未配置（系统设置 → AI 模型设置）")

    quota = _quota(db, current_user.id)
    if quota["remaining"] is not None and quota["remaining"] <= 0:
        raise HTTPException(
            status_code=429,
            detail=f"今日提问次数已用完（上限 {quota['daily_limit']} 次），明天再来吧",
        )

    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    ai_capability.record_usage(current_user.id)
    result = ai_capability.ask(db, question, req.history)
    if not result.get("ok"):
        # 上游的错误信息（含模型名与 HTTP 状态）对排错很有用，原样转给用户端
        raise HTTPException(status_code=502, detail=result.get("message") or "模型调用失败")
    return {
        "answer": result.get("answer", ""),
        "model": result.get("model", ""),
        **_quota(db, current_user.id),
    }


__all__ = ["assistant_router"]
