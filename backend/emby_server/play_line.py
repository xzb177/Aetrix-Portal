"""播放线路（2026-10 已废弃）。

2026-10 简化后只有一条播放路径：中转。本模块保留仅为兼容历史数据
（user_play_lines 表里的老值）与老客户端，``normalize`` 把任何输入折成
``"relay"``。新代码不要再引用本模块。
"""

from sqlalchemy.orm import Session

from backend.models import UserPlayLine

#: 已下线的线路值：只为兼容历史数据保留
LINE_DIRECT = "direct"
LINE_RELAY = "relay"
LINE_CDN = "cdn"
LINE_CACHE = "cache"

#: 全部折成 relay
PLAY_LINES = (LINE_RELAY,)
DEFAULT_LINE = LINE_RELAY

#: 下线线路 → relay
LEGACY_LINE_ALIASES = {
    LINE_DIRECT: LINE_RELAY,
    LINE_CDN: LINE_RELAY,
    LINE_CACHE: LINE_RELAY,
}


def normalize(line: object) -> str | None:
    """把任意输入折成 ``"relay"``；空值返回 None。"""
    key = str(line or "").strip().lower()
    if key in PLAY_LINES:
        return key
    return LEGACY_LINE_ALIASES.get(key)


def get_play_line(db: Session, user_id: int | None) -> str:
    """永远返回 ``"relay"``（保留签名仅为兼容旧调用）。"""
    return DEFAULT_LINE


def set_play_line(db: Session, user_id: int | None, line: str) -> str:
    """空操作：线路选择已下线，永远返回 ``"relay"``。"""
    return DEFAULT_LINE
