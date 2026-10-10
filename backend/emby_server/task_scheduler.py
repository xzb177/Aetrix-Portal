"""
统一后台任务调度器（v2.54.0）

合并扫描（scan）与刮削（enrich）为统一任务流。

背景
----
``scan_queue`` 和 ``enrich_worker`` 是两个独立子系统，各自有线程池，
在同一个 worker 进程里抢 CPU / DB 连接 / 网络。用户点了 11 个库的扫描，
任务在队列里显示"等待调度"，而 enrich 线程还在吭哧吭哧做刮削——扫描排队
但没人干活。

设计
----
统一调度器**不碰**两个子系统的内部实现（扫描的挂载串行、刮削的原子抢单、
TMDB 令牌桶全部保留），只做一件事：**协调**。

- 优先级：扫描（用户触发、面板可见）> 刮削（后台、可等）
- 机制：enrich worker 每次抢单前问调度器"现在有没有扫描在等？"
  有 → 让路，睡一小会儿再问；无 → 正常抢单
- 全部可配置，一键关闭回退到旧行为（两个子系统独立抢资源）

另外提供 ``get_unified_status()``：一次调用看到扫描队列 + 刮削积压，
给管理后台"后台任务"统一视图用。

配置（环境变量）
----------------
- ``TASK_SCHEDULER_ENABLED``：总开关，默认 1（开）
- ``SCAN_PREEMPT_ENRICH``：扫描优先抢占刮削，默认 1（开）
- ``ENRICH_PREEMPT_WAIT_SEC``：被抢占时 enrich 每次等待秒数，默认 5
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

# ---- 可调参数（环境变量，全部可配置，不写死） ----
TASK_SCHEDULER_ENABLED = (
    os.getenv("TASK_SCHEDULER_ENABLED", "1") or "1"
).strip().lower() not in {"0", "false", "no", "off"}

SCAN_PREEMPT_ENRICH = (
    os.getenv("SCAN_PREEMPT_ENRICH", "1") or "1"
).strip().lower() not in {"0", "false", "no", "off"}

ENRICH_PREEMPT_WAIT_SEC = max(
    1, int(os.getenv("ENRICH_PREEMPT_WAIT_SEC", "5") or 5)
)

# 让路日志节流：避免每 5 秒刷一条日志
_last_yield_log_at: float = 0.0
_YIELD_LOG_THROTTLE_SEC = 60.0


def scan_waiting_count() -> int:
    """当前等待调度的扫描任务数（进程内队列 + Redis 队列）

    只读、不加锁、不抛异常：enrich worker 的热路径上调用，
    任何异常都按"0"处理（不让路，宁可多做不误事）。
    """
    try:
        from backend.emby_server import scan_queue as _sq

        # 进程内队列（worker 进程 / 单体模式）
        with _sq._LOCK:
            local_waiting = len(_sq._QUEUE)
        if local_waiting:
            return local_waiting

        # Redis 队列（API 进程入队、worker 消费的场景下，
        # worker 进程的 _QUEUE 是空的，任务还在 Redis 里）
        try:
            from backend.emby_server import scan_queue_redis as _rq

            r = _rq._redis()
            if r is not None:
                return int(r.llen(_rq.REDIS_SCAN_QUEUE_KEY) or 0)
        except Exception:
            pass
        return 0
    except Exception:
        return 0


def should_enrich_yield() -> bool:
    """enrich worker 本轮是否应该让路给扫描

    条件（全满足才让路）：
    1. 调度器总开关开着
    2. 扫描优先配置开着
    3. 当前确实有扫描任务在等待
    """
    if not TASK_SCHEDULER_ENABLED:
        return False
    if not SCAN_PREEMPT_ENRICH:
        return False
    return scan_waiting_count() > 0


def note_enrich_yielded(wait_sec: int) -> None:
    """记录一次让路（日志节流 60 秒一条）"""
    global _last_yield_log_at
    now = time.monotonic()
    if now - _last_yield_log_at < _YIELD_LOG_THROTTLE_SEC:
        return
    _last_yield_log_at = now
    logger.info(
        "统一调度：检测到 %d 个扫描任务等待，刮削让路 %ds（SCAN_PREEMPT_ENRICH=1）",
        scan_waiting_count(),
        wait_sec,
    )


def get_unified_status() -> dict:
    """统一后台任务状态（管理后台用）

    一次调用看到：
    - scan: 等待数 / 运行数
    - enrich: pending / enriching（DB 实时计数）
    - preempt_active: 当前是否在让路
    """
    # 扫描侧
    scan_waiting = 0
    scan_running = 0
    try:
        from backend.emby_server import scan_queue as _sq

        with _sq._LOCK:
            scan_waiting = len(_sq._QUEUE)
            scan_running = len(_sq._RUNNING)
        # Redis 里可能还有（跨进程场景）
        try:
            from backend.emby_server import scan_queue_redis as _rq

            r = _rq._redis()
            if r is not None:
                scan_waiting += int(r.llen(_rq.REDIS_SCAN_QUEUE_KEY) or 0)
        except Exception:
            pass
    except Exception:
        pass

    # 刮削侧（DB 实时计数，轻量 GROUP BY）
    enrich_pending = 0
    enrich_running = 0
    try:
        from backend.database import SessionLocal
        from backend.emby_server import models as em
        from sqlalchemy import func as _func

        db = SessionLocal()
        try:
            rows = (
                db.query(em.MediaItem.enrich_status, _func.count(em.MediaItem.id))
                .filter(em.MediaItem.enrich_status.in_(("pending", "enriching")))
                .group_by(em.MediaItem.enrich_status)
                .all()
            )
            by_status = {s or "unknown": c for s, c in rows}
            enrich_pending = int(by_status.get("pending", 0))
            enrich_running = int(by_status.get("enriching", 0))
        finally:
            db.close()
    except Exception:
        pass

    preempt_active = bool(
        TASK_SCHEDULER_ENABLED and SCAN_PREEMPT_ENRICH and scan_waiting > 0
    )

    return {
        "scheduler_enabled": bool(TASK_SCHEDULER_ENABLED),
        "scan_preempt_enrich": bool(SCAN_PREEMPT_ENRICH),
        "preempt_active": preempt_active,
        "scan": {
            "waiting": scan_waiting,
            "running": scan_running,
        },
        "enrich": {
            "pending": enrich_pending,
            "enriching": enrich_running,
        },
    }
