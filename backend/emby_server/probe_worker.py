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
from backend.emby_server.scanner import needs_probe, probe_metadata, safe_probe_int

logger = logging.getLogger(__name__)

# ---- 403 熔断器 ----
# 连续 N 个 403（配额耗尽）就暂停 worker，避免空跑烧配额
# 状态存 Redis（持久化，重启不丢）；三个函数语义分离，杜绝"只读检查误清零"
_QUOTA_BREAKER_THRESHOLD = 10
_QUOTA_BREAKER_REDIS_KEY = "aetrix:quota_breaker:state"
#: 熔断后的休眠时长。原为 300s（5 分钟）——而熔断状态本身靠 Redis 的 24h TTL 过期，
#: 两者口径不一致的结果是：worker 每天醒来 288 次，每次发现「还熔着」就 continue，
#: 什么请求都不发，只是刷日志。改成 24h 与 TTL 对齐，醒来时状态多半已自然解除。
_QUOTA_BREAKER_BACKOFF_SEC = 86400  # 熔断后休眠 24 小时
_quota_lock = threading.Lock()
# Redis 不可用时的内存降级状态（进程内，重启丢失；Redis 恢复后以 Redis 为准）
_quota_mem_state = {"consecutive_403": 0, "tripped": False, "tripped_at": None}


def _quota_redis():
    """拿 Redis 客户端（不可用返回 None，降级为内存模式）"""
    try:
        from backend.database import redis_client
        return redis_client
    except Exception:
        return None


def _quota_state_get():
    """读熔断状态，返回 (consecutive_403, tripped, tripped_at)。
    Redis 可用时从 Redis 读；不可用时用进程内存（降级模式）。"""
    r = _quota_redis()
    if r is None:
        s = _quota_mem_state
        return (s["consecutive_403"], s["tripped"], s["tripped_at"])
    try:
        import json
        raw = r.get(_QUOTA_BREAKER_REDIS_KEY)
        if not raw:
            return (0, False, None)
        data = json.loads(raw)
        return (
            int(data.get("consecutive_403", 0)),
            bool(data.get("tripped", False)),
            data.get("tripped_at"),
        )
    except Exception:
        return (0, False, None)


def _quota_state_set(consecutive_403: int, tripped: bool, tripped_at=None):
    """写熔断状态。Redis 可用时持久化；不可用时写进程内存（降级模式）。"""
    import time as _time
    r = _quota_redis()
    if r is None:
        _quota_mem_state["consecutive_403"] = int(consecutive_403)
        _quota_mem_state["tripped"] = bool(tripped)
        _quota_mem_state["tripped_at"] = tripped_at or (_time.time() if tripped else None)
        return
    try:
        import json, time
        data = {
            "consecutive_403": int(consecutive_403),
            "tripped": bool(tripped),
            "tripped_at": tripped_at or (time.time() if tripped else None),
            "updated_at": time.time(),
        }
        # 24 小时过期是兜底：防止手动恢复被遗忘导致永久熔断。
        # 主要恢复方式是在管理后台手动重置（确认配额已恢复后）。
        r.setex(_QUOTA_BREAKER_REDIS_KEY, 86400, json.dumps(data))
    except Exception as e:
        logger.warning(f"[probe] 熔断状态持久化失败：{e}")


def breaker_is_tripped() -> bool:
    """纯只读：熔断器是否已触发（不修改任何状态）"""
    _, tripped, _ = _quota_state_get()
    return tripped


def breaker_record_success() -> None:
    """成功时调用：重置连续 403 计数。
    注意：熔断已触发时，单个成功不会自动解除（需在管理后台手动恢复，
    或等 24 小时兜底过期）。这是为了防止配额抖动导致反复触发/解除。"""
    with _quota_lock:
        consecutive, tripped, tripped_at = _quota_state_get()
        if consecutive > 0 and not tripped:
            _quota_state_set(0, False)


