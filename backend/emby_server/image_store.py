"""刮削图片本地化：把 TMDB 的远程图落成本服务器上的文件

**为什么要有这一层**：条目的封面原先只有 ``primary_image_url``（TMDB CDN 地址），
客户端每取一次图都要由服务器**代理去第三方拉一次**——源站慢一点、被限速、临时不可达，
整个媒体库的封面就跟着抖；条件请求（304）只省了带宽，冷启动与缓存穿透的延迟还是压在用户身上。

本地化之后图片走本机磁盘：客户端到本服务器一次往返拿到，不依赖第三方可达性。
磁盘上的那份是**缓存**，不是唯一副本：

- 条目上仍然留着远程图地址，缓存文件被清掉/被删掉都能自愈（取图时按需再落一份，见
  ``media_routes.item_image``）；
- 维护周期会清掉没被任何条目引用的文件（例如换过海报的旧文件），并按上限从旧到新淘汰。

配置（都在环境里，缺省值面向小机器）：

======================  ==========================================================
``EMBY_LOCALIZE_IMAGES``  ``0`` 关闭（默认开启）
``EMBY_IMAGE_DIR``        图片缓存目录（默认 ``<EMBY_TRANSCODE_DIR>/images``）
``EMBY_IMAGE_CACHE_MB``   缓存上限，默认 2048 MB
``EMBY_IMAGE_GRACE_SECONDS`` 新增文件保护期，默认 3600 秒（刚落盘、还没写库的文件不被清理）
``EMBY_IMAGE_TIMEOUT``    单张图下载超时（秒），默认 15
======================  ==========================================================
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024      # 单张图上限：海报/背景图不该有更大的
_LOCKS: dict = {}
_LOCKS_LOCK = threading.Lock()
_STATS = {"downloaded": 0, "failed": 0, "served": 0}


def _env_flag(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int((os.getenv(name) or "").strip() or default))
    except ValueError:
        return default


def enabled() -> bool:
    return _env_flag("EMBY_LOCALIZE_IMAGES", True)


def image_dir() -> str:
    root = os.getenv("EMBY_IMAGE_DIR", "").strip()
    if not root:
        base = os.getenv("EMBY_TRANSCODE_DIR", "/tmp/emby_transcode")
        root = os.path.join(base, "images")
    return root


def is_cached_path(path: Optional[str]) -> bool:
    """这个路径是不是我们自己的图片缓存（用来判断是不是「本地化过的图」）"""
    if not path or path.startswith("http"):
        return False
    root = os.path.abspath(image_dir())
    return os.path.abspath(path).startswith(root + os.sep)


def local_path(url: str) -> str:
    """远程图的本地文件路径（内容寻址：同一张图只落一份）"""
    digest = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:24]
    ext = os.path.splitext(url.split("?", 1)[0])[1].lower()
    if ext not in _IMAGE_EXTS:
        ext = ".jpg"
    return os.path.join(image_dir(), digest + ext)


def _download(url: str) -> Optional[bytes]:
    """下载远程图（失败返回 None：调用方退回远程地址，不影响功能）"""
    try:
        import httpx

        timeout = _env_int("EMBY_IMAGE_TIMEOUT", 15, 1)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code >= 400:
            logger.info("图片本地化跳过（HTTP %s）: %s", resp.status_code, url)
            return None
        content = resp.content or b""
        if not content or len(content) > _MAX_IMAGE_BYTES:
            logger.info("图片本地化跳过（大小 %s 字节）: %s", len(content), url)
            return None
        ctype = (resp.headers.get("content-type") or "").lower()
        if ctype and not ctype.startswith("image/"):
            logger.info("图片本地化跳过（内容类型 %s）: %s", ctype, url)
            return None
        return content
    except Exception as exc:  # noqa: BLE001 — 第三方取不到图不该影响刮削/播放
        logger.info("图片本地化失败（退回远程图）: %s（%s）", url, exc)
        return None


def localize(url: Optional[str]) -> str:
    """把远程图落成本地文件，返回本地路径；失败或未开启返回空串

    同一张图并发请求只下载一次（按 URL 单飞）；文件已经存在就直接复用。
    写文件走「临时文件 → fsync → os.replace」：中途被杀不会留下半张图。
    """
    if not url or not url.startswith("http") or not enabled():
        return ""
    path = local_path(url)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    with _LOCKS_LOCK:
        lock = _LOCKS.get(path) or threading.RLock()
        _LOCKS[path] = lock
    with lock:
        try:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
            content = _download(url)
            if not content:
                _STATS["failed"] += 1
                return ""
            os.makedirs(image_dir(), exist_ok=True)
            tmp = f"{path}.part{os.getpid()}"
            with open(tmp, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            _STATS["downloaded"] += 1
            return path
        except Exception as exc:  # noqa: BLE001 — 落盘失败同样只是“没本地化”
            logger.warning("图片本地化写盘失败 %s: %s", url, exc)
            _STATS["failed"] += 1
            return ""
        finally:
            with _LOCKS_LOCK:
                _LOCKS.pop(path, None)


def referenced_basenames(db) -> set:
    """所有条目引用到的**本地图片文件名**（分批查，避免整库读进内存）"""
    from sqlalchemy import select

    from backend.emby_server import models as em

    found: set = set()
    last_id = 0
    while True:
        rows = db.execute(
            select(em.MediaItem.id, em.MediaItem.poster_path, em.MediaItem.backdrop_path)
            .where(em.MediaItem.id > last_id)
            .order_by(em.MediaItem.id)
            .limit(5000)
        ).all()
        if not rows:
            break
        last_id = rows[-1][0]
        for _id, poster, backdrop in rows:
            for path in (poster, backdrop):
                if is_cached_path(path):
                    found.add(os.path.basename(path))
    return found


def prune(db) -> dict:
    """维护周期的图片缓存清理：先删没被引用的，再按上限从旧到新淘汰

    - **有引用的文件一张都不删**：宁可超出上限（只记日志），也不能把正在用的封面删掉；
    - 刚落下还没落库的文件有保护期（``EMBY_IMAGE_GRACE_SECONDS``）。
    """
    result = {"removed": 0, "freed_bytes": 0, "files": 0, "bytes": 0, "over_limit": False}
    if not enabled():
        return result
    root = image_dir()
    if not os.path.isdir(root):
        return result
    referenced = referenced_basenames(db)
    # 读事务到此为止：下面要删的是磁盘文件（可能几万个 os.remove，走网络挂载更慢），
    # 不能让一次长事务陪着它挂着——SQLite 的 WAL 检查点会被挂着的事务挡住，
    # 表现就是 WAL 文件长期不收敛（见 docs/performance.md 的「事务范围」）。
    # 这里没有待提交的改动（只有上面那次查询），所以 rollback 与 commit 等价，语义更明确。
    db.rollback()
    grace = _env_int("EMBY_IMAGE_GRACE_SECONDS", 3600, 0)
    now = time.time()
    kept: list[tuple[str, int, float]] = []
    for entry in os.scandir(root):
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        if entry.name in referenced or (grace and now - stat.st_mtime < grace):
            kept.append((entry.name, stat.st_size, stat.st_mtime))
            continue
        try:
            os.remove(entry.path)
            result["removed"] += 1
            result["freed_bytes"] += stat.st_size
        except OSError as exc:
            logger.info("删除图片缓存失败 %s: %s", entry.path, exc)
            kept.append((entry.name, stat.st_size, stat.st_mtime))

    total = sum(size for _n, size, _m in kept)
    cap = _env_int("EMBY_IMAGE_CACHE_MB", 2048, 0) * 1024 * 1024
    if cap and total > cap:
        for name, size, _mtime in sorted(kept, key=lambda item: item[2]):
            if total <= cap:
                break
            if name in referenced:
                continue            # 正在用的封面不淘汰
            try:
                os.remove(os.path.join(root, name))
            except OSError:
                continue
            total -= size
            result["removed"] += 1
            result["freed_bytes"] += size
        result["over_limit"] = total > cap
        if result["over_limit"]:
            logger.info("图片缓存仍超出上限（被引用的图不淘汰）：%.0f MB",
                        total / 1024 / 1024)
    result["files"] = sum(1 for entry in os.scandir(root) if entry.is_file())
    result["bytes"] = sum(entry.stat().st_size for entry in os.scandir(root)
                          if entry.is_file())
    return result


def stats() -> dict:
    """图片缓存的当前状态（健康检查 / 测试用）"""
    root = image_dir()
    files = 0
    size = 0
    if os.path.isdir(root):
        for entry in os.scandir(root):
            if not entry.is_file():
                continue
            files += 1
            try:
                size += entry.stat().st_size
            except OSError:
                pass
    return {"enabled": enabled(), "dir": root, "files": files, "bytes": size, **_STATS}
