"""StrmAssistant #9 对标：演职人员增强（RefreshPersonTask）

定时刷新演员信息：
1. 去重：同 person_tmdb_id 的重复演员行只保留一条（按 item_id 分组）
2. 补全：头像为空的演员，尝试从 TMDB 拉取最新头像

与 enrich 的 _apply_cast 互补：enrich 在刮削时写演员，
本任务在后台定期检查数据质量。
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

# 默认 24 小时跑一次
REFRESH_INTERVAL_SEC = int(os.getenv("PERSON_REFRESH_INTERVAL_SEC", "86400"))
# 单次最多处理条数（防打爆 TMDB）
MAX_ITEMS_PER_RUN = int(os.getenv("PERSON_REFRESH_MAX_ITEMS", "500"))


def find_duplicate_persons(db) -> list[tuple]:
    """找重复的演员行：同 item_id + 同 person_tmdb_id 有多条。

    返回 [(item_id, person_tmdb_id, count), ...]
    """
    from sqlalchemy import func
    from backend.emby_server import models as em

    rows = (
        db.query(
            em.EmbyPerson.item_id,
            em.EmbyPerson.person_tmdb_id,
            func.count(em.EmbyPerson.id).label("cnt"),
        )
        .filter(em.EmbyPerson.person_tmdb_id.isnot(None))
        .filter(em.EmbyPerson.person_tmdb_id != "")
        .group_by(em.EmbyPerson.item_id, em.EmbyPerson.person_tmdb_id)
        .having(func.count(em.EmbyPerson.id) > 1)
        .limit(MAX_ITEMS_PER_RUN)
        .all()
    )
    return [(r.item_id, r.person_tmdb_id, r.cnt) for r in rows]


def deduplicate_persons(db) -> int:
    """删除重复的演员行（保留 id 最小的一条）。返回删除数。"""
    from backend.emby_server import models as em

    total_deleted = 0
    for item_id, person_tmdb_id, _cnt in find_duplicate_persons(db):
        # 保留 id 最小的，删其余
        keep = (
            db.query(em.EmbyPerson.id)
            .filter(em.EmbyPerson.item_id == item_id)
            .filter(em.EmbyPerson.person_tmdb_id == person_tmdb_id)
            .order_by(em.EmbyPerson.id.asc())
            .first()
        )
        if not keep:
            continue
        deleted = (
            db.query(em.EmbyPerson)
            .filter(em.EmbyPerson.item_id == item_id)
            .filter(em.EmbyPerson.person_tmdb_id == person_tmdb_id)
            .filter(em.EmbyPerson.id != keep.id)
            .delete(synchronize_session=False)
        )
        total_deleted += deleted
    if total_deleted:
        db.commit()
    return total_deleted


def find_persons_missing_image(db, limit: int = 100) -> list:
    """找头像为空但有 person_tmdb_id 的演员（可尝试补全）。"""
    from backend.emby_server import models as em

    return (
        db.query(em.EmbyPerson)
        .filter(em.EmbyPerson.person_tmdb_id.isnot(None))
        .filter(em.EmbyPerson.person_tmdb_id != "")
        .filter((em.EmbyPerson.image.is_(None)) | (em.EmbyPerson.image == ""))
        .limit(limit)
        .all()
    )


def refresh_person_images(db) -> int:
    """补全缺失的演员头像（调 TMDB person 接口）。

    返回补全数。失败不抛异常（后台任务不该崩）。
    """
    from backend.emby_server import models as em
    from backend.emby_server.tmdb import tmdb_client, image_base

    persons = find_persons_missing_image(db, limit=50)
    if not persons:
        return 0

    fixed = 0
    client = tmdb_client()
    base = image_base()
    for p in persons:
        try:
            data = client._get(f"/person/{p.person_tmdb_id}", {"language": "en-US"})
            profile = (data or {}).get("profile_path")
            if profile:
                p.image = f"{base}/w185{profile}"
                fixed += 1
        except Exception as exc:  # noqa: BLE001 — 单个失败不影响其他
            logger.debug("刷新演员头像失败 %s: %s", p.name, exc)
    if fixed:
        db.commit()
    return fixed


def run_once(db) -> dict:
    """执行一轮：去重 + 补头像。返回统计。"""
    t0 = time.monotonic()
    deduped = deduplicate_persons(db)
    images_fixed = refresh_person_images(db)
    return {
        "deduplicated": deduped,
        "images_fixed": images_fixed,
        "elapsed_sec": round(time.monotonic() - t0, 2),
    }


def start() -> bool:
    """启动定时任务（后台线程，每 24 小时跑一轮）。"""
    import threading

    def _loop():
        while True:
            try:
                time.sleep(REFRESH_INTERVAL_SEC)
                from backend.database import get_db

                db = next(get_db())
                try:
                    stats = run_once(db)
                    logger.info("演员刷新完成: %s", stats)
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001 — 后台任务不崩
                logger.warning("演员刷新失败: %s", exc)

    t = threading.Thread(target=_loop, daemon=True, name="refresh-person")
    t.start()
    return True
