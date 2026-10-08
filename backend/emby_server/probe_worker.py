# -*- coding: utf-8 -*-
"""媒体信息探测 worker（v2.53 重构）：按需优先 + 数据库状态驱动的后台补齐。

为什么重写（生产：28.5 万条 pending 不动、worker 时不时卡死）——根因见
CHANGELOG / docs，简述：

1. **队列口径对不上**：扫描器（fast_scanner / scanner background 模式 / enrich）
   和 ALTER 默认值把 *单集、季、剧集骨架、文件名已解析出 codec 的电影* 全标成
   ``pending``，而旧调度器只抢 ``movie/series 且 video_codec 为空``。结果：
   pending 计数里绝大多数条目永远不会被抢；预提取定时器又只扫「未在队列」的条目，
   而它们**已经**是 pending → 每轮入队 0 条。日志里「预提取定时器启动」照常出现，
   实际什么都没探。
2. **抢单泄漏**：旧调度器先把一批标成 ``probing``，再判断线程池背压；背压时直接
   ``continue`` —— 这批永远停在 probing，只有重启才恢复。
3. **单条目无上限**：``subprocess.run(timeout)`` 只杀直接子进程后无限 ``wait()``；
   FUSE 挂死（D 状态）时 worker 线程被永久吃掉；``os.path.isfile`` 同理。
   线程全卡住 → 背压 → 每轮再泄漏一批 probing（第 2 条），表现为「时不时卡死」。
4. 单体模式（serve.py / main.py lifespan）根本没启动探测 worker（M11）。

新设计：

- **按需优先**：详情页 / PlaybackInfo 调 :func:`maybe_enqueue`，不阻塞请求（PlaybackInfo
  本来就从文件名解析的信息起播，v2.51 去掉了同步 ffprobe）；已在 pending 的条目把优先级
  提到 1000 并唤醒调度器，几秒内就被探到。
- **后台补齐**：不再一次性往内存里塞队列，状态全在 DB：
  ``probe_status``（pending / probing / done / degraded / failed / skipped）+
  ``probe_attempts`` + ``probe_next_retry_at`` + ``probe_claimed_at``（租约）+
  ``probe_last_error``。抢单 ``FOR UPDATE SKIP LOCKED``（PG）/ 带状态守卫的 UPDATE（SQLite）；
  租约超时（``PROBE_CLAIM_TTL_SEC``）自动放回 pending；失败指数退避，K 次后 failed。
- **整理（triage）**：启动时和每 ``PROBE_PREEXTRACT_INTERVAL_SEC`` 按 id 分段把
  ``pending`` 纠正成真实状态：不需要探测的（季/剧集/无文件/已删/已合并）→ ``skipped``，
  已有完整信息的 → ``done``；``probe_status IS NULL`` 的按同一口径入队。最近播放过的
  pending 条目提到优先级 800。
- **有上限**：每条目 解析 ≤ ``PROBE_RESOLVE_TIMEOUT_SEC``、探测 ≤ ``PROBE_ITEM_TIMEOUT_SEC``
  （所有 ffprobe/mediainfo 子进程共享这个预算，超时整组 SIGKILL，收不回就放弃等待）。
- **按挂载限流 + 熔断**：每个挂载（``mount://<id>/``、本机路径前两级）独立计并发，
  远程默认 2、本机默认 4；连续 ``PROBE_BREAKER_THRESHOLD`` 次超时 → 熔断
  ``PROBE_BREAKER_COOLDOWN_SEC``（翻倍，最长 1 小时），熔断期间该挂载的条目不抢单。
- **可观测**：心跳 + 进度（各状态计数、近 10 分钟速率、最近错误、熔断中的挂载、ETA），
  :func:`status_snapshot` 供管理接口 / health 使用；跨进程（api/worker 拆分）经 cache 共享。
- **可运维**：:func:`reset` 一键把卡住/失败的放回 pending；:func:`set_paused` 暂停/恢复
  （存在 system_configs，跨进程生效）。
- **自愈**：调度器循环体任何异常只记日志不退出；线程登记到 ``worker_registry`` 并带
  restart 回调，监督线程发现它死了会重启。

兼容：背压不再依赖线程池私有的 ``pool._work_queue.qsize()``，而是在途计数；
``probed_no_duration`` 等历史终态照旧不重探。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_

from backend.emby_server import media_probe
from backend.emby_server import models as em
from backend.emby_server import proc_util
from backend.emby_server.env_util import env_float, env_int

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: str = "1") -> bool:
    return (os.getenv(name, default) or default).strip().lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------- 配置
PROBE_ENABLED = _env_flag("PROBE_ONDEMAND_ENABLED")
# 总并发（线程池大小）
PROBE_WORKERS = env_int("PROBE_WORKERS", 4, 1, 16)
# 每个挂载的并发上限：远程（115/rclone/WebDAV/FUSE/直链）默认 2，本机磁盘默认 4
PROBE_REMOTE_CONCURRENCY = env_int("PROBE_REMOTE_CONCURRENCY", 2, 1, 16)
PROBE_LOCAL_CONCURRENCY = env_int("PROBE_LOCAL_CONCURRENCY", 4, 1, 16)
# 两次提交之间的最小间隔（全局，保护网盘配额）
PROBE_MIN_INTERVAL_SEC = env_float("PROBE_MIN_INTERVAL_SEC", 0.5, 0.0)
PROBE_CLAIM_BATCH = env_int("PROBE_CLAIM_BATCH", 20, 1, 200)
PROBE_IDLE_SLEEP_SEC = env_float("PROBE_IDLE_SLEEP_SEC", 5.0, 0.2)
# 单条目预算
PROBE_RESOLVE_TIMEOUT_SEC = env_float("PROBE_RESOLVE_TIMEOUT_SEC", 20.0, 1.0)
PROBE_ITEM_TIMEOUT_SEC = env_float("PROBE_ITEM_TIMEOUT_SEC", 60.0, 1.0)
# 抢单租约：probing 超过这么久视为抢单者已死
PROBE_CLAIM_TTL_SEC = env_float("PROBE_CLAIM_TTL_SEC", 900.0, 30.0)
PROBE_RECLAIM_EVERY_SEC = 60.0
# 抢到但因挂载并发满而在本地缓冲里等太久的，放回 pending（不计失败）
PROBE_BUFFER_MAX_SEC = 60.0
# 熔断
PROBE_BREAKER_THRESHOLD = env_int("PROBE_BREAKER_THRESHOLD", 3, 1, 100)
PROBE_BREAKER_COOLDOWN_SEC = env_float("PROBE_BREAKER_COOLDOWN_SEC", 300.0, 1.0)
PROBE_BREAKER_MAX_COOLDOWN_SEC = 3600.0
# 独占模式冷却（对标 StrmAssistant CooldownDurationSeconds）：并发为 1 时每次探测后歇 N 秒
PROBE_COOLDOWN_SEC = env_float("PROBE_COOLDOWN_SEC", 0.0, 0.0)
# 背压系数（兼容旧配置名；新调度器只抢「空闲槽位 × 系数」那么多，绝不抢了不处理）
PROBE_BACKLOG_FACTOR = 2

# 需要探测的条目类型：默认电影 + 单集（剧集/季没有文件，旧版的 "series" 是个空集）。
# 只想探电影可设 PROBE_ITEM_TYPES=movie。
PROBE_ITEM_TYPES = tuple(
    t.strip() for t in (os.getenv("PROBE_ITEM_TYPES", "movie,episode") or "movie,episode").split(",")
    if t.strip()) or ("movie", "episode")

# 预提取 / 整理（triage）
PREPROBE_ENABLED = _env_flag("PROBE_PREEXTRACT_ENABLED")
PREPROBE_INTERVAL_SEC = env_float("PROBE_PREEXTRACT_INTERVAL_SEC", 21600.0, 60.0)
PREPROBE_PRIORITY = 500
PREPROBE_SWEEP_LIMIT = env_int("PROBE_PREEXTRACT_SWEEP_LIMIT", 5000, 100, 100000)
TRIAGE_CHUNK = env_int("PROBE_TRIAGE_CHUNK", 5000, 100, 100000)
RECENT_PLAY_DAYS = 30
RECENT_PLAY_PRIORITY = 800

# 按需插队优先级（models.py 约定）
ONDEMAND_PRIORITY = 1000

# 终态：这些状态的条目 preprobe / triage 不复活
#（probed_no_duration 是扫描器历史终态，缺 codec 也不重探，否则会烧 Drive 配额）
TERMINAL_STATUSES = ("done", "degraded", "failed", "skipped", "probed_no_duration")
QUEUE_STATUSES = ("pending", "probing")

PAUSE_CONFIG_KEY = "probe_worker_paused"
STATUS_CACHE_KEY = "aetrix:probe:status"

# ---------------------------------------------------------------- 运行时状态
_dispatcher_thread: Optional[threading.Thread] = None
_preprobe_thread: Optional[threading.Thread] = None
_start_lock = threading.Lock()
_stop_event = threading.Event()
_wake = threading.Event()

_metrics_lock = threading.Lock()
_metrics: dict = {}
_recent_done: deque = deque(maxlen=20000)  # 完成时刻（monotonic），算速率


def _reset_metrics() -> None:
    with _metrics_lock:
        _metrics.clear()
        _metrics.update({
            "started_at": None, "last_loop_at": None, "last_triage_at": None,
            "last_triage": None, "processed": 0, "ok": 0, "retry": 0, "failed": 0,
            "timeouts": 0, "skipped": 0, "released": 0, "reclaimed": 0,
            "in_flight": 0, "buffered": 0, "last_error": None, "last_error_at": None,
            "loop_errors": 0,
        })
        _recent_done.clear()


_reset_metrics()


def _bump(key: str, n: int = 1) -> None:
    with _metrics_lock:
        _metrics[key] = _metrics.get(key, 0) + n


def _set_error(msg: str) -> None:
    with _metrics_lock:
        _metrics["last_error"] = (msg or "")[:300]
        _metrics["last_error_at"] = datetime.now().isoformat(timespec="seconds")


def enabled() -> bool:
    return PROBE_ENABLED


# ---------------------------------------------------------------- 口径
def _has_file():
    MI = em.MediaItem
    return and_(MI.file_path.isnot(None), MI.file_path != "")


def _shape_clause():
    """形状上「可以探测」：类型对、有文件、未删除、未被合并。"""
    MI = em.MediaItem
    return and_(MI.item_type.in_(PROBE_ITEM_TYPES), _has_file(),
                MI.deleted_at.is_(None), MI.merged_into_id.is_(None))


def _missing_info_clause():
    """缺媒体信息：没有 codec；或从没探过且没有时长（文件名解析出的 codec 不含时长）。

    「探过但仍没时长」不算缺：否则每次打开详情都会重探同一个文件。
    """
    MI = em.MediaItem
    no_codec = or_(MI.video_codec.is_(None), MI.video_codec == "")
    no_duration = or_(MI.duration_ticks.is_(None), MI.duration_ticks <= 0)
    return or_(no_codec, and_(no_duration, MI.last_probed_at.is_(None)))


def needs_probe_item(item) -> bool:
    """Python 侧同口径判定（按需入队 / 处理前复核）。"""
    if getattr(item, "item_type", None) not in PROBE_ITEM_TYPES:
        return False
    if not (getattr(item, "file_path", None) or "").strip():
        return False
    if getattr(item, "deleted_at", None) is not None or getattr(item, "merged_into_id", None):
        return False
    if not getattr(item, "video_codec", None):
        return True
    return (not (getattr(item, "duration_ticks", 0) or 0) > 0
            and getattr(item, "last_probed_at", None) is None)


def mount_key(file_path: str) -> str:
    """条目属于哪个「挂载」（并发/熔断的单位），返回一个路径前缀。"""
    fp = (file_path or "").strip()
    if fp.startswith("mount://"):
        mid = fp[len("mount://"):].split("/", 1)[0]
        return f"mount://{mid}/"
    if fp.startswith(("http://", "https://")):
        scheme, rest = fp.split("://", 1)
        return f"{scheme}://{rest.split('/', 1)[0]}/"
    parts = [p for p in fp.split("/") if p]
    if len(parts) >= 3:
        return "/" + "/".join(parts[:2]) + "/"
    if parts:
        return "/" + parts[0] + "/"
    return "/"


_remote_cache: Dict[str, bool] = {}
_REMOTE_FS = ("fuse", "nfs", "cifs", "smb", "sshfs", "rclone", "davfs", "9p")


def _proc_mounts() -> List[Tuple[str, str]]:
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as f:
            rows = [ln.split() for ln in f]
        return sorted(((r[1], r[2]) for r in rows if len(r) >= 3),
                      key=lambda x: len(x[0]), reverse=True)
    except OSError:
        return []


def is_remote_key(key: str) -> bool:
    """挂载是否远程（远程限流更狠）。只读 DB / /proc/mounts，不碰挂载本身。"""
    if key in _remote_cache:
        return _remote_cache[key]
    remote = True
    if key.startswith("mount://"):
        try:
            mid = int(key[len("mount://"):].strip("/"))
            from backend.database import SessionLocal
            db = SessionLocal()
            try:
                m = db.query(em.StorageMount.mount_type).filter(em.StorageMount.id == mid).first()
                remote = not (m is not None and (m[0] or "") == "local")
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            remote = True
    elif key.startswith(("http://", "https://")):
        remote = True
    else:
        remote = False
        for mnt, fstype in _proc_mounts():
            if key == mnt or key.startswith(mnt.rstrip("/") + "/"):
                remote = any(t in (fstype or "").lower() for t in _REMOTE_FS)
                break
    _remote_cache[key] = remote
    return remote


# ---------------------------------------------------------------- 熔断
class MountBreaker:
    """每个挂载一个熔断器：连续 N 次超时 → 打开 cooldown 秒（每次翻倍，封顶）。"""

    def __init__(self, threshold: int = None, cooldown: float = None,
                 max_cooldown: float = PROBE_BREAKER_MAX_COOLDOWN_SEC):
        self.threshold = threshold or PROBE_BREAKER_THRESHOLD
        self.base = cooldown or PROBE_BREAKER_COOLDOWN_SEC
        self.max_cooldown = max_cooldown
        self._lock = threading.Lock()
        self._state: Dict[str, dict] = {}

    def _get(self, key):
        return self._state.setdefault(key, {"fails": 0, "open_until": 0.0,
                                            "cooldown": self.base, "trips": 0})

    def allow(self, key: str) -> bool:
        with self._lock:
            st = self._state.get(key)
            return st is None or time.time() >= st["open_until"]

    def open_until(self, key: str) -> float:
        with self._lock:
            st = self._state.get(key)
            return st["open_until"] if st else 0.0

    def record_timeout(self, key: str) -> bool:
        """记一次超时；返回本次是否触发熔断。"""
        with self._lock:
            st = self._get(key)
            st["fails"] += 1
            if st["fails"] >= self.threshold and time.time() >= st["open_until"]:
                st["open_until"] = time.time() + st["cooldown"]
                st["trips"] += 1
                logger.warning("探测熔断：挂载 %s 连续 %d 次超时，%ds 内不再探测",
                               key, st["fails"], int(st["cooldown"]))
                st["cooldown"] = min(self.max_cooldown, st["cooldown"] * 2)
                return True
            return False

    def record_ok(self, key: str) -> None:
        with self._lock:
            st = self._state.get(key)
            if st:
                st["fails"] = 0
                st["cooldown"] = self.base

    def open_keys(self) -> List[str]:
        now = time.time()
        with self._lock:
            return [k for k, st in self._state.items() if st["open_until"] > now]

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            return {k: {"consecutive_timeouts": st["fails"], "trips": st["trips"],
                        "open_for_sec": max(0, int(st["open_until"] - now))}
                    for k, st in self._state.items() if st["fails"] or st["open_until"] > now}


breaker = MountBreaker()


# ---------------------------------------------------------------- 暂停开关（跨进程）
_pause_cache = {"value": False, "at": 0.0}


def is_paused(db=None, max_age: float = 10.0) -> bool:
    if time.monotonic() - _pause_cache["at"] < max_age and db is None:
        return _pause_cache["value"]
    from backend import models as base_models
    own = db is None
    if own:
        from backend.database import SessionLocal
        db = SessionLocal()
    try:
        row = db.query(base_models.SystemConfig.value).filter(
            base_models.SystemConfig.key == PAUSE_CONFIG_KEY).first()
        val = bool(row and (row[0] or "").strip() == "1")
        if own:
            db.rollback()
    except Exception:  # noqa: BLE001
        val = _pause_cache["value"]
    finally:
        if own:
            db.close()
    _pause_cache.update(value=val, at=time.monotonic())
    return val


def set_paused(db, paused: bool) -> bool:
    from backend import models as base_models
    row = db.query(base_models.SystemConfig).filter(
        base_models.SystemConfig.key == PAUSE_CONFIG_KEY).first()
    if row is None:
        row = base_models.SystemConfig(key=PAUSE_CONFIG_KEY, description="媒体信息探测 worker 暂停开关")
        db.add(row)
    row.value = "1" if paused else "0"
    db.commit()
    _pause_cache.update(value=bool(paused), at=time.monotonic())
    if not paused:
        _wake.set()
    return bool(paused)


# ---------------------------------------------------------------- 入队（按需）
def maybe_enqueue(db, item) -> bool:
    """详情页/播放触发点：缺媒体信息的电影/单集入队（或插队）。

    幂等、便宜：
    - 功能关闭 / 类型不对 / 不缺信息 / 无文件 → 跳过；
    - 正在 probing → 跳过；
    - 已在 pending 但优先级低于按需 → 提到 1000 并唤醒调度器（返回 True）；
    - 已达最大尝试次数（failed/degraded 不无限复活）→ 跳过。
    """
    try:
        if not PROBE_ENABLED:
            return False
        if not needs_probe_item(item):
            return False
        status = getattr(item, "probe_status", None)
        if status == "probing":
            return False
        prio = int(getattr(item, "probe_priority", 0) or 0)
        if status == "pending":
            if prio >= ONDEMAND_PRIORITY:
                return False
            item.probe_priority = ONDEMAND_PRIORITY
            item.probe_next_retry_at = None  # 用户在等：退避中的也立刻可抢
            db.commit()
            _wake.set()
            logger.info("按需探测插队 item=%s type=%s", item.id, item.item_type)
            return True
        if (getattr(item, "probe_attempts", 0) or 0) >= media_probe.PROBE_MAX_ATTEMPTS:
            return False
        item.probe_status = "pending"
        item.probe_priority = max(prio, ONDEMAND_PRIORITY)
        item.probe_next_retry_at = None
        db.commit()
        _wake.set()
        logger.info("按需探测入队 item=%s type=%s", item.id, item.item_type)
        return True
    except Exception as exc:  # noqa: BLE001 — 入队失败绝不能影响详情页/播放
        logger.warning("按需探测入队失败 item=%s: %s", getattr(item, "id", "?"), exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


# ---------------------------------------------------------------- 抢单 / 放回 / 回收
def _due_filter(now: datetime):
    """只抢「到重试时间」的。"""
    return or_(em.MediaItem.probe_next_retry_at.is_(None),
               em.MediaItem.probe_next_retry_at <= now)


def _like_escape(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _claim_rows(db, limit: int, library_id: Optional[int] = None,
                exclude_prefixes: Tuple[str, ...] = ()) -> List[Tuple[int, str]]:
    """原子抢一批，返回 ``[(id, file_path)]``；抢到的标 probing + 租约时刻。

    排序：优先级高的先（按需 1000 > 最近播放 800 > 预提取 500 > 新文件 100 > 0），
    同优先级新入库的先（id 倒序）。走 ``idx_item_probe (probe_status, probe_priority, id)``。
    """
    MI = em.MediaItem
    now = datetime.now()
    filters = [MI.probe_status == "pending", _due_filter(now), _shape_clause(),
               _missing_info_clause()]
    if library_id is not None:
        filters.append(MI.library_id == library_id)
    for p in exclude_prefixes:
        filters.append(~MI.file_path.like(_like_escape(p) + "%", escape="\\"))
    q = (db.query(MI.id, MI.file_path).filter(*filters)
         .order_by(MI.probe_priority.desc(), MI.id.desc()).limit(limit))
    try:
        if db.get_bind().dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True, of=MI)
        rows = q.all()
    except Exception:  # noqa: BLE001
        db.rollback()
        rows = (db.query(MI.id, MI.file_path).filter(*filters)
                .order_by(MI.probe_priority.desc(), MI.id.desc()).limit(limit).all())
    if not rows:
        # 只是 SELECT 也会开事务；不 rollback 会留下 idle in transaction 占连接
        db.rollback()
        return []
    ids = [r[0] for r in rows]
    stamp = datetime.now()
    updated = (db.query(MI)
               .filter(MI.id.in_(ids), MI.probe_status == "pending")
               .update({"probe_status": "probing", "probe_claimed_at": stamp},
                       synchronize_session=False))
    db.commit()
    if updated != len(ids):
        # 没有 FOR UPDATE 的方言上被别的进程抢走了一部分：只认租约时刻是我们的那些
        mine = {r[0] for r in db.query(MI.id).filter(
            MI.id.in_(ids), MI.probe_status == "probing", MI.probe_claimed_at == stamp).all()}
        db.rollback()
        rows = [r for r in rows if r[0] in mine]
    return [(r[0], r[1]) for r in rows]


def _claim_batch(db, limit: int, library_id: Optional[int] = None) -> List[int]:
    """兼容旧接口：只返回 id 列表。"""
    return [i for i, _ in _claim_rows(db, limit, library_id=library_id)]


def _release(ids: List[int], retry_at: Optional[datetime] = None, db=None) -> int:
    """把抢到但没处理的放回 pending（不计失败次数）。"""
    if not ids:
        return 0
    own = db is None
    if own:
        from backend.database import SessionLocal
        db = SessionLocal()
    try:
        n = (db.query(em.MediaItem)
             .filter(em.MediaItem.id.in_(list(ids)), em.MediaItem.probe_status == "probing")
             .update({"probe_status": "pending", "probe_claimed_at": None,
                      "probe_next_retry_at": retry_at}, synchronize_session=False))
        db.commit()
        _bump("released", n)
        return n
    except Exception as exc:  # noqa: BLE001
        logger.warning("探测放回 pending 失败: %s", exc)
        db.rollback()
        return 0
    finally:
        if own:
            db.close()


def reclaim_stale(db, ttl_sec: Optional[float] = PROBE_CLAIM_TTL_SEC) -> int:
    """租约过期的 probing → pending。``ttl_sec=None``：全部（启动时，单实例保证下安全）。

    没有租约时刻的 probing（老版本留下的）一律视为过期。
    """
    MI = em.MediaItem
    q = db.query(MI).filter(MI.probe_status == "probing")
    if ttl_sec is not None:
        cutoff = datetime.now() - timedelta(seconds=float(ttl_sec))
        q = q.filter(or_(MI.probe_claimed_at.is_(None), MI.probe_claimed_at < cutoff))
    n = q.update({"probe_status": "pending", "probe_claimed_at": None,
                  "probe_next_retry_at": None}, synchronize_session=False)
    db.commit()
    if n:
        _bump("reclaimed", n)
        logger.info("探测回收 %d 条过期抢单（probing → pending）", n)
    return n


def _recover_crashed(db) -> int:
    """兼容旧接口：启动时恢复崩溃残留（全部 probing → pending）。"""
    return reclaim_stale(db, ttl_sec=None)


# ---------------------------------------------------------------- 整理 / 预提取
def triage(db, chunk: int = TRIAGE_CHUNK, pause_sec: float = 0.0,
           interruptible: bool = False) -> dict:
    """把 probe_status 纠正成真实状态（幂等，按 id 分段，避免长事务锁表）。

    - pending/NULL 且形状不可探（季/剧集/无文件/已删/已合并/类型不在范围）→ skipped
    - pending/NULL 且已有完整信息 → done
    - NULL 且缺信息 → pending（优先级 ≥ 500，与旧预提取同口径）
    - 最近 30 天播放过、仍 pending 的 → 优先级 ≥ 800
    """
    MI = em.MediaItem
    stats = {"skipped": 0, "done": 0, "queued": 0, "boosted": 0}
    max_id = db.query(func.max(MI.id)).scalar() or 0
    db.rollback()
    shape = _shape_clause()
    missing = _missing_info_clause()
    lo = 0
    while lo <= max_id:
        if interruptible and _stop_event.is_set():
            break
        hi = lo + chunk
        rng = and_(MI.id >= lo, MI.id < hi)
        open_status = or_(MI.probe_status.is_(None), MI.probe_status == "pending")
        stats["skipped"] += (db.query(MI).filter(rng, open_status, ~shape)
                             .update({"probe_status": "skipped", "probe_claimed_at": None,
                                      "probe_next_retry_at": None},
                                     synchronize_session=False))
        stats["done"] += (db.query(MI).filter(rng, open_status, shape, ~missing)
                          .update({"probe_status": "done", "probe_claimed_at": None,
                                   "probe_next_retry_at": None},
                                  synchronize_session=False))
        stats["queued"] += (db.query(MI).filter(rng, MI.probe_status.is_(None), shape, missing)
                            .update({"probe_status": "pending",
                                     "probe_priority": PREPROBE_PRIORITY,
                                     "probe_next_retry_at": None},
                                    synchronize_session=False))
        db.commit()
        lo = hi
        if pause_sec:
            time.sleep(pause_sec)
    try:
        cutoff = datetime.now() - timedelta(days=RECENT_PLAY_DAYS)
        recent = (db.query(em.UserMediaData.item_id)
                  .filter(em.UserMediaData.last_played_at >= cutoff))
        stats["boosted"] = (db.query(MI)
                            .filter(MI.probe_status == "pending",
                                    or_(MI.probe_priority.is_(None),
                                        MI.probe_priority < RECENT_PLAY_PRIORITY),
                                    MI.id.in_(recent.scalar_subquery()))
                            .update({"probe_priority": RECENT_PLAY_PRIORITY},
                                    synchronize_session=False))
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 提权失败不影响整理
        logger.debug("最近播放提权失败: %s", exc)
        db.rollback()
    with _metrics_lock:
        _metrics["last_triage_at"] = datetime.now().isoformat(timespec="seconds")
        _metrics["last_triage"] = dict(stats)
    if any(stats.values()):
        logger.info("探测队列整理：skipped=%d done=%d 入队=%d 最近播放提权=%d",
                    stats["skipped"], stats["done"], stats["queued"], stats["boosted"])
    return stats


def preprobe_sweep(db, limit: int = PREPROBE_SWEEP_LIMIT) -> int:
    """预提取扫描（兼容接口）：probe_status 不在队列也不是终态、且缺信息的条目入队。

    注意 NULL 也要扫（NOT IN 对 NULL 返回 unknown 会漏掉）。
    """
    MI = em.MediaItem
    not_queued = or_(MI.probe_status.is_(None),
                     MI.probe_status.notin_(QUEUE_STATUSES + TERMINAL_STATUSES))
    ids = [r[0] for r in db.query(MI.id)
           .filter(_shape_clause(), _missing_info_clause(), not_queued)
           .order_by(MI.id.desc()).limit(limit).all()]
    if ids:
        (db.query(MI).filter(MI.id.in_(ids))
         .update({"probe_status": "pending", "probe_priority": PREPROBE_PRIORITY,
                  "probe_next_retry_at": None}, synchronize_session=False))
        db.commit()
        logger.info("预提取扫描入队 %d 条（缺媒体信息）", len(ids))
    else:
        db.rollback()
    return len(ids)


def _run_triage_once() -> None:
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        triage(db, pause_sec=0.05, interruptible=True)
        preprobe_sweep(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("探测队列整理失败: %s", exc)
        _set_error(f"整理失败: {exc}")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def _preprobe_loop() -> None:
    """整理/预提取定时器：启动先跑一轮，之后按间隔重复。"""
    from backend.emby_server import worker_registry as _wr
    logger.info("探测队列整理定时器启动（间隔 %gs）", PREPROBE_INTERVAL_SEC)
    _run_triage_once()
    _wake.set()
    while not _stop_event.is_set():
        _wr.heartbeat("probe_preextract")
        if _stop_event.wait(PREPROBE_INTERVAL_SEC):
            break
        _run_triage_once()


# ---------------------------------------------------------------- 单条目处理
def _resolve_detached(item_id: int):
    """在独立线程里解析探测地址（自带 session，可被放弃）。"""
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
        if item is None:
            return None
        return media_probe.resolve_probe_input(db, item)
    finally:
        try:
            db.rollback()
        finally:
            db.close()


def _probe_detached(path, headers, size, container, budget):
    """在独立线程里跑 probe_metadata；所有子进程共享 budget 秒的总预算。"""
    before = proc_util.timeout_count()
    with proc_util.deadline(budget):
        probe = media_probe.probe_metadata(path, headers, size=size, container=container)
    return probe, proc_util.timeout_count() - before


def _finish(item_id: int, outcome: str, reason: str = "", probe: Optional[dict] = None) -> str:
    """在新 session 里落结果。outcome: ok / retry / failed。"""
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
        if item is None:
            db.rollback()
            return "skip"
        if outcome == "ok":
            media_probe.write_back(db, item, probe or {})
            try:
                media_probe.persist_lib.serialize(db, item)
            except Exception as exc:  # noqa: BLE001
                logger.debug("媒体信息落盘异常 item=%s: %s", item_id, exc)
            return "ok"
        if outcome == "failed":
            media_probe.mark_failed(db, item, reason)
            return "failed"
        media_probe.mark_retry(db, item, reason)
        return "failed" if item.probe_status == "failed" else "retry"
    finally:
        db.close()


def process_item(item_id: int, key: Optional[str] = None) -> str:
    """处理一条（worker 线程内跑）。返回 ok / retry / failed / skip / timeout。

    期间**不持有** DB 连接：解析和探测都在可放弃的守护线程里跑，有硬上限。
    """
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
        if item is None or getattr(item, "probe_status", None) != "probing":
            db.rollback()
            return "skip"
        key = key or mount_key(item.file_path or "")
        # 抢到之后信息可能已被别的路（NFO/enrich/扫描）补上
        if not needs_probe_item(item):
            item.probe_status = "done"
            item.probe_attempts = 0
            item.probe_next_retry_at = None
            item.probe_claimed_at = None
            db.commit()
            return "skip"
        # 先试 JSON 恢复（本地盘，零探测）
        try:
            if media_probe.persist_lib.deserialize(db, item):
                return "ok"
        except Exception as exc:  # noqa: BLE001
            logger.debug("媒体信息 JSON 恢复异常 item=%s: %s", item_id, exc)
            db.rollback()
        db.rollback()
    finally:
        db.close()

    # 1) 解析地址（挂载 API / 本机 FUSE stat）
    try:
        resolved = proc_util.call_with_timeout(_resolve_detached, PROBE_RESOLVE_TIMEOUT_SEC, item_id)
    except proc_util.CallTimeout:
        breaker.record_timeout(key)
        _bump("timeouts")
        _finish(item_id, "retry", f"解析探测地址超时（>{PROBE_RESOLVE_TIMEOUT_SEC:g}s，挂载无响应）")
        return "timeout"
    except Exception as exc:  # noqa: BLE001
        return _finish(item_id, "retry", f"解析探测地址异常: {exc}")
    if not resolved:
        return _finish(item_id, "retry", "无法解析探测地址")

    # 2) 探测（所有子进程共享总预算，超时整组 SIGKILL）
    path, headers, size, container = resolved
    budget = PROBE_ITEM_TIMEOUT_SEC
    try:
        probe, n_timeouts = proc_util.call_with_timeout(
            _probe_detached, budget + proc_util.KILL_GRACE_SEC + 3,
            path, headers, size, container, budget)
    except proc_util.CallTimeout:
        breaker.record_timeout(key)
        _bump("timeouts")
        _finish(item_id, "retry", f"探测超时（>{budget:g}s）")
        return "timeout"
    except Exception as exc:  # noqa: BLE001
        return _finish(item_id, "retry", f"ffprobe 异常: {exc}")

    http_code = (probe or {}).get("_http_code")
    if http_code in media_probe.NO_RETRY_HTTP_CODES:
        breaker.record_ok(key)  # 端点有回应，挂载是活的
        return _finish(item_id, "failed", f"远端返回 HTTP {http_code}，地址无效")
    if media_probe._has_useful_data(probe):
        breaker.record_ok(key)
        return _finish(item_id, "ok", probe=probe)
    if n_timeouts:
        breaker.record_timeout(key)
        _bump("timeouts")
        _finish(item_id, "retry", "ffprobe 超时（挂载或端点无响应）")
        return "timeout"
    breaker.record_ok(key)
    return _finish(item_id, "retry",
                   (probe or {}).get("_error_detail") or "探测未返回有效媒体信息")


def _process_one(item_id: int) -> None:
    """兼容旧接口（测试/脚本）：处理一条，异常不外抛。"""
    try:
        process_item(item_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("按需探测处理异常 item=%s: %s", item_id, exc)


# ---------------------------------------------------------------- 调度器
def _record_outcome(outcome: str, err: str = "") -> None:
    with _metrics_lock:
        _metrics["processed"] += 1
        if outcome in ("ok", "retry", "failed", "skip"):
            _metrics[{"skip": "skipped"}.get(outcome, outcome)] += 1
        elif outcome == "timeout":
            _metrics["retry"] += 1
        _recent_done.append(time.monotonic())
    if err:
        _set_error(err)


def _rate_per_min(window: float = 600.0) -> float:
    now = time.monotonic()
    with _metrics_lock:
        n = sum(1 for t in _recent_done if now - t <= window)
        started = _metrics.get("_started_mono") or now
    span = min(window, max(1.0, now - started))
    return round(n * 60.0 / span, 2)


def runtime_status() -> dict:
    """本进程内调度器的运行时状态（不查 DB）。"""
    t = _dispatcher_thread
    with _metrics_lock:
        m = {k: v for k, v in _metrics.items() if not k.startswith("_")}
    m.update({
        "running": bool(t is not None and t.is_alive()),
        "paused": _pause_cache["value"],
        "rate_per_min": _rate_per_min(),
        "breakers": breaker.snapshot(),
        "abandoned": proc_util.abandoned_counts(),
        "config": {
            "workers": PROBE_WORKERS, "remote_concurrency": PROBE_REMOTE_CONCURRENCY,
            "local_concurrency": PROBE_LOCAL_CONCURRENCY,
            "min_interval_sec": PROBE_MIN_INTERVAL_SEC,
            "item_timeout_sec": PROBE_ITEM_TIMEOUT_SEC,
            "resolve_timeout_sec": PROBE_RESOLVE_TIMEOUT_SEC,
            "claim_ttl_sec": PROBE_CLAIM_TTL_SEC, "max_attempts": media_probe.PROBE_MAX_ATTEMPTS,
            "item_types": list(PROBE_ITEM_TYPES),
        },
        "reported_at": datetime.now().isoformat(timespec="seconds"),
    })
    return m


def _publish_status() -> None:
    try:
        from backend.database import cache
        cache.set(STATUS_CACHE_KEY, json.dumps(runtime_status(), ensure_ascii=False, default=str),
                  ttl=180)
    except Exception:  # noqa: BLE001
        pass


def _dispatcher_loop() -> None:
    """调度器：回收 → 抢单（只抢有空槽的量）→ 按挂载限流提交。循环体异常不退出。"""
    from backend.database import SessionLocal
    from backend.emby_server import worker_registry as _wr
    logger.info("探测调度器启动（总并发 %d，远程每挂载 %d，本机每挂载 %d，单条目上限 %gs）",
                PROBE_WORKERS, PROBE_REMOTE_CONCURRENCY, PROBE_LOCAL_CONCURRENCY,
                PROBE_ITEM_TIMEOUT_SEC)
    pool = ThreadPoolExecutor(max_workers=PROBE_WORKERS, thread_name_prefix="media-probe")
    lock = threading.Lock()
    in_flight = {"total": 0}
    per_key: Dict[str, int] = {}
    buffer: deque = deque()  # (id, key, remote, claimed_mono)
    last_submit = 0.0
    last_reclaim = time.monotonic()
    last_publish = 0.0

    def _done_cb(key):
        def _cb(fut):
            err = ""
            try:
                outcome = fut.result()
            except Exception as exc:  # noqa: BLE001
                outcome, err = "retry", f"处理异常: {exc}"
            if outcome == "timeout":
                err = f"挂载 {key} 探测超时"
            _record_outcome(outcome, err)
            with lock:
                in_flight["total"] = max(0, in_flight["total"] - 1)
                per_key[key] = max(0, per_key.get(key, 1) - 1)
            _wake.set()
        return _cb

    def _run(item_id, key):
        outcome = process_item(item_id, key)
        if outcome in ("ok", "retry", "failed", "timeout") and PROBE_WORKERS <= 1 \
                and PROBE_COOLDOWN_SEC > 0:
            _stop_event.wait(PROBE_COOLDOWN_SEC)
        return outcome

    try:
        while not _stop_event.is_set():
            _wake.clear()
            claimed_now = submitted_now = 0
            try:
                _wr.heartbeat("probe_dispatcher")
                now_m = time.monotonic()
                with _metrics_lock:
                    _metrics["last_loop_at"] = datetime.now().isoformat(timespec="seconds")
                if now_m - last_publish > 15:
                    last_publish = now_m
                    _publish_status()

                if is_paused():
                    if buffer:
                        _release([b[0] for b in buffer])
                        buffer.clear()
                    _stop_event.wait(PROBE_IDLE_SLEEP_SEC)
                    continue

                if now_m - last_reclaim > PROBE_RECLAIM_EVERY_SEC:
                    last_reclaim = now_m
                    db = SessionLocal()
                    try:
                        reclaim_stale(db)
                    finally:
                        db.close()

                with lock:
                    free = PROBE_WORKERS - in_flight["total"]
                want = max(0, PROBE_WORKERS * PROBE_BACKLOG_FACTOR - len(buffer))
                if free > 0 and want > 0:
                    db = SessionLocal()
                    try:
                        rows = _claim_rows(db, min(PROBE_CLAIM_BATCH, want),
                                           exclude_prefixes=tuple(breaker.open_keys()))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("探测抢单失败: %s", exc)
                        _set_error(f"抢单失败: {exc}")
                        db.rollback()
                        rows = []
                    finally:
                        db.close()
                    for item_id, fp in rows:
                        key = mount_key(fp)
                        buffer.append((item_id, key, is_remote_key(key), time.monotonic()))
                    claimed_now = len(rows)

                # 提交：总并发 + 每挂载并发 + 熔断
                to_release: List[int] = []
                breaker_release: Dict[float, List[int]] = {}
                keep: deque = deque()
                while buffer:
                    item_id, key, remote, ts = buffer.popleft()
                    if not breaker.allow(key):
                        until = breaker.open_until(key)
                        breaker_release.setdefault(until, []).append(item_id)
                        continue
                    limit = PROBE_REMOTE_CONCURRENCY if remote else PROBE_LOCAL_CONCURRENCY
                    with lock:
                        busy_total = in_flight["total"] >= PROBE_WORKERS
                        busy_key = per_key.get(key, 0) >= limit
                    if busy_total or busy_key:
                        if time.monotonic() - ts > PROBE_BUFFER_MAX_SEC:
                            to_release.append(item_id)
                        else:
                            keep.append((item_id, key, remote, ts))
                        continue
                    gap = PROBE_MIN_INTERVAL_SEC - (time.monotonic() - last_submit)
                    if gap > 0 and _stop_event.wait(gap):
                        keep.append((item_id, key, remote, ts))
                        break
                    last_submit = time.monotonic()
                    with lock:
                        in_flight["total"] += 1
                        per_key[key] = per_key.get(key, 0) + 1
                    try:
                        fut = pool.submit(_run, item_id, key)
                    except RuntimeError:
                        with lock:
                            in_flight["total"] -= 1
                            per_key[key] -= 1
                        keep.append((item_id, key, remote, ts))
                        break
                    fut.add_done_callback(_done_cb(key))
                    submitted_now += 1
                keep.extend(buffer)
                buffer.clear()
                buffer.extend(keep)
                if to_release:
                    _release(to_release)
                for until, ids in breaker_release.items():
                    _release(ids, retry_at=datetime.fromtimestamp(until))
                with _metrics_lock:
                    _metrics["in_flight"] = in_flight["total"]
                    _metrics["buffered"] = len(buffer)
            except Exception as exc:  # noqa: BLE001 — 调度器永不因单轮异常退出
                _bump("loop_errors")
                _set_error(f"调度循环异常: {exc}")
                logger.exception("探测调度循环异常（继续运行）")
                _stop_event.wait(PROBE_IDLE_SLEEP_SEC)
                continue
            if claimed_now == 0 and submitted_now == 0:
                _wake.wait(PROBE_IDLE_SLEEP_SEC if not buffer else 0.5)
            elif submitted_now == 0:
                _wake.wait(0.5)
    finally:
        if buffer:
            _release([b[0] for b in buffer])
        pool.shutdown(wait=False)
        logger.info("探测调度器已停止")


# ---------------------------------------------------------------- 状态 / 运维
def status_snapshot(db=None) -> dict:
    """进度：各状态计数 + 重试中 + 运行时（速率/错误/熔断）+ ETA。供管理接口/health。"""
    own = db is None
    if own:
        from backend.database import SessionLocal
        db = SessionLocal()
    try:
        MI = em.MediaItem
        rows = (db.query(MI.probe_status, func.count(MI.id))
                .filter(MI.item_type.in_(PROBE_ITEM_TYPES))
                .group_by(MI.probe_status).all())
        counts = {(s or "unknown"): int(c) for s, c in rows}
        now = datetime.now()
        retrying = db.query(func.count(MI.id)).filter(
            MI.probe_status == "pending", MI.probe_next_retry_at.isnot(None),
            MI.probe_next_retry_at > now).scalar() or 0
        stale_cut = now - timedelta(seconds=PROBE_CLAIM_TTL_SEC)
        stale = db.query(func.count(MI.id)).filter(
            MI.probe_status == "probing",
            or_(MI.probe_claimed_at.is_(None), MI.probe_claimed_at < stale_cut)).scalar() or 0
        errs = (db.query(MI.probe_last_error, func.count(MI.id))
                .filter(MI.probe_last_error.isnot(None),
                        MI.probe_status.in_(("pending", "failed")))
                .group_by(MI.probe_last_error)
                .order_by(func.count(MI.id).desc()).limit(5).all())
        db.rollback()
    finally:
        if own:
            db.close()
    rt = None
    t = _dispatcher_thread
    if t is not None and t.is_alive():
        rt = runtime_status()
        rt["source"] = "local"
    else:
        try:
            from backend.database import cache
            raw = cache.get(STATUS_CACHE_KEY)
            if raw:
                rt = json.loads(raw)
                rt["source"] = "worker"
        except Exception:  # noqa: BLE001
            rt = None
    pending = counts.get("pending", 0)
    rate = (rt or {}).get("rate_per_min") or 0
    eta_hours = round(pending / rate / 60.0, 2) if rate else None
    return {
        "enabled": PROBE_ENABLED,
        "paused": is_paused(),
        "counts": counts,
        "pending_ready": max(0, pending - int(retrying)),
        "retrying": int(retrying),
        "stale_probing": int(stale),
        "top_errors": [{"error": e, "count": int(c)} for e, c in errs],
        "runtime": rt,
        "eta_hours": eta_hours,
    }


def reset(db, scope: str = "stuck") -> dict:
    """运维重置。scope：

    - ``stuck``：所有 probing → pending（worker 卡死/崩溃后的残留）；
    - ``failed``：failed → pending，attempts 清零（例如挂载修好了）；
    - ``retrying``：退避中的 pending 立即可重试；
    - ``all``：以上全部。
    """
    MI = em.MediaItem
    out = {"stuck": 0, "failed": 0, "retrying": 0}
    if scope in ("stuck", "all"):
        out["stuck"] = reclaim_stale(db, ttl_sec=None)
    if scope in ("failed", "all"):
        out["failed"] = (db.query(MI).filter(MI.probe_status == "failed", _shape_clause(),
                                             _missing_info_clause())
                         .update({"probe_status": "pending", "probe_attempts": 0,
                                  "probe_next_retry_at": None, "probe_last_error": None},
                                 synchronize_session=False))
        db.commit()
    if scope in ("retrying", "all"):
        out["retrying"] = (db.query(MI).filter(MI.probe_status == "pending",
                                               MI.probe_next_retry_at.isnot(None))
                           .update({"probe_next_retry_at": None}, synchronize_session=False))
        db.commit()
    if scope not in ("stuck", "failed", "retrying", "all"):
        raise ValueError(f"未知 scope: {scope}")
    _wake.set()
    logger.info("探测队列重置 scope=%s → %s", scope, out)
    return out


# ---------------------------------------------------------------- 启停
def _spawn_dispatcher() -> None:
    global _dispatcher_thread
    from backend.emby_server import worker_registry as _wr
    _dispatcher_thread = threading.Thread(
        target=_dispatcher_loop, name="media-probe-dispatcher", daemon=True)
    _dispatcher_thread.start()
    _wr.register("probe_dispatcher", _dispatcher_thread, restart=_restart_dispatcher)


def _spawn_preprobe() -> None:
    global _preprobe_thread
    from backend.emby_server import worker_registry as _wr
    _preprobe_thread = threading.Thread(target=_preprobe_loop, name="media-preprobe", daemon=True)
    _preprobe_thread.start()
    _wr.register("probe_preextract", _preprobe_thread, restart=_restart_preprobe)


def _restart_dispatcher() -> None:
    with _start_lock:
        if _stop_event.is_set() or (_dispatcher_thread is not None and _dispatcher_thread.is_alive()):
            return
        _spawn_dispatcher()


def _restart_preprobe() -> None:
    with _start_lock:
        if _stop_event.is_set() or (_preprobe_thread is not None and _preprobe_thread.is_alive()):
            return
        _spawn_preprobe()


def start() -> bool:
    """启动探测 worker（幂等）。单体（main.py lifespan）与 worker 角色共用这一个入口。"""
    if not PROBE_ENABLED:
        logger.info("媒体信息探测已禁用（PROBE_ONDEMAND_ENABLED=0）")
        return False
    with _start_lock:
        if _dispatcher_thread is not None and _dispatcher_thread.is_alive():
            return True
        from backend.database import SessionLocal
        db = SessionLocal()
        try:
            # 一次性纠正：上一个进程留下的 probing 全部放回（单实例：worker 有 Redis 锁、
            # 单体只有一个进程）。老版本泄漏的 probing 行也在这里回来。
            n = reclaim_stale(db, ttl_sec=None)
            if n:
                logger.info("探测启动：%d 条残留 probing 已放回 pending", n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("探测启动回收失败: %s", exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()
        _stop_event.clear()
        _reset_metrics()
        with _metrics_lock:
            _metrics["started_at"] = datetime.now().isoformat(timespec="seconds")
            _metrics["_started_mono"] = time.monotonic()
        _spawn_dispatcher()
        if PREPROBE_ENABLED and (_preprobe_thread is None or not _preprobe_thread.is_alive()):
            _spawn_preprobe()
        from backend.emby_server import worker_registry as _wr
        _wr.ensure_supervisor()
        logger.info("媒体信息探测 worker 已启动")
        return True


def stop(timeout: float = 5.0) -> None:
    """停止 worker（测试 / 优雅退出）。"""
    _stop_event.set()
    _wake.set()
    for t in (_dispatcher_thread, _preprobe_thread):
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
    from backend.emby_server import worker_registry as _wr
    _wr.unregister("probe_dispatcher")
    _wr.unregister("probe_preextract")
