"""
安全中间件 — 用户端
从管理端适配，提供安全头、限流、输入清理
"""
import time
import secrets
from collections import defaultdict
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        return response


class RateLimiter:
    """简单内存限流器（用户端已有 Redis 限流中间件，此为补充）"""

    def __init__(self):
        self.requests: defaultdict = defaultdict(list)
        self.banned_ips: dict = {}
        self.last_cleanup = time.time()

    def is_allowed(self, ip: str, max_requests: int = 60, window: int = 60) -> tuple[bool, int]:
        now = time.time()
        if ip in self.banned_ips:
            if now < self.banned_ips[ip]:
                return False, int(self.banned_ips[ip] - now)
            del self.banned_ips[ip]
        if now - self.last_cleanup > 300:
            self._cleanup(now)
        self.requests[ip] = [t for t in self.requests[ip] if now - t < window]
        if len(self.requests[ip]) >= max_requests:
            self.banned_ips[ip] = now + min(300, window * 2)
            return False, min(300, window * 2)
        self.requests[ip].append(now)
        return True, 0

    def _cleanup(self, now: float):
        cutoff = now - 3600
        for ip in list(self.requests.keys()):
            self.requests[ip] = [t for t in self.requests[ip] if t > cutoff]
            if not self.requests[ip]:
                del self.requests[ip]
        for ip in list(self.banned_ips.keys()):
            if now >= self.banned_ips[ip]:
                del self.banned_ips[ip]
        self.last_cleanup = now


_rate_limiter = RateLimiter()


class SecurityRateLimitMiddleware(BaseHTTPMiddleware):
    """敏感接口限流 + 安全头"""

    SENSITIVE_PATHS = {
        "/api/user/auth/login": (5, 60),
        "/api/user/auth/register": (3, 3600),
    }
    DEFAULT_LIMIT = (60, 60)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not ip:
            ip = request.headers.get("X-Real-IP", "")
        if not ip:
            ip = request.client.host if request.client else "unknown"

        path = request.url.path
        max_req, window = self.SENSITIVE_PATHS.get(path, self.DEFAULT_LIMIT)
        allowed, retry_after = _rate_limiter.is_allowed(ip, max_req, window)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
