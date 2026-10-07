# -*- coding: utf-8 -*-
"""自动合并同目录视频为多版本（对标 StrmAssistant MergeMultiVersionTask）。

StrmAssistant 做法（ScheduledTask/MergeMultiVersionTask.cs）：
- 按 ProviderId（tmdb/imdb/tvdb）分组
- 同组内用 union-find 合并（处理传递性：A~B, B~C → A,B,C 一组）
- 调用 _libraryManager.MergeItems(movies) 物理合并为多版本

本模块一比一复刻：
- 定时任务：扫描 movie/series，按 tmdb_id（优先）/imdb_id 分组
- union-find 处理传递闭包
- 物理合并：被合并条目的 merged_into_id 指向主记录
- 主记录选择：复用 dedup.pick_primary（有海报 > 有 tmdb > 有简介 > id 小）

与 dedup.py 的关系：
- dedup.py 是展示层去重（API 过滤），本模块是数据层物理合并
- 两者互补：物理合并后展示层自然只有一条；展示层是合并前的兜底
"""

import logging
import os
import threading
import time
from types import SimpleNamespace
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float, lo: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, value)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


# 开关：默认开
MERGE_VERSIONS_ENABLED = (
    os.getenv("MERGE_VERSIONS_ENABLED", "1") or "1"
).strip().lower() not in ("0", "false", "no")
# 扫描间隔（秒），默认 24 小时（合并是低频操作）
MERGE_VERSIONS_INTERVAL_SEC = _env_float(
    "MERGE_VERSIONS_INTERVAL_SEC", 86400.0, 3600.0
)
# 单次最多合并组数
MERGE_VERSIONS_BATCH_LIMIT = _env_int(
    "MERGE_VERSIONS_BATCH_LIMIT", 1000, 10, 100000
)

_merge_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_start_lock = threading.Lock()


# ---------------------------------------------------------------------------
# union-find（对标 StrmAssistant 的 Union/Find）
# ---------------------------------------------------------------------------

def _find(x: int, parent: Dict[int, int]) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(a: int, b: int, parent: Dict[int, int]):
    ra, rb = _find(a, parent), _find(b, parent)
    if ra != rb:
        # 小 id 做根（稳定）
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb


def _provider_key(item) -> Optional[Tuple]:
    """去重键：与 dedup.dedup_key() 口径看齐。

    键格式：(library_id, item_type, provider, provider_id)。
    必须带 library_id（防跨库合并：同 tmdb_id 的电影分属两个库不能合并）
    和 item_type（防跨类型合并：TMDB movie/tv 编号序列独立，数字可能重合）。
    """
    tmdb_id = (getattr(item, "tmdb_id", None) or "").strip()
    imdb_id = (getattr(item, "imdb_id", None) or "").strip()
    provider = None
    provider_id = ""
    if tmdb_id:
        provider, provider_id = "tmdb", tmdb_id
    elif imdb_id:
        provider, provider_id = "imdb", imdb_id
    else:
        return None
    return (
        getattr(item, "library_id", None),
        getattr(item, "item_type", None),
        provider,
        provider_id,
    )


def find_duplicate_groups(db) -> List[List]:
    """找出需要合并的组（对标 FindDuplicateSeries/ExecuteMergeMovies 的分组逻辑）。

    返回：每组是 [item, ...]，组内条目应合并为多版本。
    只返回尚未合并的（merged_into_id IS NULL）且组内有 2+ 条目的。
    """
    from backend.emby_server import models as em

    # 只查 movie/series，有 tmdb_id 或 imdb_id，未被合并，未软删除
    # 注意：只查有 tmdb_id/imdb_id 的（无 provider ID 的不参与合并，对标 HasAnyProviderId）
    # 两阶段：先只取分组所需的轻量列（id/library_id/item_type/tmdb_id/imdb_id），
    # 找出重复组后，再按 id 加载全行做合并——避免每天拉 1 万个全量 ORM 进内存
    light_rows = (
        db.query(
            em.MediaItem.id,
            em.MediaItem.library_id,
            em.MediaItem.item_type,
            em.MediaItem.tmdb_id,
            em.MediaItem.imdb_id,
        )
        .filter(
            em.MediaItem.item_type.in_(("movie", "series")),
            em.MediaItem.deleted_at.is_(None),
            em.MediaItem.merged_into_id.is_(None),
            (em.MediaItem.tmdb_id.isnot(None) | em.MediaItem.imdb_id.isnot(None)),
        )
        .order_by(em.MediaItem.id.asc())
        .limit(MERGE_VERSIONS_BATCH_LIMIT * 10)
        .all()
    )

    # 按 provider key 分组（含 library_id/item_type，防跨库跨类型合并）
    groups: Dict[Tuple, List] = {}
    for row in light_rows:
        # Row 转命名空间，复用 _provider_key 的 getattr 口径
        item_ns = SimpleNamespace(
            library_id=row.library_id,
            item_type=row.item_type,
            tmdb_id=row.tmdb_id,
            imdb_id=row.imdb_id,
        )
        key = _provider_key(item_ns)
        if key:
            groups.setdefault(key, []).append(row.id)

    # 只保留 2+ 条目的组
    dup_id_groups = [g for g in groups.values() if len(g) >= 2]
    if not dup_id_groups:
        return []

    # 按 id 加载全行（只加载需要合并的组）
    wanted_ids = {i for g in dup_id_groups for i in g}
    items = (
        db.query(em.MediaItem)
        .filter(em.MediaItem.id.in_(wanted_ids))
        .all()
    )
    item_by_id = {item.id: item for item in items}

    # union-find 处理传递性（虽然按 key 分组已天然传递，但保留结构以对标）
    parent: Dict[int, int] = {}
    for id_group in dup_id_groups:
        for item_id in id_group:
            if item_id not in parent:
                parent[item_id] = item_id
        root = id_group[0]
        for item_id in id_group[1:]:
            _union(root, item_id, parent)

    # 按根分组（id → 全行对象）
    by_root: Dict[int, List] = {}
    for item_id in parent:
        r = _find(item_id, parent)
        item = item_by_id.get(item_id)
        if item is not None:
            by_root.setdefault(r, []).append(item)

    return [g for g in by_root.values() if len(g) >= 2]


