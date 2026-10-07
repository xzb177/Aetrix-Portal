# -*- coding: utf-8 -*-
"""视频截图预览缩略图增强（对标 StrmAssistant ExtractVideoThumbnailTask）。

StrmAssistant 做法：
- `ExtractVideoThumbnailTask`：定时任务，找出无章节缩略图的视频
  （`HasChapterImages=false`）
- `VideoThumbnailApi.RefreshThumbnailImages`：调用 Emby 的 ThumbnailGenerator
  按章节抽帧，生成拖动预览用的小图

本模块一比一复刻：
- 定时任务：找出已探测（有 duration）但无缩略图的 movie/episode
- ffmpeg 按时长均分抽 N 帧（默认 10 张），存 /data/thumbnails/{guid}/
- 有缩略图的目录即视为已提取（文件系统即状态，无需 DB 字段）
- 限并发（默认 1，Rclone 下抽帧=读文件，防 I/O 争抢）

API：EA 通过 /emby/Items/{id}/Thumbnails/{index} 取图（见 media_routes）。
"""

import logging
import os
import subprocess
import threading
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _env_float(name: str, default: float, lo: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, value)


# 开关：默认开
THUMBNAIL_ENABLED = (
    os.getenv("THUMBNAIL_EXTRACT_ENABLED", "1") or "1"
).strip().lower() not in ("0", "false", "no")
# 扫描间隔（秒），默认 6 小时
THUMBNAIL_INTERVAL_SEC = _env_float("THUMBNAIL_INTERVAL_SEC", 21600.0, 3600.0)
# 每视频抽帧数
THUMBNAIL_COUNT = _env_int("THUMBNAIL_COUNT", 10, 1, 50)
# 并发数（默认 1，Rclone 场景防 I/O 争抢）
THUMBNAIL_WORKERS = _env_int("THUMBNAIL_WORKERS", 1, 1, 3)
# 单次扫描最多处理条数
THUMBNAIL_BATCH_LIMIT = _env_int("THUMBNAIL_BATCH_LIMIT", 500, 10, 10000)
# 缩略图根目录
THUMBNAIL_ROOT = os.getenv("THUMBNAIL_ROOT", "/data/thumbnails")
# ffmpeg 超时（秒）
THUMBNAIL_FFMPEG_TIMEOUT = _env_int("THUMBNAIL_FFMPEG_TIMEOUT", 300, 60, 1800)

_thumb_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_start_lock = threading.Lock()


def thumbnail_dir(guid: str) -> str:
    """某条目的缩略图目录。"""
    # guid 为空时返回一个不可能存在的路径，避免 TypeError
    safe_guid = (guid or "").strip()
    if not safe_guid:
        return os.path.join(THUMBNAIL_ROOT, "__invalid__")
    return os.path.join(THUMBNAIL_ROOT, safe_guid[:2], safe_guid)


def has_thumbnails(guid: str) -> bool:
    """是否有已提取的缩略图（文件系统即状态）。

    要求数量达到 THUMBNAIL_COUNT，避免上次中断只生成一半时误判为已完成。
    """
    if not (guid or "").strip():
        return False
    thumbs = list_thumbnails(guid)
    # 允许一定的容差：生成数量 >= 预期数量的 80% 即视为完成
    # （某些视频太短，抽帧可能失败几张）
    return len(thumbs) >= max(1, int(THUMBNAIL_COUNT * 0.8))


def list_thumbnails(guid: str) -> List[str]:
    """列出缩略图文件（按序号排序）。"""
    if not (guid or "").strip():
        return []
    d = thumbnail_dir(guid)
    if not os.path.isdir(d):
        return []
    try:
        files = [
            f for f in os.listdir(d)
            if f.startswith("thumb_") and f.endswith(".jpg")
        ]
        # 按序号排序：thumb_000.jpg, thumb_001.jpg, ...
        files.sort()
        return [os.path.join(d, f) for f in files]
    except OSError:
        return []


def _resolve_video_path(item) -> Optional[str]:
    """解析视频文件的本地可读路径。

    file_path 已经是本地挂载路径（如 /mnt/mp/...），直接检查可读性。
    """
    path = (getattr(item, "file_path", None) or "").strip()
    if not path:
        return None
    # mount:// 格式的转成本地路径（如果有）
    if path.startswith("mount://"):
        try:
            from backend.emby_server import mounts as mount_lib
            parsed = mount_lib.parse_mount_path(path)
            if parsed:
                # 尝试从挂载表找本地路径，找不到就跳过
                return None
        except Exception:
            return None
    return path if os.path.isfile(path) else None


