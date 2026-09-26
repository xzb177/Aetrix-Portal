"""扫描队列（v2.27.0）：按远程挂载串行化 + 全局并发上限 + 队列状态与进度

问题是什么（一次线上日志审计的结论）：四个媒体库在同一分钟里依次点「扫描」，四个任务
**合法地**同时跑起来——单个媒体库的互斥只防「同一个库重复扫描」，它不防「不同的库同时打
同一个远程挂载」。于是同一个 WebDAV / rclone 端点被四个任务反复 PROPFIND（日志里那条
每 5 秒一次的同一路径，就是扫描在重新列目录），远端延迟被放大、SQLite 被四个写入方争抢，
CPU 打满而进度一动不动。

这里做四件事：

1. **按远程挂载串行化**：一个库扫描期间锁住它要读的远程挂载（``parse_mount_ids`` 出来的 id），
   其它引用同一挂载的库**排队**而不是同时打远端；只读本机目录的库不受影响，照常并行。
2. **全局并发上限**（``EMBY_SCAN_MAX_PARALLEL``，默认 2）：扫描是资源大户（ffprobe + 写库 +
   远端 IO），不设上限时「多点几下」就能把机器打满。
3. **排队而不是报错**：重复点同一个库的扫描不报 409，直接告诉你「已经在队列里/正在扫」；
   排队的任务可以取消（正在跑的不能，中途停会留下半个库的状态）。
4. **状态可查**：排队中（第几位、在等哪个挂载）+ 运行中（阶段、已发现、已处理、当前目录、
   本轮远程列举次数）都在管理端可见，见 ``snapshot`` 与 ``live_payload``。

线程模型：一个调度线程（没有任务时退出，下次入队再起）+ 每个被派发的任务一个工作线程。
**入队时就在调用方线程里派发一次**（``_pump_locked``）：排队面板点完扫描拿到的响应就是
真实状态，而不是等调度线程醒来的猜测；调度线程负责「有任务释放资源后把等在后面的接上」。
任务在自己的线程里用**独立 Session**跑 ``scanner.scan_library_sync``（与升级前的后台线程一样），
所以请求级 Session 的生命周期问题不受影响。进程内状态，EM / EA 各自单进程部署。
"""
from __future__ import annotations

# 后端拆分（v2.41.0）：AETRIX_ROLE 环境变量
# - "api"：API 进程，enqueue() 走 Redis 桥接推给 worker
# - "worker"：Worker 进程，走原有进程内队列
# - 未设置：单体模式，走原有进程内队列（向后兼容）
AETRIX_ROLE = os.getenv("AETRIX_ROLE", "").strip().lower()

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from backend.database import SessionLocal
from backend.emby_server import models as em
from backend.emby_server import scan_instrument
from backend.emby_server import scan_progress as progress

logger = logging.getLogger(__name__)

# 扫描队列开关（0 = 回到升级前「谁点谁起线程」，但仍会上报进度）
SCAN_QUEUE_ENABLED = (os.getenv("EMBY_SCAN_QUEUE", "1") or "1").strip().lower() not in ("0", "false", "no")
# 同时最多跑几个扫描（默认 2：一个在扫 + 一个可以立即接上，再多就是互相抢资源）
SCAN_MAX_PARALLEL = max(1, min(8, int(os.getenv("EMBY_SCAN_MAX_PARALLEL", "2") or 2)))
# 同一个远程挂载同时只允许一个扫描任务（0 = 关闭这条串行化，不建议）
SCAN_MOUNT_SERIAL = (os.getenv("EMBY_SCAN_MOUNT_SERIAL", "1") or "1").strip().lower() not in ("0", "false", "no")
# 队列与最近完成的任务保留多少条（给管理端看「刚才那几轮排队等了多久」）
SCAN_QUEUE_HISTORY = max(0, min(50, int(os.getenv("EMBY_SCAN_QUEUE_HISTORY", "12") or 12)))
# 进度刷盘间隔（秒）：管理端刷新页面时即使不在同一个进程也能看到进度
SCAN_PROGRESS_FLUSH_SECONDS = max(0.5, float(os.getenv("EMBY_SCAN_PROGRESS_FLUSH", "2") or 2))

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELED = "canceled"

