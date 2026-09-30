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

# 追新远端列举的超时（秒）。通用挂载默认 20s（MOUNT_TIMEOUT），
# 递归列举上万个文件的库会超时——生产实测国产剧 1.4 万文件。追新是低频后台任务，
# 给足时间换取不漏检。
CHASE_NEW_RC_TIMEOUT = float(os.getenv("CHASE_NEW_RC_TIMEOUT", "180"))

_WATCHER_STARTED = False
_WATCHER_LOCK = threading.Lock()


def _get_config(db: Session, key: str, default: str = "") -> str:
    """统一读（只许这一套）：daemon 轮询走直查，永远最新"""
    from backend.integrations import store
    return store.read_value(db, key, default)


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


def _rc_list(mount, cfg: dict, remote: str, *, recurse: bool, files_only: bool = True):
    """调一次 rclone RC 列举（统一超时与凭据口径）"""
    from backend.emby_server.mount_rclone import rc_call

    opt: dict = {"filesOnly": files_only}
    if recurse:
        opt["recurse"] = True
    body = rc_call(
        cfg["rc_url"], "/operations/list",
        {"fs": cfg.get("fs") or "", "remote": remote, "opt": opt},
        username=cfg.get("rc_user", "") or "", password=cfg.get("rc_pass", "") or "",
        # 通用挂载超时（默认 20s）对大库不够：国产剧 1.4 万个文件会超时。
        timeout=CHASE_NEW_RC_TIMEOUT,
    )
    return (body or {}).get("list") or []


def _mod_ts(entry) -> float:
    mt = (entry or {}).get("ModTime")
    if not mt:
        return 0.0
    try:
        return datetime.fromisoformat(str(mt).replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _find_new_videos_remote(db: Session, mount_id: int, rel_dir: str,
                            since_ts: float) -> list[str]:
    """远程挂载（rclone RC）按 ModTime 找新增视频

    直接对整库递归列举在生产是走不通的：国产剧 1.4 万个文件，rclone RC 要几分钟，
    超过任何合理超时，而且 11 个库串行跑一轮远超轮询间隔（每轮都超时）。

    改成**两级**：先只列顶层（一次请求、几百个目录，每个都带 ModTime），
    再对每个顶层目录列一层子目录（季级），只对「ModTime 落在窗口内」的季级
    子目录递归。实测顶层 402 个目录全部带 ModTime，正常情况下每轮只递归
    最近变动的少数几个季目录——成本从上万文件降到几十个。

    **不能在顶层按 mtime 过滤**：新出一集只改动 ``Season/`` 子目录的 mtime，
    顶层剧集目录的 mtime 不变（rclone/Drive 只更新直接父目录）。如果在顶层
    按 mtime 筛，"老剧出新集"（追新最主要的场景）会被漏掉。
    """
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if mount is None or not getattr(mount, "is_enabled", False):
        return []
    cfg = mount_lib.parse_config(mount)
    if not cfg.get("rc_url"):
        # cli 模式或非 rclone 挂载：本实现只覆盖 rc（生产实际用法）
        return []
    remote = (rel_dir or "/").lstrip("/")

    try:
        top = _rc_list(mount, cfg, remote, recurse=False, files_only=False)
    except Exception as exc:  # noqa: BLE001 — 顶层列不出来就跳过该库，不拖垮整轮
        logger.warning("[chase-new] 列 %s 顶层失败: %s", remote, exc)
        return []

    base = remote.rstrip("/")

    def _mount_url(*parts: str) -> str:
        # 拼 mount:// 路径：逐段 strip（不能对整串做 replace，
        # 那会把 mount:// 前缀里的双斜杠也去掉，得到 mount:/3/… 的错路径）
        rel = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
        return f"{MOUNT_PATH_PREFIX}{mount_id}/{base}/{rel}" if base else f"{MOUNT_PATH_PREFIX}{mount_id}/{rel}"

    found: list[str] = []
    for it in top:
        if not isinstance(it, dict):
            continue
        name = str(it.get("Name") or "")
        if not it.get("IsDir"):
            # 顶层散片
            if (os.path.splitext(name)[1].lower() in VIDEO_EXTS
                    and _mod_ts(it) > since_ts):
                found.append(_mount_url(name))
            continue
        # 顶层目录（剧集）：不按 mtime 过滤，直接列第二级（季目录/散文件）
        show_path = str(it.get("Path") or name)
        try:
            subs = _rc_list(mount, cfg, f"{base}/{show_path}" if base else show_path,
                            recurse=False, files_only=False)
        except Exception as exc:  # noqa: BLE001 — 单个剧集目录失败不影响其它
            logger.warning("[chase-new] 列 %s 第二级失败: %s", show_path, exc)
            continue
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            sub_name = str(sub.get("Name") or "")
            sub_path = str(sub.get("Path") or sub_name)
            if not sub.get("IsDir"):
                # 剧集目录下直接放视频（无季目录结构）
                if (os.path.splitext(sub_name)[1].lower() in VIDEO_EXTS
                        and _mod_ts(sub) > since_ts):
                    found.append(_mount_url(show_path, sub_path))
                continue
            if _mod_ts(sub) <= since_ts:
                continue
            # 季目录在窗口内变动：递归找新视频
            try:
                items = _rc_list(mount, cfg, f"{base}/{show_path}/{sub_path}" if base
                                 else f"{show_path}/{sub_path}",
                                 recurse=True, files_only=True)
            except Exception as exc:  # noqa: BLE001 — 单个季目录失败不影响其它
                logger.warning("[chase-new] 递归列 %s/%s 失败: %s", show_path, sub_path, exc)
                continue
            for fitem in items:
                if not isinstance(fitem, dict) or fitem.get("IsDir"):
                    continue
                fname = str(fitem.get("Name") or "")
                if not fname or os.path.splitext(fname)[1].lower() not in VIDEO_EXTS:
                    continue
                if _mod_ts(fitem) <= since_ts:
                    continue
                # 递归结果的 Path 是相对被递归目录的
                fpath = str(fitem.get("Path") or "").lstrip("/")
                found.append(_mount_url(show_path, sub_path, fpath))
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