def breaker_record_quota_error() -> bool:
    """遇到 403 配额错误时调用：计数+1，返回 True 表示刚刚触发熔断"""
    with _quota_lock:
        consecutive, tripped, tripped_at = _quota_state_get()
        if tripped:
            return False  # 已经熔断了，不重复触发
        consecutive += 1
        if consecutive >= _QUOTA_BREAKER_THRESHOLD:
            import time
            _quota_state_set(consecutive, True, time.time())
            logger.error(
                "[probe] 熔断器触发：连续 %d 个 HTTP 403（远端配额耗尽），"
                "worker 已暂停退避。配额恢复后请在管理后台手动恢复；"
                "若忘记手动恢复，24 小时后自动解除（兜底）。",
                consecutive,
            )
            return True
        else:
            _quota_state_set(consecutive, False)
            return False


def quota_breaker_reset() -> None:
    """手动重置熔断器（配额恢复后调用）"""
    with _quota_lock:
        _quota_state_set(0, False)
    logger.info("[probe] 熔断器已手动重置，worker 恢复")


def quota_breaker_status() -> dict:
    """查询熔断器状态（供管理后台展示）"""
    consecutive, tripped, tripped_at = _quota_state_get()
    return {
        "tripped": tripped,
        "consecutive_403": consecutive,
        "threshold": _QUOTA_BREAKER_THRESHOLD,
        "tripped_at": tripped_at,
        "backoff_sec": _QUOTA_BREAKER_BACKOFF_SEC,
    }


# 向后兼容：旧的 _quota_breaker_check 保留但标记废弃
def _quota_breaker_check(is_403: bool) -> bool:
    """已废弃：用 breaker_is_tripped / breaker_record_* 代替"""
    import warnings
    warnings.warn("_quota_breaker_check 已废弃", DeprecationWarning, stacklevel=2)
    if is_403:
        breaker_record_quota_error()
    else:
        breaker_record_success()
    return breaker_is_tripped()

# ---- 可调参数（环境变量） ----
# 2026-10 调低：探测会和扫描 / 追新一起打向同一个 rclone 端点，8 个线程 + 4/s 的
# 启动速率叠加上去就是请求风暴的主要来源之一（生产 24 小时 5.2 万条报错）。降一半后
# 积压消化得慢一些，但不再把 rclone 打死；两者都能用环境变量调回去。
PROBE_WORKERS = max(1, min(32, int(os.getenv("PROBE_WORKERS", "4") or 4)))
PROBE_BATCH = max(10, int(os.getenv("PROBE_BATCH", "200") or 200))
PROBE_RATE_PER_SEC = max(1, int(os.getenv("PROBE_RATE_PER_SEC", "2") or 2))
PROBE_MAX_ATTEMPTS = max(1, int(os.getenv("PROBE_MAX_ATTEMPTS", "5") or 5))
PROBE_IDLE_POLL_SEC = max(5, int(os.getenv("PROBE_IDLE_POLL_SEC", "30") or 30))
# 轮间休息：只要还有积压，每轮跑完就立刻再抢下一批（实测 200 条/30s），
# 4 核机器会被 ffprobe + rclone 打满、swap 吃到 1.2G，用户侧浏览直接卡成转圈。
# 有积压也要让出资源，默认歇 10s；调 0 可恢复旧行为。
PROBE_ROUND_PAUSE_SEC = max(0, int(os.getenv("PROBE_ROUND_PAUSE_SEC", "10") or 10))

# 探测结果里的数值字段统一走 scanner.safe_probe_int：ffprobe/MediaInfo 在远程流上
# 偶发给出 None、负数或超大值，直接落库会让整条 commit 失败、把这一轮全部打回。
_safe_int = safe_probe_int

BOOST_PRIORITY = 1000   # 按需插队的优先级（最高）
NEW_FILE_PRIORITY = 100  # 新入库文件
RETRY_PRIORITY = 10     # 重试中的老文件：低于新文件，让新片先拿到元数据
DEFAULT_PRIORITY = 0    # 从未探 / 其它