# 进度落库时的键（与 scan_progress.progress_of 的输出一致）
PROGRESS_COLUMN_KEYS = (
    "phase", "phase_label", "enumerated", "processed", "current", "elapsed_ms",
    "started_at", "phase_changed_at", "updated_at",
    "remote_lists", "remote_reused", "remote_last_at",
)


def enabled() -> bool:
    return bool(SCAN_QUEUE_ENABLED)


@dataclass
class ScanTask:
    """一个排队中 / 正在跑 / 刚跑完的扫描任务"""

    library_id: int
    name: str
    trigger: str
    mount_ids: tuple[int, ...] = ()
    local_paths: tuple[int, ...] = ()     # 只用于展示（本机来源条数）
    snapshot: object = None               # scanner.LibrarySnapshot
    state: str = STATE_QUEUED
    requested_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    queued_ms: int = 0
    duration_ms: Optional[int] = None
    waiting_for: tuple[int, ...] = ()     # 正在等哪些挂载（挂载 id）
    result: Optional[str] = None          # 终态：success / partial / failed / canceled
    error: Optional[str] = None
    request_count: int = 1                # 同一个库被连续点了几次（合并成一条）
    # 这一轮期间发生的远程目录列举（真请求 / 内存复用）：回答「慢在远端吗」
    remote_lists: int = 0
    remote_reused: int = 0
    owner_thread: Optional[threading.Thread] = None

    def as_dict(self, *, position: Optional[int] = None) -> dict:
        data = {
            "library_id": self.library_id,
            "name": self.name,
            "trigger": self.trigger,
            "state": self.state,
            "mount_ids": list(self.mount_ids),
            "local_sources": len(self.local_paths),
            "requested_at": self.requested_at.isoformat(timespec="seconds"),
            "started_at": self.started_at.isoformat(timespec="seconds") if self.started_at else None,
            "finished_at": self.finished_at.isoformat(timespec="seconds") if self.finished_at else None,
            "queued_ms": int(self.queued_ms or 0),
            "duration_ms": self.duration_ms,
            "waiting_for": list(self.waiting_for or ()),
            "result": self.result,
            "error": self.error,
            "request_count": int(self.request_count or 1),
            "remote_lists": int(self.remote_lists or 0),
            "remote_reused": int(self.remote_reused or 0),
        }
        if position is not None:
            data["position"] = position
        live = progress.progress_of(self.library_id)
        if live is not None:
            data["progress"] = live
        return data


_LOCK = threading.RLock()
_COND = threading.Condition(_LOCK)
# 进度刷盘与「结束清空」互斥（v2.27.0）：只加在库队列上不够——刷盘线程可能**先**取到
# 一份旧快照（还在扫）、再被 SQLite 写锁挡住，扫描结束时它才提交，于是
# 「已跑完」的那一行又被写回一份旧进度，面板就永远显示「扫描中 已处理 N」。
# 两者共用一把锁，最终落地的一定是清空。
_PERSIST_LOCK = threading.Lock()

_QUEUE: list[ScanTask] = []              # 等待派发（FIFO）
_RUNNING: dict[int, ScanTask] = {}       # 库 id → 正在跑的任务
_HISTORY: list[ScanTask] = []
_MOUNT_OWNER: dict[int, int] = {}        # 挂载 id → 正持有它的库 id
_SCHEDULER: Optional[threading.Thread] = None
_FLUSHER: Optional[threading.Thread] = None


# ==================== 入队 / 取消 ====================

