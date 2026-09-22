"""管理后台 · 外部服务能力中心

后台「系统设置」里的**能力**总览与配置入口。设计口径只有一句话：

> 项目只提供能力，凭据一律由管理员自己填。

因此这里不内置任何 key / 站点密钥 / 代理地址，也不锁定提供方：每个能力的字段表都在
``backend/integrations/<slug>.py`` 的 ``SPEC`` 里声明，前端按字段表渲染表单（不写死字段），
保存后由模块的 ``apply()`` 落地副作用，并提供一次**真实连通性测试**。

密钥字段对外只报「已配置」，提交 ``******`` 表示不修改、**清空表示删除**（与经济设置同一约定）。
审计日志只记字段名，不记值——免得密钥顺着操作日志漏出去。

四个端点都是**同步** ``def``：``test`` 会真实发起网络请求 / SMTP 投递（最长 60 秒），
``save`` 会落配置并触发副作用——放进 ``async def`` 就是拿整个事件循环去等它们（播放会卡）。
FastAPI 会把同步端点丢进线程池，与 v2.13 把协议路由移出事件循环是同一个做法。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.api.admin_core import _audit, get_current_admin
from backend.database import get_db
from backend.ratelimit import client_ip
from backend import integrations

logger = logging.getLogger(__name__)

capabilities_router = APIRouter(prefix="/api/admin/capabilities", tags=["管理后台-能力中心"])


class CapabilitySaveRequest(BaseModel):
    values: dict = Field(default_factory=dict)


class CapabilityTestRequest(BaseModel):
    # 测试参数（例如收件地址、要定位的 IP）；能力模块自己决定用不用
    payload: dict = Field(default_factory=dict)


def _require(slug: str) -> None:
    if slug not in integrations.CAPABILITY_MODULES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知能力：{slug}",
        )


@capabilities_router.get("")
def list_capabilities(
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """能力总览（后台中心页用）：标题、说明、分组、是否启用 / 已配置"""
    return {"capabilities": integrations.list_capabilities(db)}


@capabilities_router.get("/{slug}")
def get_capability(
    slug: str,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """单个能力的字段表与当前值（密钥为掩码）"""
    _require(slug)
    return integrations.get_capability(db, slug)


@capabilities_router.put("/{slug}")
def save_capability(
    slug: str,
    request: CapabilitySaveRequest,
    http_request: Request,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """保存能力配置；密钥留空或 ****** 视为不修改"""
    _require(slug)
    result = integrations.save_capability(db, slug, request.values)
    _audit(
        db, current_admin, "capability_update", "capability", None,
        {"slug": slug, "fields": sorted((request.values or {}).keys())},
        client_ip(http_request),
    )
    db.commit()
    return {"success": True, **result}


@capabilities_router.post("/{slug}/test")
def test_capability(
    slug: str,
    request: CapabilityTestRequest,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """真实连通性测试（走真实网络 / 真实投递；不写配置）

    失败原因原样返回，便于管理员区分「密钥填错了」还是「网络到不了」。
    """
    _require(slug)
    payload: Optional[dict] = request.payload or {}
    return integrations.test_capability(db, slug, payload)


__all__ = ["capabilities_router"]
