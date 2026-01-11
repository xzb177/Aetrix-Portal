"""
安全中间件 - 速率限制、安全头、请求验证
"""
import time
import secrets
from collections import defaultdict
from typing import Callable
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """简单的内存速率限制器"""

    def __init__(self):
        # 存储每个IP的请求时间戳: {ip: [(timestamp1, timestamp2), ...]}
        self.requests: defaultdict = defaultdict(list)
        # 存储被封禁的IP: {ip: unblock_time}
        self.banned_ips: dict = {}
        # 清理旧数据的间隔
        self.cleanup_interval = 300  # 5分钟
        self.last_cleanup = time.time()

    def is_allowed(
        self,
        ip: str,
        max_requests: int = 60,
        window_seconds: int = 60
    ) -> tuple[bool, int]:
        """
        检查IP是否允许请求

        Args:
            ip: 客户端IP
            max_requests: 时间窗口内最大请求数
            window_seconds: 时间窗口（秒）

        Returns:
            (是否允许, 剩余秒数)
        """
        current_time = time.time()

        # 检查是否被封禁
        if ip in self.banned_ips:
            if current_time < self.banned_ips[ip]:
                remaining = int(self.banned_ips[ip] - current_time)
                return False, remaining
            else:
                del self.banned_ips[ip]

        # 定期清理旧数据
        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup(current_time)

        # 清理该IP的旧请求
        self.requests[ip] = [
            ts for ts in self.requests[ip]
            if current_time - ts < window_seconds
        ]

        # 检查请求次数
        request_count = len(self.requests[ip])

        if request_count >= max_requests:
            # 超过限制，临时封禁
            ban_duration = min(300, window_seconds * 2)  # 最多5分钟
            self.banned_ips[ip] = current_time + ban_duration
            logger.warning(f"IP {ip} exceeded rate limit, banned for {ban_duration}s")
            return False, ban_duration

        # 记录本次请求
        self.requests[ip].append(current_time)
        return True, 0

    def _cleanup(self, current_time: float):
        """清理旧数据"""
        cutoff = current_time - 3600  # 删除1小时前的数据
        for ip in list(self.requests.keys()):
            self.requests[ip] = [
                ts for ts in self.requests[ip]
                if ts > cutoff
            ]
            if not self.requests[ip]:
                del self.requests[ip]

        # 清理过期的封禁
        for ip in list(self.banned_ips.keys()):
            if current_time >= self.banned_ips[ip]:
                del self.banned_ips[ip]

        self.last_cleanup = current_time


# 全局限流器实例
rate_limiter = RateLimiter()


