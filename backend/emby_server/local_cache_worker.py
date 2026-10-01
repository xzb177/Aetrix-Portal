"""VPS 本地缓存后台 worker（播放线路「本地缓存」的搬运工）

**它只做三件事**（一轮 = 一次 ``run_once``）：

1. 把近 N 天播放达到 M 次的热门条目排进缓存队列（``local_cache.enqueue_hot``）；
2. 取一条待下载的缓存，串行下载到本机（``local_cache.download_entry``）——
   **一次只下一个**，默认限速 20MB/s，检测到有人在播放时自动降到 2MB/s 让路
   （见 ``local_cache._download_to_file``）；
3. 超配额时按 LRU 淘汰最久未访问的副本（``local_cache.evict``）。

设计取舍（与 probe_worker 同一套思路：后台任务永远给前台让路）：

- 单线程串行：并发下载会把磁盘随机 IO 与带宽同时打满，播放侧立刻能感觉到；
- 每轮之间歇 ``LOCAL_CACHE_POLL_SEC`` 秒，不空转、不抢 IO；
- 默认关闭时（``local_cache_enabled=false``）整轮直接返回，什么都不做；
- 下载失败按重试额度回队列（``local_cache._fail``），超限转 failed，
  等下一轮热门轮询再给机会——坏源不会把 worker 卡死。

**挂载点**：与其它后台任务一样，非 API 角色才启动（``backend/main.py`` 的
``if not _is_api_role:`` 段与 ``backend/worker.py`` 各挂一次，见 tests/test_run_all_roles.py）。
缓存目录是**本机**资源，所以下载发生在跑后台任务的那台机器上。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from backend.database import SessionLocal
from backend.emby_server import local_cache

logger = logging.getLogger(__name__)

# 每轮之间的歇息（下完一条别立刻抢下一条：带宽与磁盘都留给播放）
POLL_SEC = max(5, int(os.getenv("LOCAL_CACHE_POLL_SEC", "30") or 30))
# 没活干时的轮询间隔（热门判定是分钟级的事，不必勤查）
IDLE_POLL_SEC = max(10, int(os.getenv("LOCAL_CACHE_IDLE_POLL_SEC", "120") or 120))
# 每轮最多把几条热门排进队列（避免一次涌入一堆下载）
HOT_BATCH = max(1, int(os.getenv("LOCAL_CACHE_HOT_BATCH", "5") or 5))

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_worker_lock = threading.Lock()


def run_once(db=None, *, hot_batch: int = HOT_BATCH) -> dict:
    """跑一轮：热门入队 → 取一条下载 → 淘汰。返回计数（可测试）。"""
    own = db is None
    db = db or SessionLocal()
    counts = {"enabled": False, "hot": 0, "queued": 0, "claimed": 0,
              "ready": 0, "failed": 0, "skipped": 0, "disabled": 0, "removed": 0}
    try:
        if not local_cache.enabled(db):
            return counts
        counts["enabled"] = True
        hot = local_cache.enqueue_hot(db, limit=hot_batch)
        counts["hot"] = hot["hot"]
        counts["queued"] = hot["queued"]
        counts["skipped"] += hot["skipped"]
        entry_id = local_cache.claim_next(db)
        if entry_id is not None:
            counts["claimed"] = 1
            result = local_cache.download_entry(db, entry_id)
            counts[result] = counts.get(result, 0) + 1
        counts["removed"] = local_cache.evict(db)["removed"]
        return counts
    finally:
        if own:
            db.close()


def _worker_loop() -> None:
    logger.info("本地缓存 worker 启动（串行下载 · 播放中自动让路，降到 %.1fMB/s）",
                local_cache.BUSY_RATE_MBPS)
    while not _stop_event.is_set():
        try:
            counts = run_once()
            if not counts["enabled"]:
                _stop_event.wait(IDLE_POLL_SEC)
                continue
            if counts["claimed"] == 0:
                _stop_event.wait(IDLE_POLL_SEC)
                continue
            logger.info("本地缓存一轮：热门 %d 条、入队 %d 条、下载 %s、淘汰 %d 条",
                        counts["hot"], counts["queued"],
                        "ready" if counts["ready"] else ("failed" if counts["failed"] else "skipped"),
                        counts["removed"])
            if POLL_SEC > 0:
                _stop_event.wait(POLL_SEC)
        except Exception:  # noqa: BLE001 — 一轮失败不能把 worker 打死
            logger.exception("本地缓存 worker 一轮异常，30s 后继续")
            _stop_event.wait(30)
    logger.info("本地缓存 worker 退出")


def start_local_cache_worker() -> bool:
    """启动后台线程（幂等）。默认关闭时线程照常起，但每轮直接返回（什么都不做）。"""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return True
        _stop_event.clear()
        _worker_thread = threading.Thread(target=_worker_loop,
                                          name="local-cache-worker", daemon=True)
        _worker_thread.start()
        return True


def stop_local_cache_worker(timeout: float = 10.0) -> None:
    """停掉后台线程（测试用）"""
    global _worker_thread
    _stop_event.set()
    with _worker_lock:
        thread, _worker_thread = _worker_thread, None
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