def enqueue(library, *, trigger: str = "manual") -> dict:
    """把一个媒体库的扫描放进队列（角色分发版）

    - API 进程（AETRIX_ROLE=api 且 Redis 可用）：推入 Redis 队列，由 worker 消费执行
    - 其他：走进程内队列（enqueue_local，原有逻辑）
    """
    if AETRIX_ROLE == "api":
        try:
            from backend.emby_server import scan_queue_redis as _rq
            if _rq.is_redis_mode():
                return _rq.push_scan_request(int(library.id), trigger=trigger)
        except Exception as e:
            logger.warning(f"Redis 入队失败，回退进程内队列：{e}")
    return enqueue_local(library, trigger=trigger)


def start_redis_consumer() -> bool:
    """Worker 进程：启动 Redis 扫描队列消费（backend/worker.py 调用）"""
    from backend.emby_server import scan_queue_redis as _rq
    return _rq.start_redis_consumer()


def stop_redis_consumer(timeout: float = 5.0) -> None:
    """停止 Redis 扫描队列消费"""
    from backend.emby_server import scan_queue_redis as _rq
    _rq.stop_redis_consumer(timeout=timeout)


def enqueue_local(library, *, trigger: str = "manual") -> dict:
    """把一个媒体库的扫描放进队列（已在队列里 / 正在跑就返回那一条，不报错）

    快照在这一刻拍下（``LibrarySnapshot.of``）：排队期间管理员改了路径 / 策略，
    这一轮仍按点击那一刻的配置跑——与「点了就开扫」的语义一致，不会出现
    「排了十分钟，跑的是十分钟后改过的配置」。

    返回 ``{"created": bool, "task": {...}}``：``created=False`` 表示这次点击被合并到已有任务。
    """
    from backend.emby_server.scanner import LibrarySnapshot  # 延迟导入：避免与 scanner 互相导入

    scan_instrument.install()   # 进度上报点（幂等；见 scan_instrument 的模块说明）
    snapshot = LibrarySnapshot.of(library)
    with _LOCK:
        existing = _task_of_locked(library.id)
        if existing is not None:
            existing.request_count += 1
            return {"created": False, "task": existing.as_dict(position=_position_locked(existing))}
        task = ScanTask(
            library_id=int(library.id),
            name=str(snapshot.name or ""),
            trigger=str(trigger or "manual"),
            mount_ids=tuple(int(m) for m in (snapshot.mount_ids or ())),
            local_paths=tuple(snapshot.paths or ()),
            snapshot=snapshot,
        )
        _QUEUE.append(task)
        # 入队时就把「在等哪个挂载」算出来：接口要立刻把理由写进提示（
        # 「已加入队列，正在等挂载：MP媒体库」），不能等调度线程下一次迭代才填上
        task.waiting_for = _conflicts_locked(task)
        # 入队/开始/结束都记一行 INFO：出问题时（“点了扫描没反应”）运维能直接从日志看出
        # 是入队了、在等哪个挂载，还是已经跑起来了——而不是只有面板上一个“扫描中”
        logger.info("扫描入队：库「%s」(id=%s) 触发=%s；等挂载 %s；队列长度 %s",
                    task.name or "?", task.library_id, task.trigger,
                    _mounts_text(task.waiting_for), len(_QUEUE))
        _ensure_scheduler_locked()
        # 就地派发一次（不等调度线程醒来）：点完扫描的响应就是**真实状态**
        # （已开扫 / 排队第几位 / 在等谁），而不是「已入队」的猜测；
        # 否则「点了扫描界面没反应」会变成一件要靠线程调度时机决定的事。
        _pump_locked()
        _COND.notify_all()
        return {"created": True, "task": task.as_dict(position=_position_locked(task))}


