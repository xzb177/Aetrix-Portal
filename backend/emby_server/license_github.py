"""GitHub Package 授权管理（v2.50.0）

用户购买 Aetrix 授权后，系统自动调 GitHub API 给他的 GitHub 账号加上
对应 container package 的读权限；到期/撤销时自动回收。

GitHub API 文档：
- 加协作者：PUT /user/packages/container/{package_name}/collaborators/{username}
- 删协作者：DELETE /user/packages/container/{package_name}/collaborators/{username}

token 从 system_configs 的 ``github_package_token`` 读，需要
``read:packages`` + ``write:packages`` 权限（classic PAT）。

第二遍打磨（审查意见落实）：
- 限流（403 rate limit / 429）指数退避重试，重试耗尽才抛异常；
- token 缺失/失效的错误信息指明去管理后台哪里更新；
- 时间统一用 naive UTC（库里 DateTime 列都是 naive，不存本地时区）。
"""
import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# GitHub API 基础地址
GITHUB_API = "https://api.github.com"
# token 在 system_configs 里的 key
TOKEN_CONFIG_KEY = "github_package_token"
# 默认的包名前缀（ghcr.io/<owner>/ 后面的部分由调用方传）
DEFAULT_PACKAGE_OWNER = "xzb177"

# 限流重试：最多重试次数与退避基数（秒）
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_BACKOFF = 5


