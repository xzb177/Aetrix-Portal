"""Google Drive 服务端凭据中转模块。

定位：
- .strm 文件中的 Google Drive 直链保持私有（不公开分享），服务端 relay 拉流时
  通过本模块自动附加服务账号（SA）的 Bearer token，客户端永远看不到直链。
- SA 的发现与 access_token 换取（JWT 断言换 token）统一复用 ``drive_changes``
  模块的既有实现（``_discover_sa_files`` / ``_sa_access_token``），
  横切能力只维护一套，本模块不重复实现 JWT 逻辑。
- access_token 在本模块再做一层进程内短缓存（55 分钟，剩余有效期大于 120 秒
  直接命中），由 threading.Lock 保护，减少重复换 token 的开销。
- 任何失败（无可用 SA、换 token 异常等）均返回 None，由调用方降级处理，
  本模块永不抛出异常。
"""

from __future__ import annotations

import logging
import threading
import time
from types import ModuleType
from typing import Any
from urllib.parse import parse_qsl, urlparse

__all__ = [
    "DRIVE_HOSTS",
    "is_drive_url",
    "get_drive_bearer_token",
    "drive_auth_headers",
    "drive_api_media_url",
]

logger = logging.getLogger(__name__)

#: 需要进行鉴权的 Google Drive 相关域名（host 小写比较）
DRIVE_HOSTS: frozenset[str] = frozenset(
    {
        "drive.google.com",
        "drive.usercontent.google.com",
        "docs.google.com",
        "www.googleapis.com",
    }
)

# Google access_token 通常 1 小时有效，这里按 55 分钟缓存，留出余量
_TOKEN_TTL_SECONDS: float = 55 * 60
# 缓存 token 剩余有效期大于该值（秒）时直接命中
_TOKEN_MIN_REMAIN_SECONDS: float = 120

_cache_lock = threading.Lock()
_cached_token: str | None = None
_cached_expire_at: float = 0.0  # time.monotonic() 基准
# P1 修复（审查）：播放 token 按 SA 轮换，不再永远用第一个 SA。
# 进程启动时随机起点，避免多 worker 进程同时从第 0 个 SA 开始。
import random as _random
_sa_rr_index = _random.randint(0, 1000000)
_sa_rr_lock = threading.Lock()


def _load_drive_changes() -> ModuleType:
    """惰性导入并返回 drive_changes 模块。

    drive_changes 依赖较重且可能拉起线程，故不在模块顶层导入，等到真正需要
    凭据时才加载，同时规避潜在的循环导入。
    """
    try:
        from . import drive_changes
    except ImportError:  # 兼容扁平导入（直接以目录方式运行）的场景
        import drive_changes
    return drive_changes


def is_drive_url(url: str) -> bool:
    """判断 url 是否指向 Google Drive 相关域名（host 小写比较）。"""
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    return host in DRIVE_HOSTS


def _is_sa_dict(obj: Any) -> bool:
    """判断对象是否为可用的 SA 凭据字典（含 client_email 与 private_key）。"""
    return (
        isinstance(obj, dict)
        and bool(obj.get("client_email"))
        and bool(obj.get("private_key"))
    )


def _read_sa_file(path: str) -> dict[str, Any] | None:
    """读取 SA json 文件。

    ``drive_changes`` 只导出了 ``_discover_sa_files``（文件列表）与
    ``_sa_access_token``（JWT 换 token），没有导出"读单个 SA 文件"的辅助函数，
    这里用标准库读一次（JSON 解析失败返回 None）。
    """
    import json

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _pick_sa() -> dict[str, Any] | None:
    """从 drive_changes 发现的 SA 文件中轮询取一个可用的 SA 字典。

    P1 修复（审查）：此前永远取第一个可用 SA，全站播放回源流量压在单个 SA
    配额上（与"100 子账号轮询"的设计相悖）。现按 round-robin 轮换，
    与 drive_changes._next_sa 同口径。
    """
    global _sa_rr_index
    try:
        drive_changes = _load_drive_changes()
        sa_files = drive_changes._discover_sa_files() or []
    except Exception:
        return None
    if not sa_files:
        return None
    # 轮询起点：每次调用换一个 SA
    with _sa_rr_lock:
        start = _sa_rr_index % len(sa_files)
        _sa_rr_index += 1
    for offset in range(len(sa_files)):
        entry = sa_files[(start + offset) % len(sa_files)]
        try:
            sa = entry if _is_sa_dict(entry) else _read_sa_file(entry)
        except Exception:
            continue
        if _is_sa_dict(sa):
            return sa
    return None


def get_drive_bearer_token() -> str | None:
    """获取 Drive 访问用的 Bearer access_token；失败返回 None，永不抛异常。

    进程内缓存 (token, expire_at)：剩余有效期大于 120 秒直接返回；缓存失效
    时经 SA 换取新 token，并按 55 分钟重新记缓存（JWT 断言逻辑由
    drive_changes._sa_access_token 内部实现，本模块不重复实现）。
    """
    global _cached_token, _cached_expire_at
    now = time.monotonic()
    with _cache_lock:
        if _cached_token and now + _TOKEN_MIN_REMAIN_SECONDS < _cached_expire_at:
            return _cached_token
    try:
        drive_changes = _load_drive_changes()
        sa = _pick_sa()
        if not sa:
            logger.debug("drive_auth: 未发现可用的 Google Drive 服务账号凭据")
            return None
        token = drive_changes._sa_access_token(sa)
        if not token:
            return None
    except Exception as exc:
        logger.warning("drive_auth: 获取 Drive Bearer token 失败，调用方降级处理: %s", exc)
        return None
    with _cache_lock:
        _cached_token = token
        _cached_expire_at = now + _TOKEN_TTL_SECONDS
    return token


def drive_auth_headers(url: str) -> dict[str, str]:
    """为 Drive 直链构造请求头；非 Drive 域名或无 token 时返回空字典。"""
    if not is_drive_url(url):
        return {}
    token = get_drive_bearer_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def drive_api_media_url(url: str) -> str:
    """把 Drive uc 直链转换为 Drive API alt=media 下载地址。

    ``https://drive.google.com/uc?export=download&id=<FILE_ID>`` 即使带上 SA 的
    Bearer token 也只会返回登录页（私有文件无法这样下载）；Drive API 的
    ``https://www.googleapis.com/drive/v3/files/<FILE_ID>?alt=media`` 才是
    Bearer token 能用的下载端点，支持 Range 分片。

    非 uc 格式的 URL 原样返回，永不抛异常。
    """
    try:
        if not url:
            return url
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() != "drive.google.com":
            return url
        if parsed.path.rstrip("/") != "/uc":
            return url
        params = dict(parse_qsl(parsed.query))
        file_id = params.get("id")
        if not file_id:
            return url
        return "https://www.googleapis.com/drive/v3/files/" + file_id + "?alt=media"
    except Exception:
        return url
