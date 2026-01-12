"""
JWT Token Handling - Shared Module

Provides JWT creation and validation for both backends.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass
from jose import JWTError, jwt
import logging

logger = logging.getLogger(__name__)


@dataclass
class TokenPayload:
    """JWT token payload."""
    sub: str  # Subject (usually user ID)
    exp: Optional[int] = None  # Expiration time
    iat: Optional[int] = None  # Issued at
    type: str = "access"  # Token type (access/refresh)
    extra: Optional[Dict[str, Any]] = None  # Additional claims


class JWTConfig:
    """JWT configuration."""
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 240,
        refresh_token_expire_days: int = 30,
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days


# Default config (will be overridden by application settings)
_default_config: Optional[JWTConfig] = None


def get_jwt_config() -> JWTConfig:
    """Get or create default JWT config."""
    global _default_config
    if _default_config is None:
        import os
        secret_key = os.getenv("SECRET_KEY", os.getenv("JWT_SECRET_KEY", ""))
        if not secret_key:
            raise ValueError("JWT secret key not configured")
        _default_config = JWTConfig(secret_key=secret_key)
    return _default_config


def set_jwt_config(config: JWTConfig) -> None:
    """Set JWT config (for testing or custom configuration)."""
    global _default_config
    _default_config = config


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
    config: Optional[JWTConfig] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        subject: Subject (usually user ID)
        expires_delta: Optional custom expiration time
        extra_claims: Additional claims to include
        config: Optional JWT config (uses default if not provided)

    Returns:
        Encoded JWT token string
    """
    config = config or get_jwt_config()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=config.access_token_expire_minutes
        )

    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access",
    }

    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(
        to_encode,
        config.secret_key,
        algorithm=config.algorithm
    )
    return encoded_jwt


def create_refresh_token(
    subject: str,
    config: Optional[JWTConfig] = None,
) -> str:
    """
    Create a JWT refresh token.

    Refresh tokens have longer expiration than access tokens.

    Args:
        subject: Subject (usually user ID)
        config: Optional JWT config

    Returns:
        Encoded JWT refresh token string
    """
    config = config or get_jwt_config()
    expires_delta = timedelta(days=config.refresh_token_expire_days)

    return create_access_token(
        subject=subject,
        expires_delta=expires_delta,
        extra_claims={"type": "refresh"},
        config=config,
    )


def decode_access_token(
    token: str,
    config: Optional[JWTConfig] = None,
) -> Optional[TokenPayload]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token string
        config: Optional JWT config

    Returns:
        TokenPayload if valid, None if invalid
    """
    config = config or get_jwt_config()

    try:
        payload = jwt.decode(
            token,
            config.secret_key,
            algorithms=[config.algorithm]
        )

        sub = payload.get("sub")
        if not sub:
            return None

        return TokenPayload(
            sub=sub,
            exp=payload.get("exp"),
            iat=payload.get("iat"),
            type=payload.get("type", "access"),
            extra={k: v for k, v in payload.items()
                   if k not in ["sub", "exp", "iat", "type"]},
        )

    except JWTError as e:
        logger.debug(f"Token decode error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected token error: {e}")
        return None


def verify_token_type(token: str, token_type: str = "access") -> bool:
    """
    Verify that a token is of the specified type.

    Args:
        token: JWT token string
        token_type: Expected token type (access/refresh)

    Returns:
        True if token is valid and of expected type
    """
    payload = decode_access_token(token)
    if not payload:
        return False

    return payload.type == token_type
