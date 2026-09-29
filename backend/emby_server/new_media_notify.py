"""新片入库通知：扫描完成后，给管理员推一条新增内容汇总

要解决的问题：扫描器发现新片后从不通知，管理员不知道库里进了什么。
通知管道（TG/邮件/站内）早已存在，这里只做「扫描完成 → 汇总新增 → 发 TG」的接线。

设计（"功能只提供能力"，库名/标题全从数据里取）：
- 触发：扫描成功 / 部分成功且本轮有新增条目时（``maybe_notify_new_media``，
  由 ``scan_queue._run_task`` 在扫描提交完成后调用）。
- 同一轮扫描只发一条汇总消息，不逐部刷屏。
- 查询新增用**独立 Session**（``SessionLocal()`` 新开），绝不碰扫描线程的
  Session——PR #202 的并发教训。
- 真正的活在 daemon 线程里做：查库 → 组消息 → 发 TG。任何异常只记日志，
  绝不影响扫描本身。
- 配置（SystemConfig）：``new_media_notify_enabled``（"1"/"0"，默认 "1"，开箱即有）、
  ``new_media_notify_channels``（逗号分隔，默认 "telegram"，以后可扩展）。
- 收件人：全部启用中的管理员（``is_staff``），走他们绑定的 TG 账号。
  没绑 TG 的管理员记一条 warning 跳过，不报错。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend import models
from backend.database import SessionLocal
from backend.emby_server import models as emby_models
from backend.integrations import store

logger = logging.getLogger(__name__)

CONFIG_ENABLED = "new_media_notify_enabled"
CONFIG_CHANNELS = "new_media_notify_channels"

DEFAULT_ENABLED = True
DEFAULT_CHANNELS = "telegram"

# 消息里最多列出的标题个数，超出截断（防刷屏）
MAX_TITLES = 10


def _get_config(db: Session) -> tuple[bool, list[str]]:
    """读通知配置；返回 (是否启用, 渠道列表)。"""
    vals = store.read_values(
        db,
        [CONFIG_ENABLED, CONFIG_CHANNELS],
        {
            CONFIG_ENABLED: "1" if DEFAULT_ENABLED else "0",
            CONFIG_CHANNELS: DEFAULT_CHANNELS,
        },
    )
    enabled = vals[CONFIG_ENABLED].strip() == "1"
    channels = [c.strip().lower() for c in vals[CONFIG_CHANNELS].split(",") if c.strip()]
    if not channels:
        channels = [DEFAULT_CHANNELS]
    return enabled, channels


def maybe_notify_new_media(
    library_id: int,
    library_name: str,
    started_at: Optional[datetime],
    added_count: int,
) -> None:
    """扫描完成后的通知入口（在扫描工作线程里调用）。

    只是起一个 daemon 线程，立即返回——TG 投递再慢也不会拖住扫描收尾。
    本轮没有新增条目时直接返回，不打扰任何人。
    """
    if not added_count or added_count <= 0:
        return
    thread = threading.Thread(
        target=_notify_worker,
        args=(library_id, library_name, started_at),
        name=f"new-media-notify-{library_id}",
        daemon=True,
    )
    thread.start()


def _notify_worker(
    library_id: int,
    library_name: str,
    started_at: Optional[datetime],
) -> None:
    """后台线程：查本轮新增 → 组消息 → 发给管理员。异常只记日志。"""
    try:
        _do_notify(library_id, library_name, started_at)
    except Exception:  # noqa: BLE001 — 通知失败绝不能影响扫描
        logger.warning(
            "新片入库通知失败（库 id=%s）", library_id, exc_info=True
        )


def _do_notify(
    library_id: int,
    library_name: str,
    started_at: Optional[datetime],
) -> None:
    db = SessionLocal()
    try:
        enabled, channels = _get_config(db)
        if not enabled:
            return

        if started_at is None:
            return
        summary = _summarize_new_items(db, library_id, started_at)
        if summary is None:
            return

        title, content = _build_message(library_name, summary)
        staff_ids = _staff_ids(db)
        if not staff_ids:
            logger.warning("新片入库通知：没有启用中的管理员，跳过发送")
            return
    finally:
        db.close()

    # 投递是异步的；工作线程里没有事件循环，用 asyncio.run 新起一个
    asyncio.run(_send_to_staff(staff_ids, title, content, channels))


def _summarize_new_items(
    db: Session, library_id: int, started_at: datetime
) -> Optional[dict]:
    """汇总本轮新增：只用聚合查询，不把几万条 ORM 对象全载进内存。

    新库首次扫描可能一次新增数万条，这里只取：
    - 新剧/新电影：总数 + 前 MAX_TITLES 个标题
    - 新集：按 series_id 分组计数
    返回 None 表示本轮无新增。
    """
    from sqlalchemy import func

    base = [
        emby_models.MediaItem.library_id == library_id,
        emby_models.MediaItem.date_added >= started_at,
    ]

    sm_q = db.query(emby_models.MediaItem.name).filter(
        *base, emby_models.MediaItem.item_type.in_(["series", "movie"])
    )
    sm_total = sm_q.count()
    sm_names = [
        (n or "").strip()
        for (n,) in sm_q.order_by(emby_models.MediaItem.date_added)
        .limit(MAX_TITLES).all()
    ]
    sm_names = [n for n in sm_names if n]

    ep_rows = (
        db.query(emby_models.MediaItem.series_id, func.count(emby_models.MediaItem.id))
        .filter(*base, emby_models.MediaItem.item_type == "episode")
        .group_by(emby_models.MediaItem.series_id)
        .all()
    )

    if sm_total == 0 and not ep_rows:
        return None

    # 新集按剧查名（一次查齐）
    series_ids = [sid for sid, _ in ep_rows if sid]
    name_map: dict = {}
    if series_ids:
        for sid, nm in (
            db.query(emby_models.MediaItem.id, emby_models.MediaItem.name)
            .filter(emby_models.MediaItem.id.in_(series_ids))
            .all()
        ):
            name_map[sid] = (nm or "").strip() or f"剧集#{sid}"
    ep_groups = [
        (name_map.get(sid, "未知剧集"), cnt) for sid, cnt in ep_rows
    ]
    ep_groups.sort(key=lambda x: x[0])

    return {
        "series_movie_total": sm_total,
        "series_movie_names": sm_names,
        "episode_groups": ep_groups,
    }


def _build_message(library_name: str, summary: dict) -> tuple[str, str]:
    """组一条汇总消息：只列标题，不写简介（不剧透）。"""
    lines: list[str] = []

    # 新剧 / 新电影：列标题
    total = summary["series_movie_total"]
    if total > 0:
        names = summary["series_movie_names"]
        suffix = f"等 {total} 部" if total > MAX_TITLES else ""
        quoted = "".join(f"《{n}》" for n in names)
        lines.append(f"📚 {library_name}新增 {total} 部：{quoted}{suffix}")

    # 老剧出新集：按剧分组，只报"哪部剧多了几集"
    groups = summary["episode_groups"]
    if groups:
        parts = [f"《{s}》新增 {c} 集" for s, c in groups[:MAX_TITLES]]
        suffix = f"等 {len(groups)} 部剧" if len(groups) > MAX_TITLES else ""
        lines.append("🎬 " + "；".join(parts) + suffix)

    title = f"{library_name}有新片入库"
    content = "\n".join(lines)
    return title, content


def _staff_ids(db: Session) -> list[int]:
    rows = (
        db.query(models.WebUser.id)
        .filter(
            models.WebUser.is_staff == True,  # noqa: E712
            models.WebUser.is_active == True,  # noqa: E712
        )
        .all()
    )
    return [r[0] for r in rows]


async def _send_to_staff(
    staff_ids: list[int], title: str, content: str, channels: list[str]
) -> None:
    """给每位管理员发通知。单个失败只记日志，不影响其他人。"""
    from backend.notifications import get_notification_service

    service = get_notification_service()
    # 只用真实存在的渠道，避免"渠道不存在"的 warning 刷屏
    valid = [c for c in channels if c in service.channels]
    if not valid:
        logger.warning("新片入库通知：配置的渠道 %s 都不可用，跳过", channels)
        return

    for staff_id in staff_ids:
        try:
            results = await service.send(
                user_id=staff_id,
                title=title,
                content=content,
                channels=valid,
                message_type="system",
            )
            if not any(results.values()):
                logger.warning(
                    "新片入库通知投递失败（管理员 id=%s）：%s", staff_id, results
                )
        except Exception:  # noqa: BLE001 — 单个管理员失败不影响其他人
            logger.warning(
                "新片入库通知投递异常（管理员 id=%s）", staff_id, exc_info=True
            )
