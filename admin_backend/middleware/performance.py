"""
性能优化和安全中间件
- 响应压缩
- 请求限流
- 安全头部
"""
import time
import gzip
import json
from typing import Callable, Dict, Optional
from collections import defaultdict
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging

from admin_utils.config import settings

logger = logging.getLogger(__name__)


# ============ 内存限流器 ============
class RateLimiter:
    """基于内存的简单限流器（生产环境建议使用 Redis）"""

    def __init__(self):
        # {ip: [(timestamp, count)]}
        self.requests: Dict[str, list] = defaultdict(list)
        self.blocked_ips: Dict[str, float] = {}  # {ip: unblock_time}

    def is_allowed(self, ip: str, limit: int = 60, window: int = 60) -> tuple[bool, int]:
        """
        检查是否允许请求
        :param ip: 客户端IP
        :param limit: 时间窗口内最大请求数
        :param window: 时间窗口（秒）
        :return: (是否允许, 剩余请求数)
        """
        now = time.time()

        # 检查是否被封禁
        if ip in self.blocked_ips:
            if now < self.blocked_ips[ip]:
                remaining = int(self.blocked_ips[ip] - now)
                return False, 0
            else:
                del self.blocked_ips[ip]

        # 清理过期记录
        cutoff = now - window
        self.requests[ip] = [t for t in self.requests[ip] if t > cutoff]

        # 检查请求数
        request_count = len(self.requests[ip])

        if request_count >= limit:
            # 超过限制，封禁一段时间
            self.blocked_ips[ip] = now + 60  # 封禁1分钟
            logger.warning(f"Rate limit exceeded for IP: {ip}, blocked for 60 seconds")
            return False, 0

        # 记录本次请求
        self.requests[ip].append(now)
        return True, limit - request_count - 1

    def cleanup(self):
        """定期清理过期数据"""
        now = time.time()
        cutoff = now - 3600  # 清理1小时前的数据

        for ip in list(self.requests.keys()):
            self.requests[ip] = [t for t in self.requests[ip] if t > cutoff]
            if not self.requests[ip]:
                del self.requests[ip]

        for ip in list(self.blocked_ips.keys()):
            if self.blocked_ips[ip] < now:
                del self.blocked_ips[ip]


# 全局限流器实例
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """请求限流中间件"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rate_limiter = rate_limiter

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 获取客户端 IP
        forwarded = request.headers.get("X-Forwarded-For")
        client_ip = (forwarded.split(",")[0].strip() if forwarded
                     else request.client.host if request.client else "unknown")

        # 白名单路径（不限流）
        whitelist = ["/health", "/docs", "/redoc", "/openapi.json"]
        if any(request.url.path.startswith(path) for path in whitelist):
            return await call_next(request)

        # 检查限流
        if settings.ENABLE_RATE_LIMIT:
            allowed, remaining = self.rate_limiter.is_allowed(
                client_ip,
                limit=settings.RATE_LIMIT_PER_MINUTE,
                window=60
            )

            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "请求过于频繁，请稍后再试",
                        "code": "RATE_LIMIT_EXCEEDED"
                    },
                    headers={
                        "Retry-After": "60",
                        "X-RateLimit-Limit": str(settings.RATE_LIMIT_PER_MINUTE),
                        "X-RateLimit-Remaining": "0",
                    }
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_PER_MINUTE)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    安全响应头中间件 - 增强版

    提供的安全保护:
    - X-Content-Type-Options: 防止 MIME 类型嗅探
    - X-Frame-Options: 防止点击劫持
    - HSTS: 强制使用 HTTPS
    - CSP: 内容安全策略，防止 XSS
    - Permissions-Policy: 限制浏览器功能
    - Cross-Origin-*: 跨域策略
    """

    # CSP 策略配置
    # 注意: 生产环境应该根据实际需求调整，移除 unsafe-inline
    CSP_POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "  # TODO: 生产环境应该使用 nonce
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https:; "
        "frame-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "require-trusted-types-for 'script'; "
        "upgrade-insecure-requests; "
    )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # ============ 基础安全响应头 ============

        # 防止 MIME 类型嗅探
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 防止点击劫持
        response.headers["X-Frame-Options"] = "DENY"

        # XSS 保护 (旧版浏览器，新版浏览器靠 CSP)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # 引用策略 - 限制 Referer 头泄露
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 权限策略 - 限制浏览器功能访问
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=(), "
            "ambient-light-sensor=(), "
            "autoplay=(), "
            "encrypted-media=(), "
            "fullscreen=(self), "
            "picture-in-picture=(self)"
        )

        # ============ 跨域策略 ============

        # 跨域开放者策略
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        # 跨域资源策略
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # ============ HSTS (仅生产环境) ============
        if not settings.DEBUG:
            # 严格传输安全 - 2年有效期，包含子域名，预加载列表
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; "
                "includeSubDomains; "
                "preload"
            )

        # ============ Content Security Policy ============
        # 在生产环境中，CSP 应该更严格。建议使用 Report-Only 模式先测试。
        # 设置环境变量 CSP_REPORT_ONLY=true 可以进入报告模式（不阻止）
        csp_report_only = getattr(settings, 'CSP_REPORT_ONLY', False)
        csp_header_name = "Content-Security-Policy-Report-Only" if csp_report_only else "Content-Security-Policy"
        response.headers[csp_header_name] = self.CSP_POLICY

        # ============ 额外安全头 ============

        # 清除站点数据提示 (浏览器退出时清除所有站点数据)
        response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage", "executionContexts"' if request.url.path == "/api/auth/logout" else ""

        return response


class PerformanceMiddleware(BaseHTTPMiddleware):
    """性能监控中间件"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.request_times: Dict[str, list] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # 处理请求
        response = await call_next(request)

        # 计算处理时间
        process_time = (time.time() - start_time) * 1000  # 毫秒

        # 添加处理时间到响应头
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

        # 记录慢请求
        if process_time > 1000:  # 超过1秒
            logger.warning(
                f"Slow request detected: {request.method} {request.url.path} "
                f"took {process_time:.2f}ms"
            )

        # 统计请求时间（用于性能分析）
        path = request.url.path
        self.request_times[path].append(process_time)

        # 保持最近100次记录
        if len(self.request_times[path]) > 100:
            self.request_times[path].pop(0)

        return response

    def get_stats(self, path: Optional[str] = None) -> dict:
        """获取性能统计"""
        if path:
            times = self.request_times.get(path, [])
        else:
            times = []
            for t in self.request_times.values():
                times.extend(t)

        if not times:
            return {"count": 0, "avg": 0, "min": 0, "max": 0}

        return {
            "count": len(times),
            "avg": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
        }


class ResponseCompressionMiddleware(BaseHTTPMiddleware):
    """响应压缩中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # 检查客户端是否支持 gzip
        accept_encoding = request.headers.get("accept-encoding", "")
        if "gzip" not in accept_encoding.lower():
            return response

        # 只压缩文本内容
        content_type = response.headers.get("content-type", "")
        if not any(ct in content_type for ct in ["application/json", "text/", "application/xml"]):
            return response

        # 检查响应大小（小于1KB的不压缩）
        if hasattr(response, "body"):
            body_bytes = response.body
            if len(body_bytes) < 1024:
                return response

            # 压缩
            compressed = gzip.compress(body_bytes, compresslevel=6)

            # 只有压缩后更小才使用压缩
            if len(compressed) < len(body_bytes):
                response.headers["content-encoding"] = "gzip"
                response.headers["content-length"] = str(len(compressed))
                response.body = compressed

        return response
