"""存储挂载：把不同来源的内容接到媒体库上

一个**挂载**就是一种「把内容接进媒体库」的方式。挂载本身不拥有条目，媒体库通过
``Library.mount_ids`` 引用它，所以同一个挂载可以被多个库共用。

支持的挂载类型（``MOUNT_TYPES``）：

============================  ====================================================
``local``                     本机目录。rclone / CloudDrive2 / SMB / NFS 已经挂到本机
                              之后，对面板就是一条路径——这类「挂载盘」不需要特殊支持，
                              但显式声明成挂载后可以单独测试、单独停用。
``strm``                      STRM 目录。本地只放 ``.strm`` 小文件，文件内容是一条播放
                              直链；扫描按文件名建条目，播放时读文件内容取直链。
``115``                       115 网盘直挂。Cookie 型 API 直接读网盘目录，**不需要把网盘
                              挂到本机**，也不依赖 115 OpenAPI。
``webdav``                    通用 WebDAV（群晖 / Nextcloud / 自建）。
``alist``                     AList / OpenList（一个挂载聚合多种网盘）。
``s3``                        S3 兼容对象存储（AWS S3 / MinIO / Cloudflare R2 / Backblaze）。
``aliyun``                    阿里云盘（Open API，refresh_token 换 access_token）。
``quark``                     夸克网盘（Cookie 型 API）。
``onedrive``                  OneDrive / SharePoint（Microsoft Graph）。
============================  ====================================================

类型元数据是**唯一事实来源**：后台下拉、表单字段、必填校验、密钥脱敏、目录浏览入口
都读同一份 ``MOUNT_TYPES``。新增类型只需在 ``mount_cloud.py``（或任何模块）里
调用 ``register_mount_types`` + ``register_providers`` 注册，后端与其他前端不用改。

约定：

- **本机可读的挂载**（``local`` / ``strm``）与历史数据完全兼容：条目仍然存真实文件路径，
  探测、图片、外挂字幕都走本机，行为和「直接在媒体库里填一个目录」一致。
- **远程挂载**（``115`` / ``webdav`` / ``alist``）的条目路径形如 ``mount://<挂载 id>/<相对路径>``，
  播放时由提供者解析成真实 URL，再由 EA 按 Range **代理转发**：Cookie / 令牌不出服务器，
  客户端拿到的仍然是本服务器的地址。
- 解析结果同时用于**扫描探测**（ffprobe 直接读 URL）与**播放**，不会出现「能扫到但播不了」。
"""
from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator, Optional

from sqlalchemy.orm import Session

from backend.emby_server import models as em
# 远程 IO 计数与「扫描会话」标记（只依赖标准库，不会形成循环导入）
from backend.emby_server import scan_progress as progress
from backend.emby_server.playback_security import (
    validate_local_file_path, validate_remote_url, safe_local_path,
)
from backend.emby_server import subtitles, transfer115

logger = logging.getLogger(__name__)

MOUNT_LOCAL = "local"
MOUNT_STRM = "strm"
MOUNT_PAN115 = "115"
MOUNT_WEBDAV = "webdav"
MOUNT_ALIST = "alist"

# 挂载类型元数据：后台下拉与「这类挂载要填什么」的说明都来自这里
#
# 每个类型：
#   value / label / hint   —— 展示
#   kind                   —— local（本机可读）| remote（条目存 mount://，播放时代理）
#   group                  —— 后台图标分组：local / cloud / gateway
#   needs_path             —— 是否要填本机目录（走 Library.paths 那一套）
#   browse                 —— 是否支持后台目录浏览（远程类型为 True）
#   root_key               —— 可写回表单的「根目录标识」字段名（浏览时点目录即写入）
#   fields[]               —— 配置字段：key / label / placeholder / secret / required / type
#                             type=account115 表示渲染成 115 账号下拉；type=select 配合 options
MOUNT_TYPES: list[dict] = [
    {
        "value": MOUNT_LOCAL,
        "label": "本地 / 已挂载目录",
        "kind": "local",
        "group": "local",
        "hint": "本机可读的目录。rclone / CloudDrive2 / SMB / NFS 挂到本机后填它的真实路径。",
        "needs_path": True,
        "browse": True,
        "root_key": "",
        "fields": [],
    },
    {
        "value": MOUNT_STRM,
        "label": "STRM 直链目录",
        "kind": "local",
        "group": "local",
        "hint": "本机目录，里面是扩展名为 .strm 的文本文件，内容为播放直链（http/https）。",
        "needs_path": True,
        "browse": True,
        "root_key": "",
        "fields": [],
    },
    {
        "value": MOUNT_PAN115,
        "label": "115 网盘直挂",
        "kind": "remote",
        "group": "cloud",
        "hint": "Cookie 型 API 直读网盘，无需把 115 挂到本机。目录 ID 填 0 表示根目录，可先浏览再选。",
        "needs_path": False,
        "browse": True,
        "root_key": "cid",
        "fields": [
            {"key": "cid", "label": "目录 ID", "placeholder": "0 = 根目录"},
            {"key": "account_id", "label": "115 账号（留空用默认账号）", "type": "account115"},
        ],
    },
    {
        "value": MOUNT_WEBDAV,
        "label": "WebDAV",
        "kind": "remote",
        "group": "gateway",
        "hint": "群晖 / Nextcloud / 自建 WebDAV。填到目录为止，例如 https://dav.example.com/media。",
        "needs_path": False,
        "browse": True,
        "root_key": "path",
        "fields": [
            {"key": "url", "label": "地址", "placeholder": "https://dav.example.com/media",
             "required": True},
            {"key": "username", "label": "用户名"},
            {"key": "password", "label": "密码", "secret": True},
        ],
    },
    {
        "value": MOUNT_ALIST,
        "label": "AList / OpenList",
        "kind": "remote",
        "group": "gateway",
        "hint": "一个挂载聚合多种网盘。填 AList 站点地址与目录路径，可用令牌或账号密码。",
        "needs_path": False,
        "browse": True,
        "root_key": "path",
        "fields": [
            {"key": "url", "label": "站点地址", "placeholder": "https://alist.example.com",
             "required": True},
            {"key": "path", "label": "目录路径", "placeholder": "/115"},
            {"key": "token", "label": "令牌（可选）", "secret": True},
            {"key": "username", "label": "用户名（可选）"},
            {"key": "password", "label": "密码（可选）", "secret": True},
        ],
    },
]

MOUNT_TYPE_LABELS = {t["value"]: t["label"] for t in MOUNT_TYPES}
MOUNT_TYPE_MAP = {t["value"]: t for t in MOUNT_TYPES}

