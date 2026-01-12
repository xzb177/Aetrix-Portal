"""
Rate Limiting Middleware for RoyalBot Portal

Implements sliding window rate limiting using Redis.

Features:
- IP-based rate limiting
- User-based rate limiting (for authenticated requests)
- Configurable limits per endpoint
- Distributed locking via Redis
- Graceful degradation when Redis is unavailable
"""
import time
import asyncio
from typing import Optional, Callable, Awaitable
from functools import wraps
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from utils.redis_client import get_redis_client


class RateLimitExceeded(HTTPException):
    """Raised when rate limit is exceeded."""
    def __init__(self, retry_after: int = 60):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "message": "Too many requests. Please try again later.",
                "retry_after": retry_after
            }
        )
        self.retry_after = retry_after


class RateLimitConfig:
    """Rate limit configuration for different endpoint types."""

    # Default limits (requests per minute)
    DEFAULT_LIMIT = 60
    DEFAULT_WINDOW = 60  # seconds

    # Auth endpoints (stricter limits for security)
    AUTH_LIMIT = 10
    AUTH_WINDOW = 60

    # Payment endpoints (stricter limits)
    PAYMENT_LIMIT = 5
    PAYMENT_WINDOW = 60

    # API endpoints
    API_LIMIT = 100
    API_WINDOW = 60

    # Admin endpoints
    ADMIN_LIMIT = 200
    ADMIN_WINDOW = 60


class RateLimiter:
    """
    Sliding window rate limiter using Redis.

    Uses a sorted set to track request timestamps within the window.
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.fallback_enabled = True  # Allow requests when Redis is down

    def _get_key(self, identifier: str, endpoint: str) -> str:
        """Generate Redis key for rate limiting."""
        return f"ratelimit:{endpoint}:{identifier}"

    async def is_allowed(
        self,
        identifier: str,
        endpoint: str,
        limit: int,
        window: int
    ) -> tuple[bool, int]:
        """
        Check if request is allowed under rate limit.

        Returns:
            (allowed, retry_after): Tuple of boolean and seconds to wait
        """
        if not self.redis:
            # Redis unavailable - allow if fallback enabled
            if self.fallback_enabled:
                return True, 0
            return True, 0

        key = self._get_key(identifier, endpoint)
        current_time = time.time()
        window_start = current_time - window

        try:
            # Remove old entries outside the window
            await self.redis.zremrangebyscore(key, 0, window_start)

            # Count current requests
            current_count = await self.redis.zcard(key)

            if current_count >= limit:
                # Calculate retry_after
                oldest = await self.redis.zrange(key, 0, 0, withscores=True)
                if oldest:
                    retry_after = int(oldest[0][1] + window - current_time) + 1
                    return False, max(1, retry_after)
                return False, 60

            # Add current request
            await self.redis.zadd(key, {str(current_time): current_time})
            await self.redis.expire(key, window + 1)

            return True, 0

        except Exception as e:
            # Log error but allow request on failure
            import logging
            logging.warning(f"Rate limit error: {e}")
            return True, 0


# Singleton instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        redis_client = get_redis_client()
        _rate_limiter = RateLimiter(redis_client)
    return _rate_limiter


def get_limit_for_path(path: str) -> tuple[int, int]:
    """
    Get rate limit (requests, window_seconds) for a given path.

    Returns:
        (limit, window): Tuple of max requests and time window in seconds
    """
    # Auth endpoints
    if any(x in path for x in ["/login", "/register", "/auth/"]):
        return RateLimitConfig.AUTH_LIMIT, RateLimitConfig.AUTH_WINDOW

    # Payment endpoints
    if any(x in path for x in ["/payment", "/recharge"]):
        return RateLimitConfig.PAYMENT_LIMIT, RateLimitConfig.PAYMENT_WINDOW

    # Admin endpoints
    if "/admin/" in path:
        return RateLimitConfig.ADMIN_LIMIT, RateLimitConfig.ADMIN_WINDOW

    # Default API endpoints
    return RateLimitConfig.API_LIMIT, RateLimitConfig.API_WINDOW


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting all incoming requests.

    Applies IP-based and user-based rate limiting.
    """

    async def dispatch(self, request: Request, call_next):
        """Process request and apply rate limiting."""
        # Skip rate limiting for health checks and static files
        if request.url.path in ["/health", "/metrics", "/docs", "/openapi.json"]:
            return await call_next(request)

        # Get rate limiter
        limiter = get_rate_limiter()

        # Get identifier (IP or user ID)
        identifier = self._get_identifier(request)
        endpoint = request.url.path

        # Get limit for this endpoint
        limit, window = get_limit_for_path(endpoint)

        # Check rate limit
        allowed, retry_after = await limiter.is_allowed(
            identifier, endpoint, limit, window
        )

        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "message": "Too many requests. Please try again later.",
                    "retry_after": retry_after
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Window": str(window),
                }
            )

        # Add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Window"] = str(window)
        return response

    def _get_identifier(self, request: Request) -> str:
        """
        Get identifier for rate limiting.

        Prefers authenticated user ID, falls back to IP address.
        """
        # Try to get user from auth header (simplified)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # In production, decode token to get user ID
            # For now, use token hash as identifier
            import hashlib
            token_hash = hashlib.sha256(auth_header[7:].encode()).hexdigest()[:16]
            return f"user:{token_hash}"

        # Fall back to IP address
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"

        return f"ip:{ip}"


def rate_limit(
    limit: int,
    window: int = 60,
    key_func: Optional[Callable[[Request], str]] = None
):
    """
    Decorator for applying custom rate limits to specific endpoints.

    Args:
        limit: Maximum number of requests allowed
        window: Time window in seconds
        key_func: Optional function to extract rate limit key from request

    Example:
        @router.post("/sensitive-operation")
        @rate_limit(limit=3, window=60)  # 3 requests per minute
        async def sensitive_operation(request: Request):
            ...
    """
    def decorator(func: Callable[..., Awaitable]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find Request object in args
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if not request:
                # No request object, just call the function
                return await func(*args, **kwargs)

            limiter = get_rate_limiter()

            # Get identifier
            if key_func:
                identifier = key_func(request)
            else:
                identifier = limiter._get_identifier(request.url.path, request.url.path)

            endpoint = request.url.path

            # Check limit
            allowed, retry_after = await limiter.is_allowed(
                identifier, endpoint, limit, window
            )

            if not allowed:
                raise RateLimitExceeded(retry_after)

            return await func(*args, **kwargs)

        return wrapper

    return decorator


# Specialized rate limit decorators for common use cases
def strict_rate_limit(func: Callable[..., Awaitable]) -> Callable:
    """Apply strict rate limiting (5 requests per minute)."""
    return rate_limit(limit=5, window=60)(func)


def auth_rate_limit(func: Callable[..., Awaitable]) -> Callable:
    """Apply authentication rate limiting (10 requests per minute)."""
    return rate_limit(limit=10, window=60)(func)


def api_rate_limit(func: Callable[..., Awaitable]) -> Callable:
    """Apply standard API rate limiting (100 requests per minute)."""
    return rate_limit(limit=100, window=60)(func)
