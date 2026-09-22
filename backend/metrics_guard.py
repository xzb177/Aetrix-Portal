"""Prometheus ``/metrics`` 的访问控制

``/metrics`` 会列出全部路由、请求计数与进程指标，裸挂在公网等于把内部结构交出去
（operations.md 之前只指望运维自己在 Nginx 上加 ``allow``）。这里给一个默认安全的兜底：

- 默认只放行 **本机（回环）与内网** 来源：本机采集（node_exporter / 同一个 Docker 网络 /
  SSH 隧道）都不受影响；
- 需要从公网采集时显式设置 ``METRICS_ALLOW_REMOTE=true``（同时建议在 Nginx 上继续限制）。

被拒绝的请求返回 403 并写一条告警日志，便于发现「有人在扫 /metrics」。
"""
from __future__ import annotations

import ipaddress
import logging
import os

logger = logging.getLogger(__name__)

_ALLOWED_TRUE = {"1", "true", "yes", "on"}
_LOCAL_HOSTS = {"localhost", "testclient", "::1"}


def remote_allowed() -> bool:
    """是否显式允许公网访问 /metrics"""
    return os.getenv("METRICS_ALLOW_REMOTE", "").strip().lower() in _ALLOWED_TRUE


def is_local_host(host: str) -> bool:
    """本机或内网地址（回环 + RFC1918）"""
    if not host:
        return False
    if host in _LOCAL_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


class MetricsGuard:
    """只放行本机/内网来源的 ASGI 包装（挂在 ``/metrics`` 上）"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or remote_allowed():
            return await self.app(scope, receive, send)

        client = scope.get("client") or ("", 0)
        host = client[0] if client else ""
        if is_local_host(host):
            return await self.app(scope, receive, send)

        logger.warning(
            "已拒绝来自 %s 的 /metrics 访问（默认只允许本机/内网；"
            "确需公网采集请设 METRICS_ALLOW_REMOTE=true 并在反代上限制）",
            host or "未知",
        )
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        })
        await send({"type": "http.response.body", "body": b"metrics: forbidden"})
