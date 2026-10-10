# -*- coding: utf-8 -*-
"""按需媒体信息探测：把 ffprobe 的结果写回条目。

背景：全库 40 万+条目全在 Google Drive 上，全量 ffprobe 会烧穿 Drive 配额。
策略（抄 Jellyfin + 生态共识）：只在用户真正访问条目（详情页/播放）且条目缺
媒体信息时入队，后台 worker 限流探测。热门内容自然补全，冷门零成本。

本模块只做「一次探测」的纯逻辑（解析地址 → ffprobe → 写回）；
队列/限流/调度在 ``probe_worker.py``。

复用：
- ``scanner.probe_metadata``：远程 Range/双 Range/mp4-moov/MediaInfo 回退，
  线上跑了很久的探测实现，不再造第二套。
- ``mounts``：``mount://<id>/<rel>`` 解析成本机路径或带鉴权头的直链 URL。
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib
from backend.emby_server import mediainfo_persist as persist_lib
from backend.emby_server.scanner import probe_metadata

logger = logging.getLogger(__name__)

# 探测一次最多尝试次数（含首次）；超限标 failed，不再打扰
PROBE_MAX_ATTEMPTS = max(1, int(os.getenv("PROBE_MAX_ATTEMPTS", "3") or 3))
# 重试退避基数（秒）：60/120/240…，与 enrich_worker 同口径，保护 Drive 配额
PROBE_RETRY_BASE_SEC = max(10, int(os.getenv("PROBE_RETRY_BASE_SEC", "60") or 60))
# 退避上限（秒）：指数退避不无限增长
PROBE_RETRY_MAX_SEC = max(60, int(os.getenv("PROBE_RETRY_MAX_SEC", "21600") or 21600))
# 这些 HTTP 状态码说明地址本身有问题，重试没用，直接判 failed
NO_RETRY_HTTP_CODES = frozenset({400, 401, 403, 404, 410})


def resolve_probe_input(db, item) -> Optional[tuple]:
    """把条目的 ``file_path`` 解析成 ``(path, headers, size, container)``。

    - ``mount://<id>/<rel>``：经挂载 provider ``resolve_final`` 拿到直链 URL +
      鉴权头（Drive 的 alt=media 要 Authorization 头，ffprobe 靠 headers 传）。
    - 本机路径：直接返回，headers 为空。
    - 解析失败（挂载被删/直链拿不到/文件不存在）返回 None，调用方记重试。
    """
    fp = (getattr(item, "file_path", None) or "").strip()
    if not fp:
        return None
    size = int(getattr(item, "size", 0) or 0)
    container = (getattr(item, "container", None) or "").strip()

    parsed = mount_lib.parse_mount_path(fp)
    if parsed:
        mount_id, rel = parsed
        mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
        if mount is None:
            logger.warning("按需探测：挂载 %s 不存在 item=%s", mount_id, getattr(item, "id", "?"))
            return None
        try:
            provider = mount_lib.build_provider(mount, db)
            target = provider.resolve_final(rel)
        except Exception as exc:  # noqa: BLE001 — 挂载异常走重试，不抛给调用方
            logger.warning("按需探测：直链解析失败 item=%s rel=%s: %s",
                           getattr(item, "id", "?"), rel, exc)
            return None
        if not target or not getattr(target, "value", None):
            return None
        headers = dict(getattr(target, "headers", None) or {})
        return (target.value, headers, size, container)

    # 本机 .strm：内容是直链，探测直链而不是这个文本文件（以前 ffprobe 读 .strm 文本
    # 必然失败，3 次后判 failed，白占名额）
    if fp.lower().endswith(".strm"):
        try:
            target = mount_lib.local_play_target(fp)
        except Exception as exc:  # noqa: BLE001
            logger.warning("按需探测：STRM 解析失败 item=%s: %s", getattr(item, "id", "?"), exc)
            return None
        if getattr(target, "kind", "") == "url" and target.value:
            return (target.value, dict(target.headers or {}), size, container)
        return None

    # 本机文件
    try:
        if os.path.isfile(fp):
            return (fp, {}, size, container)
    except OSError:
        pass
    logger.warning("按需探测：本机文件不存在 item=%s path=%s",
                   getattr(item, "id", "?"), fp[:120])
    return None


def _has_useful_data(probe: dict) -> bool:
    """探测结果里有没有值得写回的东西（任一关键字段非空即可）。"""
    if not probe:
        return False
    return bool(probe.get("video_codec") or probe.get("width") or probe.get("duration_ticks"))


def write_back(db, item, probe: dict) -> None:
    """把探测结果写回条目（只写非空值，不覆盖已有有效数据）。

    - 编码：有值才写。
    - 宽/高/码率/大小/时长：>0 才写（0 可能是探测没拿到，不能把库里已有的清掉）。
    - 成功清零 attempts；degraded（信息不全但可播）同样落库，下次不再白跑。
    """
    if probe.get("video_codec"):
        item.video_codec = probe["video_codec"]
    if probe.get("audio_codec"):
        item.audio_codec = probe["audio_codec"]
    for field in ("width", "height", "bitrate", "size"):
        try:
            value = int(probe.get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            setattr(item, field, value)
    try:
        ticks = int(probe.get("duration_ticks") or 0)
    except (TypeError, ValueError):
        ticks = 0
    if ticks > 0:
        item.duration_ticks = ticks
    if probe.get("moov_position"):
        item.moov_position = probe["moov_position"]
    item.last_probed_at = datetime.now()
    item.probe_attempts = 0
    item.probe_next_retry_at = None
    item.probe_status = "degraded" if probe.get("_degraded") else "done"
    _clear_claim(item, error=None)
    db.commit()
    logger.info("按需探测成功 item=%s %s %sx%s audio=%s",
                item.id, item.video_codec or "?", item.width or "?",
                item.height or "?", item.audio_codec or "?")


def _clear_claim(item, error: Optional[str]) -> None:
    """释放抢单租约，记录（或清空）最近失败原因。老库没这两列时静默跳过。"""
    if hasattr(type(item), "probe_claimed_at"):
        item.probe_claimed_at = None
    if hasattr(type(item), "probe_last_error"):
        item.probe_last_error = (error or "")[:250] or None


def mark_failed(db, item, reason: str) -> None:
    """判死：不再重试。"""
    item.probe_status = "failed"
    item.probe_next_retry_at = None
    _clear_claim(item, error=reason)
    db.commit()
    logger.warning("按需探测放弃 item=%s（%s 次）: %s",
                   item.id, item.probe_attempts or 0, reason)


def mark_retry(db, item, reason: str) -> None:
    """记一次失败：次数+1，指数退避；超限转 failed。"""
    attempts = (getattr(item, "probe_attempts", 0) or 0) + 1
    item.probe_attempts = attempts
    if attempts >= PROBE_MAX_ATTEMPTS:
        mark_failed(db, item, f"{reason}（已达 {PROBE_MAX_ATTEMPTS} 次上限）")
        return
    delay = min(PROBE_RETRY_MAX_SEC, PROBE_RETRY_BASE_SEC * (2 ** (attempts - 1)))
    item.probe_status = "pending"
    item.probe_next_retry_at = datetime.now() + timedelta(seconds=delay)
    _clear_claim(item, error=reason)
    db.commit()
    logger.info("按需探测失败 item=%s（%d/%d，%ds 后重试）: %s",
                item.id, attempts, PROBE_MAX_ATTEMPTS, delay, reason)


def probe_one(db, item) -> str:
    """对单个条目做一次探测，返回终态：done/degraded/failed/pending（待重试）。

    对标 StrmAssistant 的 ``OrchestrateMediaInfoProcessAsync``：
    持久化开启时先试 ``deserialize``（读 ``-mediainfo.json``），命中则零探测
    直接返回；未命中才走 ffprobe；探完自动 ``serialize`` 落盘。

    调用方需先把条目置为 probing（防重入）；本函数只负责探测与状态流转。
    任何异常都不抛给调用方——探测失败永远不能影响播放/详情页。
    """
    # 1. 先试 JSON 恢复（零探测）
    try:
        if persist_lib.deserialize(db, item):
            return "done"
    except Exception as exc:  # noqa: BLE001 — 恢复失败就走正常探测
        logger.debug("媒体信息 JSON 恢复异常 item=%s，走 ffprobe: %s",
                     getattr(item, "id", "?"), exc)

    resolved = resolve_probe_input(db, item)
    if not resolved:
        mark_retry(db, item, "无法解析探测地址")
        return item.probe_status

    path, headers, size, container = resolved
    try:
        probe = probe_metadata(path, headers, size=size, container=container)
    except Exception as exc:  # noqa: BLE001
        mark_retry(db, item, f"ffprobe 异常: {exc}")
        return item.probe_status

    http_code = (probe or {}).get("_http_code")
    if http_code in NO_RETRY_HTTP_CODES:
        mark_failed(db, item, f"远端返回 HTTP {http_code}，地址无效")
        return item.probe_status

    if not _has_useful_data(probe):
        mark_retry(db, item, "探测未返回有效媒体信息")
        return item.probe_status

    write_back(db, item, probe)
    # 2. 探完落盘（对标 SerializeMediaInfo）
    try:
        persist_lib.serialize(db, item)
    except Exception as exc:  # noqa: BLE001 — 落盘失败不影响已写库的结果
        logger.debug("媒体信息落盘异常 item=%s: %s", getattr(item, "id", "?"), exc)
    return item.probe_status
