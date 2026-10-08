"""StrmAssistant #3 对标：片头片尾探测增强

StrmAssistant 用音频指纹（Emby 内置 AudioFingerprintManager）自动探测片头。
我们没有 Emby 内部类，先做轻量版：
1. 手动标记：管理员/用户标记片头片尾区间
2. 数据模型：emby_intro_markers（marker_type: intro/outro/credits）
3. 播放时返回标记，客户端显示"跳过片头"按钮

自动音频指纹为二期（需评估 ffmpeg 负载）。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 合法的标记类型（对标 StrmAssistant 的 IntroStart/IntroEnd）
MARKER_TYPES = ("intro", "outro", "credits")
# 数据来源
SOURCES = ("manual", "auto")


def get_markers(db, item_id: int) -> list[dict]:
    """取某条目的所有片头片尾标记。"""
    from backend.emby_server import models as em

    rows = (
        db.query(em.IntroMarker)
        .filter(em.IntroMarker.item_id == item_id)
        .order_by(em.IntroMarker.start_ms.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "marker_type": r.marker_type,
            "start_ms": r.start_ms,
            "end_ms": r.end_ms,
            "source": r.source,
        }
        for r in rows
    ]


def set_marker(db, item_id: int, marker_type: str,
               start_ms: int, end_ms: int,
               source: str = "manual") -> dict:
    """设置/更新标记（同 item_id + marker_type 只保留一条，幂等）。"""
    from backend.emby_server import models as em

    if marker_type not in MARKER_TYPES:
        raise ValueError(f"非法 marker_type: {marker_type}")
    if source not in SOURCES:
        raise ValueError(f"非法 source: {source}")
    if start_ms < 0 or end_ms <= start_ms:
        raise ValueError("时间区间非法")

    # 幂等：同类型只保留一条
    existing = (
        db.query(em.IntroMarker)
        .filter(em.IntroMarker.item_id == item_id)
        .filter(em.IntroMarker.marker_type == marker_type)
        .first()
    )
    if existing:
        existing.start_ms = start_ms
        existing.end_ms = end_ms
        existing.source = source
        db.commit()
        return {"id": existing.id, "updated": True}

    marker = em.IntroMarker(
        item_id=item_id,
        marker_type=marker_type,
        start_ms=start_ms,
        end_ms=end_ms,
        source=source,
    )
    db.add(marker)
    db.commit()
    return {"id": marker.id, "updated": False}


def delete_marker(db, item_id: int, marker_type: str) -> bool:
    """删除标记。返回是否删过。"""
    from backend.emby_server import models as em

    deleted = (
        db.query(em.IntroMarker)
        .filter(em.IntroMarker.item_id == item_id)
        .filter(em.IntroMarker.marker_type == marker_type)
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()
    return bool(deleted)


def to_chapters(markers: list[dict]) -> list[dict]:
    """转 Emby Chapter 格式（供播放器显示跳过按钮）。

    对标 StrmAssistant ``ChapterApi.UpdateIntro()`` 把片头写成 Chapter Marker。
    """
    chapters = []
    for m in markers:
        chapters.append({
            "StartPositionTicks": m["start_ms"] * 10000,  # ms → ticks
            "EndPositionTicks": m["end_ms"] * 10000,
            "Name": {"intro": "片头", "outro": "片尾", "credits": "字幕"}.get(
                m["marker_type"], m["marker_type"]),
            "MarkerType": m["marker_type"],
        })
    return chapters
