# -*- coding: utf-8 -*-
"""媒体信息持久化：ffprobe 结果落盘为 ``-mediainfo.json``，下次零探测恢复。

对标 StrmAssistant（Emby 神医助手）的 ``MediaInfoApi.Serialize/DeserializeMediaInfo``：

- 探完就存：``serialize(db, item)`` 把探测结果写成 ``{guid}-mediainfo.json``。
- 恢复优先：``deserialize(db, item)`` 在 ffprobe 之前先试读 JSON；文件未变更
  （mtime + size 都对得上）才用，直接写回 DB，**零 ffprobe**。
- 隐私：JSON 里不存鉴权头、不存直链，只存恢复 DB 所需的字段 + 文件指纹。

落盘位置（对标 ``MediaInfoJsonRootFolder``）：
- 默认本地统一目录（``MEDIAINFO_JSON_DIR``，缺省 ``/data/mediainfo``），
  按 ``guid`` 前两位分片，避免单目录文件过多；
- Rclone/网盘场景下不写网盘，省 API 调用（StrmAssistant 写视频同目录，
  我们默认走本地，行为通过环境变量可配）。

文件名：``{guid}-mediainfo.json``（对标 ``-mediainfo.json`` 后缀习惯）。
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 持久化开关（对标 PersistMediaInfoOption：None/Default/Restore）
# "0" = 关；"1" = 探完就存 + 恢复时读（默认）；"restore-only" = 只读不写
def _persist_mode() -> str:
    return (os.getenv("MEDIAINFO_PERSIST_MODE", "1") or "1").strip().lower()


# 本地统一落盘目录（对标 MediaInfoJsonRootFolder）
def _json_root_dir() -> str:
    return (os.getenv("MEDIAINFO_JSON_DIR", "/data/mediainfo") or "/data/mediainfo").strip()


# 兼容 StrmAssistant 习惯的后缀
JSON_SUFFIX = "-mediainfo.json"


def enabled() -> bool:
    return _persist_mode() not in ("0", "false", "no", "off", "none")


def _json_path_for_guid(guid: str) -> str:
    """guid → 本地 JSON 路径（两位分片）。"""
    safe = "".join(c for c in (guid or "") if c.isalnum()) or "noguid"
    shard = safe[:2] if len(safe) >= 2 else "00"
    return os.path.join(_json_root_dir(), shard, f"{safe}{JSON_SUFFIX}")


def get_json_path(item) -> Optional[str]:
    """条目对应的 JSON 路径；guid 为空时返回 None。"""
    guid = (getattr(item, "guid", None) or "").strip()
    if not guid:
        return None
    return _json_path_for_guid(guid)


def _file_fingerprint(item) -> dict:
    """文件指纹：mtime + size，用于判断源文件是否变更。"""
    try:
        mtime = float(getattr(item, "file_mtime", 0) or 0)
    except (TypeError, ValueError):
        mtime = 0.0
    try:
        size = int(getattr(item, "size", 0) or 0)
    except (TypeError, ValueError):
        size = 0
    return {"file_mtime": mtime, "file_size": size}


def _has_media_info(item) -> bool:
    """DB 里有没有值得持久化的媒体信息（对标 HasMediaInfo）。"""
    return bool(getattr(item, "video_codec", None) or getattr(item, "width", 0))


def serialize(db, item) -> bool:
    """把条目的媒体信息落盘为 JSON。成功返回 True。

    只在有媒体信息时写；写失败不抛异常（持久化失败不能影响主流程）。
    """
    if not enabled() or _persist_mode() == "restore-only":
        return False
    if not _has_media_info(item):
        return False
    path = get_json_path(item)
    if not path:
        return False
    payload = {
        "version": 1,
        "item_guid": getattr(item, "guid", ""),
        "probed_at": datetime.now().isoformat(timespec="seconds"),
        **_file_fingerprint(item),
        "media": {
            "video_codec": getattr(item, "video_codec", None),
            "audio_codec": getattr(item, "audio_codec", None),
            "width": int(getattr(item, "width", 0) or 0),
            "height": int(getattr(item, "height", 0) or 0),
            "bitrate": int(getattr(item, "bitrate", 0) or 0),
            "duration_ticks": int(getattr(item, "duration_ticks", 0) or 0),
            "container": getattr(item, "container", None),
            "moov_position": getattr(item, "moov_position", None),
        },
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
        logger.debug("媒体信息已持久化 item=%s → %s", getattr(item, "id", "?"), path)
        return True
    except OSError as exc:
        logger.warning("媒体信息持久化失败 item=%s: %s", getattr(item, "id", "?"), exc)
        return False


def _fingerprint_match(item, payload: dict) -> bool:
    """JSON 里的文件指纹与当前条目是否一致（对标 HasFileChanged）。"""
    try:
        cur = _file_fingerprint(item)
        old_mtime = float(payload.get("file_mtime", 0) or 0)
        old_size = int(payload.get("file_size", 0) or 0)
    except (TypeError, ValueError):
        return False
    # mtime 和 size 都对不上才算变更；任一缺失时保守地认为未变更（避免反复重探）
    if old_mtime and cur["file_mtime"] and abs(old_mtime - cur["file_mtime"]) > 1.0:
        return False
    if old_size and cur["file_size"] and old_size != cur["file_size"]:
        return False
    return True


def deserialize(db, item) -> bool:
    """尝试从 JSON 恢复媒体信息到 DB。成功返回 True（调用方跳过 ffprobe）。

    对标 ``DeserializeMediaInfo``：文件不存在 / 指纹对不上 / 内容无效 → False。
    """
    if not enabled():
        return False
    path = get_json_path(item)
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("媒体信息 JSON 读取失败 item=%s: %s", getattr(item, "id", "?"), exc)
        return False
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return False
    # guid 对不上说明 JSON 张冠李戴，绝不用
    if (payload.get("item_guid") or "") != (getattr(item, "guid", "") or ""):
        logger.warning("媒体信息 JSON guid 不匹配 item=%s，已忽略", getattr(item, "id", "?"))
        return False
    if not _fingerprint_match(item, payload):
        logger.info("媒体信息 JSON 已过期（文件变更）item=%s", getattr(item, "id", "?"))
        return False
    media = payload.get("media") or {}
    if not (media.get("video_codec") or media.get("width")):
        return False
    # 写回 DB（只写有效值，不覆盖已有有效数据，与 write_back 同口径）
    if media.get("video_codec") and not getattr(item, "video_codec", None):
        item.video_codec = media["video_codec"]
    if media.get("audio_codec") and not getattr(item, "audio_codec", None):
        item.audio_codec = media["audio_codec"]
    for field in ("width", "height", "bitrate", "duration_ticks"):
        try:
            value = int(media.get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0 and not getattr(item, field, 0):
            setattr(item, field, value)
    if media.get("container") and not getattr(item, "container", None):
        item.container = media["container"]
    if media.get("moov_position") and not getattr(item, "moov_position", None):
        item.moov_position = media["moov_position"]
    item.last_probed_at = datetime.now()
    item.probe_attempts = 0
    item.probe_next_retry_at = None
    item.probe_status = "done"
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("媒体信息 JSON 恢复写库失败 item=%s: %s", getattr(item, "id", "?"), exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
    logger.info("媒体信息从 JSON 恢复（零探测）item=%s %s %sx%s",
                item.id, item.video_codec or "?",
                item.width or "?", item.height or "?")
    return True


def delete_json(item) -> None:
    """删除条目对应的 JSON（条目删除/文件变更时调用，对标 DeleteMediaInfoJson）。"""
    path = get_json_path(item)
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
