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


def heartbeat(name: str) -> None:
    """worker 每轮成功后调用，更新心跳时间。"""
    with _lock:
        entry = _registry.get(name)
        if entry:
            entry["last_heartbeat"] = time.time()


def snapshot() -> dict:
    """返回各 worker 存活状态（供 health 检查）。"""
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
    return out
