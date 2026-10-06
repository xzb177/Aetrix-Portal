#!/usr/bin/env python3
"""一次性回填：series 缺 production_year / premiere_date（P0-1）。

背景：2026-10 之前刮进库的 series 里 97% 没有年份——当时
``TmdbClient.apply()`` / ``apply_details()`` 只落文字与图片，从不写
``production_year`` / ``premiere_date``。本脚本对「有 tmdb_id、但
``production_year`` 为空」的 series 逐条回填。

**只读 TMDB、写 DB**：不碰扫描 / 补全流程，跑完即弃。增量安全：
只填空值，已有年份 / 首播日期的条目一律不动。

性能设计（生产约 1.8 万条）：
1. **磁盘缓存优先**：先查 ``tmdb_cache.load_details("tv", tmdb_id)``（30 天 TTL，
   之前 enrich 预热过的大部分直接命中，**零 HTTP**）。
2. **并发 + 共享令牌桶**：未命中的走 ``tmdb_client.details()``，多线程并发，
   共用进程内 ``_RequestLimiter``（默认 4 请求/秒，429 自适应退避照旧）。
   TMDB 没有真正的批量详情接口（``/tv/{id}`` 只能逐个取），这是不增加
   TMDB 调用量的前提下最快的合法打法。
3. DB 单线程批量写：每 200 条 commit 一次，Ctrl+C 中断也不丢已提交的进度。

用法（容器里，aetrix-api 与 aetrix-worker 都能连 DB）：

    docker exec aetrix-api python scripts/backfill_series_year.py --dry-run
    docker exec aetrix-api python scripts/backfill_series_year.py
    docker exec aetrix-api python scripts/backfill_series_year.py --limit 500 --workers 4

限速：脚本内 ``ENRICH_TMDB_PER_SEC`` 默认 4（只影响本进程，环境变量可覆盖）。
密钥：走管理后台「元数据与刮削」里配的 TMDB 密钥（与 enrich 同一来源）；
未配密钥时只有磁盘缓存命中能回填，脚本会明确提示。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 必须在 import backend.emby_server.tmdb **之前**：TMDB_PER_SEC 在模块 import 时读取
os.environ.setdefault("ENRICH_TMDB_PER_SEC", "4")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import tmdb_cache  # noqa: E402
from backend.emby_server.tmdb import TmdbClient, extract_air_dates  # noqa: E402

_ENDPOINT = {"series": "tv", "movie": "movie"}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kind", choices=("series", "movie"), default="series",
                    help="回填哪类条目（默认 series）")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多处理多少条（0 = 不限）")
    ap.add_argument("--workers", type=int, default=8,
                    help="详情请求的并发线程数（默认 8；限速走令牌桶，加线程不加压）")
    ap.add_argument("--batch", type=int, default=200,
                    help="每多少条 commit 一次（默认 200）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只统计、不写库")
    return ap.parse_args()


def _candidates(db, kind: str, limit: int) -> list[tuple[int, str]]:
    """捞出「有 tmdb_id、缺年份」的条目：(id, tmdb_id)。只取需要的两列。"""
    q = (db.query(em.MediaItem.id, em.MediaItem.tmdb_id)
         .filter(em.MediaItem.item_type == kind)
         .filter(em.MediaItem.tmdb_id.isnot(None))
         .filter(em.MediaItem.tmdb_id != "")
         .filter(em.MediaItem.production_year.is_(None))
         .order_by(em.MediaItem.id))
    if limit > 0:
        q = q.limit(limit)
    return [(row[0], str(row[1])) for row in q.yield_per(1000)]


def _dates_from_details(data: dict) -> tuple:
    """details 负载 → (year, premiere_datetime)；拿不到日期返回 (None, None)。"""
    if not data:
        return None, None
    return extract_air_dates(data)


def main() -> int:
    args = _parse_args()
    endpoint = _ENDPOINT[args.kind]
    started = time.monotonic()

    db = SessionLocal()
    try:
        client = TmdbClient()
        client.refresh_keys(db)
        key_info = f"{client.key_source}×{len(client.api_keys)}"
        rows = _candidates(db, args.kind, args.limit)
    finally:
        db.close()

    total = len(rows)
    effective_rate = os.environ.get("ENRICH_TMDB_PER_SEC", "4")
    print(f"[{datetime.now():%H:%M:%S}] 候选 {args.kind} {total} 条 "
          f"(tmdb_id 非空、production_year 为空)，密钥 {key_info}，"
          f"TMDB 限速 {effective_rate} 请求/秒，"
          f"{'DRY-RUN 不写库' if args.dry_run else f'每 {args.batch} 条提交'}")
    if not rows:
        print("无事可做。")
        return 0
    if client.key_source == "none":
        print("⚠ 未配置 TMDB 密钥：只有磁盘缓存命中的条目能回填，"
              "其余会跳过。请先在管理后台「元数据与刮削」填写密钥。")

    # ---- 阶段 1：磁盘缓存（零 HTTP）----
    stats = {"disk_hit": 0, "http_ok": 0, "no_date": 0, "failed": 0, "updated": 0}
    lock = threading.Lock()
    pending: list[tuple[int, str]] = []
    cached: dict[int, tuple] = {}  # item_id -> (year, premiere)

    for item_id, tmdb_id in rows:
        hit, data = tmdb_cache.load_details(endpoint, tmdb_id)
        if hit and data:
            year, premiere = _dates_from_details(data)
            if year is not None:
                cached[item_id] = (year, premiere)
                stats["disk_hit"] += 1
            else:
                stats["no_date"] += 1
        else:
            pending.append((item_id, tmdb_id))
    print(f"[{datetime.now():%H:%M:%S}] 磁盘缓存命中 {stats['disk_hit']} 条，"
          f"无日期 {stats['no_date']} 条，剩余 {len(pending)} 条走 TMDB 详情接口")

    # ---- 阶段 2：并发详情（共享令牌桶限速）----
    fetched: dict[int, tuple] = {}

    def _one(pair: tuple[int, str]) -> tuple[int, object, object]:
        item_id, tmdb_id = pair
        try:
            data = client.details(tmdb_id, args.kind)
        except Exception:  # noqa: BLE001 — 单条失败不影响整批
            return item_id, None, "failed"
        year, premiere = _dates_from_details(data)
        if year is None:
            return item_id, None, "no_date"
        return item_id, (year, premiere), "ok"

    if pending and client.key_source != "none":
        with ThreadPoolExecutor(max_workers=max(1, args.workers),
                                thread_name_prefix="backfill-year") as pool:
            futures = {pool.submit(_one, p): p for p in pending}
            done = 0
            for fut in as_completed(futures):
                item_id, payload, status = fut.result()
                done += 1
                with lock:
                    if status == "ok":
                        fetched[item_id] = payload
                        stats["http_ok"] += 1
                    elif status == "no_date":
                        stats["no_date"] += 1
                    else:
                        stats["failed"] += 1
                if done % 500 == 0 or done == len(pending):
                    el = time.monotonic() - started
                    print(f"[{datetime.now():%H:%M:%S}] TMDB 进度 {done}/{len(pending)} "
                          f"（{done / el:.1f} 条/秒，含限速等待）")
    elif pending:
        stats["failed"] += len(pending)
        print(f"[{datetime.now():%H:%M:%S}] 未配密钥：{len(pending)} 条未命中缓存的跳过")

    # ---- 阶段 3：单线程写库（只填空值）----
    updates = {**cached, **fetched}
    if args.dry_run:
        stats["updated"] = len(updates)
    else:
        db = SessionLocal()
        try:
            n = 0
            for item_id, (year, premiere) in updates.items():
                item = db.query(em.MediaItem).filter(
                    em.MediaItem.id == item_id).first()
                if item is None:
                    continue
                # 双保险：两次查询之间 enrich 可能已经填上了，不覆盖
                if item.production_year is None:
                    item.production_year = year
                    n += 1
                if premiere is not None and item.premiere_date is None:
                    item.premiere_date = premiere
                if n % args.batch == 0:
                    db.commit()
                    print(f"[{datetime.now():%H:%M:%S}] 已写库 {n}/{len(updates)}")
            db.commit()
            stats["updated"] = n
        finally:
            db.close()

    el = time.monotonic() - started
    print(f"[{datetime.now():%H:%M:%S}] 完成：候选 {total}，"
          f"磁盘命中 {stats['disk_hit']}，TMDB 取回 {stats['http_ok']}，"
          f"无日期 {stats['no_date']}，失败 {stats['failed']}，"
          f"{'可更新' if args.dry_run else '已更新'} {stats['updated']} 条，"
          f"耗时 {el:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
