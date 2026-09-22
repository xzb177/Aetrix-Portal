"""播放会话端点：补鉴权 + 会话键归一化（在协议路由注册前替换旧实现）

`backend/emby_server/api.py` 里的历史实现在会话端点上有三处问题：

1. ``GET /Sessions``（含 ``/emby/Sessions``）**没有任何鉴权**，返回全站所有未结束会话：
   用户名 / 设备 / 客户端 / IP / 正在播放的条目；
2. ``DELETE /Sessions/{key}``（含 ``/emby/Sessions/{key}``）**同样没有鉴权**，并且会调用
   ``stop_transcode()`` —— 匿名即可把任意用户踢下线；
3. 客户端没带 ``PlaySessionId`` 时，会话键回退成 ``{user.id}-{item.guid[:16]}``，而
   ``item.guid`` 就是客户端可见的条目 id：会话键可以被公开算出来。

本模块沿用 ``mount_routes.py`` 的做法——在 ``include_router`` **之前**把这几条路由换成
带鉴权的实现（``install_session_routes``），并把上报入口的会话键归一化：

- **列表**：普通用户只能看到自己的会话，``is_staff`` 可看全站；
- **结束**：只能结束自己的会话（``session.user_id == user.id``），``is_staff`` 可停任意；
- **会话键**：客户端自带的 ``PlaySessionId`` 只有满足 ``^[A-Za-z0-9_.:-]{1,64}$`` 且没有被
  别的用户占用时才复用，其余一律 ``s<随机>``（不会再出现可预测的键，也不会改写别人的会话）。

上报路由（``Sessions/Playing`` / ``Progress`` / ``Stopped``）保留 ``api.py`` 里的原处理函数：
本模块只把 body 里的 ``PlaySessionId`` 换成归一化后的可信会话键，播放进度、已看状态等
业务逻辑不重复实现（``Request.json()`` 的结果被 starlette 缓存，就地改写即可生效）。
"""
from __future__ import annotations

import inspect
import logging
import re
import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db
from backend.emby_server import api as emby_api
from backend.emby_server import compat_routes
from backend.emby_server import models as em
from backend.emby_server.auth import get_emby_user
from backend.emby_server.streaming import stop_transcodes_for

logger = logging.getLogger(__name__)

# 会话键允许的字符（会进 URL，必须排除 / 空格等会破坏路由的字符）
SESSION_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")

# 被替换的旧路由（api.py 里不带鉴权的实现）
LIST_PATHS = ("/emby/Sessions", "/Sessions")
STOP_PATHS = ("/emby/Sessions/{session_key}", "/Sessions/{session_key}")
# 上报路由：路径 → compat_routes.py 里的处理函数名（只改 body，不改逻辑）
REPORT_PATHS = {
    "/emby/Sessions/Playing": "session_playing",
    "/Sessions/Playing": "session_playing",
    "/emby/Sessions/Playing/Progress": "session_progress",
    "/Sessions/Playing/Progress": "session_progress",
    "/emby/Sessions/Playing/Stopped": "session_stopped",
    "/Sessions/Playing/Stopped": "session_stopped",
}
# 需要从路由表里摘掉的旧端点（端点名用于精确识别，避免误伤同名路径的新实现）
SUPERSEDED_ENDPOINTS = ("get_sessions", "stop_session") + tuple(set(REPORT_PATHS.values()))


def _is_staff(user: models.WebUser) -> bool:
    return bool(getattr(user, "is_staff", False))


def resolve_session_key(db: Session, user: models.WebUser, body: dict) -> str:
    """解析本次上报使用的会话键

    - 客户端自带的 ``PlaySessionId``：只在本用户已有会话（或尚未被占用）时复用；
    - 未带 / 带得不合法 / 属于别的用户：一律返回新的随机键。
    """
    raw = str(body.get("PlaySessionId") or "").strip()
    if raw and SESSION_KEY_RE.match(raw):
        owner = (
            db.query(em.PlaybackSession.user_id)
            .filter(em.PlaybackSession.session_key == raw)
            .first()
        )
        if owner is None or owner[0] == user.id:
            return raw
        logger.warning("忽略被其它用户占用的 PlaySessionId: %s", raw)
    return f"s{secrets.token_urlsafe(16)}"


# ==================== 新实现 ====================


