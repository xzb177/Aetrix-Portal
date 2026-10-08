"""后台 worker 线程存活注册表（StrmAssistant 打磨 R2）。

各 worker 启动时调用 ``register(name, thread)``，/api/health 通过
``snapshot()`` 检查线程是否存活。线程静默死亡时 health 会报 warn，
避免"后台任务停摆了却没人知道"。

v2.53：``register`` 可带 ``restart`` 回调。``ensure_supervisor()`` 起一个守护线程，
每 ``SUPERVISE_INTERVAL_SEC`` 检查一次：登记了 restart 的线程死了就调用它重启
（探测 worker 曾经线程静默退出后只剩「定时器在跑」的假象）。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# name -> {"thread", "started_at", "last_heartbeat", "restart", "restarts"}
_registry: dict = {}

SUPERVISE_INTERVAL_SEC = 30.0
_supervisor: Optional[threading.Thread] = None
_supervisor_stop = threading.Event()


def register(name: str, thread: threading.Thread,
             restart: Optional[Callable[[], None]] = None) -> None:
    """注册 worker 线程（重启后再次注册会保留重启计数）。"""
    with _lock:
        prev = _registry.get(name) or {}
        _registry[name] = {
            "thread": thread,
            "started_at": time.time(),
            "last_heartbeat": time.time(),
            "restart": restart if restart is not None else prev.get("restart"),
            "restarts": int(prev.get("restarts", 0)),
        }


def _redis():
    """取 Redis 客户端（没有则返回 None）。"""
    try:
        from backend import database as dbmod
        return dbmod.redis_client
    except Exception:
        return None


def unregister(name: str) -> None:
    with _lock:
        _registry.pop(name, None)


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
            # health_report 按 status == "crashed" 告警（此前这里没有 status 字段，告警永不触发）
            "status": "running" if alive else "crashed",
            "uptime_sec": int(now - entry["started_at"]),
            "idle_sec": int(now - entry["last_heartbeat"]),
            "restarts": int(entry.get("restarts", 0)),
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
                alive = idle >= 0 and idle < 3600
                out[name] = {
                    "alive": alive,
                    "status": "running" if alive else "crashed",
                    "uptime_sec": -1,
                    "idle_sec": idle,
                    "via": "redis",
                }
    except Exception:
        pass
    return out


def supervise_once() -> list:
    """检查一轮：死掉且登记了 restart 的线程就重启。返回被重启的名字。"""
    restarted = []
    with _lock:
        items = list(_registry.items())
    for name, entry in items:
        thread = entry.get("thread")
        restart = entry.get("restart")
        if restart is None or (thread is not None and thread.is_alive()):
            continue
        logger.warning("后台线程 %s 已退出，监督线程正在重启它", name)
        with _lock:
            if name in _registry:
                _registry[name]["restarts"] = int(_registry[name].get("restarts", 0)) + 1
        try:
            restart()
            restarted.append(name)
        except Exception as exc:  # noqa: BLE001 — 重启失败下一轮再试
            logger.warning("重启后台线程 %s 失败: %s", name, exc)
    return restarted


def _supervise_loop() -> None:
    while not _supervisor_stop.wait(SUPERVISE_INTERVAL_SEC):
        try:
            supervise_once()
        except Exception as exc:  # noqa: BLE001
            logger.warning("worker 监督线程异常: %s", exc)


def ensure_supervisor() -> None:
    """启动监督线程（幂等）。"""
    global _supervisor
    with _lock:
        if _supervisor is not None and _supervisor.is_alive():
            return
        _supervisor_stop.clear()
        _supervisor = threading.Thread(target=_supervise_loop, name="worker-supervisor",
                                       daemon=True)
        _supervisor.start()
