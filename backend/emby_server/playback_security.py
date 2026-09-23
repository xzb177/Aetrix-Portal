"""Playback URL safety checks.

Remote playback targets are validated before httpx or ffmpeg uses them.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit


def _allowed_hosts() -> set[str]:
    raw = os.getenv("EMBY_MEDIA_URL_ALLOWLIST", "")
    return {item.strip().lower().rstrip(".") for item in raw.split(",") if item.strip()}


def _private(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host.rstrip(".").lower() in {"localhost", "localhost.localdomain"}
    return any((addr.is_private, addr.is_loopback, addr.is_link_local,
                addr.is_multicast, addr.is_reserved, addr.is_unspecified))


def _resolves_private(host: str) -> bool:
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return True
    return any(_private(record[4][0]) for record in records)


def validate_remote_url(raw_url: str) -> str:
    from .mounts import MountError

    value = (raw_url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise MountError("播放地址必须是 http 或 https URL")
    if parsed.username or parsed.password:
        raise MountError("播放地址禁止携带内嵌凭据")
    host = parsed.hostname.lower().rstrip(".")
    if host not in _allowed_hosts() and (_private(host) or _resolves_private(host)):
        raise MountError("播放地址指向受保护的内部地址")
    return value


def safe_local_path(root: str, relative: str) -> str:
    """Resolve a local media path without traversal or symlink escape."""
    import os
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, relative))
    try:
        inside = os.path.commonpath([root_real, candidate]) == root_real
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("媒体路径超出挂载根目录")
    current = root_real
    for part in relative.replace(os.sep, "/").split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("媒体路径包含非法目录遍历")
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise ValueError("媒体路径禁止经过符号链接")
    return candidate


def validate_local_file_path(path: str) -> str:
    """Validate an existing absolute local path and reject symlink traversal."""
    import os
    value = os.path.abspath(path)
    current = os.path.sep
    for part in value.split(os.path.sep):
        if not part:
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise ValueError("媒体路径禁止经过符号链接")
    return value


def safe_child_name(root: str, name: str) -> str:
    """Resolve a single generated-media filename below *root*."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("媒体文件名非法")
    return safe_local_path(root, name)
