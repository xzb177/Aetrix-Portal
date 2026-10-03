"""远程挂载「路径 → 上游文件 ID」持久化映射（播放秒开）

解决的是什么
------------
播放 ``mount://1/MoviePilot/电影/某片/某片.mkv`` 时，``GoogleDriveMount`` 原本要
靠 ``_parent_id()`` **逐级下钻**去解析目录：Drive 不支持按路径查，每一级目录都要
一次 ``files.list``。4 层目录 = 4~5 次请求 × 200~500ms = **点开要等 1~2 秒**。
目录列举缓存（``MOUNT_LIST_CACHE_SECONDS``，默认 30 秒）能盖住「同一次浏览内重复
播放」，但盖不住「过一会儿再看同一个片」——缓存一过期，第一段字节就卡在目录解析上。

AList 等项目是「路径 → 文件 ID 存库，点播零 API 请求」，所以秒开。这里做同一件事：
解析出文件 ID 之后把它落库，之后同一路径直接拼下载地址，**一次 Google API 都不调**。

为什么存数据库而不是 Redis
--------------------------
挂载条目本来就在库里，而 Redis 在本项目是**可选**依赖（``REDIS_ENABLED``）。放 Redis
会让「有 Redis 的部署」和「没有的部署」行为不一致，且重启即失效（等于又要重新解析一遍）。
库是必有且唯一的持久层，放这里口径统一。

只缓存 file id，不缓存任何凭据
------------------------------
``access_token`` 有效期只有一小时、且与服务账号轮换池绑定；把它落库等于把凭据写进
磁盘。播放时取 token 的路径**一字未改**：``self._token()`` 每次现取，带提前 5 分钟
的过期判断。缓存里只有一串 Drive 文件 ID，不是秘密。

失效怎么自愈
------------
文件在 Drive 上被移动 / 改名 / 删除后，缓存里的 file id 会失效（``alt=media`` 返回
404）。这里**不做主动全量校验**——那等于每次播放都打一次 API，秒开就没了。改成
**懒失效**：缓存命中直接用，等真的 404 了，由播放路径调 :func:`invalidate` 清掉这一条
并重新解析一次、重试，把新 file id 写回。详见 ``api.py`` 里套 ``serve_remote_async``
的那一层。

判重的键用哈希而不是 ``(mount_id, rel_path`` 唯一索引
---------------------------------------------------
``rel_path`` 是 ``String(1000)``（与 ``local_cache.source_path`` 同规格）。中文路径按
utf8 一个字 3 字节算，1000 字最坏 3000 字节，**超过 PostgreSQL btree 索引项 2704
字节的上限**，建表就会失败。所以唯一索引用 ``path_hash``（sha256 定长 64 字符 =
256 字节，任何库都安全），``mount_id`` / ``rel_path`` 另存为普通列，方便排查与按挂载
清理。
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: 缓存最长存活天数：0 = 永不按时间过期（默认走下面的保守值）。
#:
#: 为什么要过期：file id 不会自己变，但**条目**会被删库/改绑挂载。留着不过期的行会
#: 无限增长（每部片一行）。180 天足够盖住任何片的复看周期，又不至于让表长到扫不动。
RETENTION_DAYS = 180

#: 进程内统计（跨重启清零，只给「现在热不热」看个大概，不做业务判断）
_stats = {"hit": 0, "miss": 0, "store": 0, "invalidate": 0}


def path_hash(mount_id: int, rel: str) -> str:
    """挂载 + 相对路径的定长键

    用 ``\\x00`` 分隔：挂载 ID 是数字、路径以 ``/`` 开头，这个分隔符不可能出现在任一
    侧，所以 ``(1, "/a")`` 与 ``(1/0, "a")`` 之类的歧义构造不出来。
    """
    raw = f"{int(mount_id)}\x00{normalize_rel(rel)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_rel(rel: str) -> str:
    """相对路径归一：统一以 ``/`` 开头、去掉尾部斜杠。

    必须归一，否则 ``/a/b`` 与 ``a/b`` 会算出两个哈希，缓存永远命中不了——
    这正是「看起来存了、其实一直不命中」最难查的那类 bug。
    """
    return "/" + (rel or "").strip().strip("/")


def _usable(db: Optional[Session]) -> bool:
    """缓存是加速手段，不是播放的前提条件：任何不可用情形都直接返回 False。"""
    if db is None:
        return False
    try:
        db.execute  # noqa: B018 — 只为触发属性访问，确保是个活的 Session
    except Exception:  # pragma: no cover
        return False
    return True


def lookup(db: Optional[Session], mount_id: int, rel: str) -> str:
    """取缓存的 file id；没有或读失败一律返回空串（调用方走原来的解析路径）"""
    if not _usable(db):
        return ""
    try:
        from backend.emby_server import models as em

        row = (
            db.query(em.MountFileIdCache)
            .filter(em.MountFileIdCache.path_hash == path_hash(mount_id, rel))
            .first()
        )
        if row is None or not row.file_id:
            _stats["miss"] += 1
            return ""
        # 命中统计与最后使用时间：LRU 淘汰的依据，也是「这套东西到底有没有用」的答案
        row.hits = int(row.hits or 0) + 1
        row.last_used_at = datetime.now()
        db.flush()
        _stats["hit"] += 1
        return str(row.file_id)
    except Exception:  # noqa: BLE001 — 缓存出问题绝不能连累播放
        logger.warning("读取文件 ID 缓存失败，回落实时解析: %s", rel, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return ""


def store(
    db: Optional[Session],
    mount_id: int,
    rel: str,
    file_id: str,
    size: int = 0,
) -> bool:
    """写回一条映射。返回是否真的写进去了（失败只记日志，不抛）。"""
    if not _usable(db) or not file_id:
        return False
    key = path_hash(mount_id, rel)
    try:
        from backend.emby_server import models as em

        row = db.query(em.MountFileIdCache).filter(
            em.MountFileIdCache.path_hash == key
        ).first()
        now = datetime.now()
        if row is None:
            db.add(em.MountFileIdCache(
                mount_id=int(mount_id),
                rel_path=normalize_rel(rel),
                path_hash=key,
                file_id=str(file_id)[:255],
                size=int(size or 0),
                hits=0,
                last_used_at=now,
            ))
        else:
            # 同一个路径解析出了不同的 id = 文件被移走又换了新 id，这一行就地更新
            row.file_id = str(file_id)[:255]
            row.size = int(size or 0)
            row.last_used_at = now
        db.flush()
        _stats["store"] += 1
        return True
    except Exception:  # noqa: BLE001
        logger.warning("写入文件 ID 缓存失败: %s", rel, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def invalidate(db: Optional[Session], mount_id: int, rel: str) -> int:
    """删掉一条映射（缓存里的 id 已失效时）。返回删掉的条数。"""
    if not _usable(db):
        return 0
    try:
        from backend.emby_server import models as em

        deleted = (
            db.query(em.MountFileIdCache)
            .filter(em.MountFileIdCache.path_hash == path_hash(mount_id, rel))
            .delete(synchronize_session=False)
        )
        db.flush()
        if deleted:
            _stats["invalidate"] += 1
        return int(deleted or 0)
    except Exception:  # noqa: BLE001
        logger.warning("删除文件 ID 缓存失败: %s", rel, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


def invalidate_all_for_mount(db: Optional[Session], mount_id: int) -> int:
    """清掉整个挂载的缓存（挂载重新授权 / 换了 drive_id 之后用）"""
    if not _usable(db):
        return 0
    try:
        from backend.emby_server import models as em

        deleted = (
            db.query(em.MountFileIdCache)
            .filter(em.MountFileIdCache.mount_id == int(mount_id))
            .delete(synchronize_session=False)
        )
        db.flush()
        return int(deleted or 0)
    except Exception:  # noqa: BLE001
        logger.warning("清空挂载 %s 的文件 ID 缓存失败", mount_id, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


def prune(db: Session, days: Optional[int] = None) -> int:
    """按最后使用时间清理长期没人碰的行。返回删掉的条数。"""
    keep_days = RETENTION_DAYS if days is None else max(0, int(days))
    if keep_days <= 0:
        return 0
    try:
        from backend.emby_server import models as em

        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = (
            db.query(em.MountFileIdCache)
            .filter(em.MountFileIdCache.last_used_at.isnot(None),
                    em.MountFileIdCache.last_used_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(deleted or 0)
    except Exception:  # noqa: BLE001
        logger.warning("清理文件 ID 缓存失败", exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


def stats(db: Optional[Session]) -> dict:
    """命中率观测（给后台看的：这套东西到底省了多少 Drive 请求）"""
    total = 0
    if _usable(db):
        try:
            from backend.emby_server import models as em

            total = int(
                db.query(em.MountFileIdCache).count() or 0
            )
        except Exception:  # noqa: BLE001
            total = 0
    hit, miss = _stats["hit"], _stats["miss"]
    return {
        "rows": total,
        "hit": hit,
        "miss": miss,
        "store": _stats["store"],
        "invalidate": _stats["invalidate"],
        "hit_rate": round(hit / (hit + miss), 4) if (hit + miss) else None,
        "retention_days": RETENTION_DAYS,
    }


__all__ = [
    "RETENTION_DAYS", "path_hash", "normalize_rel", "lookup", "store",
    "invalidate", "invalidate_all_for_mount", "prune", "stats",
]