"""域名强制 + Cloudflare 真实 IP：流节点隐藏源站 IP 的通用能力。

背景（分离架构）：流节点部署在高宽带大盘机器上，公网入口走 Cloudflare
（橙云）代理隐藏真实 IP，用户只能用域名访问。本模块提供两块开箱即用的能力：

1. ``DomainGuardMiddleware`` —— 强制域名访问：
   - 管理后台「流媒体加速」开关打开时，自动用配置的加速域名做白名单
     （DB 配置，进程内 60 秒 TTL 缓存，最长 60 秒生效）；
   - 环境变量 ``ENFORCE_DOMAIN``（逗号分隔，如 ``stream.example.com``）是运维
     手动覆盖：DB 开关未打开时才看它；都没设置时**完全透传**，单机部署行为一字不变；
   - 设置后，Host 头不在白名单的请求一律 403（防直接用 IP 绕过 CF 打源站）；
   - 例外：``/api/health`` 允许来自内网 IP（RFC1918 / 本机）的健康检查，
     主服务的节点健康检查走内网 IP 时不被误杀。

2. ``CloudflareIPMiddleware`` —— 取真实用户 IP：
   - 「流媒体加速」开关打开时自动启用；否则看环境变量 ``TRUST_CF_IP=true``
     （默认关闭，不信任任何代理头）；
   - 优先 ``CF-Connecting-IP``，回退 ``X-Forwarded-For`` 首个；
   - 只接受合法 IP 格式，非法的直接忽略（不让伪造头污染日志/限流）；
   - 把解析出的 IP 写回 ``scope["client"]``，下游的限流/日志拿到的就是真人 IP。

两个都是**纯 ASGI 中间件**（直接实现 ``__call__(scope, receive, send)``），
绝不使用 BaseHTTPMiddleware —— 后者会缓冲整个响应体，大文件流式播放会被它
拖死（2026-10-07 PR #388 的教训）。只碰 ``http.response.start`` 的头 / 直接
短路返回，不读、不改、不缓冲 body。
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# 环境变量
ENFORCE_DOMAIN_ENV = "ENFORCE_DOMAIN"
TRUST_CF_IP_ENV = "TRUST_CF_IP"

# 健康检查路径：内网来源放行，不受域名强制约束
HEALTH_PATHS = ("/api/health",)


# ---- 管理后台「流媒体加速」开关（DB 配置，store 统一 60 秒 TTL 缓存） ----
# 横切能力只许一套：带缓存的配置热读统一走 backend.integrations.store，
# 这里不另起一套 TTL。

def _accel_db_config() -> tuple[Optional[set[str]], Optional[bool]]:
    """读流媒体加速开关的 DB 配置。

    返回 ``(allowed_hosts, trust_cf)``；开关未打开或 DB 不可用时返回
    ``(None, None)``，调用方回退到环境变量。
    """
    try:
        from backend.database import SessionLocal
        from backend.integrations import store

        db = SessionLocal()
        try:
            vals = store.get_values(
                db,
                ["stream_accel_enabled", "stream_accel_domain"],
                {"stream_accel_enabled": "false", "stream_accel_domain": ""},
                ttl=60.0,
            )
        finally:
            db.close()
    except Exception:
        logger.debug("流媒体加速 DB 配置读取失败，回退环境变量", exc_info=True)
        return None, None
    enabled = (vals.get("stream_accel_enabled") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    domain = (vals.get("stream_accel_domain") or "").strip().lower()
    if enabled and domain:
        return {domain}, True
    return None, None


def _get_allowed_hosts() -> Optional[set[str]]:
    allowed, _ = _accel_db_config()
    if allowed:
        return allowed
    raw = (os.environ.get(ENFORCE_DOMAIN_ENV) or "").strip()
    if not raw:
        return None
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return hosts or None


def _trust_cf_ip() -> bool:
    _, trust_cf = _accel_db_config()
    if trust_cf:
        return True
    return (os.environ.get(TRUST_CF_IP_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _host_of(headers: dict[bytes, bytes]) -> str:
    for k, v in headers.items():
        if k.lower() == b"host":
            try:
                text = v.decode("latin-1").strip().lower()
            except Exception:
                return ""
            # 去掉端口：stream.example.com:8001 -> stream.example.com
            if text.startswith("["):  # IPv6 字面量 [::1]:8001
                end = text.find("]")
                return text[: end + 1] if end != -1 else text
            return text.split(":")[0]
    return ""


def _client_ip(scope: dict) -> str:
    client = scope.get("client")
    if isinstance(client, (list, tuple)) and client:
        return str(client[0])
    return ""


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def _valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


class DomainGuardMiddleware:
    """强制域名访问的纯 ASGI 中间件（见模块文档）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        allowed = _get_allowed_hosts()
        if not allowed:
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        # 健康检查 + 内网来源：放行（主服务节点健康检查走内网 IP）
        if path in HEALTH_PATHS and _is_private_ip(_client_ip(scope)):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        host = _host_of(headers)
        if host not in allowed:
            logger.warning("域名守卫拦截非域名访问: host=%r path=%s", host, path)
            body = b'{"error":"forbidden","reason":"direct ip access denied"}'
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class CloudflareIPMiddleware:
    """CF 真实 IP 还原的纯 ASGI 中间件（见模块文档）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") in ("http", "websocket") and _trust_cf_ip():
            headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
            real_ip = ""
            cf_ip = headers.get(b"cf-connecting-ip")
            if cf_ip:
                try:
                    real_ip = cf_ip.decode("latin-1").strip()
                except Exception:
                    real_ip = ""
            if not real_ip:
                xff = headers.get(b"x-forwarded-for")
                if xff:
                    try:
                        real_ip = xff.decode("latin-1").split(",")[0].strip()
                    except Exception:
                        real_ip = ""
            if real_ip and _valid_ip(real_ip):
                client = scope.get("client")
                port = client[1] if isinstance(client, (list, tuple)) and len(client) > 1 else 0
                scope["client"] = (real_ip, port)
                # 给下游留个标记：这个 IP 是代理头还原的
                scope.setdefault("state", {})["real_ip_from_proxy"] = real_ip
            elif real_ip:
                logger.warning("忽略非法代理 IP 头: %r", real_ip[:64])
        await self.app(scope, receive, send)
