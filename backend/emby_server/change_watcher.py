"""追新：检测挂载上的新资源，自动触发扫描 + 刮削

设计见 workspace/designs/chase-new.md v2

核心思路：
- 每 N 分钟（用户可配）检查一次
- local 类型挂载（含 rclone 挂载的 Drive/S3 等）：用文件 mtime 检测新增
- 发现新视频文件 → 整库入 scan_queue（trigger="chase-new"）
  → 扫描器增量秒跳，只处理新文件
- 新入库条目自动进 enrich 队列刮削（NFO→TMDB→豆瓣）

v1 范围：
- 本机目录：文件 mtime 检测（``find -newermt``）
- rclone RC 挂载：``/operations/list`` 递归列举 + ``ModTime`` 窗口过滤
- 115/webdav/alist 暂不直接检测，依赖每日定时扫描兜底
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend import models as base_models
from backend.database import SessionLocal
from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib
from backend.emby_server import scan_queue

logger = logging.getLogger(__name__)

CONFIG_ENABLED = "chase_new_enabled"
CONFIG_INTERVAL = "chase_new_interval"
CONFIG_LIBRARIES = "chase_new_libraries"
CONFIG_LAST_CHECK = "chase_new_last_check"
CONFIG_LAST_FOUND = "chase_new_last_found"

DEFAULT_INTERVAL = 10  # 分钟
MIN_INTERVAL = 5
MAX_INTERVAL = 120

# 视频扩展名白名单
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".wmv", ".flv", ".mov", ".rmvb", ".mpg", ".mpeg", ".webm"}

_WATCHER_STARTED = False
_WATCHER_LOCK = threading.Lock()


def _get_config(db: Session, key: str, default: str = "") -> str:
    row = db.query(base_models.SystemConfig).filter(base_models.SystemConfig.key == key).first()
    return row.value if row and row.value is not None else default


def _set_config(db: Session, key: str, value: str) -> None:
    row = db.query(base_models.SystemConfig).filter(base_models.SystemConfig.key == key).first()
    if row:
        row.value = value
    else:
        row = base_models.SystemConfig(key=key, value=value)
        db.add(row)
    db.commit()


def _parse_interval(raw: str) -> int:
    """解析轮询间隔，非法值按默认处理"""
    try:
        minutes = int(raw)
    except (ValueError, TypeError):
        logger.warning("[chase-new] 间隔配置非法 %r，按默认 %d 分钟", raw, DEFAULT_INTERVAL)
        return DEFAULT_INTERVAL
    if minutes < MIN_INTERVAL:
        logger.warning("[chase-new] 间隔 %d < 最小 %d，按最小处理", minutes, MIN_INTERVAL)
        return MIN_INTERVAL
    if minutes > MAX_INTERVAL:
        logger.warning("[chase-new] 间隔 %d > 最大 %d，按最大处理", minutes, MAX_INTERVAL)
        return MAX_INTERVAL
    return minutes


def _library_local_paths(library, db: Session) -> list[str]:
    """获取库的本机可读路径（local 类型挂载 + paths 里的本机目录）"""
    paths = []
    # paths 里的本机目录（非 mount:// 开头）
    for raw in (getattr(library, "paths", "") or "").split(","):
        p = raw.strip()
        if p and not p.startswith("mount://") and os.path.isdir(p):
            paths.append(p)
    # mount_ids 引用的 local 类型挂载
    # 注意：按 AGENTS.md 教训，paths 用 mount://子目录时 mount_ids 应为空
    # 这里只处理 mount_ids 指向的 local 挂载的根
    try:
        mount_ids = [int(x.strip()) for x in (getattr(library, "mount_ids", "") or "").split(",") if x.strip().isdigit()]
    except (ValueError, AttributeError):
        mount_ids = []
    if mount_ids:
        mounts = db.query(em.StorageMount).filter(em.StorageMount.id.in_(mount_ids)).all()
        for m in mounts:
            if getattr(m, "mount_type", "") == "local" and getattr(m, "is_enabled", False):
                mp = getattr(m, "mount_path", "") or getattr(m, "local_path", "")
                if mp and os.path.isdir(mp):
                    paths.append(mp)
    return paths


MOUNT_PATH_PREFIX = "mount://"


def _library_mount_sources(library, db: Session) -> list[tuple[int, str]]:
    """库里引用的远程挂载：返回 ``[(mount_id, 挂载内相对目录), ...]``

    追新必须覆盖**远程**媒体源。生产实测全部库都是 ``mount://3/MoviePilot/...``
    （rclone RC），只查本机目录的旧实现等于一个库都没看——线程在跑、
    last_check 在更新，却永远发现不了新资源。
    """
    sources: list[tuple[int, str]] = []
    raw_paths = [p.strip() for p in (getattr(library, "paths", "") or "").split(",") if p.strip()]
    for p in raw_paths:
        if not p.startswith(MOUNT_PATH_PREFIX):
            continue
        rest = p[len(MOUNT_PATH_PREFIX):]
        mid, _, rel = rest.partition("/")
        if not mid.isdigit():
            continue
        sources.append((int(mid), "/" + rel.lstrip("/")))
    return sources


def _find_new_videos_remote(db: Session, mount_id: int, rel_dir: str,
                            since_ts: float) -> list[str]:
    """远程挂载（rclone RC）按 ModTime 找新增视频

    rclone ``/operations/list`` 递归列举会返回每个文件的 ``ModTime``（实测 848/848 全带），
    按时间窗口过滤比全量扫描快一个量级，也不会因为「上一轮扫过」而漏掉刚上传的文件。
    """
    from backend.emby_server.mount_rclone import rc_call

    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if mount is None or not getattr(mount, "is_enabled", False):
        return []
    cfg = mount_lib.parse_config(mount)
    if not cfg.get("rc_url"):
        # cli 模式或非 rclone 挂载：本实现只覆盖 rc（生产实际用法）
        return []
    fs = cfg.get("fs") or ""
    remote = (rel_dir or "/").lstrip("/")
    body = rc_call(
        cfg["rc_url"], "/operations/list",
        {"fs": fs, "remote": remote, "opt": {"recurse": True, "filesOnly": True}},
        username=cfg.get("rc_user", "") or "", password=cfg.get("rc_pass", "") or "",
    )
    items = (body or {}).get("list") or []
    found: list[str] = []
    for it in items:
        if not isinstance(it, dict) or it.get("IsDir"):
            continue
        name = str(it.get("Name") or "")
        if not name or os.path.splitext(name)[1].lower() not in VIDEO_EXTS:
            continue
        mt = it.get("ModTime")
        if not mt:
            continue
        try:
            ts = datetime.fromisoformat(str(mt).replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue
        if ts > since_ts:
            # RC 返回的 Path 相对 remote；用 rel 拼成库内绝对路径再挂 mount:// 前缀
            rel_path = f"/{remote.rstrip('/')}/{str(it.get('Path') or '').lstrip('/')}".replace("//", "/")
            found.append(f"{MOUNT_PATH_PREFIX}{mount_id}{rel_path}")
    return found


def _find_new_videos(paths: list[str], since_ts: float) -> list[str]:
    """找出 since_ts 之后新增/修改的视频文件（用 find -newermt，C 实现比 os.walk 快）"""
    import subprocess
    from datetime import datetime, timezone

    new_files = []
    since_str = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # 构建 find 的扩展名过滤：\( -iname "*.mp4" -o -iname "*.mkv" ... \)
    ext_args = []
    for i, ext in enumerate(sorted(VIDEO_EXTS)):
        if i > 0:
            ext_args.append("-o")
        ext_args.extend(["-iname", f"*{ext}"])

    for base in paths:
        try:
            cmd = ["find", base, "-type", "f", "-newermt", since_str, "("] + ext_args + [")", "-print"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                new_files.extend(line for line in result.stdout.strip().split("\n") if line)
            elif result.returncode != 0:
                logger.warning("[chase-new] find %s 失败: %s", base, result.stderr[:200])
        except subprocess.TimeoutExpired:
            logger.warning("[chase-new] find %s 超时（60s），跳过", base)
        except Exception as e:
            logger.warning("[chase-new] find %s 异常: %s", base, e)
    return new_files


def _check_once() -> None:
    """执行一轮检查"""
    db = SessionLocal()
    try:
        enabled = _get_config(db, CONFIG_ENABLED, "0") == "1"
        if not enabled:
            return

        interval = _parse_interval(_get_config(db, CONFIG_INTERVAL, str(DEFAULT_INTERVAL)))
        # 用 2 倍间隔作为 mtime 阈值，防漏检
        since_ts = time.time() - (interval * 2 * 60)

        # 解析监听的库
        lib_filter = _get_config(db, CONFIG_LIBRARIES, "").strip()
        query = db.query(em.Library).filter(em.Library.is_enabled == True)
        if lib_filter:
            try:
                ids = [int(x.strip()) for x in lib_filter.split(",") if x.strip().isdigit()]
                if ids:
                    query = query.filter(em.Library.id.in_(ids))
            except (ValueError, AttributeError):
                pass
        libraries = query.all()

        total_found = 0
        for lib in libraries:
            try:
                found_paths = _find_new_videos(_library_local_paths(lib, db), since_ts)
                for mid, rel in _library_mount_sources(lib, db):
                    try:
                        found_paths += _find_new_videos_remote(db, mid, rel, since_ts)
                    except Exception as exc:  # noqa: BLE001 — 单个挂载失败不影响其它库
                        logger.warning("[chase-new] 库《%s》远程挂载 %s 检查失败: %s",
                                       getattr(lib, "name", lib.id), mid, exc)
                if found_paths:
                    total_found += len(found_paths)
                    logger.info("[chase-new] 库《%s》发现 %d 个新文件，触发扫描",
                                getattr(lib, "name", lib.id), len(found_paths))
                    scan_queue.enqueue(lib, trigger="chase-new")
            except Exception as e:
                logger.error("[chase-new] 库《%s》检查失败: %s", getattr(lib, "id", "?"), e)

        _set_config(db, CONFIG_LAST_CHECK, datetime.now(timezone.utc).isoformat())
        _set_config(db, CONFIG_LAST_FOUND, str(total_found))
        if total_found:
            logger.info("[chase-new] 本轮共发现 %d 个新文件", total_found)
    except Exception as e:
        logger.error("[chase-new] 轮询异常: %s", e)
    finally:
        db.close()


def _watcher_loop() -> None:
    """轮询线程主循环"""
    logger.info("[chase-new] 追新线程启动")
    while True:
        try:
            db = SessionLocal()
            try:
                enabled = _get_config(db, CONFIG_ENABLED, "0") == "1"
                interval = _parse_interval(_get_config(db, CONFIG_INTERVAL, str(DEFAULT_INTERVAL)))
            finally:
                db.close()
            if enabled:
                _check_once()
            # 每 60 秒检查一次开关，间隔到了才真正轮询
            # 简化：直接按间隔 sleep，开关变化最多延迟一个周期
            time.sleep(interval * 60)
        except Exception as e:
            logger.error("[chase-new] 线程异常: %s", e)
            time.sleep(60)


def get_config(db: Session) -> dict:
    """追新当前配置（管理后台展示）"""
    return {
        "enabled": _get_config(db, CONFIG_ENABLED, "0") == "1",
        "interval": _parse_interval(_get_config(db, CONFIG_INTERVAL, str(DEFAULT_INTERVAL))),
        "libraries": _get_config(db, CONFIG_LIBRARIES, ""),
        "last_check": _get_config(db, CONFIG_LAST_CHECK, ""),
        "last_found": int(_get_config(db, CONFIG_LAST_FOUND, "0") or "0"),
    }


def save_config(db: Session, enabled: bool, interval: int, libraries: str = "") -> dict:
    """保存追新配置，立即生效"""
    minutes = _parse_interval(str(interval))
    _set_config(db, CONFIG_ENABLED, "1" if enabled else "0")
    _set_config(db, CONFIG_INTERVAL, str(minutes))
    # 清洗库 ID 列表：只保留数字
    clean_ids = ",".join(x.strip() for x in (libraries or "").split(",") if x.strip().isdigit())
    _set_config(db, CONFIG_LIBRARIES, clean_ids)
    logger.info("[chase-new] 配置已保存: enabled=%s interval=%d libraries=%s", enabled, minutes, clean_ids)
    return get_config(db)


def start_chase_new_watcher() -> None:
    """启动追新线程（幂等）"""
    global _WATCHER_STARTED
    with _WATCHER_LOCK:
        if _WATCHER_STARTED:
            return
        _WATCHER_STARTED = True
    t = threading.Thread(target=_watcher_loop, daemon=True, name="chase-new-watcher")
    t.start()
    logger.info("[chase-new] 已启动")
