"""数据库定时备份：SQLite 在线备份 + gzip 压缩 + 按天轮转 + daemon 调度

要解决的问题：生产库是 SQLite 单文件，一旦损坏 / 误删 / 宿主机故障，
订单、积分、订阅全丢。之前备份脚本全是 PostgreSQL 口径（pg_dump），
与生产实际不匹配，等于没有备份。

设计（参照 auto_scan.py 的 daemon 模式——"功能只提供能力"）：
- 配置（SystemConfig）：``backup_enabled``（"1"/"0"，默认 "1"，开箱即有）、
  ``backup_time``（"HH:MM"，默认 "03:00"，服务器本地时间）、
  ``backup_keep_days``（默认 "7"，保留最近 N 天）、
  ``backup_last_run``（"YYYY-MM-DD"，同一天不重复跑）。
- 备份方式：``sqlite3.Connection.backup()`` 在线备份——DB 正在被读写时也安全。
  不要直接 cp 数据库文件（WAL 模式下可能拷到写一半的状态）。
- 位置：与数据库文件同目录的 ``backups/`` 子目录，
  文件名 ``<库名>-YYYYMMDD-HHMMSS.db.gz``（gzip 压缩）。
- 非 SQLite 部署：记 warning 跳过（pg/mysql 请用各自原生工具，本模块只管 sqlite）。
- 调度：worker / EM 启动时 ``start_backup_scheduler()`` 起 daemon 线程，
  每 60 秒检查一次；到点且当天没跑过就执行。任何异常只记日志，线程永不退出。
"""

from __future__ import annotations

import gzip
import logging
import re
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database import SessionLocal, engine
from backend.integrations import store

logger = logging.getLogger(__name__)

CONFIG_ENABLED = "backup_enabled"
CONFIG_TIME = "backup_time"
CONFIG_KEEP_DAYS = "backup_keep_days"
CONFIG_LAST_RUN = "backup_last_run"

DEFAULT_ENABLED = True
DEFAULT_TIME = "03:00"
DEFAULT_KEEP_DAYS = 7
CHECK_INTERVAL = 60  # 秒

