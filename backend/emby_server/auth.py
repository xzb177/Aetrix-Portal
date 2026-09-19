"""自建 Emby 服务器：认证与 Token 管理"""
import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db
from backend.emby_server import models as emby_models
from backend.security import hash_password, verify_password

bearer_scheme = HTTPBearer(auto_error=False)

# 请求头里的客户端信息（X-Emby-Authorization: MediaBrowser Client="...", Device="...", DeviceId="...", Version="..."）
DEVICE_HEADERS = ["X-Emby-Authorization", "X-MediaBrowser-Token"]


def parse_emby_authorization(header_value: Optional[str]) -> dict:
    """解析 X-Emby-Authorization 头"""
    result: dict = {}
    if not header_value:
        return result
    for part in header_value.split(","):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            value = value.strip().strip('"')
            result[key.strip()] = value
    return result


def verify_emby_password(plain: str, stored: str) -> bool:
    """校验 Emby 播放密码：支持 bcrypt 哈希与旧明文（明文仅作兼容）"""
    if not stored:
        return False
    if stored.startswith("$2"):
        from backend.security import verify_password

        return verify_password(plain, stored)
    return secrets.compare_digest(plain.encode(), stored.encode())


def ensure_emby_credentials(db: Session, user: models.WebUser, password: Optional[str] = None) -> Optional[str]:
    """确保用户拥有自建 Emby 登录凭据；设置密码时返回哈希值"""
    if not user.emby_username:
        user.emby_username = f"emby_{user.id}_{uuid.uuid4().hex[:6]}"
    if password:
        hashed = hash_password(password)
        user.emby_password = hashed
        db.commit()
        return hashed
    db.commit()
    return None


def issue_token(db: Session, user: models.WebUser, request: Request) -> tuple[str, emby_models.EmbyApiToken]:
    """为用户签发 Emby 客户端 Token（幂等：同设备复用）"""
    auth = parse_emby_authorization(request.headers.get("X-Emby-Authorization"))
    device_id = auth.get("DeviceId") or request.headers.get("X-Device-Id") or "unknown-device"
    app_name = auth.get("Client") or "Emby Client"
    app_version = auth.get("Version") or "1.0"

    token_value = secrets.token_hex(20)

    row = emby_models.EmbyApiToken(
        token=token_value,
        user_id=user.id,
        device_id=device_id,
        app_name=app_name,
        app_version=app_version,
        last_ip=request.client.host if request.client else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return token_value, row


def _token_from_request(request: Request) -> Optional[str]:
    token = request.headers.get("X-Emby-Token") or request.headers.get("X-MediaBrowser-Token")
    if token:
        return token.strip()
    auth = request.headers.get("Authorization") or request.headers.get("X-Emby-Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # Emby 传统 query 参数 api_key
    token = request.query_params.get("api_key")
    if token:
        return token
    return None


def resolve_token(db: Session, request: Request) -> Optional[tuple[models.WebUser, emby_models.EmbyApiToken]]:
    """从请求解析 Emby token，返回 (user, token_row)"""
    token_value = _token_from_request(request)
    if not token_value:
        return None
    row = (
        db.query(emby_models.EmbyApiToken)
        .filter(
            emby_models.EmbyApiToken.token == token_value,
            emby_models.EmbyApiToken.is_revoked == False,  # noqa: E712
        )
        .first()
    )
    if not row:
        return None
    user = db.query(models.WebUser).filter(models.WebUser.id == row.user_id).first()
    if not user or not user.is_active:
        return None
    return user, row


def get_emby_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> models.WebUser:
    """Emby 客户端鉴权依赖"""
    result = None
    if credentials and credentials.credentials:
        row = (
            db.query(emby_models.EmbyApiToken)
            .filter(
                emby_models.EmbyApiToken.token == credentials.credentials,
                emby_models.EmbyApiToken.is_revoked == False,  # noqa: E712
            )
            .first()
        )
        if row:
            user = db.query(models.WebUser).filter(models.WebUser.id == row.user_id).first()
            if user and user.is_active:
                result = (user, row)
    if result is None:
        result = resolve_token(db, request)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )
    user, token_row = result
    token_row.last_used_at = datetime.now()
    db.commit()
    return user


def get_admin_or_emby_user(request: Request, db: Session = Depends(get_db)) -> models.WebUser:
    """门户端鉴权：JWT 优先，回退到 Emby 客户端 token

    旧版数字 token 默认已禁用（可被枚举冒充任意用户）。
    如需临时兼容已部署前端，可设置环境变量 EMBY_ALLOW_LEGACY_TOKENS=true。
    """
    import os

    raw = (
        request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        or request.query_params.get("api_key", "")
    )
    if raw:
        from backend.security import resolve_jwt_user_id

        jwt_user_id = resolve_jwt_user_id(raw)
        if jwt_user_id is None and raw.isdigit() and os.getenv("EMBY_ALLOW_LEGACY_TOKENS", "").lower() == "true":
            jwt_user_id = int(raw)  # 旧版数字 token 兼容（需显式开启）
        if jwt_user_id is not None:
            user = db.query(models.WebUser).filter(models.WebUser.id == jwt_user_id).first()
            if user and user.is_active:
                return user

    # Emby 客户端 token
    result = resolve_token(db, request)
    if result:
        return result[0]

    raise HTTPException(status_code=401, detail="未提供认证凭证")

