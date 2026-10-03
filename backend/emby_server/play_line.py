"""播放线路选择（用户维度）。

线路定义：
- relay（中转线路，默认）：经本服务代理转发，流量过 VPS。
- cdn（CDN 线路，第 2/3 层预留）：与 relay 同口径（服务端代理转发），但客户端
  拿到的播放 URL 走管理员预留的 CDN 域名——热门分片由 CDN 边缘缓存回源，
  躲 Google Drive 单文件配额。CDN 未启用时选它等同 relay（URL 原样回落本
  服务），不会让任何人播不出来。
- cache（本地缓存线路）：优先读 VPS 本机副本（热门片由后台 worker 提前拉到
  本地，见 ``local_cache``）；本地没有就走 relay 的回源口径，并把这条片子按
  最高优先级排进缓存队列。本地缓存未启用时选它等同 relay，不会让任何人播不出来。

**direct（直连线路）已下线**（2026-10）：曾经尝试用 302 把客户端直接扔到
Google Drive 的 ``alt=media`` 地址，让流量不过 VPS。调研 Alist / RClone /
Cloudreve 三家后确认这条路走不通，三家都是服务端代理：

1. Drive 的 ``alt=media`` 要求 ``Authorization`` 头，而 302 是**重定向**，
   客户端不会把本服务请求上的请求头带到新地址去（Emby 客户端尤其不会）；
2. 唯一能塞进 URL 的 ``access_token`` 会进客户端日志、Referer 与中间代理，
   且 Google 对「URL 带 token」的请求有独立的、更严的限流；
3. 顺带一刀：缓存来的 file id 可能已失效，302 之后字节不经本机，服务器永远
   看不到上游 404，自愈重试也就没了。

所以 ``LINE_DIRECT`` 只作为**历史值**保留（老偏好、老统计、老测试都还认它），
不再出现在可选线路里。``normalize`` 负责把老值映射到 relay，读取与写入两个
方向都过它，用户不会看到一个点了没变化的死选项。

偏好存在 user_play_lines 表；无记录视为 relay，老用户行为不变。
"""

from sqlalchemy.orm import Session

from backend.models import UserPlayLine

#: 已下线的线路值：只为兼容历史数据与统计口径保留，不可选
LINE_DIRECT = "direct"
LINE_RELAY = "relay"
LINE_CDN = "cdn"
LINE_CACHE = "cache"

#: 用户可选的线路（direct 不在其中——见模块说明）
PLAY_LINES = (LINE_CDN, LINE_CACHE, LINE_RELAY)
DEFAULT_LINE = LINE_RELAY

#: 下线线路 → 等价线路。老用户存过 direct 的，读取时按 relay 对待
LEGACY_LINE_ALIASES = {LINE_DIRECT: LINE_RELAY}


def normalize(line: object) -> str | None:
    """把任意输入折成一条**当前有效**的线路；不认识的值返回 None。

    折而不是直接判存在，是为了让「老客户端还发 direct」也走得通：
    它不会 400，而是被悄悄迁到 relay（前端连提示都不需要）。
    """
    key = str(line or "").strip().lower()
    if key in PLAY_LINES:
        return key
    return LEGACY_LINE_ALIASES.get(key)


def get_play_line(db: Session, user_id: int | None) -> str:
    """读用户线路偏好（**已折成有效线路**）。

    无记录、脏数据、user_id 为空或读取异常，一律回默认 relay；库里存着已下线的
    direct（老用户）也折成 relay——不需要数据迁移，读的时候顺手换掉即可。
    偏好只是辅助：读不到也不能让播放 500。
    """
    try:
        if user_id is None:
            return DEFAULT_LINE
        pref = db.query(UserPlayLine).filter(UserPlayLine.user_id == user_id).first()
    except Exception:
        return DEFAULT_LINE
    if pref is not None:
        canonical = normalize(pref.line)
        if canonical:
            return canonical
    return DEFAULT_LINE


def set_play_line(db: Session, user_id: int, line: str) -> str:
    """写用户线路偏好，返回**实际落库**的那条线。

    非法值抛 ValueError（由路由转 400）；已下线的 direct 不算非法，写进去的是
    等价的 relay，于是老客户端重放直连偏好时顺带把这条记录迁掉了。
    """
    canonical = normalize(line)
    if canonical is None:
        raise ValueError(f"line 只能是 {PLAY_LINES} 之一，收到 {line!r}")
    pref = db.query(UserPlayLine).filter(UserPlayLine.user_id == user_id).first()
    if pref is None:
        pref = UserPlayLine(user_id=user_id, line=canonical)
        db.add(pref)
    else:
        pref.line = canonical
    db.commit()
    return pref.line