def utcnow() -> datetime:
    """naive UTC now。

    库里所有 DateTime 列都是 naive（无 tzinfo），历史代码混用了本地时间。
    授权模块统一用 UTC，避免「naive 本地时间 vs naive UTC」比较时差 8 小时
    导致提前/延后过期。调用方一律用这个函数，不要直接 datetime.now()。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GitHubPackageError(Exception):
    """GitHub Package API 调用失败"""
    pass


class GitHubRateLimitError(GitHubPackageError):
    """GitHub API 限流：调用方应停止本轮批量操作，下一轮再试"""
    pass


def _get_token(db) -> str:
    """从 system_configs 读 GitHub token"""
    from backend.integrations import store
    token = store.get_value(db, TOKEN_CONFIG_KEY, "")
    if not token:
        raise GitHubPackageError(
            "未配置 GitHub token：请前往管理后台 → 系统设置，填写 "
            f"`{TOKEN_CONFIG_KEY}`（需要 read:packages + write:packages "
            "权限的 classic PAT），保存后重试"
        )
    return token


def _is_rate_limited(status_code: int, headers, body: str) -> bool:
    """判断这次失败是不是限流（区别于权限不足）

    GitHub 对 packages 接口的限流表现为：
    - 403 + X-RateLimit-Remaining: 0，或 body 含 "rate limit"；
    - 429 Too Many Requests（带 Retry-After 头）。
    权限不足的 403（token 没勾 write:packages）body 里是
    "Resource not accessible by integration"，不能误判成限流去重试。
    """
    if status_code == 429:
        return True
    if status_code != 403:
        return False
    try:
        remaining = headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) == 0:
            return True
    except (TypeError, ValueError):
        pass
    lowered = (body or "").lower()
    return "rate limit" in lowered or "abuse" in lowered


def _retry_after_seconds(headers, attempt: int) -> float:
    """算出下一次重试前要等多久（秒）"""
    # 服务端给了明确时间就听它的
    for key in ("Retry-After", "X-RateLimit-Reset"):
        try:
            val = headers.get(key)
            if val is not None:
                wait = float(val)
                # X-RateLimit-Reset 是 Unix 时间戳，Retry-After 是秒数
                if key == "X-RateLimit-Reset":
                    wait = wait - time.time()
                if wait > 0:
                    return min(wait, 300)
        except (TypeError, ValueError):
            continue
    # 没给就指数退避：5s, 10s, 20s，上限 60s
    return min(_RATE_LIMIT_BASE_BACKOFF * (2 ** attempt), 60)


def _api_request(method: str, url: str, token: str) -> dict:
    """发 GitHub API 请求，失败抛 GitHubPackageError。

    限流（403 rate-limited / 429）会自动指数退避重试，重试耗尽后抛
    GitHubRateLimitError——调用方（尤其批量回收的 worker）收到它应该
    停下本轮，下一轮再试，而不是把每个条目都试一遍烧光配额。
    """
    last_exc: Exception | None = None
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        req = urllib.request.Request(
            url,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "aetrix-license/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", "ignore")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", "ignore")[:500]
            except Exception:
                pass
            headers = e.headers or {}
            if _is_rate_limited(e.code, headers, err_body):
                wait = _retry_after_seconds(headers, attempt)
                if attempt < _RATE_LIMIT_MAX_RETRIES:
                    logger.warning(
                        "GitHub API 限流（%s %s），%0.0f 秒后重试（第 %d 次）",
                        method, url, wait, attempt + 1,
                    )
                    time.sleep(wait)
                    continue
                last_exc = GitHubRateLimitError(
                    f"GitHub API 限流，重试 {_RATE_LIMIT_MAX_RETRIES} 次仍未恢复："
                    f"{err_body or 'rate limited'}。请稍后再试，不要频繁重试。"
                )
                break
            if e.code == 401:
                raise GitHubPackageError(
                    "GitHub token 无效或已过期：请前往管理后台 → 系统设置，"
                    f"更新 `{TOKEN_CONFIG_KEY}` 后重试"
                )
            if e.code == 403:
                raise GitHubPackageError(
                    "GitHub token 权限不足：请前往管理后台 → 系统设置，确认 "
                    f"`{TOKEN_CONFIG_KEY}` 的 token 已勾选 `write:packages` "
                    f"权限（当前返回 403）。错误详情：{err_body}"
                )
            if e.code == 404:
                raise GitHubPackageError(
                    f"Package 或用户不存在（404）：{url}。错误详情：{err_body}"
                )
            raise GitHubPackageError(
                f"GitHub API 调用失败（HTTP {e.code}）：{err_body}"
            )
        except urllib.error.URLError as e:
            raise GitHubPackageError(f"网络错误，GitHub API 不可达：{e}")
    # 只有走完重试仍限流才会到这里
    assert last_exc is not None
    raise last_exc


def _check_name(value: str, kind: str) -> str:
    """清洗用户名/包名，防止路径注入"""
    value = (value or "").strip()
    if not value or "/" in value:
        raise GitHubPackageError(f"非法的{kind}：{value!r}")
    return value


def grant_package_access(username: str, package_name: str, token: str,
                         owner: str = DEFAULT_PACKAGE_OWNER) -> None:
    """给 GitHub 用户加指定 container package 的读权限

    PUT 是幂等的：重复调用不会产生副作用，所以上层重试是安全的。

    Args:
        username: GitHub 用户名
        package_name: 包名，如 aetrix-web（不含 owner 前缀）
        token: GitHub PAT（需要 write:packages）
        owner: package 的 owner，默认 xzb177

    Raises:
        GitHubPackageError: API 调用失败
        GitHubRateLimitError: 限流且重试耗尽
    """
    username = _check_name(username, "GitHub 用户名")
    package_name = _check_name(package_name, "包名")

    url = (f"{GITHUB_API}/user/packages/container/{package_name}"
           f"/collaborators/{username}")
    logger.info("GitHub 授权：给 %s 加 %s/%s 读权限", username, owner, package_name)
    _api_request("PUT", url, token)
    logger.info("GitHub 授权成功：%s -> %s", username, package_name)


def revoke_package_access(username: str, package_name: str, token: str,
                          owner: str = DEFAULT_PACKAGE_OWNER) -> None:
    """回收 GitHub 用户的指定 container package 读权限

    DELETE 也是幂等的：用户本来就没权限时调也不会报错（GitHub 返回 204），
    所以 worker 重试是安全的。

    Raises:
        GitHubPackageError: API 调用失败
        GitHubRateLimitError: 限流且重试耗尽
    """
    username = _check_name(username, "GitHub 用户名")
    package_name = _check_name(package_name, "包名")

    url = (f"{GITHUB_API}/user/packages/container/{package_name}"
           f"/collaborators/{username}")
    logger.info("GitHub 回收：移除 %s 对 %s/%s 的权限", username, owner, package_name)
    _api_request("DELETE", url, token)
    logger.info("GitHub 回收成功：%s -/-> %s", username, package_name)


def get_token_from_db(db) -> str:
    """从数据库读 token（给 license_api / license_worker 用）"""
    return _get_token(db)