# 逐流字段：ffprobe 能拿到多少就存多少，客户端「媒体信息」页直接显示这些
_STREAM_COLS = {
    "stream_index", "stream_type", "codec", "language", "display_title", "title",
    "channels", "bit_rate", "frame_rate", "video_range", "profile", "level",
    "pixel_format", "aspect_ratio", "bit_depth", "sample_rate",
    "channel_layout", "sample_format",
}


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

    # background 模式：扫描器延迟探测，必须跑 worker。
    # layered+inline：enrich_worker 会把远程文件的探测置为 pending，也需要 worker 消费，
    # 否则 pending 任务成孤儿，元数据永远填不上（P0-5）。
    return bool(_sc.PROBE_BACKGROUND or _sc.SCAN_LAYERED)


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


#: ``retry_failed`` 分块更新的块大小（远低于任何 SQLite/PostgreSQL 的变量上限）
_RETRY_CHUNK = 500


def retry_failed(db, limit: int = 5000) -> int:
    """把 ``failed`` 的探测条目捞回队列，返回拈回数（后台「重试失败探测」用）

    为什么需要它：v2.42.14 之前「ffprobe 跑完但没时长」被判成失败，
    生产里已经堆了几万条这类 ``failed``（实测 2.6 万，93% 在 MoviePilot 目录）。
    修正分类只阻止**新增**，存量行还得有人拉回来。

    只拈 ``failed``（真正的终态失败），不动 done / degraded / probed_no_duration
    —— 后三者本来就是「已探完」的状态，重探它们只是白烧 ffprobe 与云盘配额。
    按 id 升序取，避免每次都从同一批开始。
    """
    rows = (db.query(em.MediaItem.id)
            .filter(em.MediaItem.probe_status == "failed")
            .order_by(em.MediaItem.id)
            .limit(max(1, int(limit)))
            .all())
    ids = [r[0] for r in rows]
    if not ids:
        return 0
    # 分块更新：``id IN (...)`` 会把每个 id 变成一个绑定变量，SQLite 老版本上限 999，
    # PostgreSQL 也有自己的上限。批量本来就可能捞回几千条（生产实测 2.6 万），
    # 不分块就会在某些部署上直接报「too many SQL variables」。
    for start in range(0, len(ids), _RETRY_CHUNK):
        db.query(em.MediaItem).filter(
            em.MediaItem.id.in_(ids[start:start + _RETRY_CHUNK])).update(
            {"probe_status": "pending", "probe_attempts": 0, "probe_next_retry_at": None},
            synchronize_session=False,
        )
    db.commit()
    logger.info("重试失败探测：%d 条重新入队", len(ids))
    return len(ids)


def boost_probe(db, item) -> bool:
    """按需插队：优先级提到最高、清除退避，下一轮 worker 即取。

    已探测完（done）的不需要排队，返回 False；其余返回 True。

    **终态但不是 done 的（failed / degraded / probed_no_duration）一律重新入队**：
    用户点播放就是「我想知道它到底能不能放」，此时再探一次是唯一能回答问题的办法。
    只改优先级不改状态的话，这些条目永远不会被 ``_claim_batch`` 取到（它只取 pending），
    「重新探测」按钮就成了摆设。
    """
    if (getattr(item, "probe_status", None) or "") == "done":
        return False
    item.probe_priority = BOOST_PRIORITY
    item.probe_next_retry_at = None
    if item.probe_status in ("failed", "degraded", STATUS_NO_DURATION):
        # 之前放弃 / 已降级的也给一次机会（计数清零）
        item.probe_status = "pending"
        item.probe_attempts = 0
    db.commit()
    return True


#: 单条重试的退避上限（24 小时）。
#:
#: 原上限是 1 小时。配额耗尽要 24 小时才恢复，按小时重试意味着每个文件在配额
#: 恢复前会白白打 24 次请求——正是“配额受限还在反复探测”的来源。
MAX_BACKOFF_SECONDS = 86400