def extract_thumbnails(item) -> int:
    """为单个条目抽帧。返回生成的缩略图数量。

    对标 StrmAssistant VideoThumbnailApi.RefreshThumbnailImages。
    """
    guid = (getattr(item, "guid", None) or "").strip()
    if not guid:
        logger.debug("缩略图：条目无 guid，跳过")
        return 0
    if has_thumbnails(guid):
        return 0

    video_path = _resolve_video_path(item)
    if not video_path or not os.path.isfile(video_path):
        logger.debug("缩略图：文件不可读 %s", item.file_path)
        return 0

    # 时长（秒）：duration_ticks 是 100ns
    duration_ticks = getattr(item, "duration_ticks", 0) or 0
    duration_sec = duration_ticks / 10_000_000
    if duration_sec <= 0:
        logger.debug("缩略图：无时长信息 %s", item.name)
        return 0

    out_dir = thumbnail_dir(guid)
    os.makedirs(out_dir, exist_ok=True)

    # 均分 N 个时间点，避开片头片尾各 5%
    count = THUMBNAIL_COUNT
    margin = duration_sec * 0.05
    usable = duration_sec - 2 * margin
    if usable <= 0:
        usable = duration_sec
        margin = 0

    generated = 0
    for i in range(count):
        # 时间点：margin + (i + 0.5) / count * usable
        ts = margin + (i + 0.5) / count * usable
        out_path = os.path.join(out_dir, f"thumb_{i:03d}.jpg")
        try:
            # ffmpeg 抽单帧：-ss 先行（快速定位）+ -frames:v 1
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", str(int(ts)),
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "5",  # JPEG 质量
                "-y", out_path,
            ]
            result = subprocess.run(
                cmd,
                timeout=THUMBNAIL_FFMPEG_TIMEOUT,
                capture_output=True,
            )
            if result.returncode == 0 and os.path.isfile(out_path):
                generated += 1
            else:
                logger.debug(
                    "缩略图抽帧失败 %s @%ds: %s",
                    item.name, int(ts),
                    result.stderr.decode(errors="ignore")[:200],
                )
        except subprocess.TimeoutExpired:
            logger.warning("缩略图抽帧超时 %s", item.name)
            break
        except Exception as e:
            logger.debug("缩略图抽帧异常 %s: %s", item.name, e)
            break

        if _stop_event.is_set():
            break

    if generated:
        logger.info("缩略图：%s 生成 %d 张", item.name, generated)
    return generated


def _extract_once() -> Tuple[int, int]:
    """跑一轮抽帧：返回 (检查条数, 生成条目数)。"""
    from backend.database import SessionLocal
    from backend.emby_server import models as em

    checked = 0
    done = 0
    db = SessionLocal()
    try:
        # 已探测（有 duration）且无缩略图的 movie/episode
        items = (
            db.query(em.MediaItem)
            .filter(
                em.MediaItem.item_type.in_(("movie", "episode")),
                em.MediaItem.deleted_at.is_(None),
                em.MediaItem.merged_into_id.is_(None),
                em.MediaItem.duration_ticks > 0,
                em.MediaItem.file_path.isnot(None),
            )
            .limit(THUMBNAIL_BATCH_LIMIT)
            .all()
        )
        # 过滤掉已有缩略图的（文件系统检查）
        pending = [i for i in items if not has_thumbnails(i.guid)]
        for item in pending:
            if _stop_event.is_set():
                break
            checked += 1
            try:
                n = extract_thumbnails(item)
                if n > 0:
                    done += 1
            except Exception as e:
                logger.warning("缩略图提取失败 %s: %s", item.name, e)
        return checked, done
    finally:
        db.close()


def _ffmpeg_available() -> bool:
    """检查 ffmpeg 是否可用。"""
    import shutil
    return shutil.which("ffmpeg") is not None


def _extract_loop():
    logger.info(
        "缩略图 worker 启动（间隔 %.0f 秒，每视频 %d 张）",
        THUMBNAIL_INTERVAL_SEC, THUMBNAIL_COUNT,
    )
    # ffmpeg 不可用时直接退出，避免每轮空转浪费 CPU
    if not _ffmpeg_available():
        logger.warning("缩略图 worker：未找到 ffmpeg，已禁用")
        return
    os.makedirs(THUMBNAIL_ROOT, exist_ok=True)
    try:
        checked, done = _extract_once()
        logger.info("缩略图首轮完成：检查 %d，完成 %d", checked, done)
    except Exception as e:
        logger.warning("缩略图首轮失败: %s", e)
    while not _stop_event.wait(THUMBNAIL_INTERVAL_SEC):
        try:
            checked, done = _extract_once()
            if checked:
                logger.info("缩略图完成：检查 %d，完成 %d", checked, done)
        except Exception as e:
            logger.warning("缩略图失败: %s", e)


def start() -> bool:
    """启动缩略图后台线程。"""
    global _thumb_thread
    if not THUMBNAIL_ENABLED:
        logger.info("缩略图提取已禁用（THUMBNAIL_EXTRACT_ENABLED=0）")
        return False
    with _start_lock:
        if _thumb_thread and _thumb_thread.is_alive():
            return True
        _stop_event.clear()
        _thumb_thread = threading.Thread(
            target=_extract_loop, name="thumbnail-extract", daemon=True
        )
        _thumb_thread.start()
        return True


def stop():
    _stop_event.set()
