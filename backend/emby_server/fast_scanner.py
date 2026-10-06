"""极速扫描器：rclone RC 接口 + 批量写库，目标 30 分钟扫完 20 万文件

设计原则（简洁/高效/稳定）：
- 只做文件清单同步：路径+大小+修改时间，不读 NFO、不找海报、不 ffprobe
- rclone RC 接口一次递归拉清单，不用 FUSE 逐目录爬
- 内存比对算新增/变化/删除，批量写库（一次 1000 条）
- NFO/海报/字幕/ffprobe 全延后，扔给 enrich_worker/probe_worker
- 本模块是唯一的扫描器实现（2026-10-05 起替代 scanner.py 的旧扫描体）
- 进度直接调 scan_progress 上报，不再用 monkey-patch

作者：Aetrix 团队
日期：2026-10-05
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger("fast_scanner")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# rclone RC 接口地址（aetrix-rclone 容器）
RCLONE_RC_URL = os.getenv("RCLONE_RC_URL", "http://127.0.0.1:5572")
# 批量写库大小
FAST_SCAN_BATCH = max(100, int(os.getenv("FAST_SCAN_BATCH", "1000") or 1000))
# 删除保护（从旧 scanner._removal_budget 移植）：防止来源整体不可读时误删整库
# - 本轮一个文件都没看到，但库里有条目 → 禁止清理
# - 预计删除数超过阈值（50% 或 20 条取大） → 禁止清理
REMOVAL_MAX_RATIO = float(os.getenv("SCAN_REMOVAL_MAX_RATIO", "0.5") or 0.5)
REMOVAL_MAX_ABSOLUTE = max(1, int(os.getenv("SCAN_REMOVAL_MAX_ABSOLUTE", "20") or 20))

# 视频扩展名白名单（与老扫描器一致）
VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m2ts",
    ".ts", ".mpg", ".mpeg", ".rmvb", ".rm", ".asf", ".3gp", ".f4v",
}


@dataclass
class FastScanFile:
    """rclone 列出来的一个文件"""
    path: str       # 完整路径（如 /mnt/mp/nastool/...）
    name: str       # 文件名
    size: int       # 字节
    mtime: float    # 修改时间戳


@dataclass
class FastScanStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0


# ---------------------------------------------------------------------------
# 缓存层（Redis）
# ---------------------------------------------------------------------------

# rclone 列表缓存 TTL（秒）：5 分钟
RCLONE_CACHE_TTL = max(60, int(os.getenv("RCLONE_CACHE_TTL", "300") or 300))
# Redis 连接
REDIS_HOST = os.getenv("REDIS_HOST", "aetrix-redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379") or 6379)

_redis_client = None


def _get_redis():
    """获取 Redis 客户端（懒加载，失败返回 None）"""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT,
                decode_responses=True, socket_timeout=5,
            )
            _redis_client.ping()
        except Exception as exc:
            logger.warning("Redis 连接失败，缓存禁用: %s", exc)
            _redis_client = False  # 标记为不可用，避免重复尝试
    return _redis_client or None


def _rclone_cache_key(fs: str, remote: str, recurse: bool) -> str:
    """rclone 列表缓存 key"""
    raw = f"fastscan:rclone:{fs}:{remote}:{recurse}"
    return "fastscan:rclone:" + hashlib.md5(raw.encode("utf-8")).hexdigest()


def _rclone_list_cached(fs: str, remote: str, recurse: bool = True) -> list[dict]:
    """带 Redis 缓存的 rclone 列表（TTL 5 分钟）

    缓存失效策略：
    - TTL 5 分钟自动过期（文件变化最多 5 分钟后可见）
    - 手动扫描时可通过环境变量 RCLONE_CACHE_TTL=0 禁用缓存
    """
    if RCLONE_CACHE_TTL <= 0:
        return _rclone_list(fs, remote, recurse)

    r = _get_redis()
    if r is None:
        return _rclone_list(fs, remote, recurse)

    key = _rclone_cache_key(fs, remote, recurse)
    try:
        cached = r.get(key)
        if cached:
            logger.info("rclone 缓存命中: %s", key[:40])
            return json.loads(cached)
    except Exception as exc:
        logger.warning("Redis 读缓存失败: %s", exc)

    entries = _rclone_list(fs, remote, recurse)
    try:
        r.setex(key, RCLONE_CACHE_TTL, json.dumps(entries))
    except Exception as exc:
        logger.warning("Redis 写缓存失败: %s", exc)
    return entries


def invalidate_rclone_cache(fs: str = None, remote: str = None) -> int:
    """手动失效 rclone 缓存（文件变化时调用）

    Args:
        fs: 指定 fs 则只清该 fs 的缓存，None 则清全部
        remote: 指定 remote 则只清该路径，None 则按 fs 清

    Returns:
        清除的 key 数量
    """
    r = _get_redis()
    if r is None:
        return 0
    try:
        if fs and remote:
            # 精确清除一个 key（需要 recurse=True/False 都清）
            count = 0
            for rec in (True, False):
                key = _rclone_cache_key(fs, remote, rec)
                count += r.delete(key)
            return count
        else:
            # 模糊清除
            pattern = "fastscan:rclone:*"
            keys = r.keys(pattern)
            if keys:
                return r.delete(*keys)
            return 0
    except Exception as exc:
        logger.warning("Redis 清缓存失败: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# rclone RC 接口
# ---------------------------------------------------------------------------

def _rclone_list(fs: str, remote: str, recurse: bool = True) -> list[dict]:
    """调 rclone RC 接口列目录

    Args:
        fs: rclone remote 名（如 "MP:"）
        remote: remote 下的路径（如 "nastool/剧集/国产剧"）
        recurse: 是否递归

    Returns:
        文件/目录信息列表，每项含 Path/Name/Size/ModTime/IsDir
    """
    url = f"{RCLONE_RC_URL}/operations/list"
    payload = json.dumps({
        "fs": fs,
        "remote": remote,
        "opt": {"recurse": recurse, "filesOnly": False},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
            return data.get("list", [])
    except Exception as exc:
        logger.error("rclone list 失败 fs=%s remote=%s: %s", fs, remote, exc)
        # 关键安全：rclone 失败必须抛异常，不能返回空列表
        # 否则调用方会误以为目录是空的，把库里所有文件标记为删除
        raise RuntimeError(f"rclone list 失败 fs={fs} remote={remote}: {exc}") from exc


def _parse_rclone_time(t: str) -> float:
    """解析 rclone 返回的时间字符串为时间戳"""
    if not t:
        return 0.0
    try:
        # 格式如 "2024-01-15T10:30:00.000Z"
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 路径映射：库路径 -> rclone fs + remote
# ---------------------------------------------------------------------------

# 挂载点到 rclone remote 的映射（与生产环境一致）
MOUNT_TO_RCLONE = {
    "/mnt/mp": "MP:",
    "/mnt/paul": "paul_emby:",
}


def _split_rclone_path(full_path: str) -> Optional[tuple[str, str]]:
    """把完整路径拆成 (fs, remote)

    如 "/mnt/mp/nastool/剧集/国产剧" -> ("MP:", "nastool/剧集/国产剧")
    """
    for mount, fs in MOUNT_TO_RCLONE.items():
        if full_path.startswith(mount + "/") or full_path == mount:
            remote = full_path[len(mount):].lstrip("/")
            return fs, remote
    return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

# 原盘结构目录（复用老代码 backend/emby_server/disc_filter.py 的口径）：
# BDMV/STREAM 里的 .m2ts 是码流片段，不能当独立条目入库
# （生产教训：一次扫描产出 3966 条这种碎片，占 movie 总数的 69%）
DISC_STRUCTURE_DIRS = frozenset({
    "BDMV", "VIDEO_TS", "CERTIFICATE", "AUXDATA", "SSIF",
})


def _is_disc_file(path: str) -> bool:
    """路径是否在原盘结构目录下（如 /xxx/BDMV/STREAM/00000.m2ts）"""
    upper = path.upper()
    for d in DISC_STRUCTURE_DIRS:
        if f"/{d}/" in upper:
            return True
    return False


def _collect_files(paths: tuple[str, ...]) -> list[FastScanFile]:
    """从所有库路径收集文件清单"""
    files: list[FastScanFile] = []
    for path in paths:
        # 本地路径：直接走文件系统（CI 冒烟测试用 /tmp 路径）
        import os as _os
        if _os.path.isdir(path):
            for _root, _dirs, _files in _os.walk(path):
                for _fn in _files:
                    _ext = _os.path.splitext(_fn)[1].lower()
                    if _ext not in VIDEO_EXTS:
                        continue
                    _full = _os.path.join(_root, _fn)
                    files.append(FastScanFile(path=_full, name=_fn, size=_os.path.getsize(_full), mtime=_os.path.getmtime(_full)))
            continue
        split = _split_rclone_path(path)
        if split is None:
            logger.warning("路径 %s 不在已知挂载映射中，跳过", path)
            continue
        fs, remote = split
        logger.info("rclone 列目录: fs=%s remote=%s", fs, remote)
        entries = _rclone_list_cached(fs, remote, recurse=True)
        # entries 中的 Path 是完整 remote 路径（如 "nastool/演唱会/xxx.mp4"），
        # 去掉 remote 前缀后拼到库路径上
        prefix = remote.rstrip("/") + "/" if remote else ""
        for e in entries:
            if e.get("IsDir"):
                continue
            name = e.get("Name", "")
            ext = os.path.splitext(name)[1].lower()
            if ext not in VIDEO_EXTS:
                continue
            rpath = e.get("Path", "")
            if prefix and rpath.startswith(prefix):
                rpath = rpath[len(prefix):]
            full = os.path.join(path, rpath)
            # 原盘碎文件跳过（BDMV/STREAM/*.m2ts 等）
            if _is_disc_file(full):
                continue
            files.append(FastScanFile(
                path=full,
                name=name,
                size=int(e.get("Size", 0) or 0),
                mtime=_parse_rclone_time(e.get("ModTime", "")),
            ))
        logger.info("路径 %s: 找到 %d 个视频文件", path, len(
            [f for f in files if f.path.startswith(path)]))
    return files


def _normalize_name(name: str) -> str:
    """归一化名称用于去重：小写、去空格、去常见符号"""
    import re
    n = (name or "").lower().strip()
    # 去掉年份括号、清晰度标签等
    n = re.sub(r"\(\d{4}\)", "", n)
    n = re.sub(r"[\s\.\-_]+", "", n)
    return n


def _dedupe_by_name_year(files: list[FastScanFile], parse_media_filename,
                         lib_type: str) -> list[FastScanFile]:
    """同名同年去重（用户 2026-10-05 要求）

    两个挂载（/mnt/mp 和 /mnt/paul）有同名同年资源时只保留一个，
    优先保留 /mnt/mp 的（主挂载）。
    """
    # 按挂载优先级排序：/mnt/mp 优先
    def _priority(f: FastScanFile) -> int:
        return 0 if f.path.startswith("/mnt/mp/") else 1

    seen: dict[tuple[str, Optional[int]], FastScanFile] = {}
    for f in sorted(files, key=_priority):
        try:
            parsed = parse_media_filename(f.path, lib_type)
            key = (_normalize_name(parsed.get("name", "")), parsed.get("year"), parsed.get("season"), parsed.get("episode"))
        except Exception:
            # 解析失败的用文件路径做 key（不去重）
            key = (f.path, None)
        if key not in seen:
            seen[key] = f
        # 已存在的跳过（保留优先挂载的）
    deduped = list(seen.values())
    removed = len(files) - len(deduped)
    if removed:
        logger.info("[fast] 同名同年去重：去掉 %d 个重复", removed)
    return deduped


def scan_library_fast(db, library, snapshot) -> dict:
    """极速扫描单个媒体库

    Args:
        db: SQLAlchemy Session
        library: Library ORM 对象
        snapshot: LibrarySnapshot（复用老代码的）

    Returns:
        stats 字典
    """
    from backend.emby_server import models as emby_models
    from backend.emby_server.scanner import (
        parse_media_filename, item_guid, LibrarySnapshot,
    )

    stats = FastScanStats()
    lib_id = library.id
    collection_type = getattr(library, "collection_type", "movies") or "movies"
    # tvshows -> tv, movies -> movie（parse_media_filename 要的格式）
    lib_type = "tvshows" if "tv" in collection_type.lower() else "movies"

    # 1. 拉清单
    # mount_ids 兼容：复用 mounts.library_sources 的口径（paths + mount_ids），
    # 1. 拉清单（snapshot.paths；本地路径直接走文件系统）
    # 1. 拉清单：paths 为空但 mount_ids 有值时（如部署自检），
    # 用 mounts.library_sources 解析出实际路径（对齐旧 scanner）。
    _paths = tuple(snapshot.paths)
    if not _paths and getattr(snapshot, "mount_ids", None):
        from backend.emby_server import mounts as _mounts
        _sources, _failed = _mounts.library_sources(library, db)
        _sp = tuple(s.path for s in _sources if getattr(s, path, None))
        if _sp:
            _paths = _sp
    files = _collect_files(_paths)
    logger.info("[fast] 共 %d 个视频文件", len(files))
    from backend.emby_server import scan_progress as _progress
    _progress.set_enumerated(lib_id, len(files))

    # 1b. 同名同年去重（用户 2026-10-05 要求：两个挂载的同名同年资源合并）
    # 按 (归一化名称, 年份) 去重，保留第一个（优先 /mnt/mp 的）
    files = _dedupe_by_name_year(files, parse_media_filename, lib_type)
    logger.info("[fast] 去重后 %d 个文件", len(files))
    _progress.set_enumerated(lib_id, len(files))
    _progress.set_phase(lib_id, "processing")

    # 2. 加载已有（一次查进内存）
    # 包括已软删除的：如果文件又出现了，需要取消删除。
    # 注意：soft_delete 的 ORM 钩子默认过滤掉 deleted_at 非空的行，
    # 这里必须用 include_deleted() 才能看到它们，否则复活会变 INSERT 撞 guid。
    MI = emby_models.MediaItem
    existing: dict[str, tuple[int, int, bool]] = {}  # file_path -> (id, size, is_deleted)
    from backend.emby_server import soft_delete as _soft_delete
    with _soft_delete.include_deleted():
        _existing_rows = db.query(
            MI.id, MI.file_path, MI.size, MI.deleted_at).filter(
            MI.library_id == lib_id).all()
    for item_id, file_path, size, deleted_at in _existing_rows:
        if file_path:
            existing[file_path] = (item_id, size or 0, deleted_at is not None)
    logger.info("[fast] 库里已有 %d 条", len(existing))

    # 3. 比对
    seen_paths = set()
    to_add: list[FastScanFile] = []
    to_update: list[tuple[int, FastScanFile]] = []  # (id, file)
    to_undelete: list[int] = []
    for _fi, f in enumerate(files):
        seen_paths.add(f.path)
        if _fi % 50 == 0:
            _progress.note_processed(lib_id, f.path)
        if f.path not in existing:
            to_add.append(f)
        else:
            item_id, old_size, is_deleted = existing[f.path]
            if is_deleted:
                # 文件又出现了：取消软删除
                to_undelete.append(item_id)
                if old_size != f.size:
                    to_update.append((item_id, f))
            elif old_size != f.size:
                to_update.append((item_id, f))
            else:
                stats.skipped += 1

    # 删除：库里有但文件清单里没有的（只处理未删除的）
    to_remove_ids = [
        item_id for fp, (item_id, _, is_deleted) in existing.items()
        if fp not in seen_paths and not is_deleted
    ]

    logger.info(
        "[fast] 新增=%d 更新=%d 删除=%d 跳过=%d",
        len(to_add), len(to_update), len(to_remove_ids), stats.skipped,
    )

    # 4. 批量写库
    now = datetime.now()

    # 4a. 新增（含层级处理）
    if to_add:
        _bulk_insert(db, MI, to_add, lib_id, lib_type,
                     parse_media_filename, item_guid, now, stats)

    # 4b. 更新（只更新 size，批量）
    for chunk_start in range(0, len(to_update), FAST_SCAN_BATCH):
        chunk = to_update[chunk_start:chunk_start + FAST_SCAN_BATCH]
        # 用 bulk_update_mappings 批量更新
        db.bulk_update_mappings(MI, [
            {"id": item_id, "size": f.size} for item_id, f in chunk
        ])
        db.commit()
        stats.updated += len(chunk)

    # 4b2. 取消软删除（文件又出现了）
    for chunk_start in range(0, len(to_undelete), FAST_SCAN_BATCH):
        chunk = to_undelete[chunk_start:chunk_start + FAST_SCAN_BATCH]
        db.query(MI).filter(MI.id.in_(chunk)).update(
            {"deleted_at": None}, synchronize_session=False)
        db.commit()

    # 4c. 删除（软删除）：先过删除预算，来源整体不可读时禁止清理
    _progress.set_phase(lib_id, "cleanup")
    removal_skipped = False
    removal_skip_reason = ""
    existing_visible = len([1 for _, _, is_deleted in existing.values() if not is_deleted])
    if existing_visible > 0:
        if len(files) == 0:
            removal_skipped = True
            removal_skip_reason = (
                f"本轮一个文件都没看到，但库里有 {existing_visible} 条未删除条目——"
                f"判定来源整体不可用，本轮禁止清理"
            )
        else:
            limit = max(REMOVAL_MAX_ABSOLUTE, int(existing_visible * REMOVAL_MAX_RATIO))
            if len(to_remove_ids) >= limit:
                removal_skipped = True
                removal_skip_reason = (
                    f"本轮只看到 {len(files)} 个文件，库里有 {existing_visible} 条，"
                    f"预计要删 {len(to_remove_ids)} 条（阈值 {limit}）——"
                    f"超过阈值，判定来源整体不可用，本轮禁止清理"
                )
    if removal_skipped:
        logger.warning("[fast] 删除保护拦下清理: %s", removal_skip_reason)
    else:
        for chunk_start in range(0, len(to_remove_ids), FAST_SCAN_BATCH):
            chunk = to_remove_ids[chunk_start:chunk_start + FAST_SCAN_BATCH]
            db.query(MI).filter(MI.id.in_(chunk)).update(
                {"deleted_at": now}, synchronize_session=False)
            db.commit()
            stats.removed += len(chunk)

    # 更新库的扫描状态
    library.is_scanning = False
    db.commit()

    result = {
        "added": stats.added,
        "updated": stats.updated,
        "removed": stats.removed,
        "skipped": stats.skipped,
    }
    if removal_skipped:
        result["removal_skipped"] = True
        result["failed_roots"] = [removal_skip_reason]
    return result


def _bulk_insert(db, MI, files: list[FastScanFile], lib_id: int,
                 lib_type: str, parse_media_filename, item_guid,
                 now: datetime, stats: FastScanStats) -> None:
    """批量插入新文件（含 series/season 层级）"""
    # 先解析所有文件，建出需要的 series/season
    # series_guid -> {name, year}
    series_needed: dict[str, dict] = {}
    # season_guid -> {series_guid, season_no}
    season_needed: dict[str, dict] = {}
    # 待插入的 episode/movie 列表
    items_to_insert: list[dict] = []

    for f in files:
        parsed = parse_media_filename(f.path, lib_type)
        season_no = parsed.get("season")
        episode_no = parsed.get("episode")

        if season_no is not None:
            # 剧集：算 series_guid 和 season_guid
            # series 目录 = 季目录的父目录
            dirpath = os.path.dirname(f.path)
            # 如果目录名像 Season/S01/第1季，往上一层
            basename = os.path.basename(dirpath)
            if re.match(r"^(season|s)\s*\d+$", basename, re.I) or \
               re.match(r"^第\d+季$", basename):
                series_dir = os.path.dirname(dirpath)
            else:
                series_dir = dirpath
            s_guid = item_guid(series_dir)
            se_guid = item_guid(f"{s_guid}:S{season_no:02d}")

            if s_guid not in series_needed:
                series_needed[s_guid] = {
                    "name": parsed["name"],
                    "year": parsed.get("year"),
                }
            if se_guid not in season_needed:
                season_needed[se_guid] = {
                    "series_guid": s_guid,
                    "season_no": season_no,
                }

            e_guid = item_guid(f.path)
            items_to_insert.append({
                "guid": e_guid,
                "library_id": lib_id,
                "item_type": "episode",
                "name": parsed["name"],
                "sort_name": parsed["name"].lower(),
                "production_year": parsed.get("year"),
                "season_number": season_no,
                "episode_number": episode_no,
                "file_path": f.path,
                "size": f.size,
                "container": os.path.splitext(f.name)[1].lower().lstrip("."),
                "date_added": now,
                # 探测/补全延后
                "probe_status": "pending",
                "probe_priority": 0,
                "enrich_status": "pending",
                "_series_guid": s_guid,
                "_season_guid": se_guid,
            })
        else:
            # 电影
            e_guid = item_guid(f.path)
            items_to_insert.append({
                "guid": e_guid,
                "library_id": lib_id,
                "item_type": "movie",
                "name": parsed["name"],
                "sort_name": parsed["name"].lower(),
                "production_year": parsed.get("year"),
                "file_path": f.path,
                "size": f.size,
                "container": os.path.splitext(f.name)[1].lower().lstrip("."),
                "date_added": now,
                "probe_status": "pending",
                "probe_priority": 0,
                "enrich_status": "pending",
                "_series_guid": None,
                "_season_guid": None,
            })

    # 查已有的 series/season guid（避免重复插入）
    all_parent_guids = list(series_needed.keys()) + list(season_needed.keys())
    existing_guids = set()
    if all_parent_guids:
        for chunk_start in range(0, len(all_parent_guids), FAST_SCAN_BATCH):
            chunk = all_parent_guids[chunk_start:chunk_start + FAST_SCAN_BATCH]
            for (g,) in db.query(MI.guid).filter(MI.guid.in_(chunk)).all():
                existing_guids.add(g)

    # 插入 series（不存在的）
    guid_to_id: dict[str, int] = {}
    series_to_insert = [
        {
            "guid": g,
            "library_id": lib_id,
            "item_type": "series",
            "name": info["name"],
            "sort_name": info["name"].lower(),
            "production_year": info["year"],
            "date_added": now,
            "probe_status": "done",  # 无文件可探测
            "enrich_status": "pending",
        }
        for g, info in series_needed.items()
        if g not in existing_guids
    ]
    for chunk_start in range(0, len(series_to_insert), FAST_SCAN_BATCH):
        chunk = series_to_insert[chunk_start:chunk_start + FAST_SCAN_BATCH]
        if chunk:
            db.bulk_insert_mappings(MI, chunk)
            db.commit()

    # 查 series 的 id（批量，避免 N+1）
    series_guids = list(series_needed.keys())
    for chunk_start in range(0, len(series_guids), FAST_SCAN_BATCH):
        chunk = series_guids[chunk_start:chunk_start + FAST_SCAN_BATCH]
        for row_id, row_guid in db.query(MI.id, MI.guid).filter(
                MI.guid.in_(chunk)).all():
            guid_to_id[row_guid] = row_id
    season_to_insert = []
    for g, info in season_needed.items():
        if g in existing_guids:
            continue
        series_id = guid_to_id.get(info["series_guid"])
        if series_id is None:
            continue
        season_to_insert.append({
            "guid": g,
            "library_id": lib_id,
            "item_type": "season",
            "name": f"第 {info['season_no']} 季",
            "parent_id": series_id,
            "series_id": series_id,
            "season_number": info["season_no"],
            "date_added": now,
            "probe_status": "done",
            "enrich_status": "pending",
        })
    for chunk_start in range(0, len(season_to_insert), FAST_SCAN_BATCH):
        chunk = season_to_insert[chunk_start:chunk_start + FAST_SCAN_BATCH]
        if chunk:
            db.bulk_insert_mappings(MI, chunk)
            db.commit()

    # 查 season 的 id（批量，用于 episode 的 parent_id/series_id）
    season_guids = list(season_needed.keys())
    for chunk_start in range(0, len(season_guids), FAST_SCAN_BATCH):
        chunk = season_guids[chunk_start:chunk_start + FAST_SCAN_BATCH]
        for row_id, row_guid in db.query(MI.id, MI.guid).filter(
                MI.guid.in_(chunk)).all():
            guid_to_id[row_guid] = row_id

    # 插入 episode/movie
    # 去掉内部用的 _series_guid/_season_guid，加上 parent_id/series_id
    final_items = []
    for item in items_to_insert:
        s_guid = item.pop("_series_guid")
        se_guid = item.pop("_season_guid")
        if se_guid:
            item["parent_id"] = guid_to_id.get(se_guid)
            item["series_id"] = guid_to_id.get(s_guid)
        final_items.append(item)

    for chunk_start in range(0, len(final_items), FAST_SCAN_BATCH):
        chunk = final_items[chunk_start:chunk_start + FAST_SCAN_BATCH]
        if chunk:
            # 用 upsert 避免 guid 冲突（INSERT ... ON CONFLICT DO NOTHING）
            _bulk_upsert(db, MI, chunk)
            db.commit()
            stats.added += len(chunk)


def _bulk_upsert(db, MI, mappings: list[dict]) -> None:
    """批量 upsert（PostgreSQL 用 ON CONFLICT DO NOTHING）"""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        # 按 guid 去重（同一批里可能有重复）
        seen = set()
        deduped = []
        for m in mappings:
            if m["guid"] not in seen:
                seen.add(m["guid"])
                deduped.append(m)
        if not deduped:
            return
        stmt = pg_insert(MI).values(deduped)
        stmt = stmt.on_conflict_do_nothing(index_elements=["guid"])
        db.execute(stmt)
    else:
        # 非 PG：逐条 add（测试环境用）
        for m in mappings:
            db.add(MI(**m))
# ---------------------------------------------------------------------------
# 唯一对外扫描入口（与旧 scanner.scan_library_sync 同签名）
# ---------------------------------------------------------------------------

def scan_library_sync(db, library, snapshot=None, trigger: str = "manual") -> dict:
    """扫描单个媒体库（同步入口，极速实现）

    与旧 ``scanner.scan_library_sync`` 同签名：ScanRun 流水、trigger 归一化、
    进程内互斥（同一媒体库同时只跑一个）语义保持不变；实际扫描走
    ``scan_library_fast``（不 ffprobe、不读 NFO，纯清单同步）。

    调用方（scan_queue / admin_scrape / 手动触发）无需改动。
    """
    from backend.emby_server.scanner import (
        LibrarySnapshot,
        _acquire_scan,
        _release_scan,
        begin_scan,
        fail_scan,
        finish_scan,
    )

    snap = snapshot or LibrarySnapshot.of(library)
    # 进程内互斥：重复任务在这里被拒绝，不会写库、也不会启动扫描
    _acquire_scan(snap.library_id)
    try:
        run_id = begin_scan(db, library, trigger)
        started = time.perf_counter()
        try:
            stats = scan_library_fast(db, library, snap)
        except Exception as exc:  # noqa: BLE001 — 异常落库后再原样抛给调用方
            logger.exception("[fast] 媒体库「%s」扫描失败", snap.name)
            fail_scan(db, library, exc, run_id,
                      duration_ms=int((time.perf_counter() - started) * 1000))
            raise
        stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
        finish_scan(db, library, stats, run_id)
        return stats
    finally:
        # 无论成功、失败还是异常，都释放进程内占位
        _release_scan(snap.library_id)