# 与类型元数据无关的通用密钥键（兼容老配置与云盘令牌）
LEGACY_SECRET_KEYS = {"password", "token", "cookie", "access_token"}


def register_mount_types(entries) -> None:
    """注册挂载类型（扩展模块调用）：追加元数据并刷新两张查找表"""
    global MOUNT_TYPE_LABELS, MOUNT_TYPE_MAP
    for entry in entries or ():
        if any(t["value"] == entry["value"] for t in MOUNT_TYPES):
            continue
        MOUNT_TYPES.append(dict(entry))
    MOUNT_TYPE_LABELS = {t["value"]: t["label"] for t in MOUNT_TYPES}
    MOUNT_TYPE_MAP = {t["value"]: t for t in MOUNT_TYPES}


def register_providers(mapping) -> None:
    """注册挂载提供者（扩展模块调用）"""
    _PROVIDERS.update(mapping or {})


def type_meta(mount_type: str) -> dict:
    return MOUNT_TYPE_MAP.get((mount_type or "").strip(), {})


def type_group(mount_type: str) -> str:
    return type_meta(mount_type).get("group") or "local"


def supports_browse(mount_type: str) -> bool:
    return bool(type_meta(mount_type).get("browse"))


def root_key(mount_type: str) -> str:
    """该类型的「根目录标识」字段名（空字符串表示没有这个概念）"""
    return type_meta(mount_type).get("root_key") or ""


def required_fields(mount_type: str) -> list[dict]:
    return [f for f in type_meta(mount_type).get("fields", []) if f.get("required")]


def secret_config_keys() -> set[str]:
    """不上报明文的配置键：历史密钥键 + 类型元数据里所有 secret 字段"""
    keys = set(LEGACY_SECRET_KEYS)
    for t in MOUNT_TYPES:
        for field in t.get("fields", ()):
            if field.get("secret"):
                keys.add(field["key"])
    return keys

# 远程挂载识别到的媒体扩展名（与 scanner.VIDEO_EXTS 对齐，外加 strm）
REMOTE_MEDIA_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m2ts", ".ts", ".m4v", ".strm",
}
STRM_EXT = ".strm"
REMOTE_SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}

MOUNT_PATH_PREFIX = "mount://"

# 播放代理 / 探测共用：远程请求超时（秒）
MOUNT_TIMEOUT = float(os.getenv("MOUNT_TIMEOUT", "20"))
# ffprobe / ffmpeg 读远程源时的 UA（多数网盘直链对 UA 有要求）
MOUNT_UA = os.getenv("MOUNT_UA", transfer115.PAN115_UA)
MOUNT_RANGE_CHUNK = 1024 * 256


class MountError(RuntimeError):
    """挂载不可用（配置错误、网络错误、路径不存在）"""


class MountAuthError(MountError):
    """挂载的凭据失效（Cookie / 令牌 / 密码）——调用方应提示重新配置"""


@dataclass
class MountFile:
    """挂载里枚举到的一个媒体文件"""

    rel: str           # 相对挂载根，以 "/" 开头
    name: str
    size: int = 0
    is_strm: bool = False


@dataclass
class MountEntry:
    """目录项（供后台浏览选择）

    ``entry_id`` 是提供者眼里的目录标识（115 的 cid）；本机 / WebDAV / AList 不需要它。
    """

    name: str
    rel: str
    is_dir: bool
    size: int = 0
    entry_id: str = ""


@dataclass
class PlayTarget:
    """媒体可播放目标

    - ``kind="local"``：本机文件，调用方直接按文件读；
    - ``kind="url"``：远程直链，调用方用 ``headers`` 代理转发（不要下发给客户端）。
    """

    kind: str
    value: str
    headers: dict = field(default_factory=dict)


# ==================== 路径约定 ====================

def mount_path(mount_id: int, rel: str) -> str:
    """构造远程挂载条目的入库路径"""
    clean = "/" + (rel or "").lstrip("/")
    return f"{MOUNT_PATH_PREFIX}{mount_id}{clean}"


def is_mount_path(path: Optional[str]) -> bool:
    return bool(path) and str(path).startswith(MOUNT_PATH_PREFIX)


def parse_mount_path(path: Optional[str]) -> Optional[tuple[int, str]]:
    """``mount://3/Movies/a.mkv`` → ``(3, "/Movies/a.mkv")``"""
    if not is_mount_path(path):
        return None
    rest = str(path)[len(MOUNT_PATH_PREFIX):]
    mount_id, _, rel = rest.partition("/")
    if not mount_id.isdigit():
        return None
    return int(mount_id), ("/" + rel if rel else "/")


def parse_config(mount) -> dict:
    """读取挂载的 JSON 配置（坏数据不抛异常，退化成空配置）"""
    raw = getattr(mount, "config", "") or "{}"
    if isinstance(raw, dict):
        return dict(raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — 配置坏了按空处理，由 test() 报可读错误
        return {}


def dump_config(config: dict) -> str:
    return json.dumps(config or {}, ensure_ascii=False, separators=(",", ":"))


def mount_label(mount) -> str:
    """``115 影库（115 网盘直挂）`` 这样的展示名"""
    kind = MOUNT_TYPE_LABELS.get(getattr(mount, "mount_type", ""), getattr(mount, "mount_type", ""))
    return f"{getattr(mount, 'name', '挂载')}（{kind}）"


def _is_strm_name(name: Optional[str]) -> bool:
    """文件名是否为 ``.strm``（容忍 None：条目可能没有本地路径）"""
    return bool(name) and str(name).lower().endswith(STRM_EXT)


def strm_url(content: str) -> str:
    """从 .strm 文件内容里取直链（容忍 BOM、空行、注释与前后空白）"""
    for line in (content or "").replace("\ufeff", "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", line):
            return line
    return ""


def strm_container(url: str) -> str:
    """直链里能看出真实容器就用它，看不出来交给客户端按 strm 处理"""
    try:
        suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1].lstrip(".").lower()
    except Exception:  # noqa: BLE001
        suffix = ""
    return suffix if suffix in {e.lstrip(".") for e in REMOTE_MEDIA_EXTS} else "strm"