def cancel(library_id: int) -> str:
    """取消一个**还在排队**的任务

    返回 ``canceled`` / ``running`` / ``missing``：正在跑的不能取消——中途停下会留下
    「扫了一半的库」（条目已入库、清理没做），比让它跑完更糟；要停就等它跑完或重启进程。
    """
    # 后端拆分：API 进程走 Redis 取消
    if AETRIX_ROLE == "api":
        try:
            from backend.emby_server import scan_queue_redis as _rq
            if _rq.is_redis_mode():
                return _rq.cancel_scan_request(int(library_id))
        except Exception as e:
            logger.warning(f"Redis 取消失败，回退进程内取消：{e}")
    with _LOCK:
        for index, task in enumerate(_QUEUE):
            if task.library_id == int(library_id):
                _QUEUE.pop(index)
                task.state = STATE_CANCELED
                task.result = STATE_CANCELED
                task.finished_at = datetime.now()
                _push_history_locked(task)
                logger.info("取消排队：库「%s」(id=%s)", task.name or "?", task.library_id)
                _COND.notify_all()
                return "canceled"
        if int(library_id) in _RUNNING:
            return "running"
        return "missing"


def state_of(library_id: int) -> Optional[dict]:
    """某个库当前在队列里的状态（空闲返回 None）"""
    # 后端拆分：API 进程查 Redis 里的排队位置
    if AETRIX_ROLE == "api":
        try:
            from backend.emby_server import scan_queue_redis as _rq
            if _rq.is_redis_mode():
                pos = _rq._position_of(int(library_id))
                if pos is not None:
                    return {
                        "library_id": int(library_id),
                        "state": "queued",
                        "position": pos,
                        "via": "redis",
                    }
        except Exception:
            pass
    with _LOCK:
        task = _task_of_locked(library_id)
        if task is None:
            return None
        return task.as_dict(position=_position_locked(task))


def is_busy(library_id: int) -> bool:
    # 后端拆分：API 进程查 Redis 去重集合
    if AETRIX_ROLE == "api":
        try:
            from backend.emby_server import scan_queue_redis as _rq
            r = _rq._redis()
            if r is not None and r.sismember(_rq.REDIS_SCAN_DEDUP_KEY, int(library_id)):
                return True
        except Exception:
            pass
    with _LOCK:
        return _task_of_locked(library_id) is not None


def snapshot() -> dict:
    """整个队列的快照（管理端「扫描队列」面板）"""
    # 后端拆分：API 进程的排队列表从 Redis 读（进程内队列是空的）
    redis_waiting = None
    if AETRIX_ROLE == "api":
        try:
            from backend.emby_server import scan_queue_redis as _rq
            import json as _json
            r = _rq._redis()
            if r is not None:
                redis_waiting = []
                for idx, raw in enumerate(r.lrange(_rq.REDIS_SCAN_QUEUE_KEY, 0, -1)):
                    try:
                        data = _json.loads(raw)
                    except Exception:
                        continue
                    redis_waiting.append({
                        "library_id": int(data.get("library_id", 0)),
                        "trigger": data.get("trigger", "manual"),
                        "state": "queued",
                        "position": idx + 1,
                        "via": "redis",
                    })
        except Exception:
            redis_waiting = None
    with _LOCK:
        waiting = [
            task.as_dict(position=index + 1)
            for index, task in enumerate(_QUEUE)
        ]
        if redis_waiting is not None:
            waiting = redis_waiting
        running = [task.as_dict() for task in _RUNNING.values()]
        history = [task.as_dict() for task in reversed(_HISTORY)][:SCAN_QUEUE_HISTORY]
        mounts = {str(mount_id): library_id for mount_id, library_id in _MOUNT_OWNER.items()}
        return {
            "enabled": bool(SCAN_QUEUE_ENABLED),
            "max_parallel": int(SCAN_MAX_PARALLEL),
            "mount_serial": bool(SCAN_MOUNT_SERIAL),
            "running": running,
            "waiting": waiting,
            "history": history,
            "mount_owners": mounts,
            "remote": progress.remote_stats(),
        }


