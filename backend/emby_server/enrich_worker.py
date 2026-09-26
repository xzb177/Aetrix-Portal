"""分层扫描 L2/L3：后台补全 worker（v2.40.0）

SCAN_LAYERED=1 时，扫描（L1）只做文件发现 + 指纹 + 极简入库（秒级可见），
side 图片 / NFO / TMDB 刮削全部交给本 worker 在后台补全——这就是「分层」：

- 队列持久化在 ``emby_items.enrich_status``（pending=待补全 done=已补全
  failed=重试超限 enriching=处理中），进程/容器重启不丢；启动时把崩溃残留的
  ``'enriching'`` 打回 ``'pending'``（断点续补）；
- 原子抢任务：SELECT FOR UPDATE SKIP LOCKED，多 worker/多进程不重复处理；
- 失败指数退避：attempts 计数，next_retry_at 调度，5 次后转 failed；
- 新文件优先（date_added 倒序），TMDB 令牌桶限速；
- NFO 优先原则不变：NFO 管文字，TMDB 只补图和缺失字段；
- 补全是幂等的：重复补同一条目只会覆盖出相同结果；
- IO（网络/磁盘）全部在 DB 写事务之外做，写库是单条短事务。
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
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
# 重试：最多 5 次，退避基数 60 秒（60s, 120s, 240s, 480s, 960s）
ENRICH_MAX_ATTEMPTS = max(1, int(os.getenv("ENRICH_MAX_ATTEMPTS", "5") or 5))
ENRICH_RETRY_BASE_SEC = max(10, int(os.getenv("ENRICH_RETRY_BASE_SEC", "60") or 60))

_worker_threads: list = []
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
    dirpath = os.path.dirname(path)
    return _sc.ScanFile(
        stored_path=path, name=name, local_dir=dirpath,
        size=size, container=container,
    )


def _enrich_fetch(item: Any) -> dict:
    """IO 阶段（无 DB 写事务）：side 图片/字幕 → NFO → TMDB。

    返回待写入的数据包，写库阶段只做纯 DB 操作。
    同一部剧的 TMDB 搜索由调用方经 _searched_series 去重。
    """
    from backend.emby_server import scanner as _sc
    from backend.emby_server import nfo as nfo_lib
    from backend.emby_server.tmdb import tmdb_client

    result: dict = {
        "poster": None, "fanart": None, "external_subs": [],
        "nfo_data": None, "tmdb_hit": None, "tmdb_details": None,
        "ok": True, "error": None,
    }
    item_type = item.item_type or ""
    # NFO kind 口径：series→tvshow.nfo，season→season.nfo，episode→episodedetails，movie→movie
    kind = {"series": "series", "season": "season",
            "episode": "episode", "movie": "movie"}.get(item_type, "")
    scan_file = _scanfile_from_item(item)
    if scan_file is None:
        result["ok"] = False
        result["error"] = "无 file_path，无法重建 ScanFile"
        return result

    snap = _sc.LibrarySnapshot(
        library_id=item.library_id, name="", collection_type="",
        paths=(), scrape_policy="smart",
    )
    ctx = _sc._ScanContext(snap=snap, lib_id=item.library_id, stats={})

    # 1. side 图片 / 外挂字幕（本地图片优先，不覆盖已有）
    try:
        side_poster, side_fanart, external = _sc._side_info(ctx, scan_file)
        result["poster"] = side_poster
        result["fanart"] = side_fanart
        result["external_subs"] = list(external or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("补全 side 失败 %s: %s", item.file_path, exc)

    # 2. NFO（B 方案：NFO 管文字；series/season/episode/movie 全支持）
    nfo_data = None
    if kind:
        try:
            nfo_data, _s1, _s2 = _sc._nfo_work(ctx, scan_file, kind) or (None, None, None)
            result["nfo_data"] = nfo_data
        except Exception as exc:  # noqa: BLE001
            logger.debug("补全 NFO 失败 %s: %s", item.file_path, exc)

    # 3. TMDB（NFO 有 tmdb_id 就不搜，只按需取详情补图/补缺）
    needs_repair = bool(getattr(item, "repair_requested_at", None))
    try:
        if nfo_data and nfo_data.get("tmdb_id"):
            tmdb_id = str(nfo_data["tmdb_id"])
            result["tmdb_id"] = tmdb_id
            want_details = bool(
                needs_repair
                or not (item.poster_path or item.primary_image_url)
                or not (item.imdb_id and item.aliases))
            if want_details and tmdb_client.configured:
                _tmdb_limiter.acquire()
                _hit, details = _sc._tmdb_work(
                    False, "", None, kind, tmdb_id, True)
                result["tmdb_details"] = details
        elif tmdb_client.configured and kind in ("series", "movie"):
            _tmdb_limiter.acquire()
            hit, details = _sc._tmdb_work(
                True, item.name or "", item.production_year, kind,
                getattr(item, "tmdb_id", None), True)
            result["tmdb_hit"] = hit
            result["tmdb_details"] = details
    except Exception as exc:  # noqa: BLE001
        logger.warning("补全 TMDB 失败 %s: %s", item.file_path, exc)
        result["ok"] = False
        result["error"] = str(exc)[:200]

    return result


def _enrich_apply(db, item: Any, fetched: dict) -> None:
    """写库阶段（单条短事务内调用）：把 IO 阶段拿到的数据落库。"""
    from backend.emby_server import nfo as nfo_lib
    from backend.emby_server.tmdb import tmdb_client
    from backend.emby_server import scanner as _sc
    from sqlalchemy import func as _func

    item_type = item.item_type or ""
    kind = {"series": "series", "season": "season",
            "episode": "episode", "movie": "movie"}.get(item_type, "")

    # 1. side 图片（不覆盖已有）
    if fetched.get("poster") and not item.poster_path:
        item.poster_path = fetched["poster"]
    if fetched.get("fanart") and not item.backdrop_path:
        item.backdrop_path = fetched["fanart"]

    # 2. 外挂字幕 → MediaStream（总是刷新，与视频探测无关）
    external = fetched.get("external_subs") or []
    if external or True:  # 无字幕也要清理旧的字幕轨（文件删了字幕的场景）
        db.query(em.MediaStream).filter(
            em.MediaStream.item_id == item.id,
            em.MediaStream.is_external.is_(True),
        ).delete(synchronize_session=False)
        next_index = 0
        if external:
            next_index = db.query(_func.max(em.MediaStream.stream_index)).filter(
                em.MediaStream.item_id == item.id).scalar() or 0
        for offset, (lang, sub_path) in enumerate(external, start=1):
            db.add(em.MediaStream(
                item_id=item.id, stream_index=next_index + offset,
                stream_type="Subtitle",
                codec=os.path.splitext(sub_path)[1].lstrip("."),
                language=lang, display_title=os.path.basename(sub_path),
                is_default=(offset == 1),
                is_external=True, external_path=sub_path,
            ))

    # 3. NFO + TMDB
    nfo_data = fetched.get("nfo_data")
    needs_repair = bool(getattr(item, "repair_requested_at", None))
    if fetched.get("tmdb_id"):
        item.tmdb_id = item.tmdb_id or fetched["tmdb_id"]
        details = fetched.get("tmdb_details")
        if details:
            if not (nfo_data or {}).get("imdb_id") and (
                    needs_repair or not (item.imdb_id and item.aliases)):
                tmdb_client.apply_details(item, details)
            if needs_repair or not (item.poster_path or item.primary_image_url):
                tmdb_client.apply_images(item, details)
        if nfo_data:
            nfo_lib.apply_nfo(item, nfo_data, kind)
    elif fetched.get("tmdb_hit"):
        tmdb_client.apply(item, fetched["tmdb_hit"], kind)
        details = fetched.get("tmdb_details")
        if details and not (item.imdb_id and item.aliases):
            tmdb_client.apply_details(item, details)
        if nfo_data:
            nfo_lib.apply_nfo(item, nfo_data, kind)
    elif nfo_data and not item.overview:
        nfo_lib.apply_nfo(item, nfo_data, kind)

    if needs_repair:
        item.repair_requested_at = None
    item.enrich_status = "done"
    item.enrich_attempts = 0
    item.enrich_next_retry_at = None

    # probe 衔接：需要探测的送进 probe 队列（幂等）
    try:
        if _sc.needs_probe(item, item.file_path or "", item.size or 0):
            if getattr(item, "probe_status", None) not in ("pending", "probing"):
                item.probe_status = "pending"
                item.probe_priority = max(item.probe_priority or 0, 100)
                item.probe_attempts = 0
                item.probe_next_retry_at = None
    except Exception:  # noqa: BLE001
        pass


def _claim_batch(db, limit: int) -> list:
    """原子抢一批待补全条目（多 worker/多进程不重复）。

    SELECT FOR UPDATE SKIP LOCKED：PostgreSQL/MySQL 原子跳过已被锁的行；
    SQLite 忽略 SKIP LOCKED 但事务本身串行化，同样不会重入。
    只抢「到重试时间」的（next_retry_at IS NULL 或已到期）。
    """
    now = datetime.now()
    q = (db.query(em.MediaItem)
         .filter(em.MediaItem.enrich_status == "pending")
         .filter((em.MediaItem.enrich_next_retry_at.is_(None)) |
                 (em.MediaItem.enrich_next_retry_at <= now))
         .order_by(em.MediaItem.date_added.desc())
         .limit(limit))
    try:
        rows = q.with_for_update(skip_locked=True).all()
    except Exception:
        # 方言不支持 FOR UPDATE 时退回普通查询（单 worker 仍正确）
        rows = q.all()
    claimed = []
    for r in rows:
        r.enrich_status = "enriching"
        claimed.append(r)
    if claimed:
        db.commit()
    return claimed


def _mark_failed(db, item_id: int, attempts: int, error: str) -> None:
    """失败：attempts+1，指数退避，超限转 failed。单条短事务。"""
    try:
        item = db.query(em.MediaItem).filter(
            em.MediaItem.id == item_id).first()
        if item is None:
            return
        attempts = (attempts or 0) + 1
        item.enrich_attempts = attempts
        if attempts >= ENRICH_MAX_ATTEMPTS:
            item.enrich_status = "failed"
            item.enrich_next_retry_at = None
            logger.warning("补全重试超限转 failed id=%s attempts=%s err=%s",
                           item_id, attempts, error[:120])
        else:
            backoff = ENRICH_RETRY_BASE_SEC * (2 ** (attempts - 1))
            item.enrich_status = "pending"
            item.enrich_next_retry_at = datetime.now() + timedelta(seconds=backoff)
            logger.info("补全失败待重试 id=%s attempts=%s %ss后 err=%s",
                        item_id, attempts, backoff, error[:120])
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _recover_crashed(db) -> int:
    """启动时把崩溃残留的 enriching 打回 pending（断点续补）"""
    n = (db.query(em.MediaItem)
         .filter(em.MediaItem.enrich_status == "enriching")
         .update({"enrich_status": "pending"},
                 synchronize_session=False))
    db.commit()
    return n


def _suppress_flood(db) -> int:
    """防入队洪峰：分层扫描启用前的老数据（无 file_fingerprint）默认 enrich_status
    是 pending，会一次性全进队列。用启发式直接标 done：
    - 有 last_scraped_at（已被旧扫描器刮过）→ done
    - 有 tmdb_id → done
    其余老数据保留 pending（真需要补），但按 date_added 倒序慢慢消化。
    返回标为 done 的条数。
    """
    from sqlalchemy import or_ as _or
    n = (db.query(em.MediaItem)
         .filter(em.MediaItem.enrich_status == "pending")
         .filter(em.MediaItem.file_fingerprint.is_(None))
         .filter(_or(em.MediaItem.last_scraped_at.isnot(None),
                     em.MediaItem.tmdb_id.isnot(None)))
         .update({"enrich_status": "done"}, synchronize_session=False))
    db.commit()
    return n


def _worker_loop(worker_id: int) -> None:
    logger.info("补全 worker #%d 启动（L2/L3 后台补全）", worker_id)
    # 同一部剧只搜一次 TMDB：series 级去重（worker 内内存集合）
    _searched_series: set = set()
    db = SessionLocal()
    try:
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
                item_id = item.id
                attempts = getattr(item, "enrich_attempts", 0) or 0
                # ---- IO 阶段（无写事务）：网络/磁盘全在这里 ----
                try:
                    fetched = _enrich_fetch(item)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("补全 IO 失败 id=%s: %s", item_id, exc)
                    db.rollback()
                    _mark_failed(db, item_id, attempts, str(exc))
                    continue
                if not fetched.get("ok"):
                    db.rollback()
                    _mark_failed(db, item_id, attempts,
                                 fetched.get("error") or "fetch failed")
                    continue
                # ---- 写库阶段（单条短事务） ----
                try:
                    fresh = db.query(em.MediaItem).filter(
                        em.MediaItem.id == item_id).first()
                    if fresh is None:
                        continue
                    _enrich_apply(db, fresh, fetched)
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("补全写库失败 id=%s: %s", item_id, exc)
                    db.rollback()
                    _mark_failed(db, item_id, attempts, str(exc))
            # 批次之间释放 session 身份映射，避免长连接内存膨胀
            db.expire_all()
    finally:
        db.close()
    logger.info("补全 worker #%d 退出", worker_id)


def get_progress() -> dict:
    """进度快照：给管理后台接口用。"""
    db = SessionLocal()
    try:
        from sqlalchemy import func as _func
        q = db.query(em.MediaItem.enrich_status,
                     _func.count(em.MediaItem.id)).group_by(
                         em.MediaItem.enrich_status).all()
        by_status = {s or "unknown": c for s, c in q}
        retrying = db.query(_func.count(em.MediaItem.id)).filter(
            em.MediaItem.enrich_status == "pending",
            em.MediaItem.enrich_next_retry_at.isnot(None)).scalar() or 0
        pq = db.query(em.MediaItem.probe_status,
                      _func.count(em.MediaItem.id)).group_by(
                          em.MediaItem.probe_status).all()
        probe_by_status = {s or "unknown": c for s, c in pq}
        return {
            "enrich": {
                "pending": by_status.get("pending", 0),
                "enriching": by_status.get("enriching", 0),
                "done": by_status.get("done", 0),
                "failed": by_status.get("failed", 0),
                "retrying": retrying,
            },
            "probe": probe_by_status,
            "workers": ENRICH_WORKERS,
            "enabled": ENRICH_ENABLED,
        }
    finally:
        db.close()


def start() -> None:
    """启动后台补全线程（幂等），线程数 = ENRICH_WORKERS"""
    global _worker_threads
    if not ENRICH_ENABLED:
        logger.info("补全 worker 已禁用（ENRICH_WORKER=0）")
        return
    with _worker_lock:
        _worker_threads = [t for t in _worker_threads if t.is_alive()]
        if _worker_threads:
            return
        # 启动前：恢复崩溃残留 + 防老数据洪峰（只做一次）
        db = SessionLocal()
        try:
            n = _recover_crashed(db)
            if n:
                logger.info("补全 worker 恢复 %d 条崩溃残留", n)
            m = _suppress_flood(db)
            if m:
                logger.info("补全 worker 防洪峰：%d 条老数据直接标 done", m)
        finally:
            db.close()
        _stop_event.clear()
        for i in range(ENRICH_WORKERS):
            t = threading.Thread(
                target=_worker_loop, args=(i,),
                name=f"enrich-worker-{i}", daemon=True)
            t.start()
            _worker_threads.append(t)
        logger.info("补全 worker 启动 %d 个线程", ENRICH_WORKERS)


def stop() -> None:
    """停止后台补全线程"""
    _stop_event.set()
    with _worker_lock:
        threads, _worker_threads = _worker_threads, []
    for t in threads:
        t.join(timeout=10)
