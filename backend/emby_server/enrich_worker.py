"""分层扫描 L2/L3：后台补全 worker（v2.40.0）

SCAN_LAYERED=1 时，扫描（L1）只做文件发现 + 指纹 + 极简入库（秒级可见），
side 图片 / NFO / TMDB 刮削全部交给本 worker 在后台补全——这就是「分层」：

- 队列持久化在 ``emby_items.enrich_status``（pending=待补全 done=已补全），
  进程/容器重启不丢；启动时把崩溃残留的 ``'enriching'`` 打回 ``'pending'``（断点续补）；
- 新文件优先（date_added 倒序），TMDB 令牌桶限速；
- NFO 优先原则不变：NFO 管文字，TMDB 只补图和缺失字段；
- 补全是幂等的：重复补同一条目只会覆盖出相同结果。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Optional

from backend.database import SessionLocal
from backend.emby_server import models as em

logger = logging.getLogger(__name__)

# ---- 可调参数（环境变量） ----
ENRICH_WORKERS = max(1, min(16, int(os.getenv("ENRICH_WORKERS", "4") or 4)))
ENRICH_BATCH = max(10, int(os.getenv("ENRICH_BATCH", "100") or 100))
ENRICH_TMDB_PER_SEC = max(1, int(os.getenv("ENRICH_TMDB_PER_SEC", "2") or 2))
ENRICH_IDLE_POLL_SEC = max(5, int(os.getenv("ENRICH_IDLE_POLL_SEC", "30") or 30))
ENRICH_ENABLED = (os.getenv("ENRICH_WORKER", "1") or "1").strip().lower() not in {
    "0", "false", "no", "off",
}

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_worker_lock = threading.Lock()


class _RateLimiter:
    """令牌桶：TMDB 调用限速"""

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


_tmdb_limiter = _RateLimiter(ENRICH_TMDB_PER_SEC)


def _scanfile_from_item(item: Any) -> Optional[Any]:
    """从 DB 条目重建最小 ScanFile（只够 side_info / NFO 用）"""
    # 延迟导入：避免循环依赖（scanner 导入 enrich_worker 的情况）
    from backend.emby_server import scanner as _sc
    from backend.emby_server import mounts as mount_lib

    path = (item.file_path or "").strip()
    if not path:
        return None
    name = os.path.basename(path)
    size = item.size or 0
    container = item.container or ""
    if path.startswith("mount://"):
        rest = path[len("mount://"):]
        mount_id_str, _, rel = rest.partition("/")
        try:
            mount_id = int(mount_id_str)
        except ValueError:
            return None
        if not rel.startswith("/"):
            rel = "/" + rel
        # provider 按需构建（远程 side_info / NFO 需要它列目录、读文件）
        try:
            from backend.database import SessionLocal as _SL
            _db = _SL()
            try:
                mount = _db.query(em.StorageMount).filter(
                    em.StorageMount.id == mount_id).first()
                if mount is None:
                    return None
                provider = mount_lib.build_provider(mount, _db)
            finally:
                _db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("补全 worker 构建 provider 失败 mount=%s: %s", mount_id, exc)
            return None
        return _sc.ScanFile(
            stored_path=path, name=name, local_dir=None,
            dir_rel=os.path.dirname(rel) or "/",
            size=size, container=container,
            mount_id=mount_id, rel=rel, provider=provider,
        )
    # 本机文件
    dirpath = os.path.dirname(path)
    return _sc.ScanFile(
        stored_path=path, name=name, local_dir=dirpath,
        size=size, container=container,
    )


def _enrich_one(db, item: Any) -> bool:
    """补全一个条目：side 图片 → NFO → TMDB。返回 True=补完，False=暂跳过（下次重试）"""
    from backend.emby_server import scanner as _sc
    from backend.emby_server import nfo as nfo_lib
    from backend.emby_server.tmdb import tmdb_client

    item_type = item.item_type or ""
    kind = "series" if item_type == "series" else (
        "movie" if item_type == "movie" else "")
    scan_file = _scanfile_from_item(item)
    # 最小 ctx：side_info / NFO 需要目录缓存；snap 用占位（补全不依赖扫描快照）
    snap = _sc.LibrarySnapshot(
        library_id=item.library_id, name="", collection_type="",
        paths=(), scrape_policy="smart",
    )
    ctx = _sc._ScanContext(snap=snap, lib_id=item.library_id, stats={})

    # 1. side 图片 / 外挂字幕（本地图片优先，不覆盖已有）
    if scan_file is not None:
        try:
            side_poster, side_fanart, _external = _sc._side_info(ctx, scan_file)
            if side_poster and not item.poster_path:
                item.poster_path = side_poster
            if side_fanart and not item.backdrop_path:
                item.backdrop_path = side_fanart
        except Exception as exc:  # noqa: BLE001
            logger.debug("补全 side 失败 %s: %s", item.file_path, exc)

    # 2. NFO（B 方案：NFO 管文字）
    nfo_data = None
    if scan_file is not None and kind in ("series", "movie"):
        try:
            nfo_data, _series_nfo, _season_nfo = _sc._nfo_work(
                ctx, scan_file, item_type) or (None, None, None)
        except Exception as exc:  # noqa: BLE001
            logger.debug("补全 NFO 失败 %s: %s", item.file_path, exc)

    # 3. TMDB（NFO 有 tmdb_id 就不搜，只按需取详情补图/补缺）
    needs_repair = bool(getattr(item, "repair_requested_at", None))
    try:
        if nfo_data and nfo_data.get("tmdb_id"):
            tmdb_id = str(nfo_data["tmdb_id"])
            item.tmdb_id = item.tmdb_id or tmdb_id
            want_details = bool(
                needs_repair
                or not (item.poster_path or item.primary_image_url)
                or not (item.imdb_id and item.aliases))
            details = None
            if want_details and tmdb_client.configured:
                _tmdb_limiter.acquire()
                _hit, details = _sc._tmdb_work(
                    False, "", None, kind, tmdb_id, True)
            if details:
                if not nfo_data.get("imdb_id") and (
                        needs_repair or not (item.imdb_id and item.aliases)):
                    tmdb_client.apply_details(item, details)
                if needs_repair or not (item.poster_path or item.primary_image_url):
                    tmdb_client.apply_images(item, details)
            nfo_lib.apply_nfo(item, nfo_data, kind)
        elif tmdb_client.configured and kind in ("series", "movie"):
            # 无 NFO tmdb_id：按名搜索（高置信才命中，见 tmdb.search）
            _tmdb_limiter.acquire()
            hit, details = _sc._tmdb_work(
                True, item.name or "", item.production_year, kind,
                getattr(item, "tmdb_id", None), True)
            if hit:
                tmdb_client.apply(item, hit, kind)
            if details and (not (item.imdb_id and item.aliases)):
                tmdb_client.apply_details(item, details)
            if nfo_data:
                nfo_lib.apply_nfo(item, nfo_data, kind)
        elif nfo_data and not item.overview:
            # 没配 TMDB 但有 NFO：补文字即可
            nfo_lib.apply_nfo(item, nfo_data, kind)
    except Exception as exc:  # noqa: BLE001
        logger.warning("补全 TMDB 失败 %s: %s", item.file_path, exc)
        return False

    if needs_repair:
        item.repair_requested_at = None
    item.enrich_status = "done"
    # 分层 L1 + inline 探测模式：L1 没探（避免拖慢入库），这里把需要探测的
    # 条目送进 probe_worker 队列（background 模式的 L1 已经标过 pending 了，
    # 这里幂等：已是 pending/done 的不动）。
    try:
        if _sc.needs_probe(item, item.file_path or "", item.size or 0):
            if getattr(item, "probe_status", None) not in ("pending", "probing"):
                item.probe_status = "pending"
                item.probe_priority = max(item.probe_priority or 0, 100)
                item.probe_attempts = 0
                item.probe_next_retry_at = None
    except Exception:  # noqa: BLE001
        pass
    return True


def _claim_batch(db, limit: int) -> list:
    """抢一批待补全条目（状态机占位，防多 worker 重复）"""
    rows = (db.query(em.MediaItem)
            .filter(em.MediaItem.enrich_status == "pending")
            .order_by(em.MediaItem.date_added.desc())
            .limit(limit).all())
    claimed = []
    for r in rows:
        # 单进程内占位：先标 enriching 再提交，崩溃残留由启动时打回 pending
        r.enrich_status = "enriching"
        claimed.append(r)
    if claimed:
        db.commit()
    return claimed


def _recover_crashed(db) -> int:
    """启动时把崩溃残留的 enriching 打回 pending（断点续补）"""
    n = (db.query(em.MediaItem)
         .filter(em.MediaItem.enrich_status == "enriching")
         .update({"enrich_status": "pending"},
                 synchronize_session=False))
    db.commit()
    return n


def _worker_loop() -> None:
    logger.info("补全 worker 启动（L2/L3 后台补全）")
    db = SessionLocal()
    try:
        n = _recover_crashed(db)
        if n:
            logger.info("补全 worker 恢复 %d 条崩溃残留", n)
        while not _stop_event.is_set():
            try:
                batch = _claim_batch(db, ENRICH_BATCH)
            except Exception as exc:  # noqa: BLE001
                logger.warning("补全 worker 取单失败: %s", exc)
                _stop_event.wait(ENRICH_IDLE_POLL_SEC)
                continue
            if not batch:
                _stop_event.wait(ENRICH_IDLE_POLL_SEC)
                continue
            for item in batch:
                if _stop_event.is_set():
                    break
                try:
                    ok = _enrich_one(db, item)
                    if not ok:
                        # 暂失败：打回 pending，下次重试（不转 failed，避免饿死）
                        item.enrich_status = "pending"
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("补全条目失败 id=%s: %s", item.id, exc)
                    db.rollback()
                    try:
                        item.enrich_status = "pending"
                        db.commit()
                    except Exception:  # noqa: BLE001
                        db.rollback()
    finally:
        db.close()
    logger.info("补全 worker 退出")


def start() -> None:
    """启动后台补全线程（幂等）"""
    global _worker_thread
    if not ENRICH_ENABLED:
        logger.info("补全 worker 已禁用（ENRICH_WORKER=0）")
        return
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _stop_event.clear()
        _worker_thread = threading.Thread(
            target=_worker_loop, name="enrich-worker", daemon=True)
        _worker_thread.start()


def stop() -> None:
    """停止后台补全线程"""
    _stop_event.set()
    with _worker_lock:
        t, _worker_thread = _worker_thread, None
    if t is not None:
        t.join(timeout=10)
