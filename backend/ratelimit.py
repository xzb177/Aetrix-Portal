"""进程内滑动窗口限流器

用于保护登录/注册/认证等端点免遭暴力破解。
单实例部署下足够；如需多实例共享限流状态，可将存储替换为 Redis。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Optional


class SlidingWindowLimiter:
    """滑动窗口计数限流：window 秒内最多 max_events 次"""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, max_events: int, window_seconds: float) -> tuple[bool, int]:
        """返回 (是否放行, 剩余需等待秒数)"""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            cutoff = now - window_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= max_events:
                retry_after = int(window_seconds - (now - q[0])) + 1
                return False, max(retry_after, 1)
            q.append(now)
            # 防止 key 无限增长：超过阈值时清理空队列
            if len(self._hits) > 10_000:
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


_limiter = SlidingWindowLimiter()


def check_rate_limit(key: str, max_events: int, window_seconds: float) -> tuple[bool, int]:
    """模块级便捷入口"""
    return _limiter.check(key, max_events, window_seconds)


def client_ip(request) -> str:
    """提取客户端 IP（只能信任我们自己的反代重新写入的头）

    安全：此值同时用于登录/注册/核销的限流键与登录日志，之前取
    `X-Forwarded-For` 的**第一段**——而仓库里的 Nginx 用的是
    `$proxy_add_x_forwarded_for`（把客户端自带的头追加在前面），
    于是任何人只要每次伪造一个 `X-Forwarded-For: 1.2.3.4` 就能换一个限流桶，
    暴力破解与刷接口形同不设限。现在的优先级：

    1. `X-Real-IP`：Nginx 按 `$remote_addr` 硬写，客户端无法伪造
    2. `X-Forwarded-For` 的**最后一段**：由最近一跳代理追加，才是真实客户端
    3. 直连时的 `request.client.host`
    """
    if request is None:
        return "unknown"
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        hops = [part.strip() for part in fwd.split(",") if part.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"
