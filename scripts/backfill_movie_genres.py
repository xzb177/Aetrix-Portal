#!/usr/bin/env python3
"""Movie 补类型（一次性回填）——P0-3

背景：``apply_details()`` 历史上完全忽略详情接口的 ``genres`` 字段，
凡走「tmdb_id → 详情」分支的电影（NFO 自带 tmdb_id、别名匹配、已有 id 补缺）
都永远拿不到类型，只有搜索命中走 ``apply()`` 的才有。代码已修
（``tmdb.py`` 的 ``apply_details`` 现在会从详情补类型），这个脚本把
**存量**里「有 tmdb_id 但 genres 为空」的电影一次性补上。

为什么不增加日常 TMDB 调用：
- 只处理已有 ``tmdb_id`` 的条目，不做搜索（无 tmdb_id 的靠搜索命中，
  那是 enrich 的事，不在这里猜）。
- ``details()`` 自带两级缓存（进程 300 秒 + 磁盘 30 天）与令牌桶限速：
  enrich/扫描阶段拉过的详情绝大多数还在磁盘缓存里，直接命中、
  **不产生新的 TMDB 请求**；没命中缓存的才走令牌桶慢慢补。

用法（容器里 / 工作区都行）：

    docker exec aetrix-api python scripts/backfill_movie_genres.py          # 先 dry-run 看数
    docker exec aetrix-api python scripts/backfill_movie_genres.py --apply  # 真正写库
    docker exec aetrix-api python scripts/backfill_movie_genres.py --apply --limit 500

幂等：只碰 genres 为空的条目，可反复跑。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, or_  # noqa: E402

from backend.database import SessionLocal  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server.tmdb import _genres_from_details, tmdb_client  # noqa: E402


def _missing_genres():
    """genres 为空的过滤条件：NULL / 空串 / 纯空白都算缺"""
    return or_(em.MediaItem.genres.is_(None),
               func.trim(em.MediaItem.genres) == "")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="回填有 tmdb_id 但缺类型的电影")
    p.add_argument("--apply", action="store_true",
                   help="真正写库；不加则只 dry-run 统计")
    p.add_argument("--limit", type=int, default=0,
                   help="最多处理多少条（0=不限），dry-run 时同样生效")
    p.add_argument("--batch-size", type=int, default=200,
                   help="每多少条提交一次（默认 200）")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not tmdb_client.configured:
        print("TMDB 未配置（无可用 key），无法拉详情，退出。")
        return 2

    # 总数先行（keyset 分页逐批取，不一次性 all() 吃内存）
    db = SessionLocal()
    try:
        total = (
            db.query(func.count(em.MediaItem.id))
            .filter(em.MediaItem.item_type == "movie")
            .filter(em.MediaItem.tmdb_id.isnot(None))
            .filter(_missing_genres())
            .scalar()
        ) or 0
    finally:
        db.close()
    if args.limit:
        total = min(total, args.limit)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] 待补类型电影：{total} 条（有 tmdb_id 且 genres 为空）")
    if not total:
        return 0

    fixed = 0
    still_missing = 0
    errors = 0
    done = 0
    last_id = 0
    db = SessionLocal()
    t0 = time.time()
    try:
        while done < total:
            batch = (
                db.query(em.MediaItem.id, em.MediaItem.tmdb_id)
                .filter(em.MediaItem.item_type == "movie")
                .filter(em.MediaItem.tmdb_id.isnot(None))
                .filter(_missing_genres())
                .filter(em.MediaItem.id > last_id)
                .order_by(em.MediaItem.id)
                .limit(args.batch_size)
                .all()
            )
            if not batch:
                break
            for row_id, row_tmdb_id in batch:
                last_id = row_id
                done += 1
                try:
                    # 走令牌桶 + 两级缓存：磁盘缓存命中时不产生新请求
                    data = tmdb_client.details(str(row_tmdb_id), "movie")
                except Exception as exc:  # noqa: BLE001 — 单条失败不拦整批
                    errors += 1
                    print(f"  ! id={row_id} tmdb_id={row_tmdb_id} 详情拉取失败：{exc}")
                    continue
                gnames = _genres_from_details(data or {})
                if gnames:
                    if args.apply:
                        row = db.query(em.MediaItem).filter(
                            em.MediaItem.id == row_id).first()
                        if row and not (row.genres or "").strip():
                            row.genres = ",".join(gnames)
                    fixed += 1
                else:
                    still_missing += 1
            if args.apply:
                db.commit()
            el = time.time() - t0
            print(f"  …{done}/{total}  已补 {fixed}  仍缺 {still_missing}  "
                  f"失败 {errors}  用时 {el:.0f}s")
            if args.limit and done >= args.limit:
                break
    finally:
        db.close()

    print(f"[{mode}] 完成：共 {done} 条，可补 {fixed} 条，"
          f"详情无类型 {still_missing} 条，失败 {errors} 条")
    if not args.apply:
        print("dry-run 未写库；确认数字后加 --apply 真正执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
