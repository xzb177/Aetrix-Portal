"""播放线路可观测（Phase 3）：进程内计数器

## 为什么是进程内而不是落库

计的是**这一进程经手了多少播放请求 / 多少字节出流量**。这类数字有两个特点：

1. 天然是「本进程」口径——流量确实只从本机出去，跨节点合并反而会重复计算
   （一体化部署时 EM=EA；分离部署时每个 EA 各出各的流）。所以面板上标注
   「本进程」，不谎报一个跨节点的水位。
2. 落库要**每次播放写一行**，这是播放热路径；而命中率这种**必须跨重启存活**
   的数字，项目里另有 `LocalCacheStat` 单行表在管（见 local_cache）。

计数失败绝不能影响播放：所有写入口都吞异常（``except Exception``），
最坏情况是这一轮数字没记上，播放照常。

## 记的是「有效线路」，不是用户选的那条

用户可能选了 cache 线路，但本机没副本 → 实际走的是回源直连。
这时候记 cache 会让运维以为「缓存线路很忙」，而真正的瓶颈在回源。
所以 :func:`record_request` 记的是**这次请求真正走的路径**。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

MB = 1024 * 1024


@dataclass
class LineCounter:
    """一条线路在本进程的累计计数"""

    line: str
    requests: int = 0
    bytes_out: int = 0
    degraded_requests: int = 0
    #: 降级原因 → 次数（「本机无副本，已回源」「Google 直链不可用，已回落代理」…）
    degrade_reasons: dict = field(default_factory=dict)
    last_used_at: float = 0.0

    def as_dict(self) -> dict:
        last = self.last_used_at or 0.0
        return {
            "line": self.line,
            "requests": self.requests,
            "bytes_out": self.bytes_out,
            "degraded_requests": self.degraded_requests,
            "degrade_reasons": dict(self.degrade_reasons),
            "last_used_at": last,
            "idle_seconds": int(max(0.0, time.time() - last)) if last else None,
        }


_LOCK = threading.Lock()
_COUNTERS: dict[str, LineCounter] = {}
_STARTED_AT = time.time()


def _counter(line: str) -> LineCounter:
    counter = _COUNTERS.get(line)
    if counter is None:
        counter = LineCounter(line=line)
        _COUNTERS[line] = counter
    return counter


def record_request(line: str, *, degraded: str = "") -> None:
    """记一次播放请求（按**有效线路**）

    ``degraded`` 非空时同时记一次降级——降级原因按原话累计，面板上能看出
    「这条线路一直退化成什么」，比只报一个布尔有用。
    """
    if not line:
        return
    try:
        with _LOCK:
            counter = _counter(line)
            counter.requests += 1
            counter.last_used_at = time.time()
            if degraded:
                counter.degraded_requests += 1
                key = str(degraded)[:80]
                counter.degrade_reasons[key] = counter.degrade_reasons.get(key, 0) + 1
    except Exception:  # noqa: BLE001 — 计数不该影响播放
        pass


def record_bytes(line: str, count: int) -> None:
    """记一次出流量（``count<=0`` 忽略；302 直连这类不经过本机的路径不记）

    口径：**本服务响应体里真正吐出去的字节**。不包含 ffmpeg 转码时的拉流，
    也不包含 StarletteFileResponse 整文件直发（它不走 body_iterator，
    宁可少算也不按 Content-Length 虚报）。
    """
    if not line or count <= 0:
        return
    try:
        with _LOCK:
            _counter(line).bytes_out += int(count)
    except Exception:  # noqa: BLE001 — 计数不该影响播放
        pass


def snapshot(lines: tuple) -> list[dict]:
    """按给定线路顺序导出计数（四条线路都要出现，没数据的是 0，不是缺失）"""
    try:
        with _LOCK:
            return [_counter(line).as_dict() for line in lines]
    except Exception:  # noqa: BLE001
        return [{"line": line, "requests": 0, "bytes_out": 0, "degraded_requests": 0,
                 "degrade_reasons": {}, "last_used_at": 0.0, "idle_seconds": None}
                for line in lines]


def counter(line: str) -> Optional[dict]:
    """单条线路的计数（快照组装用）"""
    rows = snapshot((line,))
    return rows[0] if rows else None


def uptime_seconds() -> int:
    """本进程已运行多久（面板标注「本进程」口径时要用）"""
    return int(max(0.0, time.time() - _STARTED_AT))


def reset() -> None:
    """测试用：清空全部计数（**不要**在生产路径调用）"""
    with _LOCK:
        _COUNTERS.clear()


def format_bytes(count: int) -> str:
    """给人看的字节数（面板直接用，省得前端再写一份）"""
    value = float(max(0, int(count or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


__all__ = [
    "LineCounter", "MB", "counter", "format_bytes", "record_bytes", "record_request",
    "reset", "snapshot", "uptime_seconds",
]