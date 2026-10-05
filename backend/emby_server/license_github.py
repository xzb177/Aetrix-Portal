"""GitHub Package 授权管理（v2.50.0）

用户购买 Aetrix 授权后，系统自动调 GitHub API 给他的 GitHub 账号加上
对应 container package 的读权限；到期/撤销时自动回收。

GitHub API 文档：
- 加协作者：PUT /user/packages/container/{package_name}/collaborators/{username}
- 删协作者：DELETE /user/packages/container/{package_name}/collaborators/{username}

token 从 system_configs 的 ``github_package_token`` 读，需要
``read:packages`` + ``write:packages`` 权限（classic PAT）。
"""
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# GitHub API 基础地址
GITHUB_API = "https://api.github.com"
# token 在 system_configs 里的 key
TOKEN_CONFIG_KEY = "github_package_token"
# 默认的包名前缀（ghcr.io/<owner>/ 后面的部分由调用方传）
DEFAULT_PACKAGE_OWNER = "xzb177"


class GitHubPackageError(Exception):
    """GitHub Package API 调用失败"""
    pass


def _get_token(db) -> str:
    """从 system_configs 读 GitHub token"""
    from backend.integrations import store
    token = store.get_value(db, TOKEN_CONFIG_KEY, "")
    if not token:
        raise GitHubPackageError(
            f"未配置 GitHub token：请在系统设置里填写 `{TOKEN_CONFIG_KEY}` "
            "（需要 read:packages + write:packages 权限的 classic PAT）"
        )
    return token


def _api_request(method: str, url: str, token: str) -> dict:
    """发 GitHub API 请求，失败抛 GitHubPackageError"""
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
        if e.code == 401:
            raise GitHubPackageError(
                "GitHub token 无效或已过期：请检查系统设置里的 "
                f"`{TOKEN_CONFIG_KEY}` 是否正确"
            )
        if e.code == 403:
            raise GitHubPackageError(
                "GitHub token 权限不足：需要勾选 `write:packages` "
                f"（当前返回 403）。错误详情：{err_body}"
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


def grant_package_access(username: str, package_name: str, token: str,
                         owner: str = DEFAULT_PACKAGE_OWNER) -> None:
    """给 GitHub 用户加指定 container package 的读权限

    Args:
        username: GitHub 用户名
        package_name: 包名，如 aetrix-web（不含 owner 前缀）
        token: GitHub PAT（需要 write:packages）
        owner: package 的 owner，默认 xzb177

    Raises:
        GitHubPackageError: API 调用失败
    """
    # 用户名做基本清洗，防止路径注入
    username = (username or "").strip()
    if not username or "/" in username:
        raise GitHubPackageError(f"非法的 GitHub 用户名：{username!r}")
    package_name = (package_name or "").strip()
    if not package_name or "/" in package_name:
        raise GitHubPackageError(f"非法的包名：{package_name!r}")

    url = (f"{GITHUB_API}/user/packages/container/{package_name}"
           f"/collaborators/{username}")
    logger.info("GitHub 授权：给 %s 加 %s/%s 读权限", username, owner, package_name)
    _api_request("PUT", url, token)
    logger.info("GitHub 授权成功：%s -> %s", username, package_name)


def revoke_package_access(username: str, package_name: str, token: str,
                          owner: str = DEFAULT_PACKAGE_OWNER) -> None:
    """回收 GitHub 用户的指定 container package 读权限

    Args:
        username: GitHub 用户名
        package_name: 包名
        token: GitHub PAT
        owner: package 的 owner

    Raises:
        GitHubPackageError: API 调用失败
    """
    username = (username or "").strip()
    if not username or "/" in username:
        raise GitHubPackageError(f"非法的 GitHub 用户名：{username!r}")
    package_name = (package_name or "").strip()
    if not package_name or "/" in package_name:
        raise GitHubPackageError(f"非法的包名：{package_name!r}")

    url = (f"{GITHUB_API}/user/packages/container/{package_name}"
           f"/collaborators/{username}")
    logger.info("GitHub 回收：移除 %s 对 %s/%s 的权限", username, owner, package_name)
    _api_request("DELETE", url, token)
    logger.info("GitHub 回收成功：%s -/-> %s", username, package_name)


def get_token_from_db(db) -> str:
    """从数据库读 token（给 license_api / license_worker 用）"""
    return _get_token(db)