#: 配额耗尽的退避：**直接**用 24 小时，不走指数。
#:
#: 指数退避对配额问题是错的——它假设“等久一点可能就好了”，而配额是 24 小时
#: 整点恢复的阶梯函数。与其 60s/120s/240s 地试 11 次，不如直接等满 24 小时。
QUOTA_BACKOFF_SECONDS = 86400


def _backoff_seconds(attempts: int) -> int:
    # 60s, 120s, 240s, 480s, … 上限 24 小时
    return min(MAX_BACKOFF_SECONDS, 60 * (2 ** max(0, attempts - 1)))


# ---- 失败分类 ----
#
# “重试”只对重试有用的事。文件已经被删了、或格式根本不支持，再试一万次也是
# 同一个结果，而每一次重试都要占用 worker 名额与云盘配额，把真正能探到的文件
# 挤到后面去（见 ``_claim_batch`` 的优先级排序）。

KIND_PERMANENT = "permanent"   # 重试无意义：直接 failed
KIND_TRANSIENT = "transient"   # 重试有意义：退避后重来

#: 确定性的永久失败：**只认「文件真的不在了」**。
#:
#: 原来还包含 400 / 405 / 415 / 416（请求不合法 / 方法或媒体类型不支持）。实测这些
#: 码在云盘与反代后面绝大多数不是「文件坏了」：签名 URL 过期、网关回了个 415、
#: Range 请求被中间层改写，都会落到这几码。把它们当永久失败 = 把**还在线播放的**
#: 条目判死，用户端直接变成「网络错误或者当前媒体库不存在该项目」。
#:
#: 它们现在归临时：走指数退避，最多试 PROBE_MAX_ATTEMPTS 次。真的不支持的格式
#: 最终还是 failed（只是多花几次名额），但不会第一次就被判死。
#:
#: 不含 401（凭据失效）：那不是文件坏了，而是部署配置坏了——管理员改完凭据
#: 文件就能探，不该被永久判死（后台手动「重新探测」仍可拉起来，但没必要让它
#: 自动占着 24 小时的重试位）。
#:
#: 403 不在这里：ffprobe 把配额耗尽也报成 403，scanner 统一归成 ``quota``，
#: 由配额熔断器处理，绝不能当成永久失败。
PERMANENT_ERRORS = frozenset({
    "not_found",
    "http_404", "http_410",   # 没了 / 已被彻底移除
})

#: ffprobe 跑成功了、只是没给出时长：这是**结果**，不是失败。
#:
#: 播放器不靠时长也能播（进度条按字节估算即可），所以这种条目必须留在可播状态里，
#: 不能进重试——否则同一批文件会反复占满 worker 名额（实测 2.6 万条 MoviePilot 目录
#: 的文件全是这一种，重试 5 轮后集体 failed，用户端报「不存在该项目」）。
STATUS_NO_DURATION = "probed_no_duration"


def _classify_failure(error: Optional[str]) -> str:
    """把 scanner 的 ``_error`` 归成「永久 / 临时」。

    认不出来的一律当**临时**（沿用旧行为）——宁可多试几次，也不要因为归错类
    而把好文件判死。``quota`` 明确归临时（且单独用 24 小时退避）。
    """
    code = str(error or "").strip().lower()
    if code in PERMANENT_ERRORS:
        return KIND_PERMANENT
    return KIND_TRANSIENT


def _apply_probe_result(db, item, info: dict) -> None:
    """把 ffprobe 结果落到条目 + 重建内封轨道（与 scanner 写循环同口径）"""
    item.size = info.get("size", 0) or item.size
    item.duration_ticks = info["duration_ticks"]
    # 码率兜底：列已是 BIGINT，但个别探测源会给出 None/负数/超大值，
    # 直接落库会让整轮 _probe_one 抛 NumericValueOutOfRange。
    item.bitrate = _safe_int(info.get("bitrate"))
    item.width = _safe_int(info.get("width"))
    item.height = _safe_int(info.get("height"))
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
        stream = em.MediaStream(
            item_id=item.id,
            **{k: v for k, v in s.items() if k in _STREAM_COLS},
        )
        # 超长 title/display_title 截断（双保险：before_insert 钩子之外再拦一道）
        em.sanitize_stream_strings(stream)
        db.add(stream)