def live_payload(library) -> Optional[dict]:
    """某个媒体库的实时扫描状态（排队中 / 正在扫 / 由别的进程在扫）；空闲返回 None

    三种来源合成一个口径：

    - 本进程队列里的任务（含实时进度与「在等哪个挂载」）；
    - 库里落盘的进度快照（``Library.scan_progress``）——刷新页面时接上刚才那几秒；
    - 库里状态是 ``running`` 但本进程没有任务：说明是**归属节点**在扫（多机部署），
      这时只说明「由别的节点执行」，不谎报一个自己看不到的进度。
    """
    task = None
    with _LOCK:
        task = _task_of_locked(library.id)
        task_payload = task.as_dict(position=_position_locked(task)) if task is not None else None

    persisted = _decode_progress(getattr(library, "scan_progress", None))
    if task_payload is not None:
        payload = dict(task_payload)
        payload["source"] = "panel"
        if "progress" not in payload and persisted:
            payload["progress"] = persisted
        return payload

    if (getattr(library, "scan_status", None) or "") == "running":
        return {
            "library_id": library.id,
            "name": getattr(library, "name", "") or "",
            "state": STATE_RUNNING,
            "source": "other",
            "message": "正在由归属节点扫描（进度只在执行那台机器上）",
            "progress": persisted,
        }
    return None


# ==================== 状态落库 ====================

def persist_progress(library_id: int, payload: Optional[dict]) -> None:
    """把进度快照写进媒体库行（None = 清空）

    单独开一个短事务：扫描线程正把 ``db.commit`` 换成 ``flush`` 做批量提交，
    进度不能共用它的会话（否则会提前把半批数据提交出去，或把批次边界打乱）。
    """
    try:
        text = json.dumps({k: payload.get(k) for k in PROGRESS_COLUMN_KEYS if k in payload},
                          ensure_ascii=False) if payload else None
        with SessionLocal() as db:
            row = db.query(em.Library).filter(em.Library.id == int(library_id)).first()
            if row is None:
                return
            row.scan_progress = text
            db.commit()
    except Exception as exc:  # noqa: BLE001 — 进度写不进去不影响扫描
        # 清空失败要比写不进去严重：面板会把一台已经跑完的机器一直显示成「扫描中 已处理 N」，
        # 而且换一轮扫描才会被覆盖。所以清空用 warning，写进度用 debug（失败也无害）。
        if payload is None:
            logger.warning("清空扫描进度失败（面板可能显示一份过期的进度）: %s", exc)
        else:
            logger.debug("写入扫描进度失败（不影响扫描）: %s", exc)


def flush_once() -> int:
    """把当前所有正在跑的进度刷一次盘（返回写入条数）

    正常由后台 flusher 每 ``SCAN_PROGRESS_FLUSH_SECONDS`` 秒调用一次；测试里直接调它，
    不用等定时器。取快照与写入必须在同一把锁里（见 ``_PERSIST_LOCK``），
    否则一份「取的时候还在扫、写的时候已经结束」的旧快照会盖掉清空。
    """
    written = 0
    with _PERSIST_LOCK:
        for payload in progress.snapshot():
            persist_progress(payload.get("library_id"), payload)
            written += 1
    return written


def clear_progress(library_id: int) -> None:
    """一轮扫描结束后清掉进度快照（与刷盘互斥；见 ``_PERSIST_LOCK``）

    内存里已经没有这个库的进度时才算「真的结束了」；如果它已经在被新一轮扫描占用
    （``progress.progress_of`` 拿得到），就不动——那是新一轮的进度，不能清掉。
    """
    with _PERSIST_LOCK:
        if progress.progress_of(library_id) is not None:
            return
        persist_progress(library_id, None)


def _decode_progress(raw) -> Optional[dict]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, dict) else None


# ==================== 调度 ====================

def _task_of_locked(library_id: int) -> Optional[ScanTask]:
    running = _RUNNING.get(int(library_id))
    if running is not None:
        return running
    for task in _QUEUE:
        if task.library_id == int(library_id):
            return task
    return None


def _position_locked(task: ScanTask) -> Optional[int]:
    if task.state != STATE_QUEUED:
        return None
    for index, item in enumerate(_QUEUE):
        if item is task:
            return index + 1
    return None


