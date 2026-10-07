"""极速扫描器：rclone RC 接口 + 批量写库，目标 30 分钟扫完 20 万文件

设计原则（简洁/高效/稳定）：
- 只做文件清单同步：路径+大小+修改时间，不读 NFO、不找海报、不 ffprobe
- rclone RC 接口一次递归拉清单，不用 FUSE 逐目录爬
- 内存比对算新增/变化/删除，批量写库（一次 1000 条）
- NFO/海报/字幕/ffprobe 全延后，扔给 enrich_worker/probe_worker
- 老 scanner.py 一个字符不动，本模块独立
- 环境变量 USE_FAST_SCANNER=1 开启，默认关闭

作者：Aetrix 团队
日期：2026-10-05
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backend.emby_server.filename_meta import parse_filename, resolution_to_wh
from backend.emby_server.pinyin_sort import make_sort_name

logger = logging.getLogger("fast_scanner")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# rclone RC 接口地址（aetrix-rclone 容器）
RCLONE_RC_URL = os.getenv("RCLONE_RC_URL", "http://127.0.0.1:5572")
# 批量写库大小
FAST_SCAN_BATCH = max(100, int(os.getenv("FAST_SCAN_BATCH", "1000") or 1000))
# 是否启用（默认关闭）
USE_FAST_SCANNER = (os.getenv("USE_FAST_SCANNER", "0") or "0").strip().lower() \
    not in {"0", "false", "no", "off"}

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
    # Drive file_id（改名/移动不变）：改名识别用。rclone lsjson 的 ID 字段。
    file_id: str = ""


@dataclass
class FastScanStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    skipped_unchanged: int = 0  # 增量扫描：mtime+size 未变更而跳过的文件数


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
                file_id=str(e.get("ID", "") or ""),
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
            key = (_normalize_name(parsed.get("name", "")), parsed.get("year"))
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
    logger.info("[fast] 库 %s(%d) 开始拉清单", library.name, lib_id)
    files = _collect_files(snapshot.paths)
    logger.info("[fast] 共 %d 个视频文件", len(files))

    # 2. 加载已有（一次查进内存）——必须在增量过滤之前，过滤要读它
    # 包括已软删除的：如果文件又出现了，需要取消删除
    MI = emby_models.MediaItem
    # file_path -> (id, size, mtime, is_deleted, drive_file_id)
    existing: dict[str, tuple] = {}
    # drive_file_id -> (id, file_path)：改名/移动识别用
    existing_by_fid: dict[str, tuple[int, str]] = {}
    for item_id, file_path, size, mtime, deleted_at, drive_fid in db.query(
            MI.id, MI.file_path, MI.size, MI.file_mtime, MI.deleted_at,
            MI.drive_file_id).filter(
            MI.library_id == lib_id).all():
        if file_path:
            existing[file_path] = (item_id, size or 0, mtime or 0,
                                   deleted_at is not None, drive_fid or "")
        if drive_fid:
            existing_by_fid[drive_fid] = (item_id, file_path or "")
    logger.info("[fast] 库里已有 %d 条", len(existing))

    # 1b. 增量过滤（v2.50.0）：mtime+size 未变且未删除的文件直接跳过
    # 用户抱怨"点一次扫描每次都要重新开始"——之前全量文件都要过 parse_media_filename
    # mtime 为 0（老数据未回填）时视为已变更，走一次全量比对后回填 mtime
    all_paths = set(f.path for f in files)  # 保留全量路径，供删除检测
    changed_files: list[FastScanFile] = []
    for f in files:
        if f.path in existing:
            _eid, old_size, old_mtime, is_deleted, _fid = existing[f.path]
            if (not is_deleted and old_mtime and old_size == f.size
                    and abs(f.mtime - old_mtime) < 1.0):
                stats.skipped_unchanged += 1
                continue
        changed_files.append(f)
    logger.info("[fast] 增量过滤：跳过 %d 个未变更，%d 个需处理",
                stats.skipped_unchanged, len(changed_files))

    # 1c. 同名同年去重（用户 2026-10-05 要求：两个挂载的同名同年资源合并）
    # 按 (归一化名称, 年份) 去重，保留第一个（优先 /mnt/mp 的）
    # 逻辑不变，只是输入从全量变为变更集（未变更的去重结果与上次一致）
    files = _dedupe_by_name_year(changed_files, parse_media_filename, lib_type)
    logger.info("[fast] 去重后 %d 个文件", len(files))

    # 3. 比对（只处理变更集；未变更的已在 1b 跳过）
    to_add: list[FastScanFile] = []
    to_update: list[tuple[int, FastScanFile]] = []  # (id, file)
    to_undelete: list[int] = []
    to_rename: list[tuple[int, FastScanFile]] = []  # (id, file)：改名/移动
    renamed_old_paths: set[str] = set()
    for f in files:
        if f.path not in existing:
            # v2.52.0: 路径是新的，但 drive_file_id 认识 = 改名/移动
            # 复用已有行（元数据全保留），只更新路径
            if f.file_id and f.file_id in existing_by_fid:
                item_id, old_path = existing_by_fid[f.file_id]
                to_rename.append((item_id, f))
                renamed_old_paths.add(old_path)
                logger.info("[fast] 识别改名/移动: %s -> %s", old_path, f.path)
            else:
                to_add.append(f)
        else:
            item_id, old_size, old_mtime, is_deleted, _fid = existing[f.path]
            mtime_changed = abs((old_mtime or 0) - f.mtime) >= 1.0
            if is_deleted:
                # 文件又出现了：取消软删除
                to_undelete.append(item_id)
                if old_size != f.size or mtime_changed:
                    to_update.append((item_id, f))
            elif old_size != f.size or mtime_changed:
                to_update.append((item_id, f))
            else:
                stats.skipped += 1

    # 删除：库里有但文件清单里没有的（只处理未删除的）
    # 用 all_paths（全量）做检测，跳过的文件不算删除；
    # 改名/移动的旧路径不算删除（那行已经复用给了新路径）
    to_remove_ids = [
        item_id for fp, (item_id, _, _, is_deleted, _f) in existing.items()
        if fp not in all_paths and fp not in renamed_old_paths and not is_deleted
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

    # 4a2. 改名/移动：更新 file_path（guid 跟着新路径走，元数据全保留）
    for chunk_start in range(0, len(to_rename), FAST_SCAN_BATCH):
        chunk = to_rename[chunk_start:chunk_start + FAST_SCAN_BATCH]
        db.bulk_update_mappings(MI, [
            {"id": item_id, "file_path": f.path,
             "guid": item_guid(f.path),
             "drive_file_id": f.file_id or None,
             "size": f.size, "file_mtime": f.mtime}
            for item_id, f in chunk
        ])
        db.commit()
        stats.updated += len(chunk)
        logger.info("[fast] 改名/移动已更新 %d 条", len(chunk))

    # 4b. 更新（size + file_mtime，批量）
    for chunk_start in range(0, len(to_update), FAST_SCAN_BATCH):
        chunk = to_update[chunk_start:chunk_start + FAST_SCAN_BATCH]
        # 用 bulk_update_mappings 批量更新
        db.bulk_update_mappings(MI, [
            {"id": item_id, "size": f.size, "file_mtime": f.mtime}
            for item_id, f in chunk
        ])
        db.commit()
        stats.updated += len(chunk)

    # 4b2. 取消软删除（文件又出现了）
    for chunk_start in range(0, len(to_undelete), FAST_SCAN_BATCH):
        chunk = to_undelete[chunk_start:chunk_start + FAST_SCAN_BATCH]
        db.query(MI).filter(MI.id.in_(chunk)).update(
            {"deleted_at": None}, synchronize_session=False)
        db.commit()

    # 4c. 删除（软删除）
    for chunk_start in range(0, len(to_remove_ids), FAST_SCAN_BATCH):
        chunk = to_remove_ids[chunk_start:chunk_start + FAST_SCAN_BATCH]
        db.query(MI).filter(MI.id.in_(chunk)).update(
            {"deleted_at": now}, synchronize_session=False)
        db.commit()
        stats.removed += len(chunk)

    # 更新库的扫描状态
    library.is_scanning = False
    db.commit()

    return {
        "added": stats.added,
        "updated": stats.updated,
        "removed": stats.removed,
        "skipped": stats.skipped,
        "skipped_unchanged": stats.skipped_unchanged,
    }


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
        # 文件名元数据（零 Drive 调用）：分辨率 / 编码 / 发行来源直接入库，
        # Width/Height 由分辨率推算，供客户端详情页与播放器显示。
        fn_meta = parse_filename(f.name)
        fn_w, fn_h = resolution_to_wh(fn_meta.get("resolution"))

        if lib_type == "tvshows" and season_no is not None:
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
                "sort_name": make_sort_name(parsed["name"]),
                "production_year": parsed.get("year"),
                "season_number": season_no,
                "episode_number": episode_no,
                "file_path": f.path,
                "drive_file_id": f.file_id or None,
                "size": f.size,
                "file_mtime": f.mtime,
                "container": os.path.splitext(f.name)[1].lower().lstrip("."),
                "date_added": now,
                # 文件名解析的视频信息（零 Drive 调用）
                "video_resolution": fn_meta.get("resolution"),
                "video_codec": fn_meta.get("video_codec"),
                "audio_codec": fn_meta.get("audio_codec"),
                "media_source": fn_meta.get("source"),
                "width": fn_w,
                "height": fn_h,
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
                "sort_name": make_sort_name(parsed["name"]),
                "production_year": parsed.get("year"),
                "file_path": f.path,
                "drive_file_id": f.file_id or None,
                "size": f.size,
                "file_mtime": f.mtime,
                "container": os.path.splitext(f.name)[1].lower().lstrip("."),
                "date_added": now,
                # 文件名解析的视频信息（零 Drive 调用）
                "video_resolution": fn_meta.get("resolution"),
                "video_codec": fn_meta.get("video_codec"),
                "audio_codec": fn_meta.get("audio_codec"),
                "media_source": fn_meta.get("source"),
                "width": fn_w,
                "height": fn_h,
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
            "sort_name": make_sort_name(info["name"]),
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
