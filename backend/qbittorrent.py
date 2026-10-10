"""qBittorrent 客户端：把磁力 / 种子链接交给下载器

只做两件面板真正需要的事：

1. **连接体检**：`POST /api/v2/auth/login` 换 SID，再 `GET /api/v2/app/version` 报版本；
2. **加种**：`POST /api/v2/torrents/add`，支持磁力链接或 `.torrent` 直链，可选保存目录与分类。

qB 的 WebUI API 需要用户名 / 密码（首次启动会给一个临时密码，在「选项 → Web UI」里可改）。
登录失败时 qB 会返回 `Fails.` 而不是报错状态码，所以这里必须看响应体，不能只看 200。

安全提醒（也写进了面板文案）：qB 的 Web UI 默认只监听本机，暴露到公网前请开 HTTPS
并打开「对本地主机以外的连接跳过身份验证」的反面——也就是**不要**关掉身份验证。
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0

_DNS_HINTS = (
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo failed",
    "name does not resolve",
    "temporary failure in name resolution",
)


def _network_error_hint(exc: httpx.HTTPError) -> str:
    """把 httpx 的网络异常翻译成"是什么 + 怎么查"的中文提示

    原始异常文本（如 ``[Errno 111] Connection refused``）对服主是天书，
    这里按异常类型给出可操作的排查步骤。注意顺序：httpx 里 ConnectTimeout
    同时是 ConnectError 的子类，必须先判超时。
    """
    text = str(exc).lower()
    if isinstance(exc, httpx.ConnectTimeout):
        return ("连接 qBittorrent 超时：目标地址长时间无响应。"
                "排查：1) 地址和端口是否正确 2) 服务器防火墙/安全组是否放行该端口 "
                "3) 是否在用公网地址访问内网服务")
    if isinstance(exc, httpx.ConnectError):
        if "refused" in text:
            return ("连不上 qBittorrent：目标地址拒绝连接。"
                    "排查：1) qBittorrent 是否正在运行 2) 地址和端口是否正确 "
                    "3) qB 的 Web UI 是否已启用（qB「选项 → Web UI」）")
        if "ssl" in text or "certificate" in text or "wrong version number" in text:
            return ("HTTPS 握手失败：对面可能没开 HTTPS。"
                    "排查：地址改成 http:// 再试，或在 qB「选项 → Web UI」里启用 HTTPS")
        if any(h in text for h in _DNS_HINTS):
            return "域名解析失败：请检查地址中的域名/IP 是否写对"
        return (f"无法与 qBittorrent 建立连接：{exc}。"
                "排查：1) 地址和端口是否正确 2) 网络是否通 3) 防火墙是否放行")
    if isinstance(exc, httpx.TimeoutException):
        return ("qBittorrent 响应超时：服务可能卡住或网络太慢。"
                "排查：1) qB 是否正常运行 2) 稍后重试")
    if isinstance(exc, httpx.ProxyError):
        return f"代理服务器连接失败：{exc}，请检查代理配置"
    return f"连接 qBittorrent 失败：{exc}"


def _http_status_hint(status_code: int, action: str = "登录") -> str:
    """登录/请求接口返回 4xx/5xx 时的可排查提示"""
    if status_code == 401:
        return ("qBittorrent 要求身份验证（HTTP 401）：可能是中间有反向代理加了认证，"
                "请检查代理配置，或确认地址直接指向 qBittorrent")
    if status_code == 404:
        return (f"qBittorrent {action}返回 404：地址路径不对"
                "（一般填到端口即可，如 http://192.168.1.10:8080），或 qB 的 Web UI 未启用")
    if status_code in (500, 502, 503, 504):
        return (f"qBittorrent/网关返回 HTTP {status_code}：服务或反向代理异常，"
                "请检查 qB 是否正常运行")
    return f"qBittorrent {action}返回 HTTP {status_code}"


def _base(url: str) -> str:
    return (url or "").strip().rstrip("/")


async def _login(client: httpx.AsyncClient, base_url: str, username: str, password: str) -> dict:
    """登录拿 SID（写进 client 的 cookie jar，后续请求自动带上）"""
    try:
        resp = await client.post(
            f"{_base(base_url)}/api/v2/auth/login",
            data={"username": username, "password": password},
            headers={"Referer": _base(base_url)},
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "message": _network_error_hint(exc)}
    except httpx.InvalidURL as exc:
        return {"ok": False, "message": f"qBittorrent 地址格式有误：{exc}，请检查是否多写了字符或端口不对"}

    body = (resp.text or "").strip()
    if resp.status_code == 403 or body.lower().startswith("banned"):
        return {"ok": False, "message": "qBittorrent 因多次登录失败已暂时封禁该 IP，请稍后再试"}
    if resp.status_code >= 400:
        return {"ok": False, "message": _http_status_hint(resp.status_code)}
    if body.lower().startswith("fails"):
        return {"ok": False, "message": "qBittorrent 用户名或密码不对"}
    # qB 用 SID Cookie 表示会话已建立；拿不到就说明对面不是 qB（或中间有反向代理吃掉了 Cookie）
    if not (resp.cookies.get("SID") or client.cookies.get("SID")):
        return {"ok": False, "message":
                "qBittorrent 没有返回会话 Cookie（对面可能不是 qBittorrent）。"
                "排查：1) 用浏览器打开该地址，确认是 qB 的 Web UI 登录页 "
                "2) 地址一般填到端口即可，不要带多余路径 "
                "3) 如经过反向代理，确认代理没有拦截或吃掉 Cookie"}
    return {"ok": True, "message": "登录成功"}


async def version(base_url: str, username: str, password: str,
                  timeout: float = DEFAULT_TIMEOUT) -> dict:
    """查版本（同时也是「登录 + 会话可用」的证据）"""
    if not _base(base_url):
        return {"ok": False, "message": "没有填写 qBittorrent 的地址"}
    if not username:
        return {"ok": False, "message": "没有填写 qBittorrent 的用户名"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            auth = await _login(client, base_url, username, password)
            if not auth.get("ok"):
                return auth
            resp = await client.get(f"{_base(base_url)}/api/v2/app/version")
    except httpx.HTTPError as exc:
        return {"ok": False, "message": _network_error_hint(exc)}
    except httpx.InvalidURL as exc:
        return {"ok": False, "message": f"qBittorrent 地址格式有误：{exc}，请检查是否多写了字符或端口不对"}
    if resp.status_code >= 400:
        return {"ok": False, "message": _http_status_hint(resp.status_code, action="查询版本")}
    return {"ok": True, "message": f"已连接 qBittorrent {resp.text.strip()}", "version": resp.text.strip()}


async def probe(base_url: str, username: str = "", password: str = "",
                timeout: float = DEFAULT_TIMEOUT) -> dict:
    """连接体检（同时报告版本与当前任务数，便于确认连的是哪台）"""
    result = await version(base_url, username, password, timeout=timeout)
    if not result.get("ok"):
        return result

    torrents = None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            auth = await _login(client, base_url, username, password)
            if auth.get("ok"):
                resp = await client.get(f"{_base(base_url)}/api/v2/torrents/info")
                if resp.status_code < 400:
                    body = resp.json()
                    torrents = len(body) if isinstance(body, list) else None
    except (httpx.HTTPError, ValueError):
        torrents = None

    return {
        "ok": True,
        "message": result["message"] + (f"（当前 {torrents} 个任务）" if torrents is not None else ""),
        "version": result.get("version"),
        "torrent_count": torrents,
    }


async def add_torrent(base_url: str, username: str, password: str, link: str,
                      save_path: str = "", category: str = "", paused: bool = False,
                      timeout: float = DEFAULT_TIMEOUT) -> dict:
    """加种：`link` 可以是磁力链接，也可以是 `.torrent` 的 http(s) 直链

    返回 `{ok, message, hash?}`。qB 的 `torrents/add` 成功时只回 `Ok.`，不返回 hash，
    所以这里如实说明「已交给下载器」，不假装知道任务状态。
    """
    link = (link or "").strip()
    if not link:
        return {"ok": False, "message": "没有可提交的下载链接：请填写磁力链接或 .torrent 地址"}
    if not (link.startswith("magnet:") or link.startswith("http://") or link.startswith("https://")):
        return {"ok": False, "message": "下载链接必须是 magnet: 磁力链接或 http(s) 的 .torrent 地址"}
    if not _base(base_url):
        return {"ok": False, "message": "没有填写 qBittorrent 的地址"}

    form: dict = {"urls": link}
    if save_path:
        form["savepath"] = save_path
    if category:
        form["category"] = category
    if paused:
        form["paused"] = "true"

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            auth = await _login(client, base_url, username, password)
            if not auth.get("ok"):
                return auth
            resp = await client.post(f"{_base(base_url)}/api/v2/torrents/add", data=form)
    except httpx.HTTPError as exc:
        return {"ok": False, "message": _network_error_hint(exc)}
    except httpx.InvalidURL as exc:
        return {"ok": False, "message": f"qBittorrent 地址格式有误：{exc}，请检查是否多写了字符或端口不对"}
    if resp.status_code >= 400:
        return {"ok": False, "message": _http_status_hint(resp.status_code, action="提交下载任务")}
    body = (resp.text or "").strip()
    if body and not body.lower().startswith("ok"):
        return {"ok": False, "message": f"qBittorrent 未接受该链接：{body[:120]}"}
    return {"ok": True, "message": "已交给 qBittorrent 下载（可在 qB 里看进度）"}


def pick_link(url: str) -> Optional[str]:
    """从管理员填的一串文本里挑出一个磁力链接（粘整段分享文本时也能用）"""
    text = (url or "").strip()
    if text.startswith("magnet:") or text.startswith("http"):
        return text
    idx = text.find("magnet:?")
    if idx >= 0:
        tail = text[idx:]
        space = tail.find(" ")
        return tail if space < 0 else tail[:space]
    return None


__all__ = ["add_torrent", "pick_link", "probe", "version"]