BACKUP_DIRNAME = "backups"
FILENAME_RE = re.compile(r"^(.+)-(\d{8})-(\d{6})\.db\.gz$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

_SCHEDULER_STARTED = False
_SCHEDULER_LOCK = threading.Lock()


def parse_time(value: str | None) -> str | None:
    """校验 "HH:MM"；合法返回规范化字符串，否则返回 None。"""
    text = (value or "").strip()
    m = _TIME_RE.match(text)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"


def get_db_file_path() -> Path | None:
    """从 engine URL 解析 SQLite 数据库文件路径；非 sqlite / 内存库返回 None。"""
    try:
        url = engine.url
    except Exception:  # noqa: BLE001 — engine 未就绪时当没有
        return None
    if url.drivername != "sqlite":
        return None
    db_name = url.database
    if not db_name or db_name == ":memory:":
        return None
    return Path(db_name).resolve()


def get_backup_dir() -> Path | None:
    """备份目录：与数据库文件同目录的 backups/。"""
    db_path = get_db_file_path()
    if db_path is None:
        return None
    return db_path.parent / BACKUP_DIRNAME


def _backup_filename(db_path: Path, when: datetime) -> str:
    stem = db_path.stem  # aetrix_unified
    return f"{stem}-{when.strftime('%Y%m%d-%H%M%S')}.db.gz"


def run_backup_now(reason: str = "manual") -> dict:
    """立即执行一次备份（含轮转）。返回 {name, size, path}。

    失败时抛异常（调用方决定是记日志还是转 500）。
    """
    db_path = get_db_file_path()
    if db_path is None:
        raise RuntimeError("当前不是 SQLite 文件数据库，跳过备份（pg/mysql 请用原生工具）")
    if not db_path.exists():
        raise RuntimeError(f"数据库文件不存在：{db_path}")
    backup_dir = get_backup_dir()
    assert backup_dir is not None
    backup_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    name = _backup_filename(db_path, now)
    final_path = backup_dir / name

    # 在线备份到临时文件（同目录，保证同文件系统，写完再改名，原子性更好）
    tmp_db = backup_dir / f".tmp-{now.strftime('%Y%m%d-%H%M%S')}.db"
    try:
        src = sqlite3.connect(str(db_path), timeout=30)
        try:
            dst = sqlite3.connect(str(tmp_db))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        # gzip 压缩到最终文件名
        with open(tmp_db, "rb") as f_in, gzip.open(final_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    finally:
        tmp_db.unlink(missing_ok=True)

    size = final_path.stat().st_size
    logger.info("数据库备份完成（%s）：%s（%.1f MB）", reason, name, size / 1024 / 1024)
    return {"name": name, "size": size, "path": str(final_path)}


def prune_old_backups(keep_days: int) -> int:
    """删除超过 keep_days 的旧备份（按文件 mtime）。返回删除数量。"""
    backup_dir = get_backup_dir()
    if backup_dir is None or not backup_dir.exists():
        return 0
    cutoff = datetime.now().timestamp() - keep_days * 86400
    removed = 0
    for f in backup_dir.glob("*.db.gz"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError as exc:  # noqa: BLE001 — 删不掉记一条，不中断
            logger.warning("删除旧备份失败 %s：%s", f.name, exc)
    if removed:
        logger.info("备份轮转：删除 %d 个超过 %d 天的旧备份", removed, keep_days)
    return removed


def list_backups() -> list[dict]:
    """列出备份文件（新的在前）。"""
    backup_dir = get_backup_dir()
    if backup_dir is None or not backup_dir.exists():
        return []
    rows = []
    for f in backup_dir.glob("*.db.gz"):
        try:
            st = f.stat()
        except OSError:  # noqa: BLE001
            continue
        rows.append({
            "name": f.name,
            "size": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    rows.sort(key=lambda r: r["name"], reverse=True)
    return rows


def get_config(db: Session) -> dict:
    """读备份配置（管理后台展示用）。"""
    vals = store.read_values(
        db,
        [CONFIG_ENABLED, CONFIG_TIME, CONFIG_KEEP_DAYS, CONFIG_LAST_RUN],
        {
            CONFIG_ENABLED: "1" if DEFAULT_ENABLED else "0",
            CONFIG_TIME: DEFAULT_TIME,
            CONFIG_KEEP_DAYS: str(DEFAULT_KEEP_DAYS),
            CONFIG_LAST_RUN: "",
        },
    )
    enabled = vals[CONFIG_ENABLED].strip() == "1"
    time_str = parse_time(vals[CONFIG_TIME]) or DEFAULT_TIME
    try:
        keep_days = int(vals[CONFIG_KEEP_DAYS].strip())
    except (TypeError, ValueError):
        keep_days = DEFAULT_KEEP_DAYS
    keep_days = max(1, min(30, keep_days))
    return {
        "enabled": enabled,
        "time": time_str,
        "keep_days": keep_days,
        "last_run": vals[CONFIG_LAST_RUN].strip(),
        "backups": list_backups(),
    }


def save_config(db: Session, enabled: bool, time_str: str, keep_days: int) -> dict:
    """保存备份配置；非法时抛 ValueError（接口转 400）。"""
    parsed = parse_time(time_str)
    if parsed is None:
        raise ValueError(f"时间格式非法，应为 HH:MM（24 小时制），收到：{time_str!r}")
    if not isinstance(keep_days, int) or not 1 <= keep_days <= 30:
        raise ValueError(f"保留天数非法，应为 1~30 的整数，收到：{keep_days!r}")
    store.write_values(
        db,
        {
            CONFIG_ENABLED: "1" if enabled else "0",
            CONFIG_TIME: parsed,
            CONFIG_KEEP_DAYS: str(keep_days),
        },
        {
            CONFIG_ENABLED: "数据库定时备份开关",
            CONFIG_TIME: "数据库备份每天执行时间（HH:MM，服务器本地时间）",
            CONFIG_KEEP_DAYS: "数据库备份保留天数（1~30）",
        },
    )
    db.commit()
    return get_config(db)


def _should_run_today(now: datetime, time_str: str, last_run: str) -> bool:
    """到点了且今天没跑过。"""
    return now.strftime("%H:%M") == time_str and last_run != now.strftime("%Y-%m-%d")


def _tick() -> None:
    """一次检查：到点就备份。异常只记日志，不向上传播。"""
    db = SessionLocal()
    try:
        cfg = get_config(db)
        if not cfg["enabled"]:
            return
        now = datetime.now()
        if not _should_run_today(now, cfg["time"], cfg["last_run"]):
            return
        # 先占位：同一天只跑一次
        store.write_values(
            db,
            {CONFIG_LAST_RUN: now.strftime("%Y-%m-%d")},
            {CONFIG_LAST_RUN: "数据库备份上次执行日期（防重复）"},
        )
        db.commit()
        try:
            result = run_backup_now(reason="scheduled")
            prune_old_backups(cfg["keep_days"])
            logger.info("定时备份完成：%s", result["name"])
        except Exception as exc:  # noqa: BLE001 — 备份失败记 error，不抛
            logger.error("定时数据库备份失败：%s", exc)
    except Exception as exc:  # noqa: BLE001 — 定时线程绝不能因一次失败退出
        logger.warning("定时备份检查异常：%s", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def start_backup_scheduler() -> bool:
    """启动备份调度线程（同一进程只启动一次；daemon，随进程退出）。

    跟 auto_scan 保持一致：在 worker / EM（一体化）进程启动，API 专职进程不启动。
    """
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return False
        _SCHEDULER_STARTED = True

    def _loop() -> None:
        while True:
            threading.Event().wait(CHECK_INTERVAL)
            _tick()

    threading.Thread(target=_loop, daemon=True, name="db-backup-scheduler").start()
    logger.info("数据库备份调度已启动（每 %s 秒检查一次，默认 %s 执行，保留 %s 天）",
                CHECK_INTERVAL, DEFAULT_TIME, DEFAULT_KEEP_DAYS)
    return True


__all__ = [
    "CONFIG_ENABLED",
    "CONFIG_KEEP_DAYS",
    "CONFIG_LAST_RUN",
    "CONFIG_TIME",
    "DEFAULT_KEEP_DAYS",
    "DEFAULT_TIME",
    "get_backup_dir",
    "get_config",
    "get_db_file_path",
    "list_backups",
    "parse_time",
    "prune_old_backups",
    "run_backup_now",
    "save_config",
    "start_backup_scheduler",
]
