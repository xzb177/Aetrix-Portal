"""认证安全工具：密码哈希 + JWT 签发/校验"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# JWT 配置：优先环境变量 SECRET_KEY；未设置时使用临时随机密钥（重启后 token 失效）
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

if os.getenv("SECRET_KEY") and len(os.getenv("SECRET_KEY", "")) < 32:
    logger.warning(
        "SECRET_KEY 长度过短（<32 字符），建议使用 48+ 字节随机密钥。"
        "生成方式: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
elif not os.getenv("SECRET_KEY"):
    logger.warning(
        "SECRET_KEY 未设置，使用临时随机密钥；重启后已签发的 token 将失效。"
        "生产环境请在环境变量中设置 SECRET_KEY。"
    )


def hash_password(password: str) -> str:
    """生成 bcrypt 密码哈希（72 字节限制内截断与 bcrypt 规范一致）"""
    pwd = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验密码"""
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:72], hashed_password.encode("utf-8")
        )
    except ValueError:
        return False


def _create_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    # jti 保证同秒签发的 token 唯一（刷新轮换语义）
    to_encode.update({"exp": expire, "type": token_type, "jti": secrets.token_hex(8)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, extra: Optional[dict[str, Any]] = None) -> str:
    payload = {"sub": str(user_id)}
    if extra:
        payload.update(extra)
    return _create_token(payload, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), "access")


def create_refresh_token(user_id: int) -> str:
    return _create_token({"sub": str(user_id)}, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str, expected_type: Optional[str] = None) -> Optional[dict]:
    """解码并校验 JWT；无效/过期/类型不符返回 None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if expected_type and payload.get("type") != expected_type:
        return None
    return payload


def resolve_jwt_user_id(token: str) -> Optional[int]:
    """从 access token 解出 user_id"""
    payload = decode_token(token, expected_type="access")
    if not payload:
        return None
    try:
        return int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
