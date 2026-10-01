"""播放线路选择（用户维度）。

线路定义：
- direct（直连线路，默认）：video_stream 先试 Google 直链 302，
  客户端直连 Google 下载，不经过服务器代理。
- relay（中转线路）：跳过一切 302，直接走 serve_remote_async 代理转发，
  流量过 VPS。适合客户端直连 Google 不通（转圈）的用户手动切换。

偏好存在 user_play_lines 表；无记录视为 direct，老用户行为不变。
"""

from sqlalchemy.orm import Session

from backend.models import UserPlayLine

LINE_DIRECT = "direct"
LINE_RELAY = "relay"
PLAY_LINES = (LINE_DIRECT, LINE_RELAY)
DEFAULT_LINE = LINE_DIRECT


def get_play_line(db: Session, user_id: int | None) -> str:
    """读用户线路偏好。

    无记录、脏数据、user_id 为空或读取异常，一律回默认 direct。
    偏好只是辅助：读不到也不能让播放 500。
    """
    try:
        if user_id is None:
            return DEFAULT_LINE
        pref = db.query(UserPlayLine).filter(UserPlayLine.user_id == user_id).first()
    except Exception:
        return DEFAULT_LINE
    if pref is not None and pref.line in PLAY_LINES:
        return pref.line
    return DEFAULT_LINE


def set_play_line(db: Session, user_id: int, line: str) -> str:
    """写用户线路偏好；line 非法抛 ValueError（由路由转 400）。"""
    if line not in PLAY_LINES:
        raise ValueError(f"line 只能是 {PLAY_LINES} 之一，收到 {line!r}")
    pref = db.query(UserPlayLine).filter(UserPlayLine.user_id == user_id).first()
    if pref is None:
        pref = UserPlayLine(user_id=user_id, line=line)
        db.add(pref)
    else:
        pref.line = line
    db.commit()
    return pref.line
