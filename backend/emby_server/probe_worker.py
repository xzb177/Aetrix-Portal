# -*- coding: utf-8 -*-
"""按需探测 worker：消费 probe 队列，后台限流跑 ffprobe。

触发：
- 用户打开详情页 / 点播放，且条目是 movie/series、缺 video_codec → ``maybe_enqueue``
  把条目标 ``probe_status='pending'``、优先级 1000（按需插队，见 models.py）。
- 扫描器对新文件本来就会标 pending（优先级 100），本 worker 顺手消费，
  等于免费拿到「新入库后台预探测」（P1）。

限流（抄 StrmTool，保护 Drive 配额）：
- 最多 ``PROBE_WORKERS``（默认 2，上限 5）并发探测；
- 每次探测启动间隔 ≥ ``PROBE_MIN_INTERVAL_SEC``（默认 1 秒）；
- 单条最多 ``PROBE_MAX_ATTEMPTS``（默认 3）次，指数退避。

抢单：``SELECT FOR UPDATE SKIP LOCKED`` 原子抢（多 worker 不重复），
方言不支持时退回普通查询（单 worker 仍正确），与 enrich_worker 同口径。
"""
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

from sqlalchemy import or_

from backend.emby_server import models as em
from backend.emby_server import media_probe

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _env_float(name: str, default: float, lo: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, value)


PROBE_ENABLED = (os.getenv("PROBE_ONDEMAND_ENABLED", "1") or "1").strip() not in ("0", "false", "no")
PROBE_WORKERS = _env_int("PROBE_WORKERS", 2, 1, 5)
PROBE_MIN_INTERVAL_SEC = _env_float("PROBE_MIN_INTERVAL_SEC", 1.0, 0.0)
PROBE_CLAIM_BATCH = _env_int("PROBE_CLAIM_BATCH", 20, 1, 100)
PROBE_IDLE_SLEEP_SEC = _env_float("PROBE_IDLE_SLEEP_SEC", 5.0, 1.0)
# 独占模式（对标 StrmAssistant GeneralOptions.CooldownDurationSeconds）：
# 并发为 1 时每次探测后冷却 N 秒，避免 ffprobe 连续读网盘互相争抢。
# 并发 >1 时不冷却（冷却只在单线程串行时有意义）。
PROBE_COOLDOWN_SEC = _env_float("PROBE_COOLDOWN_SEC", 0.0, 0.0)

# 预提取（对标 StrmAssistant ExtractMediaInfoTask）：定时把全库缺媒体信息的
# 条目扫出来入队，首播时直接命中，零等待。
# "1" = 开（默认）；"0" = 关（只保留按需探测）。
PREPROBE_ENABLED = (os.getenv("PROBE_PREEXTRACT_ENABLED", "1") or "1").strip() not in ("0", "false", "no")
# 预提取扫描间隔（秒），默认 6 小时；启动时先跑一轮。
PREPROBE_INTERVAL_SEC = _env_float("PROBE_PREEXTRACT_INTERVAL_SEC", 21600.0, 60.0)
# 预提取入队优先级（低于按需 1000，高于扫描器 100）
PREPROBE_PRIORITY = 500
# 单次扫描最多入队条数（防 40 万库一次全标 pending）
PREPROBE_SWEEP_LIMIT = _env_int("PROBE_PREEXTRACT_SWEEP_LIMIT", 5000, 100, 100000)

# 按需插队优先级（models.py 约定）；只做 movie/series，单集/季不碰
ONDEMAND_PRIORITY = 1000
PROBE_ITEM_TYPES = ("movie", "series")

_dispatcher_thread: Optional[threading.Thread] = None
_preprobe_thread: Optional[threading.Thread] = None
_start_lock = threading.Lock()
_stop_event = threading.Event()


def enabled() -> bool:
    return PROBE_ENABLED