def merge_group(db, group: List) -> int:
    """合并一组：选主记录，其余 merged_into_id 指向主记录。

    返回被合并的条目数。
    """
    from backend.emby_server import dedup

    if len(group) < 2:
        return 0
    primary = dedup.pick_primary(group)
    merged = 0
    for item in group:
        if item.id == primary.id:
            continue
        # 已被合并的跳过（防重复）
        if item.merged_into_id is not None:
            continue
        item.merged_into_id = primary.id
        merged += 1
        logger.debug(
            "多版本合并：%s (id=%d) → 主记录 %s (id=%d)",
            item.name, item.id, primary.name, primary.id,
        )
    return merged


def get_alternate_versions(db, primary_id: int) -> List:
    """获取主记录的所有版本（含主记录自己）。"""
    from backend.emby_server import models as em

    primary = db.query(em.MediaItem).filter(em.MediaItem.id == primary_id).first()
    if not primary or primary.deleted_at is not None:
        return []
    alternates = (
        db.query(em.MediaItem)
        .filter(
            em.MediaItem.merged_into_id == primary_id,
            em.MediaItem.deleted_at.is_(None),
        )
        .all()
    )
    return [primary] + alternates


def unmerge_version(db, item_id: int) -> bool:
    """解除单个条目的合并：将其 merged_into_id 清空，恢复为独立条目。

    返回 True 表示成功找到并解除。
    """
    from backend.emby_server import models as em

    item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
    if not item or not item.merged_into_id:
        return False
    item.merged_into_id = None
    logger.info("解除多版本合并：%s (id=%d) 恢复为独立条目", item.name, item.id)
    return True


def unmerge_all(db, primary_id: int) -> int:
    """解除某主记录下所有版本的合并，返回解除的数量。"""
    from backend.emby_server import models as em

    items = (
        db.query(em.MediaItem)
        .filter(em.MediaItem.merged_into_id == primary_id)
        .all()
    )
    for item in items:
        item.merged_into_id = None
    if items:
        logger.info("解除多版本合并：主记录 id=%d 下 %d 个版本恢复独立",
                    primary_id, len(items))
    return len(items)


def _merge_once() -> Tuple[int, int]:
    """跑一轮合并：返回 (组数, 合并条目数)。"""
    from backend.database import SessionLocal

    groups = []
    total_merged = 0
    db = SessionLocal()
    try:
        groups = find_duplicate_groups(db)
        groups = groups[:MERGE_VERSIONS_BATCH_LIMIT]
        for group in groups:
            if _stop_event.is_set():
                break
            try:
                merged = merge_group(db, group)
                total_merged += merged
                if merged:
                    db.commit()
            except Exception as e:
                db.rollback()
                logger.warning("合并组失败: %s", e)
        return len(groups), total_merged
    finally:
        db.close()


def _merge_loop():
    logger.info(
        "多版本合并 worker 启动（间隔 %.0f 秒）", MERGE_VERSIONS_INTERVAL_SEC
    )
    try:
        groups, merged = _merge_once()
        logger.info("多版本合并首轮完成：%d 组，合并 %d 条", groups, merged)
    except Exception as e:
        logger.warning("多版本合并首轮失败: %s", e)
    while not _stop_event.wait(MERGE_VERSIONS_INTERVAL_SEC):
        try:
            groups, merged = _merge_once()
            if groups:
                logger.info("多版本合并完成：%d 组，合并 %d 条", groups, merged)
        except Exception as e:
            logger.warning("多版本合并失败: %s", e)
        finally:
            from backend.emby_server import worker_registry as _wr
            _wr.heartbeat("merge_versions")


def start() -> bool:
    """启动多版本合并后台线程。"""
    global _merge_thread
    if not MERGE_VERSIONS_ENABLED:
        logger.info("多版本合并已禁用（MERGE_VERSIONS_ENABLED=0）")
        return False
    with _start_lock:
        if _merge_thread and _merge_thread.is_alive():
            return True
        _stop_event.clear()
        _merge_thread = threading.Thread(
            target=_merge_loop, name="merge-versions", daemon=True
        )
        _merge_thread.start()
        from backend.emby_server import worker_registry as _wr
        _wr.register("merge_versions", _merge_thread)
        return True


def stop():
    _stop_event.set()
