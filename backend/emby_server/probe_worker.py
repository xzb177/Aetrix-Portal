"""两阶段扫描 Phase 2：后台探测 worker（v2.39.0）

``SCAN_PROBE_MODE=background`` 时，扫描（Phase 1）只入库结构、不做 ffprobe，
需要探测的条目标 ``probe_status='pending'``。本模块的后台线程按优先级把它们
逐个探测完——这就是「不走 Emby 老路」的关键：**库的可见性**（Phase 1，几分钟）
与**媒体信息的完整性**（Phase 2，后台收敛）彻底解耦。

- 队列持久化在 ``emby_items``（probe_status / probe_priority /
  probe_attempts / probe_next_retry_at），进程/容器重启不丢；
- 单 worker 进程内用 ``'probing'`` 状态占位抢单（SQLite 无 SKIP LOCKED，
  单进程内状态机足够；多节点部署各扫各的库，天然不冲突）；
- 失败指数退避，超 ``PROBE_MAX_ATTEMPTS`` 次转 ``failed``；
- 令牌桶限流（``PROBE_RATE_PER_SEC``）保护云盘 API 不被打限流；
- 启动时把上次崩溃残留的 ``'probing'`` 打回 ``'pending'``（断点续传）；
- 探测是幂等的：重复探测同一条目只会覆盖出相同结果。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_

from backend.database import SessionLocal
from backend.emby_server import models as em
from backend.emby_server.mounts import resolve_play_target, MountError
from backend.emby_server.scanner import needs_probe, probe_metadata

logger = logging.getLogger(__name__)

# ---- 可调参数（环境变量） ----
PROBE_WORKERS = max(1, min(32, int(os.getenv("PROBE_WORKERS", "8") or 8)))
PROBE_BATCH = max(10, int(os.getenv("PROBE_BATCH", "200") or 200))
PROBE_RATE_PER_SEC = max(1, int(os.getenv("PROBE_RATE_PER_SEC", "4") or 4))
PROBE_MAX_ATTEMPTS = max(1, int(os.getenv("PROBE_MAX_ATTEMPTS", "5") or 5))
PROBE_IDLE_POLL_SEC = max(5, int(os.getenv("PROBE_IDLE_POLL_SEC", "30") or 30))

BOOST_PRIORITY = 1000   # 按需插队的优先级（新文件 100，普通 0）
NEW_FILE_PRIORITY = 100

_STREAM_COLS = {"stream_index", "stream_type", "codec", "language",
                "display_title", "title", "channels", "bit_rate"}


class _RateLimiter:
    """令牌桶：探测启动限速，保护云盘 API"""

    def __init__(self, rate_per_sec: int):
        self._rate = max(1, rate_per_sec)
        self._tokens = float(self._rate)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    float(self._rate),
                    self._tokens + (now - self._updated) * self._rate,
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(min(wait, 0.5))


_rate_limiter = _RateLimiter(PROBE_RATE_PER_SEC)

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_worker_lock = threading.Lock()


def enabled() -> bool:
    """后台探测是否启用（读 scanner 的统一开关）"""
    from backend.emby_server import scanner as _sc

    return bool(_sc.PROBE_BACKGROUND)


def reset_stale_probing(db=None) -> int:
    """把崩溃残留的 'probing' 打回 'pending'（断点续传），返回复位数"""
    own = db is None
    db = db or SessionLocal()
    try:
        n = (
            db.query(em.MediaItem)
            .filter(em.MediaItem.probe_status == "probing")
            .update({"probe_status": "pending"}, synchronize_session=False)
        )
        db.commit()
        if n:
            logger.info("探测 worker：%d 条残留 'probing' 已打回 pending", n)
        return n
    finally:
        if own:
            db.close()


def boost_probe(db, item) -> bool:
    """按需插队：优先级提到最高、清除退避，下一轮 worker 即取。

    已探测完（done）的不需要排队，返回 False；其余返回 True。
    """
    if (getattr(item, "probe_status", None) or "") == "done":
        return False
    item.probe_priority = BOOST_PRIORITY
    item.probe_next_retry_at = None
    if item.probe_status == "failed":
        # 之前放弃的也给一次机会（计数清零）
        item.probe_status = "pending"
        item.probe_attempts = 0
    db.commit()
    return True


def _backoff_seconds(attempts: int) -> int:
    # 60s, 120s, 240s, 480s, … 上限 1 小时
    return min(3600, 60 * (2 ** max(0, attempts - 1)))


def _apply_probe_result(db, item, info: dict) -> None:
    """把 ffprobe 结果落到条目 + 重建内封轨道（与 scanner 写循环同口径）"""
    item.size = info.get("size", 0) or item.size
    item.duration_ticks = info["duration_ticks"]
    item.bitrate = info["bitrate"]
    item.width = info["width"]
    item.height = info["height"]
    item.video_codec = info["video_codec"]
    item.audio_codec = info["audio_codec"]
    item.audio_languages = info["audio_languages"]
    item.subtitle_languages = info["subtitle_languages"]
    item.last_probed_at = datetime.now()
    item.probe_status = "done"
    item.probe_attempts = 0
    item.probe_next_retry_at = None
    # 内封轨道重建：只保留非外挂轨（外挂字幕由扫描维护，不在这里动）
    if item.id is None:
        db.flush()
    db.query(em.MediaStream).filter(
        em.MediaStream.item_id == item.id,
        em.MediaStream.is_external.isnot(True),
    ).delete(synchronize_session=False)
    for s in info.get("streams") or []:
        db.add(em.MediaStream(
            item_id=item.id,
            **{k: v for k, v in s.items() if k in _STREAM_COLS},
        ))


def _fail(db, item, reason: str) -> None:
    attempts = (item.probe_attempts or 0) + 1
    item.probe_attempts = attempts
    if attempts >= PROBE_MAX_ATTEMPTS:
        item.probe_status = "failed"
        item.probe_next_retry_at = None
        logger.warning("探测放弃 item=%s（%d 次）: %s", item.id, attempts, reason)
    else:
        item.probe_status = "pending"
        item.probe_next_retry_at = datetime.now() + timedelta(
            seconds=_backoff_seconds(attempts))
        logger.info("探测失败 item=%s，第 %d 次，%ds 后重试: %s",
                    item.id, attempts, _backoff_seconds(attempts), reason)


def _probe_one(item_id: int) -> str:
    """探测单个条目（工作线程内自带 Session）。返回 done / skipped / failed"""
    _rate_limiter.acquire()
    db = SessionLocal()
    try:
        item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
        if item is None or item.probe_status != "probing":
            return "skipped"
        try:
            # 双检：迁移来的旧行可能已有有效数据，直接标 done，不发网络请求
            if not needs_probe(item, item.file_path, item.size):
                item.probe_status = "done"
                item.probe_attempts = 0
                item.probe_next_retry_at = None
                db.commit()
                return "skipped"
            target = resolve_play_target(item.file_path, db)
            info = probe_metadata(target.value, target.headers, size=item.size or 0)
        except MountError as exc:
            db.rollback()
            item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
            if item is not None:
                _fail(db, item, f"解析播放目标失败: {exc}")
                db.commit()
            return "failed"
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
            if item is not None:
                _fail(db, item, f"探测异常: {exc}")
                db.commit()
            return "failed"
        if info and info.get("duration_ticks"):
            _apply_probe_result(db, item, info)
            db.commit()
            return "done"
        _fail(db, item, "ffprobe 未返回有效时长")
        db.commit()
        return "failed"
    finally:
        db.close()


def _claim_batch(db, limit: int) -> list[int]:
    """原子抢占一批待探测条目（状态机占位），返回 id 列表"""
    now = datetime.now()
    rows = (
        db.query(em.MediaItem.id)
        .filter(
            em.MediaItem.probe_status == "pending",
            em.MediaItem.item_type.in_(["movie", "episode"]),
            em.MediaItem.file_path.isnot(None),
            or_(em.MediaItem.probe_next_retry_at.is_(None),
                em.MediaItem.probe_next_retry_at <= now),
        )
        .order_by(em.MediaItem.probe_priority.desc(), em.MediaItem.id)
        .limit(limit)
        .all()
    )
    ids = [r[0] for r in rows]
    if not ids:
        return []
    db.query(em.MediaItem).filter(
        em.MediaItem.id.in_(ids),
        em.MediaItem.probe_status == "pending",
    ).update({"probe_status": "probing"}, synchronize_session=False)
    db.commit()
    return ids


def run_once(db=None, limit: int = PROBE_BATCH) -> dict:
    """跑一轮：抢一批 → 并发探测 → 等全部结束。返回计数（可测试）。"""
    own = db is None
    db = db or SessionLocal()
    try:
        ids = _claim_batch(db, limit)
    finally:
        if own:
            db.close()
    if not ids:
        return {"claimed": 0, "done": 0, "skipped": 0, "failed": 0}
    counts = {"claimed": len(ids), "done": 0, "skipped": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS,
                            thread_name_prefix="probe-worker") as pool:
        for result in pool.map(_probe_one, ids):
            counts[result] = counts.get(result, 0) + 1
    logger.info("探测 worker 一轮：claimed=%d done=%d skipped=%d failed=%d",
                counts["claimed"], counts["done"], counts["skipped"], counts["failed"])
    return counts


def _worker_loop() -> None:
    logger.info("探测 worker 启动（workers=%d, 限流=%d/s, 最大尝试=%d）",
                PROBE_WORKERS, PROBE_RATE_PER_SEC, PROBE_MAX_ATTEMPTS)
    while not _stop_event.is_set():
        try:
            counts = run_once()
            if counts["claimed"] == 0:
                _stop_event.wait(PROBE_IDLE_POLL_SEC)
        except Exception:  # noqa: BLE001
            logger.exception("探测 worker 一轮异常，10s 后继续")
            _stop_event.wait(10)
    logger.info("探测 worker 退出")


def start_probe_worker() -> bool:
    """启动后台探测线程（幂等）。未启用 background 模式时什么都不做，返回 False。"""
    global _worker_thread
    if not enabled():
        return False
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return True
        _stop_event.clear()
        reset_stale_probing()
        _worker_thread = threading.Thread(target=_worker_loop,
                                          name="probe-worker-main", daemon=True)
        _worker_thread.start()
        return True


def stop_probe_worker(timeout: float = 10.0) -> None:
    """停掉后台线程（测试用）"""
    global _worker_thread
    _stop_event.set()
    with _worker_lock:
        t, _worker_thread = _worker_thread, None
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