def _ensure_scheduler_locked() -> None:
    global _SCHEDULER
    if _SCHEDULER is not None and _SCHEDULER.is_alive():
        return
    _SCHEDULER = threading.Thread(target=_scheduler_loop, name="scan-scheduler", daemon=True)
    _SCHEDULER.start()
    _ensure_flusher_locked()


def _ensure_flusher_locked() -> None:
    global _FLUSHER
    if _FLUSHER is not None and _FLUSHER.is_alive():
        return
    _FLUSHER = threading.Thread(target=_flusher_loop, name="scan-progress-flusher", daemon=True)
    _FLUSHER.start()


def _limits_locked() -> tuple[int, bool]:
    """当前生效的并发上限与挂载串行化开关（队列关掉时都不限制 = 升级前行为）"""
    if not SCAN_QUEUE_ENABLED:
        return 1_000_000, False
    return SCAN_MAX_PARALLEL, bool(SCAN_MOUNT_SERIAL)


def _conflicts_locked(task: ScanTask) -> tuple[int, ...]:
    """这个任务在等哪些挂载（同一挂载被别的库占着；自己的任务不可能重复占）"""
    if not SCAN_MOUNT_SERIAL:
        return ()
    busy = {
        mount_id for mount_id, owner in _MOUNT_OWNER.items()
        if owner != task.library_id
    }
    return tuple(sorted(m for m in (task.mount_ids or ()) if m in busy))


def _pick_locked() -> Optional[ScanTask]:
    """挑下一个可以跑的任务（跳过被挂载挡住的，别让队头阻塞别的挂载）"""
    limit, mount_serial = _limits_locked()
    for task in _QUEUE:
        task.waiting_for = _conflicts_locked(task) if mount_serial else ()
        if task.waiting_for:
            continue
        if len(_RUNNING) >= limit:
            return None
        return task
    return None


def _pump_locked() -> int:
    """立刻派发所有「现在就能跑」的任务（调用方必须已持有 _COND 的锁），返回派发数

    并发满了、或队头的任务在等挂载时停下（不等它——让后面不冲突的任务先跑）。
    """
    dispatched = 0
    while True:
        task = _pick_locked()
        if task is None:
            return dispatched
        _dispatch_locked(task)
        dispatched += 1


def _dispatch_locked(task: ScanTask) -> None:
    _QUEUE.remove(task)
    task.state = STATE_RUNNING
    task.started_at = datetime.now()
    task.queued_ms = int((task.started_at - task.requested_at).total_seconds() * 1000)
    task.waiting_for = ()
    _RUNNING[task.library_id] = task
    if SCAN_MOUNT_SERIAL:
        for mount_id in task.mount_ids or ():
            _MOUNT_OWNER[int(mount_id)] = task.library_id
    logger.info("扫描开始：库「%s」(id=%s) 排队 %.1fs；占用挂载 %s；同时 %s 个在跑",
                task.name or "?", task.library_id, (task.queued_ms or 0) / 1000,
                _mounts_text(task.mount_ids), len(_RUNNING))
    task.owner_thread = threading.Thread(
        target=_run_task, args=(task,), name=f"scan-lib{task.library_id}", daemon=True,
    )
    task.owner_thread.start()


def _scheduler_loop() -> None:
    global _SCHEDULER
    while True:
        with _COND:
            if _pump_locked() == 0:
                if not _QUEUE:
                    _SCHEDULER = None
                    _COND.notify_all()
                    return
                # 队伍里有活但都被挂载挡住（或并发已满）：等释放 / 等新任务
                _COND.wait(timeout=0.25)


def _release_locked(task: ScanTask) -> None:
    _RUNNING.pop(task.library_id, None)
    for mount_id in task.mount_ids or ():
        if _MOUNT_OWNER.get(int(mount_id)) == task.library_id:
            _MOUNT_OWNER.pop(int(mount_id), None)
    _push_history_locked(task)
    _COND.notify_all()


