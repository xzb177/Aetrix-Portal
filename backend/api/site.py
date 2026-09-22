"""站点信息（公开端点）

前端在启动时读一次这里，决定顶栏站名 / 登录页标题 / 浏览器标题 / 主题色。
**不需要鉴权**：这些信息本来就要显示给未登录的访客看（登录页），其中也不含任何凭据——
私钥、API Key 之类一律不出现在这里。

值来自「站点与品牌」能力（后台「系统设置」里填），非法值由能力模块自己回落——
主题色的十六进制校验与 Logo 的协议校验都在 ``backend/integrations/branding.py``。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.integrations import branding as branding_capability

logger = logging.getLogger(__name__)

site_router = APIRouter(prefix="/api/site", tags=["站点信息"])


@site_router.get("/branding")
def get_branding(db: Session = Depends(get_db)):
    """站点名称 / Logo / 主题色 / SEO（公开）"""
    return branding_capability.public_info(db)


__all__ = ["site_router"]
