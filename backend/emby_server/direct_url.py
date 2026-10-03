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
   - 服务账号型 remote：走 ``ServiceAccountPool`` 轮换池 —— 递归扫描
     ``SA_POOL_DIR``（默认 ``/sa-accounts``）下所有 ``*.json``，round-robin
     取 token，token 按账号缓存 1 小时；被限流（429/403）的账号自动冷却
     5 分钟（``SA_POOL_COOLDOWN_SEC`` 可调），期间跳过；全部冷却则返回 None；
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
import asyncio
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


def _oauth_refresh_form(client_id: str, client_secret: str, refresh_token: str) -> dict:
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }


def _oauth_token_from_response(resp) -> Optional[tuple[str, float]]:
    """把 refresh_token 换票响应翻译成 ``(access_token, expiry_ts)``，失败 None。"""
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


async def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Optional[tuple[str, float]]:
    """用 refresh_token 换新的 access token。返回 (token, expiry_ts)，失败 None。"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data=_oauth_refresh_form(client_id, client_secret, refresh_token),
            )
    except Exception as exc:
        logger.warning("直链：刷新 token 请求失败: %s", exc)
        return None
    return _oauth_token_from_response(resp)


def refresh_access_token_sync(
    client_id: str, client_secret: str, refresh_token: str,
) -> Optional[tuple[str, float]]:
    """``_refresh_access_token`` 的同步版本（供同步的挂载提供者使用）

    原生 Google Drive 挂载在扫描工作线程里就要换票，不能走 async 那条路。
    """
    if not (client_id and client_secret and refresh_token):
        return None
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                _GOOGLE_TOKEN_URL,
                data=_oauth_refresh_form(client_id, client_secret, refresh_token),
            )
    except Exception as exc:
        logger.warning("直链：刷新 token 请求失败: %s", exc)
        return None
    return _oauth_token_from_response(resp)


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


class SARateLimited(Exception):
    """服务账号被限流（token 接口返回 429/403）。

    调用方（轮换池）应将该账号标记为冷却，一段时间后再用。
    """


def _sa_load_info(sa_file: str, remote: str) -> Optional[dict]:
    """读服务账号 JSON 并校验有效性。读不到/类型不对/缺字段一律 None。

    同步与异步两条取票路共用这一段：失败原因（哪个文件、什么问题）与日志口径必须一致，
    不能因为走 sync 还是 async 就给出不一样的解释。
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
    return sa_info


def _sa_token_from_response(resp, remote: str) -> Optional[tuple[str, float]]:
    """把 token 接口响应翻译成 ``(access_token, expiry_ts)``。

    429/403 抛 ``SARateLimited``（轮换池据此冷却该账号并换下一个），
    其余失败一律 None —— 换票只是优化，绝不能把播放带崩。
    """
    if resp.status_code in (429, 403):
        # 限流：抛给轮换池做冷却故障转移（不记为普通失败）
        logger.warning("直链：[%s] 服务账号被限流（%s），将冷却", remote, resp.status_code)
        raise SARateLimited(f"token endpoint returned {resp.status_code}")
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


def _sa_token_form(sa_info: dict, remote: str) -> Optional[tuple[str, dict]]:
    """JWT assertion + 换票表单；签不出 JWT 返回 None。"""
    assertion = _sa_jwt_assertion(sa_info, remote)
    if not assertion:
        return None
    token_uri = sa_info.get("token_uri") or "https://oauth2.googleapis.com/token"
    return token_uri, {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }


async def _sa_access_token(sa_file: str, remote: str) -> Optional[tuple[str, float]]:
    """用服务账号 JSON 生成 Google access token（异步）。返回 (token, expiry_ts)。

    ``sa_file`` 路径从 rclone.conf 的 ``service_account_file`` 动态读取，
    不 hardcode。429/403 抛 ``SARateLimited``（调用方做冷却故障转移）；
    其它失败返回 None（调用方回退到代理）。
    """
    sa_info = _sa_load_info(sa_file, remote)
    if not sa_info:
        return None
    form = _sa_token_form(sa_info, remote)
    if not form:
        return None
    token_uri, data = form
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_uri, data=data)
    except Exception as exc:
        logger.warning("直链：[%s] 服务账号 token 请求失败: %s", remote, exc)
        return None
    return _sa_token_from_response(resp, remote)


def _sa_access_token_sync(sa_file: str, remote: str) -> Optional[tuple[str, float]]:
    """``_sa_access_token`` 的同步版本，语义与日志逐条一致。

    为什么需要同步版：挂载提供者体系全是同步的（``_CloudMount`` 用 ``httpx.Client``，
    扫描遍历跑在线程池里，路由走 ``run_in_threadpool``）。原生 Google Drive 挂载
    要在**工作线程**里取票，而 ``asyncio.run`` 会为每次取票新建事件循环——
    在有 16 个遍历线程的扫描里那样做等于自己制造负载。
    """
    sa_info = _sa_load_info(sa_file, remote)
    if not sa_info:
        return None
    form = _sa_token_form(sa_info, remote)
    if not form:
        return None
    token_uri, data = form
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(token_uri, data=data)
    except Exception as exc:
        logger.warning("直链：[%s] 服务账号 token 请求失败: %s", remote, exc)
        return None
    return _sa_token_from_response(resp, remote)


