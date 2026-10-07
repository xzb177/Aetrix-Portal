# -*- coding: utf-8 -*-
"""独立的外挂字幕扫描（对标 StrmAssistant ScanExternalSubtitleTask）。

StrmAssistant 做法：
- `ScanExternalSubtitleTask`：独立定时任务，遍历视频条目
- `SubtitleApi.HasExternalSubtitleChanged()`：对比库里已记录的外挂字幕 vs
  重新探测到的，有变化才更新（不是无脑全刷）
- `SubtitleApi.UpdateExternalSubtitles()`：只更新字幕轨道，不碰其他元数据

本模块一比一复刻：
- 定时任务：每 N 小时扫一遍（默认 12 小时），找出外挂字幕有变化的条目
- 变化检测：DB 里 is_external 字幕的 external_path 集合 vs 目录里实际探测到的
- 只更新有变化的条目；复用 subtitle_match 的匹配逻辑
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import List, Optional, Set, Tuple

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
SUBTITLE_SCAN_ENABLED = (
    os.getenv("SUBTITLE_SCAN_ENABLED", "1") or "1"
).strip().lower() not in ("0", "false", "no")
# 扫描间隔（秒），默认 12 小时
SUBTITLE_SCAN_INTERVAL_SEC = _env_float("SUBTITLE_SCAN_INTERVAL_SEC", 43200.0, 3600.0)
# 单次扫描最多处理条数（防大库一次扫太久）
SUBTITLE_SCAN_BATCH_LIMIT = _env_int("SUBTITLE_SCAN_BATCH_LIMIT", 10000, 100, 100000)

_scan_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_start_lock = threading.Lock()


def _detect_external_subtitles(video_path: str) -> Optional[Set[str]]:
    """探测视频同目录下的外挂字幕，返回路径集合。

    对标 StrmAssistant SubtitleApi.GetExternalSubtitleStreams。

    返回 None 表示"未知"（目录不可访问，如远程 mount:// 路径或挂载掉线），
    调用方必须跳过、**不得**按"没有字幕"处理（否则会误删 DB 里的合法字幕）。
    只有成功列出目录且确实没有字幕时才返回空集合。
    """
    from backend.emby_server import subtitle_match as sm

    directory = os.path.dirname(video_path or "")
    if not directory or not os.path.isdir(directory):
        return None
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    try:
        found = sm.find_external_subtitles_in(names, video_path)
    except Exception as e:
        logger.debug("字幕探测失败 %s: %s", video_path, e)
        return None
    return {path for _lang, path in found}


def _get_db_external_subtitles(db, item_id: int) -> Set[str]:
    """DB 里已记录的外挂字幕路径集合。"""
    from backend.emby_server import models as em

    rows = (
        db.query(em.MediaStream.external_path)
        .filter(
            em.MediaStream.item_id == item_id,
            em.MediaStream.stream_type == "Subtitle",
            em.MediaStream.is_external == True,  # noqa: E712
        )
        .all()
    )
    return {r[0] for r in rows if r[0]}


def has_external_subtitle_changed(db, item_id: int, video_path: str) -> bool:
    """外挂字幕是否有变化（对标 HasExternalSubtitleChanged）。

    DB 集合 vs 实际探测集合，不一致即为变化。
    探测结果未知（None）时返回 False：跳过，不误判。
    """
    current = _get_db_external_subtitles(db, item_id)
    detected = _detect_external_subtitles(video_path)
    if detected is None:
        return False
    return current != detected


def update_external_subtitles(db, item) -> int:
    """更新条目的外挂字幕（对标 UpdateExternalSubtitles）。

    只重建字幕轨道（is_external 的 Subtitle），不动视频/音频轨。
    返回更新后的字幕条数。
    """
    from backend.emby_server import models as em
    from backend.emby_server import subtitle_match as sm

    detected = _detect_external_subtitles(item.file_path)
    if detected is None:
        # 目录不可访问（远程 mount:// 路径、挂载掉线）：未知，不动 DB
        return 0
    if not detected:
        # 目录里没有字幕：删掉 DB 里残留的外挂字幕记录
        deleted = (
            db.query(em.MediaStream)
            .filter(
                em.MediaStream.item_id == item.id,
                em.MediaStream.stream_type == "Subtitle",
                em.MediaStream.is_external == True,  # noqa: E712
            )
            .delete(synchronize_session=False)
        )
        if deleted:
            logger.debug("字幕扫描：%s 移除了 %d 条残留外挂字幕", item.name, deleted)
        return 0

    # 重新匹配语言（find_external_subtitles_in 返回 (lang, path)）
    directory = os.path.dirname(item.file_path)
    try:
        names = os.listdir(directory)
        matched = sm.find_external_subtitles_in(names, item.file_path)
    except OSError:
        return 0

    # 删旧建新（只动外挂字幕）
    db.query(em.MediaStream).filter(
        em.MediaStream.item_id == item.id,
        em.MediaStream.stream_type == "Subtitle",
        em.MediaStream.is_external == True,  # noqa: E712
    ).delete(synchronize_session=False)

    # 现有轨道的最大 index，从它后面开始编号
    max_idx = (
        db.query(em.MediaStream.stream_index)
        .filter(em.MediaStream.item_id == item.id)
        .order_by(em.MediaStream.stream_index.desc())
        .first()
    )
    next_idx = (max_idx[0] + 1) if max_idx and max_idx[0] is not None else 0

    count = 0
    for lang, path in matched:
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        stream = em.MediaStream(
            item_id=item.id,
            stream_index=next_idx,
            stream_type="Subtitle",
            codec=ext or "srt",
            language=lang or "und",
            display_title=os.path.basename(path),
            title=os.path.basename(path),
            is_default=(count == 0),  # 与扫描器一致：第一条外挂字幕为默认
            is_external=True,
            external_path=path,
        )
        db.add(stream)
        next_idx += 1
        count += 1

    logger.debug("字幕扫描：%s 更新为 %d 条外挂字幕", item.name, count)
    return count


def _scan_once() -> Tuple[int, int]:
    """扫一轮：返回 (检查条数, 更新条数)。"""
    from backend.database import SessionLocal
    from backend.emby_server import models as em

    checked = 0
    updated = 0
    pending_commit = 0
    db = SessionLocal()
    try:
        # 流式迭代（yield_per），避免 1 万 ORM 常驻内存
        # order_by(id) 保证大库下每轮推进，不永远扫"任意"子集
        query = (
            db.query(em.MediaItem)
            .filter(
                em.MediaItem.item_type.in_(("movie", "episode")),
                em.MediaItem.deleted_at.is_(None),
                em.MediaItem.merged_into_id.is_(None),
                em.MediaItem.file_path.isnot(None),
            )
            .order_by(em.MediaItem.id.asc())
            .yield_per(500)
            .limit(SUBTITLE_SCAN_BATCH_LIMIT)
        )
        for item in query:
            if _stop_event.is_set():
                break
            # 先判路径可探测性：mount:// 或不可访问目录直接跳过，
            # 避免先打 1 万次 DB 查询再发现全是"未知"
            if _detect_external_subtitles(item.file_path) is None:
                db.expunge(item)
                continue
            checked += 1
            try:
                if has_external_subtitle_changed(db, item.id, item.file_path):
                    update_external_subtitles(db, item)
                    # 同步更新条目的 subtitle_languages（EA 展示用）
                    # 字幕被删光时要清空，避免残留旧值
                    langs = sorted({
                        s.language for s in db.query(em.MediaStream).filter(
                            em.MediaStream.item_id == item.id,
                            em.MediaStream.stream_type == "Subtitle",
                        ).all() if s.language
                    })
                    item.subtitle_languages = ",".join(langs) if langs else None
                    pending_commit += 1
                    updated += 1
                    # 攒批提交（100 条一 commit），避免上千短事务
                    if pending_commit >= 100:
                        db.commit()
                        pending_commit = 0
            except Exception as e:
                db.rollback()
                pending_commit = 0
                logger.warning("字幕扫描条目失败 %s: %s", item.file_path, e)
            finally:
                # 及时释放，避免 identity map 无限增长
                db.expunge(item)
        if pending_commit:
            db.commit()
        return checked, updated
    finally:
        db.close()


def _scan_loop():
    logger.info(
        "字幕扫描 worker 启动（间隔 %.0f 秒）", SUBTITLE_SCAN_INTERVAL_SEC
    )
    # 启动先跑一轮
    try:
        checked, updated = _scan_once()
        logger.info("字幕扫描首轮完成：检查 %d，更新 %d", checked, updated)
    except Exception as e:
        logger.warning("字幕扫描首轮失败: %s", e)
    while not _stop_event.wait(SUBTITLE_SCAN_INTERVAL_SEC):
        try:
            checked, updated = _scan_once()
            logger.info("字幕扫描完成：检查 %d，更新 %d", checked, updated)
        except Exception as e:
            logger.warning("字幕扫描失败: %s", e)
        finally:
            from backend.emby_server import worker_registry as _wr
            _wr.heartbeat("subtitle_scan")


def start() -> bool:
    """启动字幕扫描后台线程。返回 True 表示已启动。"""
    global _scan_thread
    if not SUBTITLE_SCAN_ENABLED:
        logger.info("字幕扫描已禁用（SUBTITLE_SCAN_ENABLED=0）")
        return False
    with _start_lock:
        if _scan_thread and _scan_thread.is_alive():
            return True
        _stop_event.clear()
        _scan_thread = threading.Thread(
            target=_scan_loop, name="subtitle-scan", daemon=True
        )
        _scan_thread.start()
        from backend.emby_server import worker_registry as _wr
        _wr.register("subtitle_scan", _scan_thread)
        return True


def stop():
    _stop_event.set()