def local_play_target(path: str) -> PlayTarget:
    """本机文件的播放目标；``.strm`` 读内容当直链（STRM 无需挂载也能播）"""
    try:
        path = validate_local_file_path(path)
    except ValueError as exc:
        raise MountError(str(exc)) from exc
    if _is_strm_name(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                url = strm_url(f.read())
        except OSError as exc:
            raise MountError(f"读取 STRM 文件失败: {path} ({exc})") from exc
        if url:
            return PlayTarget("url", validate_remote_url(url), {"User-Agent": MOUNT_UA})
        raise MountError(f"STRM 文件里没有可用的直链: {path}")
    return PlayTarget("local", path)


# ==================== 提供者（按挂载类型解析）====================

# ==================== 目录列举缓存（扫描与播放共用）====================
# 远程挂载的每一次列目录都是一次网络往返。扫描方向本来就有「本次扫描内单飞」的缓存，
# 但**播放**方向完全裸奔，而且 ``resolve_play_target`` 是**每次请求新建一个提供者**：
# 提供者实例上的 cid/pickcode 缓存对播放根本不存在，于是一次播放要重新逐级列目录
# （115 的 ``/电影/2024/x.mkv`` 就是 3 次网盘往返），多个人同时播就是几十次。
#
# 所以把缓存**下沉到提供者层**，按（挂载、类型指纹、目录）做 TTL 缓存，扫描与播放共用：
#   MOUNT_LIST_CACHE_SECONDS  目录列举缓存有效期（0 = 关闭，默认 5）
#   MOUNT_LIST_CACHE_MAX      最多缓存多少个目录（满了整体清空，内存有上限）
# 失败**不缓存**（网盘抖动不该被固化 TTL 秒），返回值是**拷贝**（调用方会排序/裁剪，
# 共享同一个 list 对象会让它们互相污染）。
MOUNT_LIST_CACHE_SECONDS = max(0.0, float(os.getenv("MOUNT_LIST_CACHE_SECONDS", "5") or 0))
MOUNT_LIST_CACHE_MAX = max(50, int(os.getenv("MOUNT_LIST_CACHE_MAX", "2000") or 2000))
# 远程并发上限（v2.27.0）：同时最多几个远程请求在飞。WebDAV / rclone / 网盘代理在高并发下
# 并不会更快——它们要么排队、要么限流，四个库同时扫一个端点时延迟被放大到十几倍。
# 本机目录（local / strm / rclone 最终落到本机路径的用法）不吃这个名额。
MOUNT_REMOTE_CONCURRENCY = max(1, min(16, int(os.getenv("MOUNT_REMOTE_CONCURRENCY", "2") or 2)))

_LIST_CACHE: dict = {}
_LIST_LOCKS: dict = {}
_LIST_CACHE_LOCK = threading.Lock()
_REMOTE_SEM: Optional[threading.BoundedSemaphore] = None
_REMOTE_SEM_SIZE = MOUNT_REMOTE_CONCURRENCY
_REMOTE_SEM_LOCK = threading.Lock()
_LIST_CACHE_STATS = {"hits": 0, "misses": 0, "expired": 0, "evictions": 0, "waits": 0}


def list_cache_stats() -> dict:
    """缓存命中情况（健康检查 / 测试用）"""
    with _LIST_CACHE_LOCK:
        return {**_LIST_CACHE_STATS, "entries": len(_LIST_CACHE),
                "ttl_seconds": MOUNT_LIST_CACHE_SECONDS,
                "remote_concurrency": MOUNT_REMOTE_CONCURRENCY,
                "scan_session": progress.in_scan_session()}


def invalidate_list_cache(mount_id: Optional[int] = None) -> None:
    """清掉目录列举缓存

    扫描开始前应当清一次（``scanner.clear_dir_cache`` 已经代劳）：扫描必须看到**当下**
    的目录，不能被播放刚填进去的缓存挡住——否则新加的文件要等下一轮扫描才入腹。
    """
    with _LIST_CACHE_LOCK:
        if mount_id is None:
            _LIST_CACHE.clear()
            return
        for key in [k for k in _LIST_CACHE if k[0] == mount_id]:
            _LIST_CACHE.pop(key, None)


def _config_fingerprint(provider) -> str:
    """挂载配置指纹：配置改了（换目录 / 换地址）就不该命中旧缓存

    只在进程内当缓存键用，不落日志、不外传（:36 里可能含密钥）。新建的临时挂载
    （测试连接，id 为空）也靠它区分，不至于和别的临时挂载串味。
    """
    config = getattr(provider, "config", None)
    if not isinstance(config, dict):
        return ""
    try:
        return json.dumps(config, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 — 指纹算不出来就退化成“不区分配置”
        return ""


def _list_cache_key(provider, kind: str, rel: str) -> tuple:
    mount = getattr(provider, "mount", None)
    return (
        getattr(mount, "id", None),
        (getattr(mount, "mount_type", "") or "").strip(),
        _config_fingerprint(provider),
        kind,
        rel or "/",
    )


def _cache_get(key: tuple) -> Optional[list]:
    """取缓存（命中返回**拷贝**；过期则删除并当未命中）

    扫描会话期间（``scan_progress.in_scan_session()``）**不看过期时间**：一轮扫描里同一个目录
    会被反复问到（目录指纹、外挂字幕、播放侧预取），TTL 只有 5 秒——扫描跑几分钟就是几十次
    多余的 PROPFIND，日志里那种「同一路径每 5 秒重复一次」正是这么来的。会话开始时
    ``scanner.clear_dir_cache`` 已经清过一次缓存，所以这里留下的都是**本轮**的数据。
    """
    now = time.monotonic()
    with _LIST_CACHE_LOCK:
        row = _LIST_CACHE.get(key)
        if row is not None and (row[0] > now or progress.in_scan_session()):
            _LIST_CACHE_STATS["hits"] += 1
            return list(row[1])
        if row is not None:
            _LIST_CACHE.pop(key, None)
            _LIST_CACHE_STATS["expired"] += 1
        _LIST_CACHE_STATS["misses"] += 1
        return None


def _cache_put(key: tuple, entries) -> None:
    with _LIST_CACHE_LOCK:
        if len(_LIST_CACHE) >= MOUNT_LIST_CACHE_MAX:
            _LIST_CACHE.clear()          # 满了整体清空：换来内存有上限，不会随库变大
            _LIST_CACHE_STATS["evictions"] += 1
        _LIST_CACHE[key] = (time.monotonic() + MOUNT_LIST_CACHE_SECONDS, tuple(entries))


def _single_flight_lock(key: tuple) -> threading.RLock:
    """拿这个目录的单飞锁（已在请求中就等它，别让并发请求各自去问一遍网盘）

    必须是**可重入锁**：子类的列目录实现可以包装在别的被缓存的方法上（同一提供者实例、
    同一个键），不可重入的话同一个线程会把自己锁死在第二层上。
    """
    with _LIST_CACHE_LOCK:
        lock = _LIST_LOCKS.get(key)
        if lock is not None:
            _LIST_CACHE_STATS["waits"] += 1
            return lock
        lock = threading.RLock()
        _LIST_LOCKS[key] = lock
        return lock


def _remote_semaphore() -> threading.BoundedSemaphore:
    """远程请求名额（上限是 MOUNT_REMOTE_CONCURRENCY；测试改了常量会重新建一个）"""
    global _REMOTE_SEM, _REMOTE_SEM_SIZE
    with _REMOTE_SEM_LOCK:
        if _REMOTE_SEM is None or _REMOTE_SEM_SIZE != MOUNT_REMOTE_CONCURRENCY:
            _REMOTE_SEM = threading.BoundedSemaphore(MOUNT_REMOTE_CONCURRENCY)
            _REMOTE_SEM_SIZE = MOUNT_REMOTE_CONCURRENCY
        return _REMOTE_SEM


@contextlib.contextmanager
def remote_io_slot():
    """占用一个「远程请求」名额（v2.27.0 的远程限流）

    只包住**真的会发出网络请求**的那一步（列目录、远程探测），缓存命中与单飞等待都不占名额——
    否则并发请求同一个目录时，等锁的线程会把名额白白占住，反而降低吞吐。
    """
    sem = _remote_semaphore()
    sem.acquire()
    progress.note_remote_inflight(1)
    try:
        yield
    finally:
        progress.note_remote_inflight(-1)
        sem.release()


def _is_remote_provider(provider) -> bool:
    """这个提供者背后是不是远程端点（按挂载类型的 kind 判定，本机目录不吃名额）"""
    mount = getattr(provider, "mount", None)
    meta = type_meta(getattr(mount, "mount_type", "") or "")
    return (meta.get("kind") or "") == "remote"


def _call_remote(provider, fn: Callable, rel: str) -> list:
    """真的列一次目录（远程会占用名额，并记一次「远程列举」用于扫描统计）"""
    if not _is_remote_provider(provider):
        return fn(provider, rel)
    with remote_io_slot():
        entries = fn(provider, rel)
    progress.note_remote_listing()
    return entries


def cached_listing(fn: Callable) -> Callable:
    """把提供者的「列目录」实现包一层共用 TTL 缓存

    用装饰器而不是在基类里转发，是为了不重命名/不改动各个子类的实现（九个子类、五种
    协议），同时保证 ``self.list_dir`` 的任何调用点（包括基类的 ``exists`` / ``size``
    和子类自己的 ``walk_media``）都走缓存。
    """

    @functools.wraps(fn)
    def wrapper(self, rel: str = "/", fresh: bool = False):
        if fresh or MOUNT_LIST_CACHE_SECONDS <= 0:
            return _call_remote(self, fn, rel)
        key = _list_cache_key(self, fn.__name__, rel)
        hit = _cache_get(key)
        if hit is not None:
            progress.note_remote_listing(reused=True)
            return hit
        lock = _single_flight_lock(key)
        with lock:
            try:
                hit = _cache_get(key)        # 等锁期间别人可能已经列完了
                if hit is not None:
                    progress.note_remote_listing(reused=True)
                    return hit
                entries = _call_remote(self, fn, rel)   # 失败就往上抛：异常不进缓存
                _cache_put(key, entries)
                return list(entries)
            finally:
                with _LIST_CACHE_LOCK:
                    _LIST_LOCKS.pop(key, None)

    return wrapper


def list_dir_uncached(provider, rel: str = "/") -> list:
    """绕过缓存列目录（后台目录选择器 / 管理页的「刷新」用；看当下而不是 5 秒前的）"""
    impl = getattr(type(provider).list_dir, "__wrapped__", None)
    if impl is None:            # 没被装饰（自定义提供者）：照常调用
        return _call_remote(provider, lambda prov, path: prov.list_dir(path), rel)
    return _call_remote(provider, impl, rel)


class MountProvider:
    """挂载提供者基类"""

    mount_type = ""
    kind = "local"

    def __init__(self, mount, db: Optional[Session] = None, library=None):
        self.mount = mount
        self.db = db
        self.library = library
        self.config = parse_config(mount)

    # ---- 能力 ----

    @property
    def local_root(self) -> Optional[str]:
        """本机可读时的根目录（远程挂载返回 None）"""
        return None

    def capabilities(self) -> dict:
        return {"browse": True, "local": self.local_root is not None}

    # ---- 接口 ----

    def test(self) -> dict:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def list_dir(self, rel: str = "/") -> list[MountEntry]:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def walk_media(self) -> Iterator[MountFile]:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def resolve(self, rel: str) -> PlayTarget:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def read_text(self, rel: str) -> str:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def resolve_final(self, rel: str) -> PlayTarget:
        """播放真正使用的解析入口：.strm 先取文件内容，再当直链播

        STRM 在**任何**挂载里都按内容解析（本机 / 115 / WebDAV / AList / 云盘），
        否则客户端会收到一个文本文件。为此不得不看文件内容时才走 ``read_text``，
        避免与 ``resolve``（只拿文件本身的地址）互相递归。
        """
        if _is_strm_name(rel):
            url = strm_url(self.read_text(rel))
            if not url:
                raise MountError(f"STRM 文件里没有可用的直链: {rel}")
            return PlayTarget("url", validate_remote_url(url), {"User-Agent": MOUNT_UA})
        return self.resolve(rel)

    # ---- 公共实现 ----

    def exists(self, rel: str) -> bool:
        root = self.local_root
        if root is not None:
            return os.path.exists(os.path.join(root, rel.lstrip("/")))
        try:
            parent, _, name = rel.rstrip("/").rpartition("/")
            return any(e.name == name for e in self.list_dir(parent or "/"))
        except MountError:
            return False

    def size(self, rel: str) -> int:
        root = self.local_root
        if root is not None:
            try:
                return os.path.getsize(os.path.join(root, rel.lstrip("/")))
            except OSError:
                return 0
        try:
            parent, _, name = rel.rstrip("/").rpartition("/")
            for e in self.list_dir(parent or "/"):
                if e.name == name:
                    return e.size
        except MountError:
            pass
        return 0


class LocalMount(MountProvider):
    """本机目录（``local`` / ``strm``）

    这两类挂载对扫描器完全没有新要求：目录就在本机，探测、图片、字幕都走本地文件。
    单独做成挂载的价值在于**可测试、可停用、可被多个库共用**，以及 STRM 目录的播放
    直链解析。``strm`` 与 ``local`` 的区别只有一个：目录里的 ``.strm`` 文件在扫描时
    也被当作媒体条目（``local`` 只扫视频文件）。
    """

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        self.kind = "local"
        self.mount_type = getattr(mount, "mount_type", MOUNT_LOCAL) or MOUNT_LOCAL
        self.path = (getattr(mount, "path", "") or "").strip()

    @property
    def local_root(self) -> Optional[str]:
        return self.path or None

    def _require_path(self) -> str:
        if not self.path:
            raise MountError("未配置目录路径")
        if not os.path.isdir(self.path):
            raise MountError(f"目录不可用: {self.path}")
        return self.path

    def test(self) -> dict:
        path = self._require_path()
        count = 0
        try:
            with os.scandir(path) as it:
                for _ in it:
                    count += 1
        except OSError as exc:
            raise MountError(f"目录不可读: {exc}") from exc
        return {"ok": True, "message": f"目录可读（顶层 {count} 项）", "path": path}

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        root = self._require_path()
        try:
            target = safe_local_path(root, (rel or "/").lstrip("/"))
        except ValueError as exc:
            raise MountError(str(exc)) from exc
        if not os.path.isdir(target):
            raise MountError(f"目录不存在: {rel}")
        entries: list[MountEntry] = []
        for name in sorted(os.listdir(target)):
            if name.startswith("."):
                continue
            full = os.path.join(target, name)
            is_dir = os.path.isdir(full)
            size = 0 if is_dir else (os.path.getsize(full) if os.path.exists(full) else 0)
            entries.append(MountEntry(
                name=name,
                rel=f"/{os.path.relpath(full, root).replace(os.sep, '/')}",
                is_dir=is_dir, size=size,
            ))
        return entries

    def walk_media(self) -> Iterator[MountFile]:
        root = self._require_path()
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in REMOTE_MEDIA_EXTS:
                    continue
                # 普通目录里混着 .strm 也认（很多人把 strm 和视频放一起），
                # 播放时统一由 local_play_target 读文件内容取直链。
                is_strm = _is_strm_name(fname)
                full = os.path.join(dirpath, fname)
                rel = "/" + os.path.relpath(full, root).replace(os.sep, "/")
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                yield MountFile(rel=rel, name=fname, size=size, is_strm=is_strm)

    def resolve(self, rel: str) -> PlayTarget:
        root = self._require_path()
        try:
            path = safe_local_path(root, (rel or "/").lstrip("/"))
        except ValueError as exc:
            raise MountError(str(exc)) from exc
        return local_play_target(path)

    def read_text(self, rel: str) -> str:
        root = self._require_path()
        try:
            path = safe_local_path(root, (rel or "/").lstrip("/"))
        except ValueError as exc:
            raise MountError(str(exc)) from exc
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except OSError as exc:
            raise MountError(f"读取文件失败: {rel} ({exc})") from exc


class Pan115Mount(MountProvider):
    """115 网盘直挂（Cookie 型 API，不依赖 115 OpenAPI）"""

    kind = "remote"
    mount_type = MOUNT_PAN115

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        self.root_cid = str(self.config.get("cid") or "0")
        # rel → cid / pickcode 缓存（只在本次提供者实例内，不跨请求）
        self._cid_cache: dict[str, str] = {"": self.root_cid, "/": self.root_cid}
        self._pick_cache: dict[str, str] = {}

    # ---- Cookie ----
    def _cookie(self) -> str:
        account_id = self.config.get("account_id")
        try:
            account_id = int(account_id) if account_id not in (None, "", "0") else None
        except (TypeError, ValueError):
            account_id = None
        if self.db is None:
            # 没有数据库会话（例如单独构造提供者做测试）：只认挂载内 Cookie 与服务器级兜底
            explicit = transfer115.normalize_cookie(self.config.get("cookie") or "")
            cookie = explicit or transfer115.normalize_cookie(
                os.getenv(transfer115.PAN115_COOKIE_ENV, "")
            )
            source = "挂载配置" if explicit else f"服务器级 {transfer115.PAN115_COOKIE_ENV}"
        else:
            cookie, source = transfer115.resolve_cookie(
                self.db, library=self.library, account_id=account_id,
            )
        if not cookie:
            raise MountAuthError(f"未解析到 115 Cookie（来源：{source}）")
        return cookie

    def _client(self) -> transfer115.Pan115Client:
        return transfer115.Pan115Client(self._cookie())

    def _wrap(self, exc: Exception) -> MountError:
        if isinstance(exc, transfer115.Pan115AuthError):
            return MountAuthError(str(exc))
        return MountError(str(exc))

    # ---- 目录 ----
    def test(self) -> dict:
        client = self._client()
        try:
            info = client.check()
            entries = client.list_dir(self.root_cid)
        except (transfer115.Pan115Error, transfer115.Pan115AuthError) as exc:
            raise self._wrap(exc) from exc
        root = "根目录" if self.root_cid == "0" else f"目录 {self.root_cid}"
        return {
            "ok": True,
            "message": f"Cookie 有效（uid={info.get('uid') or '未知'}），{root} 下有 {len(entries)} 项",
            "uid": info.get("uid"),
        }

    @cached_listing
    def _raw_list(self, cid: str) -> list[dict]:
        try:
            entries = self._client().list_dir(cid or "0")
        except (transfer115.Pan115Error, transfer115.Pan115AuthError) as exc:
            raise self._wrap(exc) from exc
        for entry in entries:
            entry["cid"] = str(entry.get("cid") or "")
        return entries

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        raw = self._raw_list(self._cid_of(rel))
        prefix = ("/" + (rel or "").lstrip("/")).rstrip("/")
        entries = []
        for item in raw:
            name = item.get("name") or ""
            child_rel = f"{prefix}/{name}"
            self._cid_cache.setdefault(child_rel, item.get("cid") or "")
            entries.append(MountEntry(
                name=name, rel=child_rel,
                is_dir=bool(item.get("is_dir")),
                size=int(item.get("size") or 0),
                entry_id=item.get("cid") or "",
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def walk_media(self) -> Iterator[MountFile]:
        stack: list[tuple[str, str]] = [("/", self.root_cid)]
        seen: set[str] = set()
        while stack:
            rel, cid = stack.pop()
            if cid in seen and cid != self.root_cid:
                continue  # 防目录环（115 正常不会出现，但扫描不能因此死循环）
            seen.add(cid)
            for item in self._raw_list(cid):
                name = item.get("name") or ""
                child_rel = f"{rel.rstrip('/')}/{name}"
                if item.get("is_dir"):
                    self._cid_cache[child_rel] = item.get("cid") or ""
                    stack.append((child_rel, item.get("cid") or ""))
                    continue
                if os.path.splitext(name)[1].lower() not in REMOTE_MEDIA_EXTS:
                    continue
                self._pick_cache[child_rel] = str(item.get("pickcode") or "")
                yield MountFile(rel=child_rel, name=name,
                                size=int(item.get("size") or 0), is_strm=_is_strm_name(name))

    def _cid_of(self, rel: str) -> str:
        """把相对路径解析成 cid（逐级列目录，结果缓存到本次提供者实例）"""
        rel = "/" + (rel or "").lstrip("/")
        rel = rel.rstrip("/") or "/"
        if rel in self._cid_cache and self._cid_cache[rel]:
            return self._cid_cache[rel]
        cid = self.root_cid
        for part in [p for p in rel.split("/") if p]:
            child = next(
                (e for e in self._raw_list(cid) if e.get("name") == part and e.get("is_dir")),
                None,
            )
            if child is None:
                raise MountError(f"115 上找不到目录: {rel}")
            cid = child.get("cid") or ""
        self._cid_cache[rel] = cid
        return cid

    def _locate(self, rel: str) -> dict:
        """定位文件项：返回 ``{pickcode, name, size}``"""
        rel = "/" + (rel or "").lstrip("/")
        if rel in self._pick_cache:
            return {"pickcode": self._pick_cache[rel], "name": os.path.basename(rel)}
        parent, _, name = rel.rpartition("/")
        for item in self._raw_list(self._cid_of(parent or "/")):
            if item.get("name") == name:
                return {
                    "pickcode": str(item.get("pickcode") or ""),
                    "name": name,
                    "size": int(item.get("size") or 0),
                }
        raise MountError(f"115 上找不到文件: {rel}")

    def resolve(self, rel: str) -> PlayTarget:
        entry = self._locate(rel)
        if not entry.get("pickcode"):
            raise MountError(f"115 未返回该文件的 pickcode: {rel}")
        try:
            url = self._client().download_url(entry["pickcode"])
        except (transfer115.Pan115Error, transfer115.Pan115AuthError) as exc:
            raise self._wrap(exc) from exc
        # 直链自带签名，但仍带上 UA/Cookie：EA 代理转发，客户端看不到这些头
        return PlayTarget("url", url, {
            "User-Agent": MOUNT_UA,
            "Referer": "https://115.com/",
            "Cookie": self._cookie(),
        })

    def read_text(self, rel: str) -> str:
        import httpx

        target = self.resolve(rel)
        with httpx.Client(timeout=MOUNT_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(target.value, headers=target.headers)
        if resp.status_code >= 400:
            raise MountError(f"读取 115 文件失败: HTTP {resp.status_code}")
        return resp.content.decode("utf-8", errors="ignore")


def _http_client():
    import httpx

    return httpx.Client(timeout=MOUNT_TIMEOUT, follow_redirects=True)


class WebDavMount(MountProvider):
    """通用 WebDAV"""

    kind = "remote"
    mount_type = MOUNT_WEBDAV

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        self.base = (self.config.get("url") or "").strip().rstrip("/")
        self.username = self.config.get("username") or ""
        self.password = self.config.get("password") or ""

    def _require_base(self) -> str:
        if not self.base.startswith(("http://", "https://")):
            raise MountError("WebDAV 地址必须以 http:// 或 https:// 开头")
        return self.base

    def _auth(self):
        import httpx

        return httpx.BasicAuth(self.username, self.password) if self.username else None

    def _url_of(self, rel: str) -> str:
        base = self._require_base()
        rel = "/" + (rel or "").lstrip("/")
        return base + urllib.parse.quote(rel) if rel != "/" else base + "/"

    def test(self) -> dict:
        base = self._require_base()
        try:
            with _http_client() as client:
                resp = client.request(
                    "PROPFIND", base + "/", headers={"Depth": "0"}, auth=self._auth(),
                )
        except Exception as exc:  # noqa: BLE001 — 网络错误统一成可读提示
            raise MountError(f"连接 WebDAV 失败: {exc}") from exc
        if resp.status_code in (401, 403):
            raise MountAuthError(f"WebDAV 拒绝访问（HTTP {resp.status_code}），请检查账号密码")
        if resp.status_code >= 400:
            raise MountError(f"WebDAV 返回 HTTP {resp.status_code}")
        return {"ok": True, "message": f"WebDAV 可访问（HTTP {resp.status_code}）", "url": base}

    def _propfind(self, rel: str) -> list[dict]:
        base = self._require_base()
        url = self._url_of(rel)
        try:
            with _http_client() as client:
                resp = client.request(
                    "PROPFIND", url,
                    headers={"Depth": "1", "Content-Type": "application/xml"},
                    auth=self._auth(),
                )
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"连接 WebDAV 失败: {exc}") from exc
        if resp.status_code in (401, 403):
            raise MountAuthError(f"WebDAV 拒绝访问（HTTP {resp.status_code}）")
        if resp.status_code >= 400:
            raise MountError(f"WebDAV 返回 HTTP {resp.status_code}")
        try:
            root = ET.fromstring(resp.content or b"<root/>")
        except ET.ParseError as exc:
            raise MountError(f"WebDAV 返回了无法解析的响应: {exc}") from exc
        ns = "{DAV:}"
        base_path = urllib.parse.urlparse(base).path.rstrip("/")
        out: list[dict] = []
        request_path = urllib.parse.urlparse(url).path.rstrip("/")
        for node in root.findall(f"{ns}response"):
            href = (node.findtext(f"{ns}href") or "").strip()
            if not href:
                continue
            path = urllib.parse.unquote(urllib.parse.urlparse(href).path).rstrip("/")
            name = path.rsplit("/", 1)[-1]
            if path == request_path or not name:
                continue  # PROPFIND 会带回自己
            is_dir = node.find(f"{ns}propstat/{ns}prop/{ns}resourcetype/{ns}collection") is not None
            length = node.findtext(f"{ns}propstat/{ns}prop/{ns}getcontentlength") or "0"
            rel_from_base = path[len(base_path):].strip("/") if base_path and path.startswith(base_path) else path.strip("/")
            out.append({
                "name": urllib.parse.unquote(name),
                "rel": "/" + rel_from_base,
                "is_dir": is_dir,
                "size": int(length or 0),
            })
        return out

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        entries = [MountEntry(name=e["name"], rel=e["rel"], is_dir=e["is_dir"], size=e["size"])
                   for e in self._propfind(rel)]
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def walk_media(self) -> Iterator[MountFile]:
        stack = ["/"]
        while stack:
            rel = stack.pop()
            for entry in self.list_dir(rel):
                if entry.is_dir:
                    stack.append(entry.rel)
                    continue
                if os.path.splitext(entry.name)[1].lower() in REMOTE_MEDIA_EXTS:
                    yield MountFile(rel=entry.rel, name=entry.name, size=entry.size,
                                    is_strm=_is_strm_name(entry.name))

    def resolve(self, rel: str) -> PlayTarget:
        headers = {"User-Agent": MOUNT_UA}
        if self.username:
            import base64

            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return PlayTarget("url", self._url_of(rel), headers)

    def read_text(self, rel: str) -> str:
        target = self.resolve(rel)
        with _http_client() as client:
            resp = client.get(target.value, headers=target.headers)
        if resp.status_code >= 400:
            raise MountError(f"读取 WebDAV 文件失败: HTTP {resp.status_code}")
        return resp.content.decode("utf-8", errors="ignore")


class AlistMount(MountProvider):
    """AList / OpenList（一个挂载聚合多种网盘）"""

    kind = "remote"
    mount_type = MOUNT_ALIST

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        self.base = (self.config.get("url") or "").strip().rstrip("/")
        self.root = "/" + (self.config.get("path") or "").strip().strip("/")
        self.token = (self.config.get("token") or "").strip()
        self.username = self.config.get("username") or ""
        self.password = self.config.get("password") or ""

    def _require_base(self) -> str:
        if not self.base.startswith(("http://", "https://")):
            raise MountError("AList 地址必须以 http:// 或 https:// 开头")
        return self.base

    def _headers(self) -> dict:
        headers = {"User-Agent": MOUNT_UA, "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def _login(self) -> str:
        if not self.username:
            raise MountAuthError("未配置令牌，也没有可登录的账号密码")
        body = self._post("/api/auth/login", {"username": self.username, "password": self.password})
        if body.get("code") != 200:
            raise MountAuthError(f"AList 登录失败: {body.get('message') or body.get('code')}")
        token = ((body.get("data") or {}) if isinstance(body.get("data"), dict) else {}).get("token")
        if not token:
            raise MountAuthError("AList 登录未返回令牌")
        self.token = str(token)
        return self.token

    def _post(self, path: str, payload: dict) -> dict:
        import httpx

        headers = self._headers()
        try:
            with httpx.Client(timeout=MOUNT_TIMEOUT, follow_redirects=True) as client:
                resp = client.post(f"{self._require_base()}{path}", json=payload, headers=headers)
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"连接 AList 失败: {exc}") from exc
        if resp.status_code in (401, 403):
            raise MountAuthError(f"AList 拒绝访问（HTTP {resp.status_code}）")
        if resp.status_code >= 400:
            raise MountError(f"AList 返回 HTTP {resp.status_code}")
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"AList 返回了无法解析的响应: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _api(self, path: str, payload: dict) -> dict:
        """带一次自动登录重试的调用（未配置令牌时先登录拿令牌）"""
        if not self.token and self.username:
            self._login()
        body = self._post(path, payload)
        if body.get("code") == 401 and self.username:
            self._login()
            body = self._post(path, payload)
        if body.get("code") != 200:
            message = str(body.get("message") or f"code={body.get('code')}")
            if "password" in message.lower() or "token" in message.lower():
                raise MountAuthError(f"AList: {message}")
            raise MountError(f"AList: {message}")
        return body

    def _abs(self, rel: str) -> str:
        rel = "/" + (rel or "").lstrip("/")
        path = (self.root.rstrip("/") + rel).replace("//", "/")
        return path.rstrip("/") or "/"

    def test(self) -> dict:
        body = self._api("/api/fs/list", {
            "path": self.root or "/", "password": "", "page": 1, "per_page": 0, "refresh": False,
        })
        data = body.get("data")
        total = len((data or {}).get("content") or []) if isinstance(data, dict) else 0
        return {"ok": True, "message": f"AList 可访问（{self.root or '/'} 下 {total} 项）"}

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        path = self._abs(rel)
        body = self._api("/api/fs/list", {
            "path": path, "password": "", "page": 1, "per_page": 0, "refresh": False,
        })
        data = body.get("data") or {}
        content = (data.get("content") or []) if isinstance(data, dict) else []
        prefix = ("/" + (rel or "").lstrip("/")).rstrip("/")
        entries = [
            MountEntry(
                name=str(item.get("name") or ""),
                rel=f"{prefix}/{item.get('name')}",
                is_dir=bool(item.get("is_dir")),
                size=int(item.get("size") or 0),
            )
            for item in content
        ]
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def walk_media(self) -> Iterator[MountFile]:
        stack = ["/"]
        while stack:
            rel = stack.pop()
            for entry in self.list_dir(rel):
                if entry.is_dir:
                    stack.append(entry.rel)
                    continue
                if os.path.splitext(entry.name)[1].lower() in REMOTE_MEDIA_EXTS:
                    yield MountFile(rel=entry.rel, name=entry.name, size=entry.size,
                                    is_strm=_is_strm_name(entry.name))

    def _raw_url(self, rel: str) -> tuple[str, dict]:
        path = self._abs(rel)
        body = self._api("/api/fs/get", {"path": path, "password": ""})
        data = body.get("data") or {}
        raw = str(data.get("raw_url") or data.get("url") or "")
        if not raw:
            raise MountError(f"AList 未返回直链: {path}")
        headers = {"User-Agent": MOUNT_UA}
        if self.token:
            headers["Authorization"] = self.token
        return raw, headers

    def resolve(self, rel: str) -> PlayTarget:
        raw, headers = self._raw_url(rel)
        return PlayTarget("url", raw, headers)

    def read_text(self, rel: str) -> str:
        target, headers = self._raw_url(rel)
        with _http_client() as client:
            resp = client.get(target, headers=headers)
        if resp.status_code >= 400:
            raise MountError(f"读取 AList 文件失败: HTTP {resp.status_code}")
        return resp.content.decode("utf-8", errors="ignore")


_PROVIDERS = {
    MOUNT_LOCAL: LocalMount,
    MOUNT_STRM: LocalMount,
    MOUNT_PAN115: Pan115Mount,
    MOUNT_WEBDAV: WebDavMount,
    MOUNT_ALIST: AlistMount,
}


def build_provider(mount, db: Optional[Session] = None, library=None) -> MountProvider:
    """按挂载类型构造提供者（未知类型 → 明确报错，而不是静默当成空库）"""
    mount_type = (getattr(mount, "mount_type", "") or "").strip()
    provider_cls = _PROVIDERS.get(mount_type)
    if provider_cls is None:
        raise MountError(f"不支持的挂载类型: {mount_type or '(空)'}")
    return provider_cls(mount, db, library)


def test_mount(mount, db: Optional[Session] = None, library=None) -> dict:
    """测试连接：返回 ``{ok, message, detail}``；失败不抛异常，交给后台展示"""
    try:
        result = build_provider(mount, db, library).test()
        return {"ok": True, "message": result.get("message", "连接正常"), "detail": result}
    except MountAuthError as exc:
        return {"ok": False, "message": str(exc), "auth_error": True}
    except MountError as exc:
        return {"ok": False, "message": str(exc), "auth_error": False}
    except Exception as exc:  # noqa: BLE001 — 兜底：任何异常都要变成可读提示
        logger.warning("挂载测试异常 %s: %s", getattr(mount, "id", None), exc)
        return {"ok": False, "message": f"连接失败: {exc}", "auth_error": False}


def record_test_result(db: Optional[Session], mount, result: dict) -> None:
    """把测试结果写回挂载（仅展示用）"""
    if db is None or mount is None:
        return
    mount.last_checked_at = datetime.now()
    mount.last_check_ok = bool(result.get("ok"))
    mount.last_check_message = (str(result.get("message") or ""))[:300]
    db.commit()


# ==================== 媒体库 → 来源 ====================

@dataclass
class LibrarySource:
    """扫描来源：本机目录 or 一个挂载"""

    label: str
    kind: str                      # local / mount
    path: str = ""                 # 本机目录（kind=local）
    mount: Any = None              # StorageMount（kind=mount）
    provider: Optional[MountProvider] = None


def parse_mount_ids(library) -> list[int]:
    raw = (getattr(library, "mount_ids", "") or "").replace("，", ",")
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and int(part) not in out:
            out.append(int(part))
    return out


def library_sources(library, db: Session) -> tuple[list[LibrarySource], list[dict]]:
    """把媒体库的 ``paths`` + 挂载解析成扫描来源

    返回 ``(可用来源, 不可用来源)``：不可用来源（路径不存在 / 账号失效 / 网络不通）
    会记进 ``failed``，扫描器据此**跳过清理阶段**，避免把「读不到」当成「文件已删除」。
    """
    sources: list[LibrarySource] = []
    failed: list[dict] = []

    for raw in (getattr(library, "paths", "") or "").split(","):
        path = raw.strip()
        if not path:
            continue
        if not os.path.isdir(path):
            failed.append({"label": path, "reason": "目录不存在或不可读"})
            continue
        sources.append(LibrarySource(label=path, kind="local", path=path))

    mount_ids = parse_mount_ids(library)
    if mount_ids:
        mounts = {
            m.id: m for m in db.query(em.StorageMount).filter(em.StorageMount.id.in_(mount_ids)).all()
        }
        for mount_id in mount_ids:
            mount = mounts.get(mount_id)
            if mount is None:
                failed.append({"label": f"挂载 #{mount_id}", "reason": "挂载不存在（可能已被删除）"})
                continue
            if not mount.is_enabled:
                failed.append({"label": mount_label(mount), "reason": "挂载已停用"})
                continue
            try:
                provider = build_provider(mount, db, library)
            except MountError as exc:
                failed.append({"label": mount_label(mount), "reason": str(exc)})
                continue
            sources.append(LibrarySource(
                label=mount_label(mount), kind="mount", mount=mount, provider=provider,
            ))
    return sources, failed


def load_mount(db: Session, mount_id: int):
    return db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()


def resolve_play_target(file_path: Optional[str], db: Session, library=None) -> PlayTarget:
    """把条目的 ``file_path`` 解析成播放/探测目标

    - 本机路径（含 ``.strm``）→ 直接读文件，strm 读内容是直链；
    - ``mount://<id>/<rel>`` → 由提供者解析成远程直链（带鉴权头，只在本机使用）。

    条目没有路径时（虚拟库聚合条目、容器类型、源文件被删后重扫前的残留行）
    明确报 MountError → 上层转成 404，而不是让 ``.lower()`` 抛 500。
    """
    if not file_path:
        raise MountError("该条目没有可播放的媒体路径（虚拟库聚合条目或源文件已丢失）")
    parsed = parse_mount_path(file_path)
    if parsed is None:
        return local_play_target(file_path)
    mount_id, rel = parsed
    mount = load_mount(db, mount_id)
    if mount is None:
        raise MountError(f"挂载 #{mount_id} 不存在（该条目来自已删除的挂载）")
    if not mount.is_enabled:
        raise MountError(f"挂载「{mount.name}」已停用")
    target = build_provider(mount, db, library).resolve_final(rel)
    if target.kind == "url":
        target.value = validate_remote_url(target.value)
    return target


def media_exists(file_path: str, db: Session, library=None) -> bool:
    """条目对应的媒体当前是否可读（本机路径 / 远程挂载都支持）"""
    if not file_path:
        return False
    parsed = parse_mount_path(file_path)
    if parsed is None:
        return os.path.exists(file_path)
    mount = load_mount(db, parsed[0])
    if mount is None or not mount.is_enabled:
        return False
    try:
        return build_provider(mount, db, library).exists(parsed[1])
    except MountError:
        return False


# ==================== 字幕模块的挂载解析钩子 ====================

def mount_source_resolver(path: str):
    """给 ``subtitles`` 模块用的解析器：``mount://<id>/<rel>`` → ``(直链, 请求头)``

    字幕模块只处理路径字符串、没有数据库会话；这里开一个短命 Session 自己解析
    （与扫描 / 播放同一口径），避免把 db 传进一个工具模块。
    """
    if parse_mount_path(path) is None:
        return None
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        target = resolve_play_target(path, db)
    except MountError as exc:
        logger.warning("字幕来源解析失败 %s: %s", path, exc)
        return None
    finally:
        db.close()
    return (target.value, target.headers) if target.kind == "url" else None


subtitles.register_mount_resolver(mount_source_resolver)


# ==================== 扩展挂载类型 ====================
# s3 / aliyun / quark / onedrive（mount_cloud.py）与 rclone（mount_rclone.py）定义在
# 单独模块里（避免本文件继续膨胀）。它们导入时调用 register_mount_types +
# register_providers，因此类型元数据与提供者在应用启动时就已经齐了，后面的代码
# 无需知道有哪些扩展类型。
from backend.emby_server import mount_cloud, mount_rclone  # noqa: E402,F401  (导入即注册)
