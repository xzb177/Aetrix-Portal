"""
首页媒体库板块排序 API

- GET /api/homepage/sections/order: 返回当前板块顺序（library id 数组）
- PUT /api/homepage/sections/order: 保存板块顺序

顺序存在 system_configs 表，key='homepage_section_order'，value 为 JSON 数组。
未设置时返回空数组，前端按默认顺序（id 升序）显示。
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models
from backend.models import SystemConfig
from backend.api.admin_core import get_current_admin
from backend.emby_server import models as emby_models

router = APIRouter(prefix="/api/homepage/sections", tags=["首页-板块排序"])

ORDER_KEY = "homepage_section_order"


def _get_order(db: Session) -> list:
    cfg = db.query(SystemConfig).filter(SystemConfig.key == ORDER_KEY).first()
    if not cfg or not cfg.value:
        return []
    try:
        order = json.loads(cfg.value)
        return order if isinstance(order, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _set_order(db: Session, order: list):
    cfg = db.query(SystemConfig).filter(SystemConfig.key == ORDER_KEY).first()
    if not cfg:
        cfg = SystemConfig(
            key=ORDER_KEY,
            value=json.dumps(order),
            description="首页媒体库板块排序（library id 数组）",
        )
        db.add(cfg)
    else:
        cfg.value = json.dumps(order)
    db.commit()


class OrderUpdate(BaseModel):
    order: list[int]


@router.get("/order")
def get_section_order(db: Session = Depends(get_db)):
    """返回当前板块顺序（library id 数组）。空数组表示用默认顺序。"""
    return {"order": _get_order(db)}


@router.put("/order")
def set_section_order(
    body: OrderUpdate,
    db: Session = Depends(get_db),
    _admin: models.WebUser = Depends(get_current_admin),
):
    """保存板块顺序。body: {"order": [24, 22, 26, ...]}

    P1 修复（审查）：此前无任何鉴权，匿名可改写全站首页板块排序。
    GET 保持公开（首页渲染需要），PUT 仅管理员。
    """
    # 校验：所有 id 必须是存在的 library
    if body.order:
        existing_ids = {
            r[0] for r in db.query(emby_models.Library.id).all()
        }
        invalid = [i for i in body.order if i not in existing_ids]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"无效的 library id: {invalid}",
            )
    _set_order(db, body.order)
    return {"order": body.order}

