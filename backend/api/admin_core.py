"""
管理后台 API · 公共骨架

`backend/api/admin.py` 原本单文件两千多行，所有管理端点挤在一起：审计要改一处，
得在几千行里翻。这里抽出**所有管理端点共用的骨架**：

- ``admin_router``：全后台端点挂在同一个 ``/api/admin`` 路由上；
- ``get_current_admin``：统一的管理员鉴权依赖（is_staff 的 WebUser）；
- ``_audit``：写操作审计落库（``admin_user_id`` 存 WebUser.id）；
- ``_generate_code`` / ``_log_out``：卡码生成与时间序列化，多个子模块共用。

业务端点按域拆到同目录的兄弟模块，导入即注册（路由对象是同一个）：

- ``admin_auth.py``：管理员登录 / 当前身份 / 改密
- ``admin.py``：订阅、用户、卡码、公告、工单、求片、操作日志、统计、经济系统管理
- ``admin_economy.py``：邀请返利、积分台账、经济设置与统计、用户详情 / 趋势 / 订阅总览

**这个文件只放「多个后台模块都要用」的东西**：单一模块专用的导入留在各自模块里，
免得这里变成一锅谁都能塞东西的公共大杂烩，也免得出现「这里导入了但没人用」的死代码。
新增共享依赖时，先确认至少两个后台模块要用它。

管理员操作会触发通知发送到用户前台，实现前后台联动。
"""
import logging
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend import admin_roles, models
from backend.database import get_db
from backend.security import resolve_jwt_user_id

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin", tags=["管理后台"])

security = HTTPBearer(auto_error=False)

CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code(length: int = 12) -> str:
    """生成人类易读的卡码（去掉易混淆的 0/O/1/I）"""
    alphabet = "".join(c for c in CODE_ALPHABET if c not in "0O1I")
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ==================== 鉴权依赖 ====================

def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> models.WebUser:
    """管理员鉴权：JWT access token，且必须是 is_staff 的 WebUser

    与用户端相同的 token 体系；身份仍然是 ``is_staff``，**角色**（super / operator /
    viewer，见 backend/admin_roles.py）只决定能写什么——判定集中在这一个依赖里，
    避免出现「某个写接口忘了判角色」的漏洞。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
        )

    user_id = resolve_jwt_user_id(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的凭证",
        )

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user or not user.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员已被禁用",
        )

    # 角色判定：只读角色不能写；运营角色不能改系统设置 / 上游 Key / 策略 / 管理员本身
    admin_roles.ensure_admin_allowed(request, user)

    return user


def _audit(
    db: Session,
    admin: models.WebUser,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict | None = None,
    ip: str | None = None,
) -> None:
    """写操作审计日志（admin_user_id 存 WebUser.id）"""
    db.add(models.AdminLog(
        admin_user_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip,
    ))


def _log_out(model) -> str:
    return model.created_at.isoformat() if model.created_at else ""
