#!/usr/bin/env python3
"""系统性去重合并：一次性清理存量重复记录。

按 (library_id, tmdb_id) 或 (library_id, 归一化标题, 年份) 分组，
每组只保留一条主记录：
- series：把重复剧的 seasons/episodes 全部挪到主记录下，再删重复的 series
- movie：直接删重复的 movie（保留主记录）

主记录选择：有海报 > 有 tmdb_id > 有简介 > id 最小（最早入库）。

用法：
    # 预览（不写库）
    python3 scripts/dedup_merge.py --dry-run
    # 执行
    python3 scripts/dedup_merge.py
    # 只处理指定库
    python3 scripts/dedup_merge.py --library-id 5

注意：在 VPS 上运行，连接生产数据库。执行前建议先备份。
"""

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from backend.database import SessionLocal
from backend.emby_server import models as em
from backend.emby_server import dedup as dedup_lib


def _pick_primary(db, ids: list[int]):
    """从一组 id 中选主记录。"""
    items = db.query(em.MediaItem).filter(em.MediaItem.id.in_(ids)).all()
    return dedup_lib.pick_primary(items)


def merge_group(db, key: tuple, ids: list[int], dry_run: bool = False) -> dict:
    """合并一组重复记录，返回统计。"""
    lib_id, item_type = key[0], key[1]
    items = db.query(em.MediaItem).filter(em.MediaItem.id.in_(ids)).all()
    by_id = {i.id: i for i in items}
    primary = dedup_lib.pick_primary(items)
    duplicates = [i for i in items if i.id != primary.id]

    stats = {"primary_id": primary.id, "primary_name": primary.name,
             "merged": len(duplicates), "episodes_moved": 0}

    if dry_run:
        return stats

    if item_type == "series":
        # 把重复剧的 seasons 和 episodes 挪到主记录下
        dup_ids = [d.id for d in duplicates]
        # seasons: parent_id 指向重复 series 的
        seasons = db.query(em.MediaItem).filter(
            em.MediaItem.item_type == "season",
            em.MediaItem.parent_id.in_(dup_ids),
        ).all()
        for s in seasons:
            s.parent_id = primary.id
            s.series_id = primary.id
        # episodes: series_id 指向重复 series 的
        episodes = db.query(em.MediaItem).filter(
            em.MediaItem.item_type == "episode",
            em.MediaItem.series_id.in_(dup_ids),
        ).all()
        for e in episodes:
            e.series_id = primary.id
            # parent_id 指向旧 season 的，需要映射到新 season
            # （新 season 按 season_number 找，找不到就保持原样）
        stats["episodes_moved"] = len(episodes)
        # episode 的 parent_id（season）映射
        # 建 (old_season_id -> new_season_id) 映射表
        season_map = {}
        for s in seasons:
            # s 已经挪过去了，按 season_number 找主记录下是否已有同季
            existing = db.query(em.MediaItem).filter(
                em.MediaItem.item_type == "season",
                em.MediaItem.series_id == primary.id,
                em.MediaItem.season_number == s.season_number,
                em.MediaItem.id != s.id,
            ).first()
            if existing:
                # 主记录下已有同季：把集挪到已有季，删重复季
                season_map[s.id] = existing.id
        # 更新 episodes 的 parent_id
        for e in episodes:
            if e.parent_id in season_map:
                e.parent_id = season_map[e.parent_id]
        # 删被合并掉的重复季
        for old_sid, new_sid in season_map.items():
            old_season = db.get(em.MediaItem, old_sid)
            if old_season:
                db.delete(old_season)

    # 删重复的主记录（series/movie）
    for d in duplicates:
        db.delete(d)

    return stats


def main():
    parser = argparse.ArgumentParser(description="系统性去重合并存量数据")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写库")
    parser.add_argument("--library-id", type=int, default=None, help="只处理指定库")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        groups = dedup_lib.group_duplicates(db, library_id=args.library_id)
        print(f"找到 {len(groups)} 个重复组")
        if not groups:
            return

        total_merged = 0
        total_episodes = 0
        for key, ids in sorted(groups.items()):
            lib_id, item_type = key[0], key[1]
            stats = merge_group(db, key, ids, dry_run=args.dry_run)
            total_merged += stats["merged"]
            total_episodes += stats.get("episodes_moved", 0)
            key_desc = key[3] if len(key) > 3 else key
            print(f"  [{item_type}] 库{lib_id} {stats['primary_name'][:30]}: "
                  f"合并 {stats['merged']} 条重复 "
                  f"(主记录 id={stats['primary_id']})")
            if args.dry_run:
                continue
            # 每组合并后提交，避免长事务
            db.commit()

        print(f"\n总计：合并 {total_merged} 条重复记录，"
              f"挪动 {total_episodes} 集")
        if args.dry_run:
            print("（预览模式，未写库）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