def _mounts_text(mount_ids) -> str:
    """日志里的挂载：没有就写「无」，有就写成 [1, 3]（名字由调用方 / 面板负责）"""
    ids = [int(m) for m in (mount_ids or ())]
    return "[" + ", ".join(str(mid) for mid in ids) + "]" if ids else "无"


def _push_history_locked(task: ScanTask) -> None:
    if SCAN_QUEUE_HISTORY <= 0:
        return
    _HISTORY.append(task)
    while len(_HISTORY) > SCAN_QUEUE_HISTORY:
        _HISTORY.pop(0)


def _run_task(task: ScanTask) -> None:
    """在工作线程里真正跑一轮扫描（独立 Session，与升级前的后台线程一致）"""
    from backend.emby_server.scanner import scan_library_sync  # 延迟导入，见模块 docstring

    db = SessionLocal()
    # 开扫前绑定「当前线程在扫哪个库」并建进度条目：绑定之后 scanner 的包装层
    # （枚举 / 处理 / 阶段）才知道该把数字记到谁名下；结束无论成败都解绑
    progress.begin_scan(task.library_id, task.name)
    remote_before = progress.remote_stats()
    try:
        library = db.query(em.Library).filter(em.Library.id == task.library_id).first()
        if library is None:
            task.state = STATE_FAILED
            task.result = STATE_FAILED
            task.error = "媒体库已被删除"
            return
        scan_library_sync(db, library, task.snapshot, trigger=task.trigger)
        task.state = STATE_DONE
        task.result = (library.scan_status or "success")
    except Exception as exc:  # noqa: BLE001 — 后台线程的异常必须落到队列状态里
        logger.exception("媒体库 %s 扫描失败", task.library_id)
        task.state = STATE_FAILED
        task.result = STATE_FAILED
        task.error = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        task.finished_at = datetime.now()
        if task.started_at is not None:
            task.duration_ms = int((task.finished_at - task.started_at).total_seconds() * 1000)
        # 这一轮期间的远程列举次数（全局计数器的差值）：并发时两轮共用一个计数器，
        # 所以它是「这一轮跑的时间里发生了多少次」，不是「只因这一轮发生」——足够回答
        # 「慢在网络吗」，不需要为此把计数器拆到每个扫描线程（远程请求发生在 IO 线程池里）
        after = progress.remote_stats()
        task.remote_lists = max(0, int(after["lists"]) - int(remote_before["lists"]))
        task.remote_reused = max(0, int(after["reused"]) - int(remote_before["reused"]))
        progress.end_scan(task.library_id)
        try:
            db.close()   # 先关扫描会话：它可能还攥着 SQLite 的读事务，边上有写就会 "database is locked"
        except Exception:  # noqa: BLE001
            pass
        # 清进度快照要在「标成已结束」之前：反过来会留下一个「队列面板已经显示跑完、
        # 库里却还挂着上一轮进度」的瞬间（面板就会显示成「完成 + 正在处理 1234」）
        clear_progress(task.library_id)
        logger.info("扫描结束：库「%s」(id=%s) → %s；耗时 %.1fs；本轮远程列举 %s 次（复用 %s）",
                    task.name or "?", task.library_id, task.result or task.state,
                    (task.duration_ms or 0) / 1000, task.remote_lists, task.remote_reused)
        with _COND:
            _release_locked(task)


def _flusher_loop() -> None:
    """把正在跑的进度定期刷盘（刷新页面 / 另一个进程也能看到）"""
    while True:
        time.sleep(SCAN_PROGRESS_FLUSH_SECONDS)
        try:
            if progress.session_depth() > 0:
                flush_once()
        except Exception as exc:  # noqa: BLE001 — 刷盘失败不影响扫描
            logger.debug("扫描进度刷盘失败: %s", exc)


def reset_for_tests() -> None:
    """清空队列状态（测试用；生产代码不调用）"""
    global _SCHEDULER
    with _COND:
        _QUEUE.clear()
        _RUNNING.clear()
        _HISTORY.clear()
        _MOUNT_OWNER.clear()
        _SCHEDULER = None
        progress.reset()
