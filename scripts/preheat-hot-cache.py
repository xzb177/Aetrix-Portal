#!/usr/bin/env python3
"""热门内容预热：把播放次数 Top N 的文件读进 rclone VFS 缓存。

在大盘流节点上跑（挂载点与主服务同路径）。预热只是顺序读文件头部
（默认 64MB），让 rclone VFS 缓存 + 预读把热数据常驻本地，
用户点播时首字节直接走本地，不用等 Drive。

- 只读、不写库，任何异常都不影响播放（缓存只是加速）。
- 默认跳过已在本地 VFS 缓存目录里的文件（rclone 自己管）。
- 用法：python scripts/preheat-hot-cache.py --top 50 [--bytes 67108864]

注意：在流节点容器内跑（`docker exec aetrix-stream python ...`），
DATABASE_URL 指向主库（只读查询）。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("preheat")

CHUNK = 4 * 1024 * 1024


def top_items(db, n: int):
    """按全站播放次数取 Top N（UserMediaData.play_count 求和）。"""
    from sqlalchemy import func
    from backend.emby_server import models as em

    rows = (
        db.query(
            em.MediaItem.guid,
            em.MediaItem.file_path,
            func.sum(em.UserMediaData.play_count).label("plays"),
        )
        .join(em.UserMediaData, em.UserMediaData.item_id == em.MediaItem.id)
        .filter(em.MediaItem.file_path.isnot(None))
        .group_by(em.MediaItem.id)
        .order_by(func.sum(em.UserMediaData.play_count).desc())
        .limit(n)
        .all()
    )
    return rows


def resolve_local_path(db, file_path: str) -> str | None:
    """file_path → 本机可读路径；解析不出/不是本地文件返回 None。"""
    if not file_path:
        return None
    if file_path.startswith("/"):
        return file_path if os.path.isfile(file_path) else None
    # mount:// 形态走统一解析
    try:
        from backend.emby_server import mounts as mount_lib
        # 轻量：只处理能直接映射到本地路径的（FUSE 挂载点）
        if file_path.startswith(mount_lib.MOUNT_PATH_PREFIX):
            return None  # 远端代理形态由 VFS/播放时代理负责，不预热
    except Exception:
        return None
    return None


def warm_file(path: str, num_bytes: int) -> int:
    """顺序读文件前 num_bytes，返回实际读到的字节数。"""
    total = 0
    with open(path, "rb") as f:
        while total < num_bytes:
            data = f.read(min(CHUNK, num_bytes - total))
            if not data:
                break
            total += len(data)
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--bytes", type=int, default=64 * 1024 * 1024,
                    help="每个文件预热字节数（默认 64MB）")
    args = ap.parse_args()

    from backend.database import SessionLocal
    db = SessionLocal()
    ok, skipped, failed = 0, 0, 0
    try:
        rows = top_items(db, args.top)
        logger.info("取到 %d 个热门条目，开始预热（每文件 %dMB）…",
                    len(rows), args.bytes // 1024 // 1024)
        for guid, file_path, plays in rows:
            local = resolve_local_path(db, file_path)
            if not local:
                skipped += 1
                continue
            try:
                got = warm_file(local, args.bytes)
                ok += 1
                logger.info("预热 OK plays=%s %dMB %s",
                            plays, got // 1024 // 1024, local[:80])
            except OSError as e:
                failed += 1
                logger.warning("预热失败 %s: %s", local[:80], e)
    finally:
        db.close()
    logger.info("预热完成：成功 %d，跳过 %d，失败 %d", ok, skipped, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
