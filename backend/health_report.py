"""后台健康检查：把「真的出事了」反映到 status 上。

## 为什么要做

``/health`` 以前硬编码返回 ``status="healthy"``——不管数据库断开、Redis 挂了、
worker 刷几千条探测失败、扫描队列堆积，前台「服务健康」页一律显示正常。

这不是"少一个指标"，而是**看板在最需要的时候失明**：出问题时没人能从页面看到，
只能去翻日志。生产上刮削链整条挂掉（series 全部搜不到）而页面一片绿，
就是这么发生的。

## 口径

按严重度分三档，让页面上能一眼看出该不该慌：

- ``ok``      一切正常
- ``warn``   降级但还能用：磁盘吃紧、Redis 不可用（有本地回退）、探测/刮削失败率高
- ``down``    核心不可用：数据库不通、补全队列堆积到处理不过来

**刻意不纳入**：单条条目的刮削失败不算 warn（TMDB 对中文剧集收录差是常态，
几百条 failed 属于正常业务状态，报出来只会天天误警）。只统计**失败率**与
**堆积量**，这两者才代表系统出了问题。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func

logger = logging.getLogger(__name__)

# 阈值：经验值，按公测规模调过
WARN_DISK_FREE_PERCENT = 15.0
WARN_PROBE_FAIL_RATIO = 0.30        # 探测失败率超过 30%
WARN_ENRICH_FAIL_RATIO = 0.30       # 刮削失败率超过 30%
DOWN_QUEUE_BACKLOG = 500            # 补全队列堆积超过这个数就是处理不过来了


def _count(db, item_type: str, status: str) -> int:
    from backend.emby_server import models as em
    try:
        return db.query(func.count(em.MediaItem.id)).filter(
            em.MediaItem.item_type == item_type,
            em.MediaItem.probe_status == status,
        ).scalar() or 0
    except Exception as exc:  # noqa: BLE001 — 统计失败不该让健康检查 500
        logger.debug("统计 probe %s 失败: %s", status, exc)
        return 0


def _enrich_count(db, status: str) -> int:
    from backend.emby_server import models as em
    try:
        return db.query(func.count(em.MediaItem.id)).filter(
            em.MediaItem.enrich_status == status).scalar() or 0
    except Exception as exc:  # noqa: BLE001
        logger.debug("统计 enrich %s 失败: %s", status, exc)
        return 0


def library_scan_summary(db) -> dict:
    """各媒体库最近一轮扫描的结果概览（扫描失败的库一眼可见）"""
    from backend.emby_server import models as em
    out = {
        "libraries_total": 0,
        "scanning": 0,
        "failed": 0,
        "never_scanned": 0,
        "last_failed": [],
    }
    try:
        rows = db.query(em.Library).all()
    except Exception as exc:  # noqa: BLE001
        logger.debug("读媒体库失败: %s", exc)
        return out
    out["libraries_total"] = len(rows)
    for lib in rows:
        status = (getattr(lib, "scan_status", None) or "").strip()
        if getattr(lib, "is_scanning", False) or status == "running":
            out["scanning"] += 1
        elif status == "failed":
            out["failed"] += 1
            if len(out["last_failed"]) < 5:
                out["last_failed"].append({
                    "id": lib.id, "name": lib.name,
                    "error": (lib.scan_error or "")[:200],
                    "at": str(lib.last_scan_at or ""),
                })
        elif not lib.last_scan_at:
            out["never_scanned"] += 1
    return out


def collect(db) -> dict:
    """返回 ``{level, status, issues[], metrics{}}``"""
    from sqlalchemy import func

    issues: list[dict] = []
    metrics: dict[str, Any] = {}
    level = "ok"

    def _bump(new_level: str) -> None:
        nonlocal level
        order = {"ok": 0, "warn": 1, "down": 2}
        if order.get(new_level, 0) > order.get(level, 0):
            level = new_level

    # ---- 数据库 ----
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        metrics["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        metrics["database"] = "error"
        _bump("down")
        issues.append({"level": "down", "key": "database",
                       "message": f"数据库不可用：{str(exc)[:120]}"})

    # ---- Redis（队列/熔断器/分布式锁都靠它）----
    try:
        from backend import database as dbmod
        r = dbmod.redis_client
        if r is None:
            metrics["redis"] = "not_configured"
        else:
            r.ping()
            metrics["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        metrics["redis"] = "error"
        _bump("warn")
        issues.append({"level": "warn", "key": "redis",
                       "message": f"Redis 不可用：{str(exc)[:120]}"})

    # ---- 磁盘余量 ----
    try:
        from backend.emby_server import maintenance
        rep = maintenance.resource_report()
        free_pct = rep.get("disk_free_percent")
        metrics["disk_free_percent"] = free_pct
        if free_pct is not None and float(free_pct) < WARN_DISK_FREE_PERCENT:
            _bump("warn")
            issues.append({"level": "warn", "key": "disk",
                           "message": f"磁盘余量偏低（{float(free_pct):.0f}% 剩余）"})
        metrics["transcode_sessions"] = rep.get("transcode_sessions", 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("读磁盘信息失败: %s", exc)

    # ---- 后台 worker 存活（StrmAssistant 打磨 R2）----
    # 线程静默死亡时这里报 warn，避免"后台任务停摆了却没人知道"
    try:
        from backend.emby_server import worker_registry as _wr
        workers = _wr.snapshot()
        metrics["workers"] = workers
        dead = [n for n, s in workers.items() if not s["alive"]]
        if dead:
            _bump("warn")
            issues.append({"level": "warn", "key": "workers",
                           "message": f"后台 worker 线程已死亡：{', '.join(dead)}"})
    except Exception as exc:  # noqa: BLE001
        logger.debug("读 worker 状态失败: %s", exc)

    # ---- 媒体探测失败率 ----
    try:
        done = _count(db, "movie", "done") + _count(db, "episode", "done")
        degraded = _count(db, "movie", "degraded") + _count(db, "episode", "degraded")
        # ffprobe 跑完但没时长：可播、不算失败，但必须进分母，
        # 否则它们从总量里消失，失败率会虚低（v2.42.14 新增状态）
        no_duration = (_count(db, "movie", "probed_no_duration")
                       + _count(db, "episode", "probed_no_duration"))
        failed = _count(db, "movie", "failed") + _count(db, "episode", "failed")
        total = done + degraded + no_duration + failed
        ratio = (failed / total) if total else 0.0
        metrics["probe_degraded"] = degraded
        metrics["probe_no_duration"] = no_duration
        metrics["probe_failed"] = failed
        metrics["probe_ratio"] = round(ratio, 4)
        # 样本太少时不算数（刚开机的库会误报）
        if total >= 20 and ratio >= WARN_PROBE_FAIL_RATIO:
            _bump("warn")
            issues.append({
                "level": "warn", "key": "probe",
                "message": f"媒体探测失败率 {ratio:.0%}（{failed}/{total}），"
                           "通常是存储源读不到或云盘异常"})
    except Exception as exc:  # noqa: BLE001
        logger.debug("统计探测失败率出错: %s", exc)

    # ---- 补全/刮削失败率与堆积 ----
    try:
        edone = _enrich_count(db, "done")
        efailed = _enrich_count(db, "failed")
        epending = _enrich_count(db, "pending")
        eenriching = _enrich_count(db, "enriching")
        etotal = edone + efailed
        eratio = (efailed / etotal) if etotal else 0.0
        metrics.update({
            "enrich_done": edone, "enrich_failed": efailed,
            "enrich_pending": epending, "enriching": eenriching,
            "enrich_fail_ratio": round(eratio, 4),
        })
        if etotal >= 20 and eratio >= WARN_ENRICH_FAIL_RATIO:
            _bump("warn")
            issues.append({
                "level": "warn", "key": "enrich",
                "message": f"元数据补全失败率 {eratio:.0%}（{efailed}/{etotal}），"
                           "检查 TMDB Key 与网络"})
        backlog = epending + eenriching
        metrics["enrich_backlog"] = backlog
        if backlog >= DOWN_QUEUE_BACKLOG:
            _bump("down")
            issues.append({
                "level": "down", "key": "enrich_backlog",
                "message": f"补全队列堆积 {backlog} 条，已经处理不过来"})

        # v2.42.9：把「堆积」与「没在跑」拆开 —— 处置完全不同：
        # 前者是等它跑（或加线程），后者要去查 worker 有没有起、是不是卡住了。
        # 以前只有堆积一条结论，看的人只能猜。
        try:
            from backend.emby_server import scan_progress as progress
            from backend.emby_server import enrich_worker

            tp = progress.throughput()
            metrics["enrich_done_per_min"] = tp["done_per_min"]
            metrics["enrich_idle_sec"] = tp["idle_sec"]
            metrics["enrich_stages"] = progress.stage_stats()
            # worker 被显式关掉（ENRICH_WORKER=0）时不报「没在跑」：那就是设计如此
            stalled = (enrich_worker.ENRICH_ENABLED
                       and backlog >= DOWN_QUEUE_BACKLOG
                       and tp["done_per_min"] <= 0)
            if stalled:
                if tp["samples"] == 0:
                    # 计数器是进程内的：刚重启时还没完成过任何条目，不能当故障
                    _bump("warn")
                    issues.append({
                        "level": "warn", "key": "enrich_no_progress",
                        "message": f"补全队列堆积 {backlog} 条，而本进程还没完成过任何条目："
                                   "刚重启请稍等，否则检查补全 worker 是否在跑"})
                else:
                    _bump("down")
                    issues.append({
                        "level": "down", "key": "enrich_stalled",
                        "message": f"补全队列堆积 {backlog} 条，且近 "
                                   f"{tp['window_sec'] // 60} 分钟没有完成任何条目"
                                   "（只在重试 / 失败）—— 是卡住了，不是跑得慢"})
        except Exception as exc:  # noqa: BLE001
            logger.debug("统计补全速率出错: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("统计补全状态出错: %s", exc)

    # ---- 扫描（库级别的真实故障）----
    try:
        scans = library_scan_summary(db)
        metrics["scans"] = scans
        if scans["failed"]:
            names = "、".join(x["name"] for x in scans["last_failed"][:3])
            _bump("warn")
            issues.append({
                "level": "warn", "key": "scan",
                "message": f"{scans['failed']} 个媒体库最近一次扫描失败：{names}"})
    except Exception as exc:  # noqa: BLE001
        logger.debug("统计扫描状态出错: %s", exc)

    return {
        "level": level,
        "status": {"ok": "healthy", "warn": "degraded", "down": "unhealthy"}[level],
        "issues": issues,
        "metrics": metrics,
    }
