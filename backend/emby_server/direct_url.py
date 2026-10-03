"""Google Drive 令牌：服务账号轮换池 + OAuth refresh_token 换票。

## 这里曾经还有什么（已删除，2026-10）

本模块原本还负责「直链 302」：把播放请求重定向到 Google Drive 的
``alt=media`` 地址，让客户端自己下载、流量不过 VPS。调研 Alist / RClone /
Cloudreve 后确认这条路不可行，三家均为服务端代理：

1. ``alt=media`` 需要 ``Authorization`` 头，而 302 是重定向——客户端不会把
   本服务请求上的请求头带到新地址（Emby 客户端尤其不会）；
2. 唯一能进 URL 的 ``access_token`` 会进客户端日志 / Referer / 中间代理，
   且 Google 对「URL 带 token」的请求有独立且更严的限流。

因此直链那一整套（``build_direct_url`` / ``get_direct_url`` /
``try_google_direct_url`` / ``parse_rclone_url`` / ``get_file_id`` /
``direct_url_enabled`` / 解析结果缓存）连同 ``ENABLE_DIRECT_URL``、
``RCLONE_RC_*``、``DIRECT_URL_CACHE_TTL`` 三个环境变量一起删干净了 ——
它们只为拼那条 302 地址而存在。rclone remote 的 OAuth 取票（``get_access_token``
与 rclone.conf 解析）随之删除：原生 Google Drive 挂载走本模块的
``ServiceAccountPool`` / ``refresh_access_token_sync``，不读 rclone.conf。

现在本模块只剩**令牌**层，由 ``mount_google``（Google Drive 原生挂载）使用：

- OAuth 型挂载：``refresh_access_token_sync``（client_id + refresh_token）；
- 服务账号型挂载：``ServiceAccountPool`` 轮换池 —— 递归扫描
  ``SA_POOL_DIR``（默认 ``/sa-accounts``）下所有 ``*.json``，round-robin
  取 token，token 按账号缓存 1 小时；被限流（429/403）的账号自动冷却
  5 分钟（``SA_POOL_COOLDOWN_SEC`` 可调），期间跳过；全部冷却则返回 None。

所有失败一律返回 None（调用方回退到无凭据形态），绝不抛异常。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import asyncio
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


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
        logger.warning("Drive 令牌：刷新 token 返回 %s", resp.status_code)
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
        logger.warning("Drive 令牌：刷新 token 请求失败: %s", exc)
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
        logger.warning("Drive 令牌：刷新 token 请求失败: %s", exc)
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
        # 函数级导入：jose 缺失时取票降级为 None，绝不能影响 EA 启动与正常播放
        from jose import jwt as _jose_jwt
        return _jose_jwt.encode(
            claims, sa_info["private_key"], algorithm="RS256",
            headers=headers or None,
        )
    except Exception as exc:
        logger.warning("Drive 令牌：[%s] 服务账号 JWT 签名失败: %s", remote, type(exc).__name__)
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
        logger.warning("Drive 令牌：[%s] 无法读取服务账号文件: %s", remote, exc)
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Drive 令牌：[%s] 服务账号 JSON 解析失败: %s", remote, type(exc).__name__)
        return None
    if not isinstance(sa_info, dict) or sa_info.get("type") != "service_account":
        logger.warning("Drive 令牌：[%s] 服务账号文件类型不正确", remote)
        return None
    if not sa_info.get("private_key") or not sa_info.get("client_email"):
        logger.warning("Drive 令牌：[%s] 服务账号文件缺少 private_key/client_email", remote)
        return None
    return sa_info


def _sa_token_from_response(resp, remote: str) -> Optional[tuple[str, float]]:
    """把 token 接口响应翻译成 ``(access_token, expiry_ts)``。

    429/403 抛 ``SARateLimited``（轮换池据此冷却该账号并换下一个），
    其余失败一律 None —— 换票只是优化，绝不能把播放带崩。
    """
    if resp.status_code in (429, 403):
        # 限流：抛给轮换池做冷却故障转移（不记为普通失败）
        logger.warning("Drive 令牌：[%s] 服务账号被限流（%s），将冷却", remote, resp.status_code)
        raise SARateLimited(f"token endpoint returned {resp.status_code}")
    if resp.status_code != 200:
        logger.warning("Drive 令牌：[%s] 服务账号 token 返回 %s", remote, resp.status_code)
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    token = data.get("access_token", "")
    if not token:
        logger.warning("Drive 令牌：[%s] 服务账号 token 响应无 access_token", remote)
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

    ``sa_file`` 由调用方给（原生挂载传配置里的 ``sa_file``，轮换池传
    ``SA_POOL_DIR`` 扫描出来的账号文件），不在这里拼路径。429/403 抛
    ``SARateLimited``（调用方做冷却故障转移）；其它失败返回 None。
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
        logger.warning("Drive 令牌：[%s] 服务账号 token 请求失败: %s", remote, exc)
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
        logger.warning("Drive 令牌：[%s] 服务账号 token 请求失败: %s", remote, exc)
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
            logger.warning("Drive 令牌：服务账号目录不存在 %s，轮换池为空", self._sa_dir)
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
        logger.info("Drive 令牌：服务账号池加载 %d 个账号（%s）", len(accounts), self._sa_dir)

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
        logger.info("Drive 令牌：服务账号池预热开始（%d 个）", len(accounts))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(5, len(accounts)), thread_name_prefix="sa-prewarm"
        ) as ex:
            futs = [ex.submit(self._prewarm_one, acct) for acct in accounts]
            for fut in concurrent.futures.as_completed(futs):
                try:
                    fut.result()
                except Exception:
                    pass
        logger.info("Drive 令牌：服务账号池预热完成")

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
            logger.info("Drive 令牌：服务账号 %s 冷却结束，恢复使用", _short_sa_name(p))

    def _mark_cooling(self, path: str) -> None:
        with self._lock:
            self._cooldown_until[path] = time.time() + self._cooldown_sec
        logger.warning(
            "Drive 令牌：服务账号 %s 被限流，冷却 %d 秒", _short_sa_name(path), int(self._cooldown_sec)
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
                logger.warning("Drive 令牌：服务账号 %s 取 token 异常，跳过", _short_sa_name(path))
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
                logger.warning("Drive 令牌：服务账号 %s 取 token 异常，跳过", _short_sa_name(path))
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
