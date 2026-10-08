"""后台 worker 线程存活注册表（StrmAssistant 打磨 R2）。

各 worker 启动时调用 ``register(name, thread)``，/api/health 通过
``snapshot()`` 检查线程是否存活。线程静默死亡时 health 会报 warn，
避免"后台任务停摆了却没人知道"。
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
# name -> {"thread": Thread, "started_at": float, "last_heartbeat": float}
_registry: dict = {}


def register(name: str, thread: threading.Thread) -> None:
    """注册 worker 线程。"""
    with _lock:
        _registry[name] = {
            "thread": thread,
            "started_at": time.time(),
            "last_heartbeat": time.time(),
        }


def _redis():
    """取 Redis 客户端（没有则返回 None）。"""
    try:
        from backend import database as dbmod
        return dbmod.redis_client
    except Exception:
        return None


def heartbeat(name: str) -> None:
    """worker 每轮成功后调用，更新心跳时间（进程内 + Redis 跨进程）。"""
    with _lock:
        entry = _registry.get(name)
        if entry:
            entry["last_heartbeat"] = time.time()
    # 跨进程：API 容器的 /api/health 要能看到 worker 容器的线程状态
    try:
        r = _redis()
        if r is not None:
            r.setex(f"worker:heartbeat:{name}", 3600, str(int(time.time())))
            r.setex(f"worker:alive:{name}", 3600, "1")
    except Exception:
        pass


def snapshot() -> dict:
    """返回各 worker 存活状态（供 health 检查）。

    合并进程内注册表 + Redis 跨进程心跳（worker 容器写，API 容器读）。
    """
    out = {}
    now = time.time()
    with _lock:
        items = list(_registry.items())
    for name, entry in items:
        thread = entry["thread"]
        alive = bool(thread and thread.is_alive())
        out[name] = {
            "alive": alive,
            "uptime_sec": int(now - entry["started_at"]),
            "idle_sec": int(now - entry["last_heartbeat"]),
        }
    # Redis 跨进程心跳（API 容器看 worker 容器的状态）
    # 心跳超过 1 小时未更新 → 视为死亡（线程崩了或容器挂了）
    try:
        r = _redis()
        if r is not None:
            for key in r.scan_iter("worker:heartbeat:*"):
                name = key.decode() if isinstance(key, bytes) else key
                name = name.split(":", 2)[-1]
                if name in out:
                    continue
                ts = r.get(key)
                ts = float(ts) if ts else 0
                idle = int(now - ts) if ts else -1
                out[name] = {
                    "alive": idle >= 0 and idle < 3600,
                    "uptime_sec": -1,
                    "idle_sec": idle,
                    "via": "redis",
                }
    except Exception:
        pass
    return out