class SecurityMiddleware(BaseHTTPMiddleware):
    """安全中间件"""

    # 敏感操作需要更严格的限制
    SENSITIVE_PATHS = {
        "/api/auth/login": (5, 60),      # 登录: 5次/分钟
        "/api/auth/register": (3, 3600), # 注册: 3次/小时
    }

    # 默认限制
    DEFAULT_LIMIT = (60, 60)  # 60次/分钟

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 获取客户端IP
        ip = self._get_client_ip(request)

        # 获取该路径的速率限制
        path = request.url.path
        limit = self.SENSITIVE_PATHS.get(path, self.DEFAULT_LIMIT)
        max_requests, window_seconds = limit

        # 检查速率限制
        allowed, retry_after = rate_limiter.is_allowed(ip, max_requests, window_seconds)

        if not allowed:
            logger.warning(f"Rate limit exceeded for IP {ip} on {path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "请求过于频繁，请稍后再试",
                    "retry_after": retry_after
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Window": str(window_seconds),
                }
            )

        # 处理请求
        response = await call_next(request)

        # 添加安全头
        self._add_security_headers(response)

        # 添加速率限制头
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Window"] = str(window_seconds)
        response.headers["X-Content-Type-Options"] = "nosniff"

        return response

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP"""
        # 检查代理头
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"

    def _add_security_headers(self, response: Response):
        """添加安全响应头"""
        # 防止点击劫持
        response.headers["X-Frame-Options"] = "DENY"

        # 防止MIME类型嗅探
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 启用浏览器XSS过滤
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # 限制引用来源
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 内容安全策略
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )

        # HSTS (仅在HTTPS时启用)
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def generate_csrf_token() -> str:
    """生成CSRF令牌"""
    return secrets.token_urlsafe(32)


def validate_csrf_token(token: str, stored_token: str) -> bool:
    """验证CSRF令牌"""
    return secrets.compare_digest(token, stored_token)


class InputSanitizer:
    """输入清理工具"""

    # 危险字符和模式
    DANGEROUS_PATTERNS = [
        "<script", "javascript:", "onclick=", "onerror=",
        "onload=", "eval(", "expression(", "vbscript:",
        "data:text/html", "--", ";", "xp_", "union select",
    ]

    @classmethod
    def sanitize_string(cls, value: str, max_length: int = 1000) -> str:
        """清理字符串输入"""
        if not isinstance(value, str):
            return ""

        # 限制长度
        if len(value) > max_length:
            value = value[:max_length]

        # 转换为小写进行检查
        value_lower = value.lower()

        # 检查危险模式
        for pattern in cls.DANGEROUS_PATTERNS:
            if pattern in value_lower:
                logger.warning(f"Detected dangerous pattern in input: {pattern}")
                # 移除危险内容
                value = value.replace(pattern, "").replace(pattern.upper(), "")

        return value.strip()

    @classmethod
    def sanitize_email(cls, email: str) -> str:
        """清理邮箱输入"""
        if not isinstance(email, str):
            return ""

        email = email.strip().lower()
        # 基本邮箱格式验证
        if "@" not in email or "." not in email.split("@")[-1]:
            return ""

        # 限制长度
        if len(email) > 254:
            return ""

        return email

    @classmethod
    def sanitize_sort_column(cls, column: str, allowed_columns: set) -> str:
        """验证排序列名"""
        if column not in allowed_columns:
            return next(iter(allowed_columns)) if allowed_columns else "id"
        return column

    @classmethod
    def validate_pagination(cls, page: int, page_size: int, max_page_size: int = 100) -> tuple[int, int]:
        """验证分页参数"""
        page = max(1, min(page, 10000))  # 限制最大页数
        page_size = max(1, min(page_size, max_page_size))
        return page, page_size


# 安全相关的工具函数
def generate_secure_token(length: int = 32) -> str:
    """生成安全的随机令牌"""
    return secrets.token_urlsafe(length)


def hash_sensitive_data(data: str) -> str:
    """对敏感数据进行哈希（用于日志）"""
    import hashlib
    return hashlib.sha256(data.encode()).hexdigest()[:16]


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF 保护中间件 - Double Submit Cookie 模式

    此中间件验证所有状态修改操作 (POST, PUT, DELETE, PATCH) 的 CSRF token。
    白名单路径（如登录、登出）不需要 CSRF 验证。
    """

    # 需要 CSRF 验证的 HTTP 方法
    PROTECTED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

    # 白名单路径（不需要 CSRF 验证）
    WHITELIST_PATHS = {
        "/api/auth/login",
        "/api/auth/logout",
        "/health",
        "/api/auth/validate-token",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 只对状态修改操作进行 CSRF 验证
        if request.method in self.PROTECTED_METHODS:
            # 检查是否在白名单中
            if any(request.url.path.startswith(path) for path in self.WHITELIST_PATHS):
                return await call_next(request)

            # 从 cookie 获取 CSRF token
            csrf_cookie = request.cookies.get("admin_csrf_token")

            # 从 header 获取 CSRF token
            csrf_header = request.headers.get("X-CSRF-Token")

            # 验证 CSRF token
            if not csrf_cookie or not csrf_header:
                logger.warning(f"CSRF token missing for {request.url.path} from {self._get_client_ip(request)}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token 缺失", "code": "CSRF_TOKEN_MISSING"}
                )

            # 使用恒定时间比较防止时序攻击
            if not secrets.compare_digest(csrf_cookie, csrf_header):
                logger.warning(f"CSRF token mismatch for {request.url.path} from {self._get_client_ip(request)}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token 无效", "code": "CSRF_TOKEN_INVALID"}
                )

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件的别名（保持向后兼容）"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        return await SecurityMiddleware(request, call_next)
