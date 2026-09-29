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
import re
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024      # 单张图上限：海报/背景图不该有更大的
_LOCKS: dict = {}
_LOCKS_LOCK = threading.Lock()
_STATS = {"downloaded": 0, "failed": 0, "served": 0}

# ---------- 缩略图 ----------
# 海报墙下发 TMDB 原图（500KB–2MB/张）是带宽杀手：缩略图把单张压到几十 KB。
# 尺寸全部参数化（EMBY_THUMB_WIDTHS），只提供能力，不写死业务尺寸。
# “有界”旋钮（最大边/超大图拒绝/并发信号量/内存上限）见下面的 _env_int 之后那段。
_THUMB_QUALITY = 82            # JPEG 质量：82 是体积/观感的甜点
_THUMB_WIDTHS_ENV = "EMBY_THUMB_WIDTHS"

try:  # Pillow 缺席时模块仍可导入（缩略图能力静默关闭，原图逻辑不受影响）
    from PIL import Image as _PILImage
    _PIL_OK = True
except Exception:  # noqa: BLE001
    _PILImage = None
    _PIL_OK = False


def pil_available() -> bool:
    return _PIL_OK


def thumb_widths() -> list[int]:
    """后台预生成的缩略图宽度档（环境变量 EMBY_THUMB_WIDTHS，逗号分隔）"""
    raw = (os.getenv(_THUMB_WIDTHS_ENV) or "320,640").strip()
    out: list[int] = []
    for part in raw.split(","):
        try:
            w = int(part.strip())
        except ValueError:
            continue
        if 1 <= w <= _THUMB_MAX_DIM and w not in out:
            out.append(w)
    return out or [320]


def thumb_variant_path(path: str, max_width: int | None = None,
                       max_height: int | None = None) -> str:
    """缩略图的文件路径（内容寻址：原图 digest + 尺寸，后缀统一 .jpg）"""
    digest = os.path.basename(path).rsplit(".", 1)[0]
    tag = ""
    if max_width:
        tag += f"_w{max_width}"
    if max_height:
        tag += f"_h{max_height}"
    return os.path.join(image_dir(), digest + tag + ".jpg")


def _clamp_dim(value) -> int | None:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return min(v, _THUMB_MAX_DIM)