def get_sessions_scoped(
    request: Request,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    """在线会话列表：普通用户只看自己的，管理员（is_staff）看全站

    旧实现没有任何鉴权，任何人拿到的是全站会话（用户名 / 设备 / 客户端 / IP / 在看的条目）。
    """
    query = db.query(em.PlaybackSession).filter(em.PlaybackSession.ended_at.is_(None))
    if not _is_staff(user):
        query = query.filter(em.PlaybackSession.user_id == user.id)
    sessions = query.order_by(em.PlaybackSession.last_update_at.desc()).all()

    if not sessions:
        return []
    # 会话列表会被客户端周期性轮询：一次性取回关联条目与用户，
    # 避免「每条会话各查两次」的 N+1（N 台设备同时播放就是 2N 次查询）
    item_ids = {session.item_id for session in sessions}
    user_ids = {session.user_id for session in sessions}
    items = {
        item.id: item
        for item in db.query(em.MediaItem).filter(em.MediaItem.id.in_(item_ids)).all()
    }
    owners = {
        user.id: user
        for user in db.query(models.WebUser).filter(models.WebUser.id.in_(user_ids)).all()
    }
    return [
        emby_api._now_playing_dto(session, items[session.item_id], owners[session.user_id])
        for session in sessions
        if session.item_id in items and session.user_id in owners
    ]


def stop_session_checked(
    session_key: str,
    user: models.WebUser = Depends(get_emby_user),
    db: Session = Depends(get_db),
):
    """结束播放会话：只能结束自己的，管理员（is_staff）可结束任意会话

    旧实现既没有鉴权，会话键又能从「用户 id + 条目 id」直接算出来。
    """
    session = (
        db.query(em.PlaybackSession)
        .filter(em.PlaybackSession.session_key == session_key)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="播放会话不存在")
    if session.user_id != user.id and not _is_staff(user):
        raise HTTPException(status_code=403, detail="只能结束自己的播放会话")

    # 转码会话按「用户 + 条目 guid」反查（播放会话键与转码 uuid 不是一回事，
    # 旧写法 stop_transcode(session_key) 永远匹配不上）
    item_guid = emby_api.item_guid_for(db, session.item_id)
    session.ended_at = datetime.now()
    db.commit()
    stop_transcodes_for(session.user_id, item_guid)
    return {"success": True}


def _install_report_routes(router, originals: dict) -> int:
    """上报路由：改 body 里的会话键后交给 api.py 的原处理函数

    不改业务逻辑，只保证「会话键一定是随机的、且不会指向别人的会话」。
    """
    installed = 0
    for path, endpoint_name in REPORT_PATHS.items():
        original = originals[endpoint_name]

        async def report(
            request: Request,
            user: models.WebUser = Depends(get_emby_user),
            db: Session = Depends(get_db),
            _original=original,
        ):
            body = await request.json()
            if isinstance(body, dict):
                # 就地改写：starlette 会缓存 Request.json() 的结果，
                # 原处理函数随后读到的就是归一化后的 body。
                body["PlaySessionId"] = resolve_session_key(db, user, body)
            # 原处理函数是同步 def（拆分后跑在线程池）时不 await，直接取返回值
            result = _original(request, user, db)
            if inspect.isawaitable(result):
                result = await result
            return result

        router.post(path)(report)
        installed += 1
    return installed


def install_session_routes(router) -> dict:
    """替换会话端点实现（必须在 ``app.include_router(emby_router)`` **之前**调用）

    返回替换统计，供启动日志与冒烟测试断言。
    """
    kept = []
    superseded = 0
    for route in router.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(getattr(route, "endpoint", None), "__name__", "")
        is_old_list = path in LIST_PATHS and endpoint == "get_sessions"
        is_old_stop = path in STOP_PATHS and endpoint == "stop_session"
        is_old_report = REPORT_PATHS.get(path) == endpoint
        if is_old_list or is_old_stop or is_old_report:
            superseded += 1
            continue
        kept.append(route)
    if superseded:
        router.routes = kept

    for path in LIST_PATHS:
        router.get(path)(get_sessions_scoped)
    for path in STOP_PATHS:
        router.delete(path)(stop_session_checked)
    report_routes = _install_report_routes(
        router, {name: getattr(compat_routes, name) for name in set(REPORT_PATHS.values())}
    )

    logger.info(
        "会话端点：已替换 %d 条旧路由（未鉴权列表/结束 + 可预测会话键），注册 %d 条带鉴权上报路由",
        superseded,
        report_routes,
    )
    return {"superseded": superseded, "report_routes": report_routes}


__all__ = [
    "install_session_routes",
    "resolve_session_key",
    "get_sessions_scoped",
    "stop_session_checked",
    "LIST_PATHS",
    "STOP_PATHS",
    "REPORT_PATHS",
    "SESSION_KEY_RE",
]
