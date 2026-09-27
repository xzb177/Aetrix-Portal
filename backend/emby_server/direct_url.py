"""Google Drive 直链 302：EA 返回重定向，客户端直连 Google 下载，不经过服务器代理。

背景：rclone 的 ``--rc-serve`` HTTP 服务对含全角字符（！！、：等）文件名的
GET 请求返回 404（HEAD 200 / GET 404），这是 rclone 的 bug。直链绕开 rclone
HTTP 层，客户端直接从 ``www.googleapis.com`` 取文件。

流程：
1. 从 ``target.value``（形如 ``http://rclone:5572/[paul_emby:]/video/...``）
   解析出 rclone fs 与 remote 路径；
2. 调 rclone RC ``operations/stat`` 查 Google Drive file ID；
3. 从 rclone.conf 读 OAuth access token（过期自动用 refresh_token 刷新）；
4. 拼出 ``https://www.googleapis.com/drive/v3/files/{id}?alt=media&access_token=...``。

所有失败一律返回 None（调用方回退到原有代理逻辑），绝不抛异常。

配置（环境变量）：
- ``ENABLE_DIRECT_URL``：总开关，默认 ``true``，设为 ``false`` 关闭直链；
- ``RCLONE_RC_URL``：rclone RC 地址，默认 ``http://rclone:5572``；
- ``RCLONE_RC_USER`` / ``RCLONE_RC_PASS``：rclone RC 认证；
- ``RCLONE_CONF_PATH``：rclone.conf 路径，默认 ``/config/rclone/rclone.conf``。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

# rclone --rc-serve 的 URL 形如 http://host:port/[fs:]/remote/path（path 为 URL 编码）
_RCLONE_SERVE_RE = re.compile(r"^https?://[^/]+/\[([^/\]]+)\]/(.*)$", re.DOTALL)

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# token 缓存（进程级）：{"expiry": float, "token": str}
_token_cache: dict = {"expiry": 0.0, "token": ""}
_token_lock = threading.Lock()


def direct_url_enabled() -> bool:
    """总开关，默认开启；设为 false/0/no/off 关闭。"""
    return os.getenv("ENABLE_DIRECT_URL", "true").strip().lower() not in {
        "false", "0", "no", "off",
    }


def _rc_base() -> str:
    return os.getenv("RCLONE_RC_URL", "http://rclone:5572").rstrip("/")


def _rc_auth_header() -> Optional[str]:
    user = os.getenv("RCLONE_RC_USER", "")
    pwd = os.getenv("RCLONE_RC_PASS", "")
    if not user or not pwd:
        return None
    creds = f"{user}:{pwd}".encode("utf-8")
    return "Basic " + base64.b64encode(creds).decode("ascii")


def parse_rclone_url(url: str) -> Optional[tuple[str, str]]:
    """解析 rclone serve URL -> (fs, remote_path)。

    ``http://rclone:5572/[paul_emby:]/video/%E5%89%A7...`` ->
    ``("paul_emby:", "video/剧集...")``。remote_path 会做 URL decode。
    非 rclone serve 格式返回 None。
    """
    if not url:
        return None
    m = _RCLONE_SERVE_RE.match(url.strip())
    if not m:
        return None
    fs, encoded_path = m.group(1), m.group(2)
    # 去掉 query string（如果有）
    encoded_path = encoded_path.split("?", 1)[0]
    try:
        remote_path = unquote(encoded_path)
    except Exception:
        return None
    if not fs or not remote_path:
        return None
    return fs, remote_path


async def get_file_id(fs: str, remote_path: str) -> Optional[str]:
    """调 rclone RC ``operations/stat`` 查 Drive file ID。失败返回 None。"""
    auth = _rc_auth_header()
    if not auth:
        logger.warning("直链：未配置 RCLONE_RC_USER/RCLONE_RC_PASS，跳过")
        return None
    url = f"{_rc_base()}/operations/stat"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": auth, "Content-Type": "application/json"},
                json={"fs": fs, "remote": remote_path},
            )
    except Exception as exc:
        logger.warning("直链：operations/stat 请求失败 %s: %s", remote_path[:60], exc)
        return None
    if resp.status_code != 200:
        logger.warning("直链：operations/stat 返回 %s: %s", resp.status_code, remote_path[:60])
        return None
    try:
        file_id = resp.json().get("item", {}).get("ID")
    except Exception:
        file_id = None
    if not file_id:
        logger.warning("直链：operations/stat 未返回 file ID: %s", remote_path[:60])
        return None
    return str(file_id)


def _read_conf_text() -> Optional[str]:
    path = os.getenv("RCLONE_CONF_PATH", "/config/rclone/rclone.conf")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        logger.warning("直链：无法读取 rclone.conf %s: %s", path, exc)
        return None


def _parse_conf_section(conf: str, remote: str) -> Optional[dict]:
    """解析 rclone.conf 里指定 remote 的 section，返回键值字典。"""
    # section 名形如 [paul_emby]
    pattern = re.compile(
        r"^\[" + re.escape(remote) + r"\]\s*\n(.*?)(?=^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(conf)
    if not m:
        return None
    section = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        section[key.strip()] = value.strip()
    return section


def _token_from_conf(remote: str) -> Optional[dict]:
    """从 rclone.conf 读出 token/client_id/client_secret。失败返回 None。"""
    conf = _read_conf_text()
    if not conf:
        return None
    section = _parse_conf_section(conf, remote)
    if not section:
        logger.warning("直链：rclone.conf 里没有 [%s] section", remote)
        return None
    token_raw = section.get("token", "")
    if not token_raw:
        logger.warning("直链：[%s] 没有 token", remote)
        return None
    try:
        token_data = json.loads(token_raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("直链：[%s] token JSON 解析失败", remote)
        return None
    return {
        "access_token": token_data.get("access_token", ""),
        "refresh_token": token_data.get("refresh_token", ""),
        "expiry": token_data.get("expiry", ""),
        "client_id": section.get("client_id", ""),
        "client_secret": section.get("client_secret", ""),
    }


def _expiry_to_ts(expiry: str) -> float:
    try:
        # "2026-09-27T10:00:00.000000000+08:00" 之类；兼容 Z 后缀
        dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0.0


async def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Optional[tuple[str, float]]:
    """用 refresh_token 换新的 access token。返回 (token, expiry_ts)，失败 None。"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
    except Exception as exc:
        logger.warning("直链：刷新 token 请求失败: %s", exc)
        return None
    if resp.status_code != 200:
        logger.warning("直链：刷新 token 返回 %s", resp.status_code)
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    token = data.get("access_token", "")
    if not token:
        return None
    expires_in = data.get("expires_in", 3600)
    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        expires_in = 3600
    return token, time.time() + expires_in