def maybe_enqueue(db, item) -> bool:
    """详情页/播放触发点：缺媒体信息的电影/剧集入队。

    幂等、便宜（命中时一次 UPDATE）。以下情况直接跳过：
    - 功能关闭 / 不是 movie、series / 已有 video_codec / 无 file_path；
    - 已在队列（pending/probing）；
    - 已达最大尝试次数（failed/degraded 不无限复活）。

    返回 True 表示本次入队成功。
    """
    try:
        if not PROBE_ENABLED:
            return False
        if getattr(item, "item_type", None) not in PROBE_ITEM_TYPES:
            return False
        if getattr(item, "video_codec", None):
            return False
        if not (getattr(item, "file_path", None) or "").strip():
            return False
        if getattr(item, "probe_status", None) in ("pending", "probing"):
            return False
        if (getattr(item, "probe_attempts", 0) or 0) >= media_probe.PROBE_MAX_ATTEMPTS:
            return False
        item.probe_status = "pending"
        item.probe_priority = max(int(getattr(item, "probe_priority", 0) or 0), ONDEMAND_PRIORITY)
        item.probe_next_retry_at = None
        db.commit()
        logger.info("按需探测入队 item=%s type=%s", item.id, item.item_type)
        return True
    except Exception as exc:  # noqa: BLE001 — 入队失败绝不能影响详情页/播放
        logger.warning("按需探测入队失败 item=%s: %s", getattr(item, "id", "?"), exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def _due_filter(now: datetime):
    """只抢「到重试时间」的。"""
    return or_(em.MediaItem.probe_next_retry_at.is_(None),
               em.MediaItem.probe_next_retry_at <= now)


def _claim_batch(db, limit: int, library_id: Optional[int] = None) -> List[int]:
    """原子抢一批待探测条目，抢到的标 probing。

    范围：pending + movie/series + 缺 video_codec（NULL 或空串）+ 有 file_path。
    排序：优先级高的先（按需 1000 插队在扫描器 100 之前），同优先级按 id。
    ``library_id``：可选的库过滤（测试用，生产传 None 即全库）。

    返回条目 id 列表（不返回 ORM 对象：调用方拿到结果后往往已关 session，
    再读对象属性会 DetachedInstanceError；id 跨线程也安全）。
    """
    now = datetime.now()
    missing_codec = or_(em.MediaItem.video_codec.is_(None),
                        em.MediaItem.video_codec == "")
    filters = [em.MediaItem.probe_status == "pending",
               em.MediaItem.item_type.in_(PROBE_ITEM_TYPES),
               missing_codec,
               em.MediaItem.file_path.isnot(None),
               em.MediaItem.file_path != "",
               _due_filter(now)]
    if library_id is not None:
        filters.append(em.MediaItem.library_id == library_id)
    q = (db.query(em.MediaItem.id)
         .filter(*filters)
         .order_by(em.MediaItem.probe_priority.desc(), em.MediaItem.id)
         .limit(limit))
    try:
        rows = q.with_for_update(skip_locked=True).all()
    except Exception:
        # 方言不支持 FOR UPDATE 时退回普通查询（单 worker 仍正确）
        rows = q.all()
    ids = [r[0] for r in rows]
    if ids:
        (db.query(em.MediaItem)
         .filter(em.MediaItem.id.in_(ids))
         .update({"probe_status": "probing"}, synchronize_session=False))
        db.commit()
    else:
        # 只是 SELECT 也会开事务；worker 接下来睡眠，不 rollback 会留下
        # idle in transaction 占连接（与 enrich_worker 同一教训）。
        db.rollback()
    return ids


def _recover_crashed(db) -> int:
    """启动时恢复崩溃残留：probing → pending（幂等，只动 movie/series）。"""
    rows = (db.query(em.MediaItem)
            .filter(em.MediaItem.probe_status == "probing",
                    em.MediaItem.item_type.in_(PROBE_ITEM_TYPES))
            .all())
    for r in rows:
        r.probe_status = "pending"
        r.probe_next_retry_at = None
    if rows:
        db.commit()
    else:
        db.rollback()
    return len(rows)


def preprobe_sweep(db, limit: int = PREPROBE_SWEEP_LIMIT) -> int:
    """预提取扫描（对标 StrmAssistant ExtractMediaInfoTask.FetchPreExtractTaskItems）。

    把全库「缺媒体信息、未判死、未在队列」的 movie/series 标为 pending，
    优先级 ``PREPROBE_PRIORITY``（500），由调度器慢慢消费。

    幂等、可重复跑；返回本次入队条数。
    """
    missing_codec = or_(em.MediaItem.video_codec.is_(None),
                        em.MediaItem.video_codec == "")
    # 注意：probe_status 为 NULL 的也要扫（NOT IN 对 NULL 返回 unknown 会漏掉）
    # done/degraded 也要排除：已探测过（即使没拿到 codec）的不再重复入队，
    # 否则无法探测的文件会被无限重复排队
    not_queued = or_(em.MediaItem.probe_status.is_(None),
                     em.MediaItem.probe_status.notin_(
                         ("pending", "probing", "failed", "done", "degraded")))
    q = (db.query(em.MediaItem.id)
         .filter(em.MediaItem.item_type.in_(PROBE_ITEM_TYPES),
                 missing_codec,
                 em.MediaItem.file_path.isnot(None),
                 em.MediaItem.file_path != "",
                 em.MediaItem.deleted_at.is_(None),
                 em.MediaItem.merged_into_id.is_(None),
                 not_queued)
         .order_by(em.MediaItem.id)
         .limit(limit))
    try:
        rows = q.with_for_update(skip_locked=True).all()
    except Exception:
        rows = q.all()
    ids = [r[0] for r in rows]
    if ids:
        (db.query(em.MediaItem)
         .filter(em.MediaItem.id.in_(ids))
         .update({"probe_status": "pending",
                  "probe_priority": PREPROBE_PRIORITY,
                  "probe_next_retry_at": None},
                 synchronize_session=False))
        db.commit()
        logger.info("预提取扫描入队 %d 条（缺媒体信息）", len(ids))
    else:
        db.rollback()
    return len(ids)


def _preprobe_loop() -> None:
    """预提取定时器：启动先跑一轮，之后按间隔重复。"""
    from backend.database import SessionLocal
    logger.info("预提取定时器启动（间隔 %gs）", PREPROBE_INTERVAL_SEC)
    # 启动先跑一轮
    _run_preprobe_once()
    while not _stop_event.is_set():
        if _stop_event.wait(PREPROBE_INTERVAL_SEC):
            break
        _run_preprobe_once()


def _run_preprobe_once() -> None:
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        n = preprobe_sweep(db)
        if n:
            logger.info("预提取扫描完成，本次入队 %d 条", n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("预提取扫描失败: %s", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def _process_one(item_id: int) -> None:
    """单个条目的完整处理（worker 线程内跑，自带 session）。"""
    from backend.database import SessionLocal
    db = SessionLocal()
    probed = False
    try:
        item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
        if item is None or getattr(item, "probe_status", None) != "probing":
            db.rollback()
            return
        # 抢到之后 codec 可能已被别的路（NFO/enrich/JSON 恢复）补上，没必要再探
        if getattr(item, "video_codec", None):
            item.probe_status = "done"
            item.probe_attempts = 0
            item.probe_next_retry_at = None
            db.commit()
            return
        media_probe.probe_one(db, item)
        probed = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("按需探测处理异常 item=%s: %s", item_id, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()
        # 独占模式冷却（对标 StrmAssistant CooldownDurationSeconds）：
        # 单线程时每次**实际执行探测**后歇一会，避免连续读网盘互相争抢。
        # 被跳过（已有 codec / 状态不对）时不冷却。
        if probed and PROBE_WORKERS <= 1 and PROBE_COOLDOWN_SEC > 0:
            _stop_event.wait(PROBE_COOLDOWN_SEC)


def _dispatcher_loop() -> None:
    """调度器：抢单 → 限流提交到线程池。"""
    from backend.database import SessionLocal
    logger.info("按需探测调度器启动（并发≤%d，启动间隔≥%gs）",
                PROBE_WORKERS, PROBE_MIN_INTERVAL_SEC)
    pool = ThreadPoolExecutor(max_workers=PROBE_WORKERS,
                              thread_name_prefix="media-probe")
    last_submit = 0.0
    try:
        while not _stop_event.is_set():
            db = SessionLocal()
            try:
                claimed = _claim_batch(db, PROBE_CLAIM_BATCH)
            except Exception as exc:  # noqa: BLE001
                logger.warning("按需探测抢单失败: %s", exc)
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                claimed = []
            finally:
                db.close()
            if not claimed:
                _stop_event.wait(PROBE_IDLE_SLEEP_SEC)
                continue
            for item_id in claimed:
                gap = PROBE_MIN_INTERVAL_SEC - (time.monotonic() - last_submit)
                if gap > 0 and _stop_event.wait(gap):
                    break
                last_submit = time.monotonic()
                pool.submit(_process_one, item_id)
    finally:
        pool.shutdown(wait=False)


def start() -> None:
    """启动按需探测 worker（幂等）。"""
    global _dispatcher_thread, _preprobe_thread
    if not PROBE_ENABLED:
        logger.info("按需探测已禁用（PROBE_ONDEMAND_ENABLED=0）")
        return
    with _start_lock:
        if _dispatcher_thread is not None and _dispatcher_thread.is_alive():
            return
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            n = _recover_crashed(db)
            if n:
                logger.info("按需探测恢复 %d 条崩溃残留", n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("按需探测恢复崩溃残留失败: %s", exc)
        finally:
            db.close()
        _stop_event.clear()
        _dispatcher_thread = threading.Thread(
            target=_dispatcher_loop, name="media-probe-dispatcher", daemon=True)
        _dispatcher_thread.start()
        logger.info("按需探测 worker 已启动")
        # 预提取定时器（对标 StrmAssistant ExtractMediaInfoTask）
        if PREPROBE_ENABLED and (_preprobe_thread is None or not _preprobe_thread.is_alive()):
            _preprobe_thread = threading.Thread(
                target=_preprobe_loop, name="media-preprobe", daemon=True)
            _preprobe_thread.start()
            logger.info("预提取定时器已启动")


def stop() -> None:
    """停止 worker（测试用）。"""
    _stop_event.set()
    for t in (_dispatcher_thread, _preprobe_thread):
        if t is not None and t.is_alive():
            t.join(timeout=5)
