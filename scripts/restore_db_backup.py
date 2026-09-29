#!/usr/bin/env python3
"""SQLite 备份恢复脚本（配合 backend/emby_server/db_backup.py 的定时备份）。

恢复步骤：
  1. 先停掉应用容器（否则恢复中的文件替换可能与正在写的进程冲突）：
       docker compose stop api worker ea   # 按你的实际服务名调整
  2. 跑本脚本，按提示选一个备份恢复：
       python3 scripts/restore_db_backup.py [--db /data/aetrix_unified.db] [--yes]
  3. 重启容器：
       docker compose up -d

安全机制：恢复前会自动把**当前**数据库再备份一份
（backups/ 下以 pre-restore- 为前缀），手滑选错了还能救回来。
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def find_backups(backup_dir: Path) -> list[Path]:
    files = sorted(backup_dir.glob("*.db.gz"), key=lambda p: p.name, reverse=True)
    return files


def gunzip_to(src_gz: Path, dst: Path) -> None:
    with gzip.open(src_gz, "rb") as f_in, open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def verify_sqlite(path: Path) -> bool:
    """简单校验：能打开且 sqlite_master 可读。"""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        finally:
            con.close()
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="从定时备份恢复 SQLite 数据库")
    ap.add_argument("--db", default="/data/aetrix_unified.db",
                    help="数据库文件路径（默认 /data/aetrix_unified.db）")
    ap.add_argument("--yes", action="store_true",
                    help="跳过二次确认（已用 --index 指定备份时可用）")
    ap.add_argument("--index", type=int, default=None,
                    help="直接指定要恢复的备份序号（从 1 开始，见列表）")
    args = ap.parse_args()

    db_path = Path(args.db)
    backup_dir = db_path.parent / "backups"
    if not backup_dir.exists():
        print(f"备份目录不存在：{backup_dir}", file=sys.stderr)
        return 1
    backups = find_backups(backup_dir)
    if not backups:
        print(f"没有找到备份文件（{backup_dir}/*.db.gz）", file=sys.stderr)
        return 1

    print("可用的备份（新的在前）：")
    for i, b in enumerate(backups, 1):
        size_mb = b.stat().st_size / 1024 / 1024
        print(f"  [{i}] {b.name}  ({size_mb:.1f} MB)")

    idx = args.index
    if idx is None:
        try:
            idx = int(input("输入要恢复的序号：").strip())
        except (ValueError, EOFError):
            print("已取消", file=sys.stderr)
            return 1
    if not 1 <= idx <= len(backups):
        print(f"序号非法：{idx}", file=sys.stderr)
        return 1
    chosen = backups[idx - 1]

    if not args.yes:
        print(f"\n即将用 {chosen.name} 覆盖 {db_path}")
        print("⚠️  请确认应用容器已停止（docker compose stop api worker ea），否则可能损坏数据。")
        confirm = input("输入 YES 继续：").strip()
        if confirm != "YES":
            print("已取消", file=sys.stderr)
            return 1

    # 1. 先把当前库再备一份（防手滑）
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safety_name = f"pre-restore-{stamp}.db.gz"
    if db_path.exists():
        safety_path = backup_dir / safety_name
        with open(db_path, "rb") as f_in, gzip.open(safety_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        print(f"当前库已先备份为：{safety_name}")
    else:
        print(f"注意：{db_path} 当前不存在，将直接恢复（无安全备份）")

    # 2. 解压选中备份到临时文件并校验
    tmp_path = backup_dir / f".restore-{stamp}.db"
    try:
        gunzip_to(chosen, tmp_path)
        if not verify_sqlite(tmp_path):
            print("备份文件校验失败（不是有效的 SQLite 库），已中止，未动当前库。", file=sys.stderr)
            return 1
        # 3. 原子替换：先删 WAL/SHM 残留，再改名覆盖
        for suffix in ("-wal", "-shm"):
            p = db_path.parent / (db_path.name + suffix)
            p.unlink(missing_ok=True)
        tmp_path.replace(db_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"恢复完成：{chosen.name} -> {db_path}")
    print("请重启应用容器：docker compose up -d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
