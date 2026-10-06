"""播放线路可观测（Phase 3）：每条线路一张卡片的快照组装

## 一张卡片回答四个问题

| 问题 | 数据来源 | 口径 |
|---|---|---|
| 这条线路**能不能用** | 线路自身配置（play_line / cdn / local_cache） | 配置口径，跨重启有效 |
| 它**是不是在降级** | 配置缺口 + 本进程运行时的降级计数（line_stats） | 两者都给，不编结论 |
| 有**多少人/多少流量**在这条线上 | ``user_play_lines`` 分布 + line_stats 计数 | 用户数是全库；流量是本进程 |
| 它的**效果**如何 | cache 命中率 / CDN 缓存口径 / 中转出流量 | 复用各模块已有口径，不重算 |

## 「降级」到底指什么

不是「线路挂了」——这四条线路**没有一条会挂**：它们全都以回源/代理兜底，
区别只在于**有没有按这条线路该有的方式工作**。所以降级只有一种含义：

> 用户选了（或被分流到）这条线路，但它退化成了另一条线路的行为。

例：本地缓存线路在缓存未启用、或本机没有副本时，用户拿到的其实是回源代理的流——
功能没坏，但「本地缓存」这个名字此刻是空的。面板必须说清楚，否则管理员会以为
缓存线路在正常工作。这与代码里的既有口径一致（cdn / cache 未启用时**等同 relay**）。
（direct / 302 直连已下线：Google Drive 的重定向带不过 Authorization 头，
token 放 URL 又会被限流，所以不再作为线路存在；面板上它只在末尾留一张历史卡片。）

## 不做的事

**不做灰度发布 / 0% 流量影子评估**（Phase 3 明确排除）。影子评估要的是「同一份流量
同时喂两套策略再比对结果」，那是另一套采样与比对机制，硬塞进这一版只会做出一个
看起来像灰度、实际上没有对照组的开关。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.emby_server import cdn, line_stats, local_cache, play_line
from backend.models import UserPlayLine

logger = logging.getLogger(__name__)

#: 面板上的展示顺序 = 用户侧「线路选择」的顺序（play_line.PLAY_LINES），
#: 按「成本从低到高」排给运维看：CDN 边缘 → 本机缓存 → 代理中转。
#: 已下线的 direct 放最后并标「已下线」：历史计数留着（否则从面板上看不出
#: 「为什么请求数一夜之间涨到代理中转」），但一眼能看出它不再可用。
LINE_ORDER = (play_line.LINE_CDN, play_line.LINE_CACHE,
              play_line.LINE_RELAY, play_line.LINE_DIRECT)

LINE_LABELS = {
    play_line.LINE_DIRECT: "直连（已下线）",
    play_line.LINE_CDN: "CDN",
    play_line.LINE_CACHE: "本地缓存",
    play_line.LINE_RELAY: "代理中转",
}

#: 每条线路的一句话：它到底把流量送到哪
LINE_SUMMARY = {
    play_line.LINE_DIRECT: "已下线：Google Drive 无法用 302 真直链（重定向带不过 "
                           "Authorization 头，token 放 URL 会被限流），只留历史计数",
    play_line.LINE_CDN: "URL 走 CDN 域名，热门分片由边缘缓存（回源省配额）",
    play_line.LINE_CACHE: "优先读 VPS 本机副本，命中不过网络也不碰云盘配额",
    play_line.LINE_RELAY: "本服务代理转发（当前默认线路，流量过 VPS）",
}


def _users_by_line(db: Session) -> dict:
    """用户线路偏好分布（多少人选了这条线）

    没有偏好记录的用户走默认 relay（play_line.get_play_line），所以这里
    **只统计显式选过的**。已下线的 direct 按等价线路 relay 归类——它读出来
    就是 relay，面板上再挂一个「直连有人选」会让人以为死选项还生效。
    """
    try:
        rows = (
            db.query(UserPlayLine.line, UserPlayLine.user_id).all()
        )
    except Exception:  # noqa: BLE001 — 读不到就报 0，不谎报
        logger.debug("读取用户线路偏好失败（按 0 计）", exc_info=True)
        return {}
    counts: dict = {}
    for line, _user_id in rows:
        # 已下线的 direct 折成 relay（与 get_play_line 同口径）
        key = play_line.normalize(line) or play_line.DEFAULT_LINE
        counts[key] = counts.get(key, 0) + 1
    return counts


def _cdn_state(db: Session) -> dict:
    try:
        return cdn.config_payload(db)
    except Exception:  # noqa: BLE001
        logger.debug("读取 CDN 配置失败（按未启用计）", exc_info=True)
        return {"enabled": False, "domain": "", "normalized": None}


def _cache_state(db: Session) -> dict:
    try:
        return local_cache.stats(db)
    except Exception:  # noqa: BLE001
        logger.debug("读取本地缓存统计失败（按未启用计）", exc_info=True)
        return {"enabled": False, "entries": {}, "entries_total": 0,
                "bytes_used": 0, "hits": 0, "misses": 0, "hit_rate": None,
                "dir_exists": False, "max_bytes": 0}


def _line_card(line: str, *, users: dict, counts: dict, cdn_state: dict,
               cache_state: dict) -> dict:
    """组装一条线路的卡片数据（纯函数，好测）"""
    label = LINE_LABELS.get(line, line)
    counter = counts.get(line) or {}

    # 1) 能不能用：这条线路依赖的能力有没有就绪
    ready = True
    ready_note = "始终可用（无额外依赖）"
    degraded_by_config = ""
    if line == play_line.LINE_CDN:
        ready = bool(cdn_state.get("enabled")) and bool(cdn_state.get("normalized"))
        if not cdn_state.get("enabled"):
            ready_note = "CDN 总开关未启用"
            degraded_by_config = "CDN 未启用 → 等同中转"
        elif not cdn_state.get("normalized"):
            ready_note = "CDN 已启用但域名未填（或不合法）"
            degraded_by_config = "CDN 域名未配置 → 等同中转"
        else:
            ready_note = "CDN 已启用"
    elif line == play_line.LINE_CACHE:
        ready = bool(cache_state.get("enabled"))
        if not ready:
            ready_note = "本地缓存总开关未启用"
            degraded_by_config = "本地缓存未启用 → 等同中转"
        elif not cache_state.get("dir_exists"):
            ready_note = "已启用但缓存目录不存在"
            degraded_by_config = "缓存目录不存在 → 等同中转"
        else:
            ready_note = f"缓存目录 {cache_state.get('dir')}"
    elif line == play_line.LINE_DIRECT:
        ready = False
        ready_note = "已下线：302 真直链不可行，老用户偏好已自动按代理中转处理"
    elif line == play_line.LINE_RELAY:
        ready_note = "当前默认线路：始终可用，视频流量经本服务转发"

    # 2) 运行态降级：按次数从高到低，管理员一眼看出「一直退化成什么」
    reasons = sorted(
        ((str(k), int(v)) for k, v in (counter.get("degrade_reasons") or {}).items()),
        key=lambda item: -item[1],
    )

    # 3) 效果数据：只报各模块已有的真实口径，不在这里重算一遍
    effect: dict = {}
    if line == play_line.LINE_CACHE:
        hits = int(cache_state.get("hits") or 0)
        misses = int(cache_state.get("misses") or 0)
        effect = {
            "hit_rate": cache_state.get("hit_rate"),
            "hits": hits,
            "misses": misses,
            "bytes_used": int(cache_state.get("bytes_used") or 0),
            "max_bytes": int(cache_state.get("max_bytes") or 0),
            "entries": cache_state.get("entries") or {},
            "entries_total": int(cache_state.get("entries_total") or 0),
        }
    elif line == play_line.LINE_CDN:
        effect = {
            "segment_cache_header": cdn.SEGMENT_CACHE_HEADER,
            "domain": cdn_state.get("normalized") or "",
        }
    elif line == play_line.LINE_DIRECT:
        # 已下线，只留历史口径：曾经 302 直连时字节不经本机
        effect = {"vps_bytes": 0, "note": "已下线：历史计数（当时 302 直连，字节不经本机）"}
    else:
        effect = {"note": "流量过本机，带宽与出网费由这条线路承担"}

    return {
        "line": line,
        "label": label,
        "summary": LINE_SUMMARY.get(line, ""),
        #: 已下线的线路（目前只有 302 直连）：只留历史计数，不再计入「就绪」分母
        "retired": line == play_line.LINE_DIRECT,
        "ready": ready,
        "ready_note": ready_note,
        "degraded_by_config": degraded_by_config,
        "degraded_reasons": [{"reason": reason, "count": count} for reason, count in reasons],
        "requests": int(counter.get("requests") or 0),
        "bytes_out": int(counter.get("bytes_out") or 0),
        "degraded_requests": int(counter.get("degraded_requests") or 0),
        "idle_seconds": counter.get("idle_seconds"),
        "users": int(users.get(line) or 0),
        "effect": effect,
    }


def snapshot(db: Session) -> dict:
    """四条线路的完整快照（管理端一次拿全，前端不用拼）"""
    users = _users_by_line(db)
    counts = {row["line"]: row for row in line_stats.snapshot(LINE_ORDER)}
    cdn_state = _cdn_state(db)
    cache_state = _cache_state(db)
    cards = [
        _line_card(line, users=users, counts=counts,
                   cdn_state=cdn_state, cache_state=cache_state)
        for line in LINE_ORDER
    ]
    total_users = sum(int(v) for v in users.values())
    return {
        "lines": cards,
        "total_users": total_users,
        "default_line": play_line.DEFAULT_LINE,
        "uptime_seconds": line_stats.uptime_seconds(),
        "scope_note": "流量与降级计数只统计本进程（流量确实只从本机出去，"
                      "跨节点合并会重复计算）；用户数是全库口径。"
                      "流量指本服务响应体实际吐出的字节（Range 分片与远程代理），"
                      "不含转码时 ffmpeg 的拉流与整文件直发。",
    }


def card_for(db: Session, line: str) -> Optional[dict]:
    """单条线路的卡片（测试与将来按线路下钻用）"""
    for card in snapshot(db)["lines"]:
        if card["line"] == line:
            return card
    return None


__all__ = ["LINE_LABELS", "LINE_ORDER", "LINE_SUMMARY", "card_for", "snapshot"]