def _sa_pool_dir() -> str:
    return os.getenv("SA_POOL_DIR", "/sa-accounts")


def _short_sa_name(path: str) -> str:
    return os.path.basename(path)


class ServiceAccountPool:
    """服务账号轮换池：把 Google Drive API 配额分散到多个服务账号上。

    - 初始化时递归扫描 ``SA_POOL_DIR``（默认 ``/sa-accounts``）下所有 ``*.json``，
      只收录 ``type=service_account`` 且含私钥/邮箱的有效账号；
    - ``get_token()`` 按 round-robin 返回健康账号的 access token，线程安全；
    - 每个账号的 token 缓存 1 小时（提前 5 分钟视为过期）；
    - 账号被限流（429/403）时自动冷却（默认 5 分钟），期间跳过；
      全部冷却时返回 None（调用方回退到代理）；
    - 启动时后台预热所有账号的 token（不阻塞启动）；
    - 后台线程每 10 分钟清理过期的冷却标记。

    所有失败都收敛为 None，绝不抛异常影响播放。
    """

    def __init__(
        self,
        sa_dir: Optional[str] = None,
        cooldown_sec: float = 300.0,
        prewarm: bool = True,
        healthcheck_interval: float = 600.0,
    ):
        self._sa_dir = sa_dir or _sa_pool_dir()
        try:
            self._cooldown_sec = max(0.0, float(os.getenv("SA_POOL_COOLDOWN_SEC", cooldown_sec)))
        except (TypeError, ValueError):
            self._cooldown_sec = 300.0
        self._lock = threading.Lock()
        self._accounts: list[dict] = []          # {"path", "email"}，按 path 排序
        self._tokens: dict[str, dict] = {}       # path -> {"token", "expiry"}
        self._cooldown_until: dict[str, float] = {}  # path -> 冷却结束时间戳
        self._cursor = 0
        self._scan_accounts()
        if prewarm and os.getenv("SA_POOL_PREWARM", "true").strip().lower() not in {
            "false", "0", "no", "off",
        }:
            self._start_prewarm()
        if healthcheck_interval > 0:
            self._start_healthcheck(healthcheck_interval)

    # ---- 初始化 ----

    def _scan_accounts(self) -> None:
        accounts = []
        if not os.path.isdir(self._sa_dir):
            logger.warning("直链：服务账号目录不存在 %s，轮换池为空", self._sa_dir)
            with self._lock:
                self._accounts = []
            return
        for root, _dirs, files in os.walk(self._sa_dir):
            for name in sorted(files):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("type") != "service_account":
                    continue
                if not data.get("private_key") or not data.get("client_email"):
                    continue
                accounts.append({"path": path, "email": data["client_email"]})
        accounts.sort(key=lambda a: a["path"])
        with self._lock:
            self._accounts = accounts
        logger.info("直链：服务账号池加载 %d 个账号（%s）", len(accounts), self._sa_dir)

    @property
    def account_count(self) -> int:
        with self._lock:
            return len(self._accounts)

    # ---- 后台任务 ----

    def _start_prewarm(self) -> None:
        t = threading.Thread(target=self._prewarm_all, name="sa-pool-prewarm", daemon=True)
        t.start()

    def _prewarm_all(self) -> None:
        import concurrent.futures

        with self._lock:
            accounts = list(self._accounts)
        if not accounts:
            return
        logger.info("直链：服务账号池预热开始（%d 个）", len(accounts))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(5, len(accounts)), thread_name_prefix="sa-prewarm"
        ) as ex:
            futs = [ex.submit(self._prewarm_one, acct) for acct in accounts]
            for fut in concurrent.futures.as_completed(futs):
                try:
                    fut.result()
                except Exception:
                    pass
        logger.info("直链：服务账号池预热完成")

    def _prewarm_one(self, acct: dict) -> None:
        try:
            result = asyncio.run(_sa_access_token(acct["path"], acct["email"]))
        except SARateLimited:
            self._mark_cooling(acct["path"])
            return
        except Exception:
            return
        if result:
            token, expiry = result
            with self._lock:
                self._tokens[acct["path"]] = {"token": token, "expiry": expiry}

    def _start_healthcheck(self, interval: float) -> None:
        t = threading.Thread(
            target=self._healthcheck_loop, args=(interval,),
            name="sa-pool-healthcheck", daemon=True,
        )
        t.start()

    def _healthcheck_loop(self, interval: float) -> None:
        while True:
            time.sleep(interval)
            try:
                with self._lock:
                    self._purge_cooldowns(time.time())
            except Exception:
                pass

    # ---- 冷却管理 ----

    def _purge_cooldowns(self, now: float) -> None:
        expired = [p for p, ts in self._cooldown_until.items() if ts <= now]
        for p in expired:
            del self._cooldown_until[p]
            logger.info("直链：服务账号 %s 冷却结束，恢复使用", _short_sa_name(p))

    def _mark_cooling(self, path: str) -> None:
        with self._lock:
            self._cooldown_until[path] = time.time() + self._cooldown_sec
        logger.warning(
            "直链：服务账号 %s 被限流，冷却 %d 秒", _short_sa_name(path), int(self._cooldown_sec)
        )

    def _healthy_accounts(self, now: float) -> list[dict]:
        self._purge_cooldowns(now)
        return [a for a in self._accounts if a["path"] not in self._cooldown_until]

    # ---- 对外接口 ----

    def _ordered_accounts(self, now: float) -> list[dict]:
        """健康账号的 round-robin 顺序（跳过冷却中的；空池返回空列表）。

        游标在这里推进，所以 async 与 sync 两条取票路共用同一份轮换语义——
        谁先调谁先拿，不会出现「同步路把 async 路的账号全占了」。
        """
        with self._lock:
            healthy = self._healthy_accounts(now)
            if not healthy:
                return []
            start = self._cursor % len(healthy)
            self._cursor += 1
            return healthy[start:] + healthy[:start]

    def _cached_token(self, path: str, now: float) -> Optional[tuple[str, float]]:
        """这个账号的 token 还在有效期内吗（提前 5 分钟视为过期）。"""
        with self._lock:
            cached = self._tokens.get(path)
            if cached and cached["token"] and now < cached["expiry"] - 300:
                return cached["token"], cached["expiry"]
        return None

    def _store_token(self, path: str, token: str, expiry: float) -> None:
        with self._lock:
            self._tokens[path] = {"token": token, "expiry": expiry}

    async def get_token(self) -> Optional[tuple[str, float]]:
        """按 round-robin 返回 (access_token, expiry_ts)。

        跳过冷却中的账号；全部冷却或池为空时返回 None。
        429/403 的账号自动进入冷却并尝试下一个；其它失败直接试下一个。
        """
        now = time.time()
        for acct in self._ordered_accounts(now):
            path = acct["path"]
            cached = self._cached_token(path, now)
            if cached:
                return cached
            try:
                result = await _sa_access_token(path, acct["email"])
            except SARateLimited:
                self._mark_cooling(path)
                continue
            except Exception:
                # _sa_access_token 内部已捕获绝大多数异常；这里兜底
                logger.warning("直链：服务账号 %s 取 token 异常，跳过", _short_sa_name(path))
                continue
            if not result:
                # 账号级失败（文件损坏/400 等），换下一个，不冷却
                continue
            token, expiry = result
            self._store_token(path, token, expiry)
            return token, expiry
        return None

    def get_token_sync(self) -> Optional[tuple[str, float]]:
        """``get_token`` 的同步版本（扫描遍历与后台 worker 都在工作线程里取票）

        轮换、冷却、缓存与异步版**共用同一份实现**（``_ordered_accounts`` /
        ``_cached_token`` / ``_store_token``），所以两条路的账号选择顺序、
        冷却时长、缓存时长逐条一致——不存在「同步路拿到的号更容易被限流」这种偏差。
        """
        now = time.time()
        for acct in self._ordered_accounts(now):
            path = acct["path"]
            cached = self._cached_token(path, now)
            if cached:
                return cached
            try:
                result = _sa_access_token_sync(path, acct["email"])
            except SARateLimited:
                self._mark_cooling(path)
                continue
            except Exception:
                logger.warning("直链：服务账号 %s 取 token 异常，跳过", _short_sa_name(path))
                continue
            if not result:
                continue
            token, expiry = result
            self._store_token(path, token, expiry)
            return token, expiry
        return None


