"""
Password Handling - Shared Module

Provides password hashing, verification, and validation utilities.
"""
import secrets
import string
import re
import bcrypt
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# Password complexity requirements
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


class PasswordPolicy:
    """Password policy configuration."""

    def __init__(
        self,
        min_length: int = MIN_PASSWORD_LENGTH,
        max_length: int = MAX_PASSWORD_LENGTH,
        require_uppercase: bool = True,
        require_lowercase: bool = True,
        require_digits: bool = True,
        require_special: bool = True,
        forbidden_patterns: Optional[list[str]] = None,
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_digits = require_digits
        self.require_special = require_special
        self.forbidden_patterns = forbidden_patterns or []


# Default password policy
_default_policy = PasswordPolicy()


def set_password_policy(policy: PasswordPolicy) -> None:
    """Set the default password policy."""
    global _default_policy
    _default_policy = policy


def get_password_policy() -> PasswordPolicy:
    """Get the default password policy."""
    return _default_policy


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches hash
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception as e:
        logger.warning(f"Password verification error: {e}")
        return False


class PasswordValidationError(Exception):
    """Raised when password validation fails."""

    def __init__(self, message: str, errors: list[str]):
        self.message = message
        self.errors = errors
        super().__init__(message)


def validate_password_strength(
    password: str,
    policy: Optional[PasswordPolicy] = None,
) -> tuple[bool, list[str]]:
    """
    Validate password strength against policy.

    Args:
        password: Password to validate
        policy: Optional password policy (uses default if not provided)

    Returns:
        Tuple of (is_valid, error_messages)
    """
    policy = policy or get_password_policy()
    errors = []

    # Check length
    if len(password) < policy.min_length:
        errors.append(f"Password must be at least {policy.min_length} characters")

    if len(password) > policy.max_length:
        errors.append(f"Password must not exceed {policy.max_length} characters")

    # Check character requirements
    if policy.require_uppercase and not re.search(r'[A-Z]', password):
        errors.append("Password must contain at least one uppercase letter")

    if policy.require_lowercase and not re.search(r'[a-z]', password):
        errors.append("Password must contain at least one lowercase letter")

    if policy.require_digits and not re.search(r'\d', password):
        errors.append("Password must contain at least one digit")

    if policy.require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("Password must contain at least one special character")

    # Check forbidden patterns
    for pattern in policy.forbidden_patterns:
        if pattern.lower() in password.lower():
            errors.append(f"Password must not contain '{pattern}'")

    # Check for common weak passwords
    common_passwords = [
        "password", "12345678", "qwerty123", "admin123",
        "letmein", "welcome1", "monkey123", "password1"
    ]
    if password.lower() in common_passwords:
        errors.append("Password is too common")

    # Check for sequential characters
    if any(str(i) * 3 in password for i in range(10)):
        errors.append("Password must not contain repeated digits")

    return len(errors) == 0, errors


def generate_random_password(
    length: int = 16,
    policy: Optional[PasswordPolicy] = None,
) -> str:
    """
    Generate a secure random password.

    Args:
        length: Password length
        policy: Optional password policy to follow

    Returns:
        Generated password string
    """
    policy = policy or get_password_policy()

    # Ensure minimum length
    length = max(length, policy.min_length)

    # Character sets
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*()_+-=[]{}|;:,.<>?"

    # Build character pool
    pool = lowercase
    if policy.require_uppercase:
        pool += uppercase
    if policy.require_digits:
        pool += digits
    if policy.require_special:
        pool += special

    # Generate password
    password = "".join(secrets.choice(pool) for _ in range(length))

    # Ensure requirements are met
    if policy.require_uppercase and not re.search(r'[A-Z]', password):
        password = password[:-1] + secrets.choice(uppercase)
    if policy.require_digits and not re.search(r'\d', password):
        password = password[:-1] + secrets.choice(digits)
    if policy.require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        password = password[:-1] + secrets.choice(special)

    # Validate
    is_valid, errors = validate_password_strength(password, policy)
    if not is_valid:
        # Recursively generate if requirements not met
        return generate_random_password(length, policy)

    return password


def generate_reset_token() -> str:
    """
    Generate a secure token for password reset.

    Returns:
        URL-safe random token
    """
    return secrets.token_urlsafe(32)
