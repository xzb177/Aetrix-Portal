"""管理后台 · 首次运行向导（setup_mode，借鉴 twilight-kotomi）

全新部署没有管理员时，管理后台不再靠「默认 admin/admin 裸奔」：
第一次打开 /admin/ 会被前端送到初始化向导页（/setup），在这里建第一个管理员；
成功后入口**永久关闭**（``setup_completed=True``），此后 POST 直接 403。

两个端点都是免鉴权的——还没有身份可鉴（见
``scripts/check_auth_coverage.py`` 的 PRE_AUTH 登记与
``scripts/check_admin_audit_coverage.py`` 的 EXCEPTIONS 登记）：

- ``GET  /api/admin/setup/status`` → ``{"setup_completed": bool}``
- ``POST /api/admin/setup``         → ``{username, password}`` 建第一个管理员并置旗

安全要点（都是真实会踩到的坑）：

1. **完成后永久 403**：置旗成功后 POST 只认 ``setup_completed``，不再看别的；
2. **防「旗丢了、库里有管理员」**：如果库里已经有 ``is_staff`` 账号但旗没置
   （比如从老版本升级上来、或被人手动删了配置行），视为已完成：自愈补旗并 403，
   不给攻击者留一个「再造一个超级管理员」的洞；
3. **限流**：与管理员登录同口径（8 次/分钟/IP），防字典跑向导入口；
4. **不写第二套建账号逻辑**：复用 ``backend/admin_accounts.py`` 的
   ``validate_username / check_password_strength / upsert_admin``；
5. **并发双击**：模块级锁串行化临界区，避免两次 POST 几乎同时进来时
   第二个把第一个刚设好的密码又覆盖掉。
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.admin_accounts import (
    AdminAccountError,
    check_password_strength,
    upsert_admin,
    validate_username,
)
from backend.authlog import client_ip as log_ip, record_event, user_agent
from backend.database import get_db
from backend.ratelimit import check_rate_limit, client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/setup", tags=["管理后台·首次运行向导"])

SETUP_COMPLETED_KEY = "setup_completed"
SETUP_COMPLETED_DESC = "首次运行向导是否已完成（True 后初始化入口永久关闭）"

# 向导入口的并发串行化：单节点部署够用（多节点部署下第二个请求至多把密码再设一次，
# 仍然是同一个管理员账号，不会造出第二个管理员——upsert 按用户名幂等）。
_setup_lock = threading.Lock()


def is_setup_completed(db: Session) -> bool:
    """向导是否已完成。

    两个真相源：``setup_completed`` 配置旗，以及库里是否已有管理员。
    库里已有管理员但旗没置 = 老版本升级/配置行丢失，视为已完成并自愈补旗，
    防止向导入口在已有管理员的部署上被重新打开。
    """
    row = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == SETUP_COMPLETED_KEY
    ).first()
    if row and (row.value or "").strip().lower() == "true":
        return True
    has_admin = (
        db.query(models.WebUser.id)
        .filter(models.WebUser.is_staff.is_(True))
        .first()
        is not None
    )
    if has_admin:
        # 自愈：管理员已存在，补旗，避免入口悬空
        if row:
            row.value = "true"
        else:
            db.add(models.SystemConfig(
                key=SETUP_COMPLETED_KEY, value="true", description=SETUP_COMPLETED_DESC,
            ))
        db.commit()
        logger.warning("setup_completed 旗缺失但库里已有管理员：已自愈补旗，向导入口保持关闭")
        return True
    return False


def _mark_setup_completed(db: Session) -> None:
    row = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == SETUP_COMPLETED_KEY
    ).first()
    if row:
        row.value = "true"
    else:
        db.add(models.SystemConfig(
            key=SETUP_COMPLETED_KEY, value="true", description=SETUP_COMPLETED_DESC,
        ))
    db.commit()


@router.get("/status")
def setup_status(db: Session = Depends(get_db)) -> dict:
    """向导状态：前端进 /admin/ 前先问一次，决定去向导页还是登录页。"""
    return {"setup_completed": is_setup_completed(db)}


class SetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


@router.post("")
def setup_first_admin(
    http_request: Request,
    request: SetupRequest,
    db: Session = Depends(get_db),
) -> dict:
    """建第一个管理员并永久关闭向导入口。完成后再次调用一律 403。"""
    ip = client_ip(http_request)
    allowed, retry_after = check_rate_limit(f"admin_setup:{ip}", 8, 60)
    if not allowed:
        record_event(
            db, username=request.username.strip(), ip=log_ip(http_request),
            agent=user_agent(http_request), success=False, reason="admin_setup_failed",
            detail=f"尝试过于频繁，已限流（{retry_after}s）",
        )
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")

    with _setup_lock:
        if is_setup_completed(db):
            record_event(
                db, username=request.username.strip(), ip=log_ip(http_request),
                agent=user_agent(http_request), success=False, reason="admin_setup_failed",
                detail="初始化已完成，入口已关闭",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="初始化已完成：向导入口已永久关闭",
            )

        try:
            username = validate_username(request.username)
            check_password_strength(request.password)
        except AdminAccountError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            user, created, _applied = upsert_admin(db, username, password=request.password)
        except AdminAccountError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        _mark_setup_completed(db)
        user_id = user.id

    record_event(
        db, username=username, user_id=user_id, ip=log_ip(http_request),
        agent=user_agent(http_request), success=True, reason="admin_setup",
        detail="首次运行向导创建第一个管理员" if created else "首次运行向导（账号已存在，已升级为管理员）",
    )
    logger.info("首次运行向导完成：管理员 %r 已就绪，向导入口永久关闭", username)
    return {"ok": True, "username": username, "setup_completed": True}