def _fail(db, item, reason: str, error: Optional[str] = None) -> None:
    """记一次失败，按**错误类型**决定：直接放弃、退避重试，还是等配额恢复

    三条分支对应三类完全不同的处置：

    - **永久失败**（文件没了 / 格式不支持）：直接 ``failed``，不再重试。
      重试一万次还是同一个结果，而每一次都要占 worker 名额与云盘配额。
    - **配额耗尽**：等满 24 小时，且**不计入尝试次数**。配额是部署/账号的
      状态，不是这个文件的错——计进 5 次上限就等于“因为配额问题把文件判死”。
    - **其它临时失败**：指数退避，上限 24 小时；并把优先级降到 ``RETRY_PRIORITY``，
      让重试中的老文件排在新入库文件之后（用户要看的元数据先填上）。
    """
    kind = _classify_failure(error)

    if kind == KIND_PERMANENT:
        item.probe_status = "failed"
        item.probe_attempts = PROBE_MAX_ATTEMPTS
        item.probe_next_retry_at = None
        logger.warning("探测放弃 item=%s（永久失败 %s）: %s", item.id, error, reason)
        return

    if str(error or "") == "quota":
        item.probe_status = "pending"
        item.probe_next_retry_at = datetime.now() + timedelta(
            seconds=QUOTA_BACKOFF_SECONDS)
        item.probe_priority = RETRY_PRIORITY
        logger.warning(
            "探测遇配额耗尽 item=%s：等 %d 小时后再试（不计入失败次数）",
            item.id, QUOTA_BACKOFF_SECONDS // 3600,
        )
        return

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
        # 重试中的老文件降优先级：新入库的文件先探
        item.probe_priority = RETRY_PRIORITY
        logger.info("探测失败 item=%s，第 %d 次，%ds 后重试: %s",
                    item.id, attempts, _backoff_seconds(attempts), reason)


