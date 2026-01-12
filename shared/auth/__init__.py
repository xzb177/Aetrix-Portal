"""
Shared Authentication Module

Common authentication utilities for both backends.
"""
from .jwt import (
    create_access_token,
    decode_access_token,
    create_refresh_token,
    TokenPayload,
)
from .password import (
    hash_password,
    verify_password,
    validate_password_strength,
    generate_random_password,
)

__all__ = [
    "create_access_token",
    "decode_access_token",
    "create_refresh_token",
    "TokenPayload",
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "generate_random_password",
]
