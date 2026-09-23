"""扫描实时进度与远程 IO 计数（v2.27.0）

四个媒体库在同几秒内启动扫描时，面板上能看到的信息只有 ``scan_status=running`` 与
``item_count=0``——「到底扫到哪了、还要多久、现在卡在谁身上」全靠猜，管理员只能盯着容器 CPU。
这里保存**进程内**的实时进度：枚举到几个文件、处理到第几个、当前目录 / 当前文件、
最近一次远程请求发生在什么时候；管理端每几秒轮询一次就能画出进度条。

同时给扫描队列提供三条远程 IO 计数（真实请求数 / 复用次数 / 在飞的请求数），用来回答
「这轮为什么慢、慢在网络还是慢在解析」。

为什么单独一个模块（而不是塞进 ``scanner.py``）：``scanner`` 依赖 ``mounts``，而 ``mounts``
需要上报远程请求；进度状态若放在 scanner 里，mounts 就得反过来导入 scanner —— 直接形成
循环依赖。这个模块**不导入任何项目内模块**（只用标准库），三方都只依赖它。

进程内、不持久化：EM / EA 都是单进程部署，进程内的数据最实时；跨进程 / 刷新页面看的是
落库快照（``Library.scan_progress``，由 ``scan_queue`` 定期刷盘，见 scan_queue.flush_once）。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

# 阶段名 → 给人看的中文（管理端直接用，前端不再维护一份）
PHASE_LABELS = {
    "enumerating": "枚举文件",
    "processing": "处理条目",
    "cleanup": "清理条目",
}

# 当前路径截断长度：库里的 JSON 不该因为一条超长路径无限长
CURRENT_MAX = 200

# 枚举计数每多少个文件上报一次：看得见，又不让锁成为开销（1000 个文件 = 40 次上报）
ENUMERATED_EVERY = 25

_LOCK = threading.Lock()

# 库 id → 进度字典（只有正在扫的库才在表里）
_PROGRESS: dict[int, dict] = {}

# 扫描会话深度：>0 表示本进程有一轮扫描正在进行（mounts 据此不吃 TTL 过期，见 cached_listing）
_SESSION_DEPTH = 0

# 远程 IO 计数：真实请求 / 缓存复用 / 在飞数量 / 峰值 / 最近一次时间
_REMOTE = {"lists": 0, "reused": 0, "inflight": 0, "peak_inflight": 0, "last_at": None}

# 「当前线程正在扫哪个库」：进度上报点在包装层（见 scan_instrument），它需要知道归属。
# 一个扫描任务全程只在它自己的工作线程里跑，所以线程局部变量足够且不会串库。
_CTX = threading.local()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def bind(library_id: int) -> None:
    """把「当前线程正在扫的库」绑上（开扫前调用）"""
    _CTX.library_id = int(library_id)


def unbind() -> None:
    _CTX.library_id = None


def current_library_id() -> Optional[int]:
    """当前线程正在扫的库（没绑定则 None：直接调 scanner 的单测就是这个情况）"""
    value = getattr(_CTX, "library_id", None)
    return int(value) if value is not None else None


def begin_scan(library_id: int, name: str = "", phase: str = "enumerating") -> dict:
    """登记一个库开始扫描（返回刚建好的进度字典）

    同时把「扫描会话」计数加一：扫描期间的远程目录列举不再受 TTL 影响（见 mounts.cached_listing），
    否则一轮扫描里同一个目录会被反复 PROPFIND——日志里那条「每 5 秒一次」就是这么来的。
    """
    global _SESSION_DEPTH
    entry = {
        "library_id": int(library_id),
        "name": name or "",
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "enumerated": 0,
        "processed": 0,
        "current": "",
        "started_at": _now_iso(),
        "phase_changed_at": _now_iso(),
        "updated_at": _now_iso(),
        "started_monotonic": time.monotonic(),
        "remote_lists_base": _REMOTE["lists"],
        "remote_reused_base": _REMOTE["reused"],
    }
    with _LOCK:
        _PROGRESS[int(library_id)] = entry
        _SESSION_DEPTH += 1
    bind(library_id)   # 让包装层知道这一轮属于谁（同一线程内全程有效）
    return dict(entry)


def end_scan(library_id: int) -> None:
    """扫描结束（成功 / 失败 / 被取消都走这里）：清掉进度并把会话计数减一"""
    global _SESSION_DEPTH
    with _LOCK:
        _PROGRESS.pop(int(library_id), None)
        _SESSION_DEPTH = max(0, _SESSION_DEPTH - 1)
    unbind()


def set_phase(library_id: int, phase: str) -> None:
    """切换阶段（枚举 → 处理 → 清理）"""
    with _LOCK:
        entry = _PROGRESS.get(int(library_id))
        if entry is None or entry["phase"] == phase:
            return
        entry["phase"] = phase
        entry["phase_label"] = PHASE_LABELS.get(phase, phase)
        entry["phase_changed_at"] = _now_iso()
        entry["updated_at"] = _now_iso()


def set_enumerated(library_id: int, total: int) -> None:
    """已发现（枚举到）的文件数（调用方按节流频率上报，不是每个文件一次）"""
    with _LOCK:
        entry = _PROGRESS.get(int(library_id))
        if entry is None:
            return
        entry["enumerated"] = int(total)
        entry["updated_at"] = _now_iso()


def note_processed(library_id: int, current: Optional[str] = None) -> None:
    """处理完一个文件（写库循环里调用）；可顺带更新「当前文件 / 当前目录」"""
    with _LOCK:
        entry = _PROGRESS.get(int(library_id))
        if entry is None:
            return
        entry["processed"] = int(entry["processed"]) + 1
        entry["updated_at"] = _now_iso()
        if current:
            entry["current"] = str(current)[:CURRENT_MAX]


def progress_of(library_id: int) -> Optional[dict]:
    """某个库的实时进度（不在扫就返回 None）；对外字段与落库快照一致"""
    with _LOCK:
        entry = _PROGRESS.get(int(library_id))
        if entry is None:
            return None
        return _public(entry)


def _public(entry: dict) -> dict:
    elapsed_ms = int((time.monotonic() - float(entry.get("started_monotonic") or time.monotonic())) * 1000)
    return {
        "library_id": entry.get("library_id"),
        "name": entry.get("name") or "",
        "phase": entry.get("phase"),
        "phase_label": entry.get("phase_label"),
        "enumerated": int(entry.get("enumerated") or 0),
        "processed": int(entry.get("processed") or 0),
        "current": entry.get("current") or "",
        "elapsed_ms": max(0, elapsed_ms),
        "started_at": entry.get("started_at"),
        "phase_changed_at": entry.get("phase_changed_at"),
        "updated_at": entry.get("updated_at"),
        # 本轮扫描期间的远程列举（真实请求 / 复用），用于回答「慢在网络吗」
        "remote_lists": max(0, int(_REMOTE["lists"]) - int(entry.get("remote_lists_base") or 0)),
        "remote_reused": max(0, int(_REMOTE["reused"]) - int(entry.get("remote_reused_base") or 0)),
        "remote_last_at": _REMOTE["last_at"],
    }


def snapshot() -> list[dict]:
    """所有正在扫的库的实时进度（管理端的「扫描队列」面板用）"""
    with _LOCK:
        return [_public(entry) for entry in _PROGRESS.values()]


def running_library_ids() -> list[int]:
    with _LOCK:
        return list(_PROGRESS.keys())


def in_scan_session() -> bool:
    """本进程是否有扫描正在进行（mounts 用它决定目录列举能不能吃 TTL 过期）"""
    with _LOCK:
        return _SESSION_DEPTH > 0


def session_depth() -> int:
    with _LOCK:
        return _SESSION_DEPTH


# ==================== 远程 IO 计数 ====================

def note_remote_listing(*, reused: bool = False) -> None:
    """一次远程目录列举：真实请求（reused=False）或内存复用（reused=True）"""
    with _LOCK:
        if reused:
            _REMOTE["reused"] += 1
            return
        _REMOTE["lists"] += 1
        _REMOTE["last_at"] = _now_iso()


def note_remote_inflight(delta: int) -> None:
    """在飞的远程请求数 +1 / -1（并记录峰值：峰值长期顶在上限说明该调大或该查网络）"""
    with _LOCK:
        value = max(0, int(_REMOTE["inflight"]) + int(delta))
        _REMOTE["inflight"] = value
        _REMOTE["peak_inflight"] = max(int(_REMOTE["peak_inflight"]), value)


def remote_stats() -> dict:
    with _LOCK:
        return {
            "lists": int(_REMOTE["lists"]),
            "reused": int(_REMOTE["reused"]),
            "inflight": int(_REMOTE["inflight"]),
            "peak_inflight": int(_REMOTE["peak_inflight"]),
            "last_at": _REMOTE["last_at"],
        }


def reset() -> None:
    """清空全部进度与计数（测试用；生产代码不调用）"""
    global _SESSION_DEPTH
    with _LOCK:
        _PROGRESS.clear()
        _SESSION_DEPTH = 0
        _REMOTE.update({"lists": 0, "reused": 0, "inflight": 0, "peak_inflight": 0, "last_at": None})
    unbind()