async def get_access_token(fs: str) -> Optional[str]:
    """拿有效的 Google OAuth access token（缓存 + 过期自动刷新）。失败返回 None。

    ``fs`` 形如 ``paul_emby:``，对应 rclone.conf 里的 ``[paul_emby]`` section。
    """
    remote = fs.rstrip(":")
    cache_key = remote
    now = time.time()
    with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached and cached["token"] and now < cached["expiry"] - 300:
            return cached["token"]

    info = _token_from_conf(remote)
    if not info:
        return None

    access_token = info["access_token"]
    if access_token and now < _expiry_to_ts(info["expiry"]) - 300:
        with _token_lock:
            _token_cache[cache_key] = {"expiry": _expiry_to_ts(info["expiry"]), "token": access_token}
        return access_token

    # 过期或没有：用 refresh_token 刷新
    if not (info["refresh_token"] and info["client_id"] and info["client_secret"]):
        logger.warning("直链：[%s] 无法刷新 token（缺 refresh_token/client_id/client_secret）", remote)
        return None
    refreshed = await _refresh_access_token(info["client_id"], info["client_secret"], info["refresh_token"])
    if not refreshed:
        return None
    new_token, new_expiry = refreshed
    with _token_lock:
        _token_cache[cache_key] = {"expiry": new_expiry, "token": new_token}
    logger.info("直链：[%s] access token 已刷新", remote)
    return new_token


def build_direct_url(file_id: str, access_token: str) -> str:
    """拼 Google Drive 直接下载地址。"""
    return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&access_token={access_token}"


async def get_direct_url(fs: str, remote_path: str) -> Optional[str]:
    """路径 -> Google Drive 直链。任一步失败返回 None（调用方回退到代理）。"""
    file_id = await get_file_id(fs, remote_path)
    if not file_id:
        return None
    token = await get_access_token(fs)
    if not token:
        return None
    return build_direct_url(file_id, token)


async def try_google_direct_url(rclone_url: str) -> Optional[str]:
    """入口：rclone serve URL -> Google Drive 直链；不可用时返回 None。

    非 rclone URL、开关关闭、任一步失败都返回 None，调用方走原有代理逻辑。
    """
    if not direct_url_enabled():
        return None
    parsed = parse_rclone_url(rclone_url)
    if not parsed:
        return None
    fs, remote_path = parsed
    try:
        return await get_direct_url(fs, remote_path)
    except Exception as exc:  # noqa: BLE001 — 直链只是优化，绝不能影响正常播放
        logger.warning("直链：异常回退到代理: %s", exc)
        return None
