"""Google Drive 直链 302：EA 返回重定向，客户端直连 Google 下载，不经过服务器代理。

背景：rclone 的 ``--rc-serve`` HTTP 服务对含全角字符（！！、：等）文件名的
GET 请求返回 404（HEAD 200 / GET 404），这是 rclone 的 bug。直链绕开 rclone
HTTP 层，客户端直接从 ``www.googleapis.com`` 取文件。

流程：
1. 从 ``target.value``（形如 ``http://rclone:5572/[paul_emby:]/video/...``）
   解析出 rclone fs 与 remote 路径；
2. 调 rclone RC ``operations/stat`` 查 Google Drive file ID；
3. 拿 Google access token：
   - OAuth 型 remote：从 rclone.conf 读 token，过期自动用 refresh_token 刷新；
   - 服务账号型 remote：读 ``service_account_file`` 指向的 JSON，用私钥签发
     JWT（OAuth2 JWT Bearer 流程）换 access token，1 小时有效期，进程内缓存；
4. 拼出 ``https://www.googleapis.com/drive/v3/files/{id}?alt=media&access_token=...``。

所有失败一律返回 None（调用方回退到原有代理逻辑），绝不抛异常。

配置（环境变量）：
- ``ENABLE_DIRECT_URL``：总开关，默认 ``true``，设为 ``false`` 关闭直链；
- ``RCLONE_RC_URL``：rclone RC 地址，默认 ``http://rclone:5572``；
- ``RCLONE_RC_USER`` / ``RCLONE_RC_PASS``：rclone RC 认证；
- ``RCLONE_CONF_PATH``：rclone.conf 路径，默认 ``/config/rclone/rclone.conf``；
- ``DIRECT_URL_CACHE_TTL``：直链解析结果的缓存秒数，默认 ``5``，设 ``0`` 关闭。
  播放时拖一次进度条就是几十上百个 Range 请求，没有缓存等于每个请求都重新
  调一次 ``operations/stat``（一次网络往返）去问同一个文件的 file ID。
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

# 区分「没进过缓存」与「缓存过一次失败」——两者都拿 None 返回，但后者不该
# 每次都再去 stat 一遍、每次都打一条 warning。
_MISS = object()

# rclone --rc-serve 的 URL 形如 http://host:port/[fs:]/remote/path（path 为 URL 编码）
_RCLONE_SERVE_RE = re.compile(r"^https?://[^/]+/\[([^/\]]+)\]/(.*)$", re.DOTALL)

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# token 缓存（进程级）：{"expiry": float, "token": str}
_token_cache: dict = {"expiry": 0.0, "token": ""}
_token_lock = threading.Lock()

# 解析结果缓存（进程级）：{"<fs>\n<remote_path>": {"url": str | None, "expires": float}}
#
# 借鉴 go-emby 的 cdnLinks 思路：直链解析结果按极短 TTL 复用，避免拖进度条时
# 每个 Range 请求都重新 stat 一次。TTL 刻意压到 5 秒 —— 够覆盖一次连续 seek
# 的那一串请求，又短到文件被删/改名后几乎立刻失效。
#
# 同时缓存「失败」：服务账号型 remote 没有 OAuth token，每次都会走到
# "rclone.conf 里没有 [X] section" 这条 warning，播放器一路 seek 就刷一屏日志。
_url_cache: dict = {}
_url_lock = threading.Lock()

_URL_CACHE_MAX = 512


def _url_cache_ttl() -> float:
    try:
        return max(0.0, float(os.getenv("DIRECT_URL_CACHE_TTL", "5")))
    except ValueError:
        return 5.0


def _url_cache_get(key: str):
    with _url_lock:
        hit = _url_cache.get(key)
        if hit is not None and hit["expires"] > time.time():
            return hit["url"]
        if hit is not None:
            _url_cache.pop(key, None)
    return _MISS


def _url_cache_put(key: str, url: Optional[str]) -> None:
    ttl = _url_cache_ttl()
    if ttl <= 0:
        return
    now = time.time()
    with _url_lock:
        # 顺手清掉过期的，别让只播放不 seek 的场景把表撑大
        for k in [k for k, v in _url_cache.items() if v["expires"] <= now]:
            _url_cache.pop(k, None)
        if len(_url_cache) >= _URL_CACHE_MAX and key not in _url_cache:
            oldest = min(_url_cache.items(), key=lambda kv: kv[1]["expires"])[0]
            _url_cache.pop(oldest, None)
        _url_cache[key] = {"url": url, "expires": now + ttl}


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
    """从 rclone.conf 读出 OAuth token 或服务账号文件路径。失败返回 None。

    返回字典固定包含 ``access_token``/``refresh_token``/``expiry``/
    ``client_id``/``client_secret``（OAuth，没有就是空串）和
    ``service_account_file``（服务账号型 remote 的 JSON 路径，没有就是空串）。
    """
    conf = _read_conf_text()
    if not conf:
        return None
    section = _parse_conf_section(conf, remote)
    if not section:
        logger.warning("直链：rclone.conf 里没有 [%s] section", remote)
        return None
    info = {
        "access_token": "",
        "refresh_token": "",
        "expiry": "",
        "client_id": section.get("client_id", ""),
        "client_secret": section.get("client_secret", ""),
        "service_account_file": section.get("service_account_file", ""),
    }
    token_raw = section.get("token", "")
    if token_raw:
        try:
            token_data = json.loads(token_raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("直链：[%s] token JSON 解析失败", remote)
        else:
            info["access_token"] = token_data.get("access_token", "")
            info["refresh_token"] = token_data.get("refresh_token", "")
            info["expiry"] = token_data.get("expiry", "")
    if not info["access_token"] and not info["service_account_file"]:
        logger.warning("直链：[%s] 没有 token 也没有 service_account_file", remote)
        return None
    return info


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


def _sa_jwt_assertion(sa_info: dict, remote: str) -> Optional[str]:
    """用服务账号私钥签发 JWT assertion（Google OAuth2 JWT Bearer 流程）。

    私钥内容绝不打日志。签发失败返回 None。
    """
    now = int(time.time())
    claims = {
        "iss": sa_info["client_email"],
        "scope": "https://www.googleapis.com/auth/drive",
        "aud": sa_info.get("token_uri") or "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    headers = {}
    if sa_info.get("private_key_id"):
        headers["kid"] = sa_info["private_key_id"]
    try:
        # 函数级导入：jose 缺失时直链降级为 None，绝不能影响 EA 启动与正常播放
        from jose import jwt as _jose_jwt
        return _jose_jwt.encode(
            claims, sa_info["private_key"], algorithm="RS256",
            headers=headers or None,
        )
    except Exception as exc:
        logger.warning("直链：[%s] 服务账号 JWT 签名失败: %s", remote, type(exc).__name__)
        return None


async def _sa_access_token(sa_file: str, remote: str) -> Optional[tuple[str, float]]:
    """用服务账号 JSON 生成 Google access token。返回 (token, expiry_ts)，失败 None。

    ``sa_file`` 路径从 rclone.conf 的 ``service_account_file`` 动态读取，
    不 hardcode。任何异常都返回 None（调用方回退到代理）。
    """
    try:
        with open(sa_file, "r", encoding="utf-8") as f:
            sa_info = json.load(f)
    except OSError as exc:
        logger.warning("直链：[%s] 无法读取服务账号文件: %s", remote, exc)
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("直链：[%s] 服务账号 JSON 解析失败: %s", remote, type(exc).__name__)
        return None
    if not isinstance(sa_info, dict) or sa_info.get("type") != "service_account":
        logger.warning("直链：[%s] 服务账号文件类型不正确", remote)
        return None
    if not sa_info.get("private_key") or not sa_info.get("client_email"):
        logger.warning("直链：[%s] 服务账号文件缺少 private_key/client_email", remote)
        return None
    token_uri = sa_info.get("token_uri") or "https://oauth2.googleapis.com/token"
    assertion = _sa_jwt_assertion(sa_info, remote)
    if not assertion:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
    except Exception as exc:
        logger.warning("直链：[%s] 服务账号 token 请求失败: %s", remote, exc)
        return None
    if resp.status_code != 200:
        logger.warning("直链：[%s] 服务账号 token 返回 %s", remote, resp.status_code)
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    token = data.get("access_token", "")
    if not token:
        logger.warning("直链：[%s] 服务账号 token 响应无 access_token", remote)
        return None
    expires_in = data.get("expires_in", 3600)
    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        expires_in = 3600
    return token, time.time() + expires_in


async def get_access_token(fs: str) -> Optional[str]:
    """拿有效的 Google access token（缓存 + 过期自动刷新）。失败返回 None。

    ``fs`` 形如 ``paul_emby:``，对应 rclone.conf 里的 ``[paul_emby]`` section。
    优先级：OAuth 有效 token > OAuth 刷新 > 服务账号 JWT。两者都有时 OAuth 优先。
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

    # OAuth 刷新（token 过期或缺失时）
    if info["refresh_token"] and info["client_id"] and info["client_secret"]:
        refreshed = await _refresh_access_token(info["client_id"], info["client_secret"], info["refresh_token"])
        if refreshed:
            new_token, new_expiry = refreshed
            with _token_lock:
                _token_cache[cache_key] = {"expiry": new_expiry, "token": new_token}
            logger.info("直链：[%s] access token 已刷新", remote)
            return new_token
        # 刷新失败：如果配了服务账号，继续走 SA 路径

    # 服务账号：用 JWT 生成 access token（1 小时有效，同样进缓存）
    sa_file = info.get("service_account_file", "")
    if sa_file:
        sa_result = await _sa_access_token(sa_file, remote)
        if sa_result:
            sa_token, sa_expiry = sa_result
            with _token_lock:
                _token_cache[cache_key] = {"expiry": sa_expiry, "token": sa_token}
            logger.info("直链：[%s] 服务账号 token 已生成", remote)
            return sa_token
        return None

    logger.warning("直链：[%s] 无法刷新 token（缺 refresh_token/client_id/client_secret）", remote)
    return None


def build_direct_url(file_id: str, access_token: str) -> str:
    """拼 Google Drive 直接下载地址。"""
    return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&access_token={access_token}"


async def get_direct_url(fs: str, remote_path: str) -> Optional[str]:
    """路径 -> Google Drive 直链。任一步失败返回 None（调用方回退到代理）。

    结果按 ``DIRECT_URL_CACHE_TTL`` 短缓存，成功与失败都缓存。
    """
    key = f"{fs}\n{remote_path}"
    hit = _url_cache_get(key)
    if hit is not _MISS:
        return hit

    file_id = await get_file_id(fs, remote_path)
    if not file_id:
        _url_cache_put(key, None)
        return None
    token = await get_access_token(fs)
    if not token:
        _url_cache_put(key, None)
        return None
    url = build_direct_url(file_id, token)
    _url_cache_put(key, url)
    return url


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
