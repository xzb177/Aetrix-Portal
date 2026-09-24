"""认证安全工具：密码哈希 + JWT 签发/校验"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# JWT 配置。
#
# 重要：模块导入阶段仍保留一个临时值，让 CLI / 测试可以先导入模型；真正启动
# EM/EA 时由 validate_secret_key() fail-closed。这样不会把“随机密钥能启动”误当成
# 生产安全配置，也不会让导入期异常吞掉清晰的启动错误。
_RAW_SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
_ALLOW_EPHEMERAL_SECRET = os.getenv("ALLOW_EPHEMERAL_SECRET", "").strip().lower() in {
    "1", "true", "yes", "on",
}
SECRET_KEY = _RAW_SECRET_KEY or secrets.token_urlsafe(48)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))


def validate_secret_key() -> str:
    """验证服务启动所需的固定 JWT 密钥，并返回实际密钥。

    生产默认拒绝未配置或过短的密钥。临时随机密钥只能通过显式的
    ``ALLOW_EPHEMERAL_SECRET=true`` 开启，适合一次性本地测试，不应写进生产环境。
    """
    # JWT 签名密钥在导入时固定；运行中改环境变量不能悄悄造成“校验通过但
    # 签名仍用旧值”。同时允许配对检查在测试中临时移除环境变量验证拒绝行为。
    if os.getenv("SECRET_KEY", "").strip() != _RAW_SECRET_KEY:
        raise RuntimeError("SECRET_KEY 在模块导入后发生变化；请使用同一固定密钥重启服务。")
    if not _RAW_SECRET_KEY:
        if _ALLOW_EPHEMERAL_SECRET:
            logger.warning(
                "ALLOW_EPHEMERAL_SECRET 已开启：当前使用临时 JWT 密钥，重启后所有 token 将失效；"
                "仅适用于一次性开发/测试。"
            )
            return SECRET_KEY
        raise RuntimeError(
            "SECRET_KEY 未设置。为避免 JWT 在重启后更换、或使用不可控的临时密钥，"
            "服务拒绝启动。请设置至少 32 字符的随机 SECRET_KEY；"
            "一次性本地测试可显式设置 ALLOW_EPHEMERAL_SECRET=true。"
        )
    if len(_RAW_SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY 长度不足 32 字符，服务拒绝启动。"
            "请使用 python3 -c \"import secrets; print(secrets.token_urlsafe(48))\" 生成随机密钥。"
        )
    return _RAW_SECRET_KEY


if _RAW_SECRET_KEY and len(_RAW_SECRET_KEY) < 32:
    logger.warning("SECRET_KEY 长度不足 32 字符；服务启动时将拒绝该配置。")
elif not _RAW_SECRET_KEY and not _ALLOW_EPHEMERAL_SECRET:
    logger.warning("SECRET_KEY 未设置；EM/EA 在启动生命周期阶段将拒绝启动。")


_BCRYPT_SHA256_PREFIX = "$bcrypt-sha256$"


def _bcrypt_input(password: str) -> bytes:
    """把任意长度 UTF-8 密码压到固定长度摘要，再交给 bcrypt。

    bcrypt 原生只看前 72 **字节**；直接截断会让两个不同的长密码变成同一个凭据。
    新哈希使用显式前缀，旧 `$2b$...` 哈希仍按旧规则校验并可在成功登录时升级。
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(password: str) -> str:
    """生成不会因 bcrypt 72 字节限制而碰撞的 bcrypt 哈希"""
    digest = bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode("ascii")
    return f"{_BCRYPT_SHA256_PREFIX}{digest}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验新摘要 bcrypt、旧 bcrypt 与历史错误格式；异常一律失败"""
    if not hashed_password:
        return False
    try:
        encoded = hashed_password.encode("ascii")
        if hashed_password.startswith(_BCRYPT_SHA256_PREFIX):
            encoded = hashed_password[len(_BCRYPT_SHA256_PREFIX):].encode("ascii")
            return bcrypt.checkpw(_bcrypt_input(plain_password), encoded)
        # 历史版本将密码按 72 字节截断，必须保留兼容登录路径；成功后由调用方可升级。
        return bcrypt.checkpw(plain_password.encode("utf-8")[:72], encoded)
    except (ValueError, TypeError, UnicodeEncodeError):
        return False


def needs_password_rehash(hashed_password: str) -> bool:
    """是否仍是旧 bcrypt/明文格式，需要在成功认证后升级"""
    return bool(hashed_password) and not hashed_password.startswith(_BCRYPT_SHA256_PREFIX)


def _create_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    # 每个 JWT 都带随机 jti，便于日志关联与排查。
    to_encode.update({"exp": expire, "type": token_type, "jti": secrets.token_hex(16)})
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