def resized_variant(path: str, max_width=None, max_height=None) -> str:
    """按需生成等比缩放版本，返回缩略图路径；不需要/失败返回空串（调用方用原图）

    - 只缩小不放大：原图本来就小就直接返回 ""（省一次转码）；
    - 超大原图（默认 >25MP）直接拒绝：Pillow 解码要吃掉几百 MB 内存；
    - 有界并发：同一时刻最多 _THUMB_CONCURRENCY（默认 4）个转码，海报墙
      几十张同时请求也不会把 CPU 打满（海报墙/预热/补生成三条路共用信号量）；
    - 同一尺寸并发只生成一次（沿用 _LOCKS 的按路径单飞）；
    - 写文件走「临时文件 → fsync → os.replace」，中途被杀不留半张图。
    """
    if not _PIL_OK:
        return ""
    width = _clamp_dim(max_width)
    height = _clamp_dim(max_height)
    if not width and not height:
        return ""
    if not path or not os.path.isfile(path):
        return ""
    target = thumb_variant_path(path, width, height)
    if os.path.isfile(target) and os.path.getsize(target) > 0:
        return target
    with _LOCKS_LOCK:
        lock = _LOCKS.get(target) or threading.RLock()
        _LOCKS[target] = lock
    try:
        with lock:
            if os.path.isfile(target) and os.path.getsize(target) > 0:
                return target
            tmp = None
            # 信号量在按路径锁之内：只有真正要转码的线程才占名额
            with _GEN_SEMAPHORE:
                try:
                    with _PILImage.open(path) as img:
                        ow, oh = img.size
                        if ow * oh > _THUMB_MAX_PIXELS:
                            logger.info("原图过大(%dMP)跳过缩略图 %s",
                                        ow * oh // 1_000_000, path)
                            return ""
                        img.load()
                        box_w = width or 10 ** 7
                        box_h = height or 10 ** 7
                        if ow <= box_w and oh <= box_h:
                            return ""  # 已经够小，不用转
                        if img.mode in ("RGBA", "LA", "PA", "P"):
                            img = img.convert("RGB")
                        img.thumbnail((box_w, box_h), _PILImage.LANCZOS)
                        os.makedirs(image_dir(), exist_ok=True)
                        tmp = f"{target}.part{os.getpid()}"
                        img.save(tmp, "JPEG", quality=_THUMB_QUALITY,
                                 optimize=True, progressive=True)
                        with open(tmp, "rb") as fh:
                            os.fsync(fh.fileno())
                        os.replace(tmp, target)
                        tmp = None  # 已换名成功，不用再清
                except Exception as exc:  # noqa: BLE001 — 缩略图失败只是“没小图”，原图照发
                    logger.info("缩略图生成失败 %s: %s", path, exc)
                    if tmp:
                        try:
                            if os.path.isfile(tmp):
                                os.remove(tmp)
                        except OSError:
                            pass
                    return ""
            return target
    finally:
        with _LOCKS_LOCK:
            _LOCKS.pop(target, None)


# ---------- 后台预热队列 ----------
# 入库/刮削落下原图后，把缩略图生成扔进这个单线程队列：不阻塞入库主流程，
# 单线程串行也天然限速，不会跟扫描抢 CPU。
_THUMB_QUEUE = None  # queue.Queue[str]，延迟初始化
_THUMB_QUEUE_LOCK = threading.Lock()


def _thumb_worker() -> None:
    import queue as _queue_mod

    assert _THUMB_QUEUE is not None
    while True:
        path = _THUMB_QUEUE.get()
        try:
            if path and os.path.isfile(path):
                for w in thumb_widths():
                    resized_variant(path, max_width=w)
        except Exception as exc:  # noqa: BLE001
            logger.info("缩略图预热失败 %s: %s", path, exc)
        finally:
            _THUMB_QUEUE.task_done()


def enqueue_thumb_warm(path: str) -> None:
    """原图落盘后调用：后台生成各档缩略图。失败/关闭都静默（按需生成会兜底）。"""
    global _THUMB_QUEUE
    if not _PIL_OK or not path:
        return
    try:
        import queue as _queue_mod

        with _THUMB_QUEUE_LOCK:
            if _THUMB_QUEUE is None:
                _THUMB_QUEUE = _queue_mod.Queue()
                t = threading.Thread(target=_thumb_worker, name="thumb-warm",
                                     daemon=True)
                t.start()
            q = _THUMB_QUEUE
        q.put_nowait(path)
    except Exception:  # noqa: BLE001 — 预热永远不能影响主流程
        pass


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


# ---------- 缩略图“有界”旋钮（借鉴 go-emby：并发 / 内存 / 尺寸三处设上限） ----------
# 海报墙一次几十张图同时请求缩略图：不限并发会把 CPU 打满，不限内存会把服务
# 器吃光，不限尺寸会被恶意参数拖死。这里三处都有上限，全部可环境变量调。
_THUMB_MAX_DIM = _env_int("EMBY_THUMB_MAX_DIM", 4096, 64)
# 单次请求允许的最大边长（防滥用）：超出钳制到这个值
_THUMB_MAX_PIXELS = _env_int("EMBY_THUMB_MAX_MEGAPIXELS", 25, 1) * 1_000_000
# 原图超过这么多像素直接拒绝转码（Pillow 解码 25MP ≈ 75MB 内存，再大不碰）
_THUMB_CONCURRENCY = _env_int("EMBY_THUMB_CONCURRENCY", 4, 1)
# 同时转码的缩略图数（信号量）：海报墙/预热/补生成三条路共用一把
_GEN_SEMAPHORE = threading.Semaphore(_THUMB_CONCURRENCY)
_THUMB_MEM_CAP = _env_int("EMBY_THUMB_MEM_MB", 32, 0) * 1024 * 1024
# 内存缓存总量上限（默认 32MB）：一张缩略图几十 KB，32MB ≈ 缓存上千张热图
_THUMB_MEM_ENTRY_MAX = 2 * 1024 * 1024  # 单条目上限：超过 2MB 的不进内存（异常）


class _ThumbMemCache:
    """缩略图内存 LRU：总量有上限，key 是内容寻址文件名（≈ ETag:宽:高）

    缩略图文件名 = <原图 sha1>_w320.jpg：原图一变文件名就变，宽高也在名
    字里，所以 key 天然等价于「ETag:宽:高」，不会取到过期内容。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, bytes] = {}
        self._bytes = 0

    def get(self, key: str):
        with self._lock:
            data = self._data.get(key)
            if data is None:
                return None
            # LRU：命中的挪到队尾
            del self._data[key]
            self._data[key] = data
            return data

    def put(self, key: str, data: bytes) -> None:
        if not key or not data or len(data) > _THUMB_MEM_ENTRY_MAX:
            return
        if _THUMB_MEM_CAP <= 0:
            return
        with self._lock:
            old = self._data.pop(key, None)
            if old is not None:
                self._bytes -= len(old)
            self._data[key] = data
            self._bytes += len(data)
            while self._data and self._bytes > _THUMB_MEM_CAP:
                oldest = next(iter(self._data))  # py3.7+ dict 有序：队头最老
                self._bytes -= len(self._data.pop(oldest))

    def drop(self, key: str) -> None:
        with self._lock:
            old = self._data.pop(key, None)
            if old is not None:
                self._bytes -= len(old)

    def snapshot(self) -> dict:
        with self._lock:
            return {"entries": len(self._data), "bytes": self._bytes,
                    "cap_bytes": _THUMB_MEM_CAP}


_THUMB_MEM = _ThumbMemCache()


def thumb_mem_get(name: str):
    """内存缓存读（未命中返回 None，调用方回退读盘）"""
    return _THUMB_MEM.get(name)


def thumb_mem_put(name: str, data: bytes) -> None:
    """内存缓存写（超上限自动淘汰最老，失败静默）"""
    _THUMB_MEM.put(name, data)


def thumb_mem_drop(name: str) -> None:
    """删文件时顺手清内存（prune 用）"""
    _THUMB_MEM.drop(name)


def is_thumb_variant(path: str) -> bool:
    """是不是缩略图文件（服务层用它决定走内存缓存还是 FileResponse）"""
    return _thumb_digest(os.path.basename(path or "")) is not None


def pick_dim(*values) -> int | None:
    """多个尺寸别名取第一个合法值：标准 Emby maxWidth/maxHeight 优先，其次 w/h"""
    for v in values:
        d = _clamp_dim(v)
        if d:
            return d
    return None


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
            # 原图落盘后，后台预热各档缩略图（不阻塞调用方，失败静默）
            enqueue_thumb_warm(path)
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


_THUMB_NAME_RE = re.compile(r"^[0-9a-f]{8,}(_[wh]\d+)+$")


def _thumb_digest(name: str) -> Optional[str]:
    """缩略图文件名反查原图 digest；不是缩略图返回 None

    缩略图命名：<hex digest>_w320.jpg / _h640.jpg / _w320_h640.jpg
    （digest 是原图文件名的 sha1，40 位；tag 一定是 _w数字 / _h数字 组合，
    原图文件名里不会出现这种后缀，所以不会误判）
    """
    base, dot, _ext = name.partition(".")
    if not dot or _THUMB_NAME_RE.match(base) is None:
        return None
    return base.split("_", 1)[0]


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
    # 下面两段是缩略图感知的清理：
    # - 被引用的原图的缩略图同样受保护（不删）；
    # - 删掉原图时，它的缩略图一起删（不留孤儿小图）。
    referenced_digests = {name.rsplit(".", 1)[0] for name in referenced}
    thumbs_of: dict[str, list[str]] = {}
    for entry in os.scandir(root):
        if not entry.is_file():
            continue
        digest = _thumb_digest(entry.name)
        if digest:
            thumbs_of.setdefault(digest, []).append(entry.name)
    # 读事务到此为止：下面要删的是磁盘文件（可能几万个 os.remove，走网络挂载更慢），
    # 不能让一次长事务陪着它挂着——SQLite 的 WAL 检查点会被挂着的事务挡住，
    # 表现就是 WAL 文件长期不收敛（见 docs/performance.md 的「事务范围」）。
    # 这里没有待提交的改动（只有上面那次查询），所以 rollback 与 commit 等价，语义更明确。
    db.rollback()
    grace = _env_int("EMBY_IMAGE_GRACE_SECONDS", 3600, 0)
    now = time.time()
    kept: list[tuple[str, int, float]] = []
    protected = set(referenced)  # 原图 + 被引用的缩略图：清理与淘汰都不动

    def _remove_file(name: str) -> int:
        """删一个文件（含它的缩略图），返回释放的字节数"""
        freed = 0
        candidates = [name]
        digest = name.rsplit(".", 1)[0]
        candidates.extend(n for n in thumbs_of.get(digest, []) if n != name)
        for cname in candidates:
            try:
                st = os.stat(os.path.join(root, cname))
                os.remove(os.path.join(root, cname))
                thumb_mem_drop(cname)  # 内存里那份也清掉（key 是文件名，内容寻址）
                freed += st.st_size
                result["removed"] += 1
                result["freed_bytes"] += st.st_size
            except OSError as exc:
                logger.info("删除图片缓存失败 %s: %s", cname, exc)
        return freed

    for entry in os.scandir(root):
        if not entry.is_file():
            continue
        digest = _thumb_digest(entry.name)
        if entry.name in referenced or (digest and digest in referenced_digests):
            if digest and digest in referenced_digests:
                protected.add(entry.name)
            try:
                stat = entry.stat()
            except OSError:
                continue
            kept.append((entry.name, stat.st_size, stat.st_mtime))
            continue
        if digest and digest not in referenced_digests:
            # 孤儿缩略图（原图早被删了）：直接清掉，不占保护期
            try:
                stat = entry.stat()
                os.remove(entry.path)
                thumb_mem_drop(entry.name)
                result["removed"] += 1
                result["freed_bytes"] += stat.st_size
            except OSError as exc:
                logger.info("删除图片缓存失败 %s: %s", entry.path, exc)
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        if grace and now - stat.st_mtime < grace:
            kept.append((entry.name, stat.st_size, stat.st_mtime))
            continue
        freed_before = result["freed_bytes"]
        _remove_file(entry.name)
        if result["freed_bytes"] == freed_before:
            kept.append((entry.name, stat.st_size, stat.st_mtime))

    total = sum(size for _n, size, _m in kept)
    cap = _env_int("EMBY_IMAGE_CACHE_MB", 2048, 0) * 1024 * 1024
    if cap and total > cap:
        for name, size, _mtime in sorted(kept, key=lambda item: item[2]):
            if total <= cap:
                break
            if name in protected:
                continue            # 正在用的封面（含它的缩略图）不淘汰
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
    thumbs = 0
    if os.path.isdir(root):
        for entry in os.scandir(root):
            if not entry.is_file():
                continue
            files += 1
            if _thumb_digest(entry.name):
                thumbs += 1
            try:
                size += entry.stat().st_size
            except OSError:
                pass
    return {"enabled": enabled(), "dir": root, "files": files, "thumbs": thumbs,
            "bytes": size, "pil": _PIL_OK,
            "thumb_max_dim": _THUMB_MAX_DIM,
            "thumb_concurrency": _THUMB_CONCURRENCY,
            "thumb_mem": _THUMB_MEM.snapshot(), **_STATS}


# ---------- 历史补生成 ----------
# 3 万+条目已有海报但没缩略图：按 id 水位增量补，断点续跑。
# 限速：每批有条数上限 + 单批时间上限 + 条目间小睡，不跟扫描抢资源。
_BACKFILL_KEY = "thumb_backfill_last_id"
_BACKFILL_BATCH = 200
_BACKFILL_MAX_SECONDS = 240
_BACKFILL_SLEEP = 0.05


def backfill_status(db) -> dict:
    """补生成进度（管理后台展示用）"""
    from backend.integrations import store

    vals = store.read_values(db, [_BACKFILL_KEY], {_BACKFILL_KEY: "0"})
    try:
        last_id = int(vals[_BACKFILL_KEY] or 0)
    except ValueError:
        last_id = 0
    return {"last_id": last_id, "widths": thumb_widths(), "pil": _PIL_OK,
            "enabled": enabled()}


def backfill_thumbnails(db, batch_size: int = _BACKFILL_BATCH,
                        max_seconds: float = _BACKFILL_MAX_SECONDS) -> dict:
    """补生成一批缩略图（幂等、可重入）

    - 从 SystemConfig 的水位键继续，不重复做；
    - 每批最多 batch_size 条 / max_seconds 秒，超时即停，下次继续；
    - 条目间睡 _BACKFILL_SLEEP 秒，给扫描让路；
    - 每批结束提交水位，进程被杀也不丢进度。
    """
    from sqlalchemy import select

    from backend.emby_server import models as em
    from backend.integrations import store

    result = {"processed": 0, "generated": 0, "skipped": 0, "last_id": 0,
              "done": False}
    if not enabled() or not _PIL_OK:
        return result
    vals = store.read_values(db, [_BACKFILL_KEY], {_BACKFILL_KEY: "0"})
    try:
        last_id = int(vals[_BACKFILL_KEY] or 0)
    except ValueError:
        last_id = 0
    widths = thumb_widths()
    deadline = time.time() + max(1.0, max_seconds)
    batch = max(1, min(batch_size, 2000))
    while result["processed"] < batch and time.time() < deadline:
        rows = db.execute(
            select(em.MediaItem.id, em.MediaItem.poster_path,
                   em.MediaItem.backdrop_path)
            .where(em.MediaItem.id > last_id)
            .order_by(em.MediaItem.id)
            .limit(500)
        ).all()
        if not rows:
            result["done"] = True
            break
        for _id, poster, backdrop in rows:
            last_id = _id
            result["processed"] += 1
            made = False
            for path in (poster, backdrop):
                if not path or not is_cached_path(path):
                    continue
                if not os.path.isfile(path):
                    continue
                for w in widths:
                    if resized_variant(path, max_width=w):
                        made = True
            if made:
                result["generated"] += 1
            else:
                result["skipped"] += 1
            time.sleep(_BACKFILL_SLEEP)
            if result["processed"] >= batch or time.time() >= deadline:
                break
        store.write_values(db, {_BACKFILL_KEY: str(last_id)},
                           {_BACKFILL_KEY: "缩略图补生成水位（条目 id）"})
        db.commit()
    result["last_id"] = last_id
    return result