def _probe_one(item_id: int) -> str:
    """探测单个条目（工作线程内自带 Session）。

    返回值是给 ``run_once`` 计数用的，取值：
    ``done``（探到时长）/ ``probed_no_duration``（跑完但无时长，可播放）/
    ``degraded``（远程可访问但媒体信息不完整）/ ``skipped``（已探完或被抢走）/
    ``paused_quota``（配额熔断中）/ ``failed``（真的探不出来）。
    """
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
            # 熔断器：已触发则直接跳过，不烧配额（纯只读，不碰计数器）
            if breaker_is_tripped():
                return "paused_quota"
            target = resolve_play_target(item.file_path, db)
            info = probe_metadata(target.value, target.headers, size=item.size or 0)
            # 检查是否 403，更新熔断器（语义分离：记录 vs 只读检查）
            is_403 = bool(info and info.get("_error") == "quota")
            if is_403:
                breaker_record_quota_error()
            else:
                # 非 403（成功或其它错误）：重置连续计数
                breaker_record_success()
            if is_403 and breaker_is_tripped():
                # 熔断中，把当前条目打回 pending（不是它的错，是配额问题）
                # 配额 403 不增加普通文件失败次数，且**不排到马上重试**——
                # 直接走 _fail 的配额分支，等满 24 小时，与熔断窗口对齐。
                db.rollback()
                item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
                if item is not None:
                    _fail(db, item, "远端配额耗尽，熔断中", error="quota")
                    db.commit()
                return "paused_quota"
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
        # 远端 HTTP 错误（403/404/401…）优先于「信息不完整」：403 已交给上面的熔断器，
        # 其余按失败重试收敛——别静默终结成 degraded，否则熔断器永远看不到远程文件的
        # 配额耗尽，「文件已被删除」也永远不会变成 failed（生产 4.3 万 degraded 里混着它们）。
        if info and info.get("_error"):
            _fail(db, item, info.get("_error_detail") or f"探测失败（{info['_error']}）",
                  error=info.get("_error"))
            db.commit()
            return "failed"
        # 远程可访问但拿不到 duration：这是信息降级，不是文件坏了。
        # 不进入 5 次重试/failed 风暴，否则大批云盘 MP4 会持续占满 worker。
        if info and info.get("_degraded"):
            item.size = info.get("size", 0) or item.size
            item.last_probed_at = datetime.now()
            item.probe_status = "degraded"
            item.probe_attempts = 0
            item.probe_next_retry_at = None
            db.commit()
            logger.warning("探测降级 item=%s：%s", item.id,
                           info.get("_error_detail", "远程媒体信息不完整"))
            return "degraded"
        # 到这里已经排除了 duration_ticks / _error / _degraded 三种情况，剩下的就是
        # 「跑完了但没给时长」与「有错但没被归类」两类，先分清再处置。
        err_detail = (info or {}).get("_error_detail") if info else None
        error = (info or {}).get("_error") if info else None
        if not error:
            # **没有 _error = ffprobe 跑完了，只是没给出时长**（MP4 缺 moov、流媒体片段、
            # 容器损坏到读不出时长等）。这是信息降级，不是文件没了：
            #   - 判 failed 会让用户端报「网络错误或者当前媒体库不存在该项目」，而文件其实能播；
            #   - 退避重试 5 轮只会让这批文件反复占满 worker 名额（实测 2.6 万条）。
            # 所以记成一个**终态但不失败**的状态，与 degraded 同类：不重试、可播放。
            item.size = (info or {}).get("size", 0) or item.size
            item.last_probed_at = datetime.now()
            item.probe_status = STATUS_NO_DURATION
            item.probe_attempts = 0
            item.probe_next_retry_at = None
            db.commit()
            logger.info("探测完成但无时长 item=%s（可播放，不重试）: %s",
                        item.id, err_detail or "ffprobe 未返回有效时长")
            return STATUS_NO_DURATION
        _fail(db, item, err_detail or f"探测失败（{error}）", error=error)
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
    counts = {"claimed": len(ids), "done": 0, "skipped": 0, "failed": 0,
              STATUS_NO_DURATION: 0}
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS,
                            thread_name_prefix="probe-worker") as pool:
        for result in pool.map(_probe_one, ids):
            counts[result] = counts.get(result, 0) + 1
    logger.info("探测 worker 一轮：claimed=%d done=%d skipped=%d failed=%d 无时长=%d",
                counts["claimed"], counts["done"], counts["skipped"], counts["failed"],
                counts[STATUS_NO_DURATION])
    return counts


def _worker_loop() -> None:
    logger.info("探测 worker 启动（workers=%d, 限流=%d/s, 最大尝试=%d）",
                PROBE_WORKERS, PROBE_RATE_PER_SEC, PROBE_MAX_ATTEMPTS)
    while not _stop_event.is_set():
        try:
            # 熔断中：退避睡眠，不空转烧 CPU/DB
            if breaker_is_tripped():
                logger.warning(
                    "[probe] 熔断器已触发，worker 退避 %d 秒（配额恢复后手动重置）",
                    _QUOTA_BREAKER_BACKOFF_SEC,
                )
                _stop_event.wait(_QUOTA_BREAKER_BACKOFF_SEC)
                continue
            counts = run_once()
            if counts["claimed"] == 0:
                _stop_event.wait(PROBE_IDLE_POLL_SEC)
            elif PROBE_ROUND_PAUSE_SEC > 0:
                # 有积压也要让出资源：连续满载会把整台机器压垮，
                # 优先保证用户侧浏览不被后台探测拖死。
                _stop_event.wait(PROBE_ROUND_PAUSE_SEC)
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