# 进程级单例：EA 进程内只建一个池
_sa_pool: Optional[ServiceAccountPool] = None
_sa_pool_lock = threading.Lock()


def get_sa_pool() -> ServiceAccountPool:
    """返回进程级服务账号轮换池单例（懒加载，线程安全）。"""
    global _sa_pool
    with _sa_pool_lock:
        if _sa_pool is None:
            _sa_pool = ServiceAccountPool()
        return _sa_pool


async def get_access_token(fs: str) -> Optional[str]:
    """拿有效的 Google access token（缓存 + 过期自动刷新）。失败返回 None。

    ``fs`` 形如 ``paul_emby:``，对应 rclone.conf 里的 ``[paul_emby]`` section。
    优先级：OAuth 有效 token > OAuth 刷新 > 服务账号轮换池。两者都有时 OAuth 优先。
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

    # 服务账号型 remote：走轮换池（配额分散到多个 SA + 限流自动故障转移）。
    # rclone.conf 里 service_account_file 的存在只作为"这是 SA 型 remote"的判据，
    # 实际用哪个 SA 的 token 由池子 round-robin 决定。
    sa_file = info.get("service_account_file", "")
    if sa_file:
        try:
            pool_result = await get_sa_pool().get_token()
        except Exception as exc:
            logger.warning("直链：[%s] 服务账号池异常: %s", remote, exc)
            return None
        if pool_result:
            sa_token, sa_expiry = pool_result
            with _token_lock:
                _token_cache[cache_key] = {"expiry": sa_expiry, "token": sa_token}
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
