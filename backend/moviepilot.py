"""MoviePilot 客户端：把求片变成它的订阅，让片子真的被搜索下载

MoviePilot（`jxxghp/MoviePilot`）有**两套凭据**，用途完全不同，本项目两种都支持：

- **API_TOKEN**（面板里的「API 密钥」）：走查询参数 `?token=` 或 `?apikey=` / 请求头
  `X-Api-Key`，可以查订阅列表等只读接口。用它**不能**新增订阅。
- **用户名 / 密码**：登录 `/api/v1/login/access-token` 拿 JWT，
  `POST /api/v1/subscribe/` 只认这个（MoviePilot 侧要求登录用户身份）。

所以只想「测一下通不通」填 API 密钥就够；要让求片真的被提交成订阅，必须填用户名密码。
两种都没配或都不对时，这里一律返回 `{ok: False, message: ...}` 的可读原因，
不抛异常、不留「假成功」。

新增订阅的请求体字段沿用 MoviePilot 的 `schemas.Subscribe`：`name` / `year` / `type`
（`电影` / `电视剧`），可选 `season` / `save_path`。
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 求片类型（本项目存 movie / tv）→ MoviePilot 的 MediaType 取值
MOVIEPILOT_TYPES = {
    "movie": "电影",
    "tv": "电视剧",
    "电影": "电影",
    "电视剧": "电视剧",
}

DEFAULT_TIMEOUT = 15.0


def media_type(raw: Optional[str]) -> str:
    """把本项目的求片类型翻译成 MoviePilot 的类型（认不出来时返回空串，交给它自己识别）"""
    return MOVIEPILOT_TYPES.get((raw or "").strip().lower(), "")


def _base(url: str) -> str:
    return (url or "").strip().rstrip("/")


async def login(base_url: str, username: str, password: str,
                timeout: float = DEFAULT_TIMEOUT) -> dict:
    """用户名 / 密码换 JWT（MoviePilot 的 `/api/v1/login/access-token`，OAuth2 密码流）"""
    if not username or not password:
        return {"ok": False, "message": "没有填写 MoviePilot 的用户名 / 密码"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(
                f"{_base(base_url)}/api/v1/login/access-token",
                data={"username": username, "password": password},
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"无法连接 MoviePilot: {exc}"}

    if resp.status_code in (400, 401, 403, 422):
        return {"ok": False, "message": "MoviePilot 拒绝了用户名或密码"}
    if resp.status_code >= 400:
        return {"ok": False, "message": f"MoviePilot 登录返回 HTTP {resp.status_code}"}
    try:
        token = str((resp.json() or {}).get("access_token") or "")
    except ValueError:
        return {"ok": False, "message": "MoviePilot 登录返回的不是 JSON（地址可能指向别的服务）"}
    if not token:
        return {"ok": False, "message": "MoviePilot 登录成功但没有返回 access_token"}
    return {"ok": True, "token": token, "message": "登录成功"}


async def list_subscribes(base_url: str, api_key: str,
                          timeout: float = DEFAULT_TIMEOUT) -> dict:
    """用 API_TOKEN 查订阅列表（`GET /api/v1/subscribe/list?token=…`）

    这也是「API 密钥是否有效」最直接的证据：形状是 `[{...}]`，凭据不对时是 401。
    """
    if not api_key:
        return {"ok": False, "message": "没有填写 API 密钥", "items": []}
    url = f"{_base(base_url)}/api/v1/subscribe/list"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, params={"token": api_key},
                                    headers={"X-Api-Key": api_key})
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"无法连接 MoviePilot: {exc}", "items": []}
    if resp.status_code == 401:
        return {"ok": False, "message": "API 密钥不对（在 MoviePilot 的「设定 → 系统」里看 API_TOKEN）", "items": []}
    if resp.status_code >= 400:
        return {"ok": False, "message": f"MoviePilot 返回 HTTP {resp.status_code}", "items": []}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "message": "MoviePilot 返回的不是 JSON（地址可能指向别的服务）", "items": []}
    items = data if isinstance(data, list) else (data.get("data") or [])
    return {"ok": True, "items": items if isinstance(items, list) else [], "message": ""}


async def subscribe(base_url: str, *, username: str, password: str,
                    name: str, year: Optional[str] = None, mtype: str = "",
                    season: Optional[int] = None, save_path: str = "",
                    timeout: float = DEFAULT_TIMEOUT) -> dict:
    """新增订阅（需要用户名 / 密码换来的 JWT）

    返回 `{ok, message, id}`；`message` 直接来自 MoviePilot（它会把「已存在」等情况说清楚），
    拿不到时退回我们自己写的原因。
    """
    auth = await login(base_url, username, password, timeout=timeout)
    if not auth.get("ok"):
        return auth

    payload: dict = {"name": name}
    if year:
        payload["year"] = str(year)
    if mtype:
        payload["type"] = mtype
    if season:
        payload["season"] = int(season)
    if save_path:
        payload["save_path"] = save_path

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(
                f"{_base(base_url)}/api/v1/subscribe/",
                json=payload,
                headers={"Authorization": f"Bearer {auth['token']}"},
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"提交订阅时无法连接 MoviePilot: {exc}"}

    if resp.status_code in (401, 403):
        return {"ok": False, "message": "MoviePilot 拒绝了登录令牌：请重新填写用户名 / 密码"}
    if resp.status_code >= 400:
        return {"ok": False, "message": f"MoviePilot 返回 HTTP {resp.status_code}"}
    try:
        body = resp.json() or {}
    except ValueError:
        return {"ok": False, "message": "MoviePilot 返回的不是 JSON"}

    if isinstance(body, dict) and "success" in body:
        ok = bool(body.get("success"))
        return {
            "ok": ok,
            "message": str(body.get("message") or ("订阅已提交" if ok else "MoviePilot 未能创建订阅")),
            "id": (body.get("data") or {}).get("id") if isinstance(body.get("data"), dict) else None,
        }
    return {"ok": True, "message": "订阅已提交", "id": None}


async def probe(base_url: str, api_key: str = "", username: str = "",
                password: str = "", timeout: float = DEFAULT_TIMEOUT) -> dict:
    """连接体检：分别验证「API 密钥（只读）」与「用户名密码（可订阅）」两条能力

    返回 `{ok, message, can_query, can_subscribe, subscribe_count, version?}`。
    `ok` 只要有一项可用就为真——只填 API 密钥也算连上了，但 `can_subscribe=False`，
    面板会据此提示「还不能提交订阅」。
    """
    base = _base(base_url)
    can_query = False
    can_subscribe = False
    details: list[str] = []
    subscribe_count = None
    version = ""

    if api_key:
        listed = await list_subscribes(base, api_key, timeout=timeout)
        if listed.get("ok"):
            can_query = True
            subscribe_count = len(listed.get("items") or [])
            details.append(f"API 密钥可用（当前 {subscribe_count} 条订阅）")
        else:
            details.append(str(listed.get("message") or "API 密钥不可用"))
    else:
        details.append("未填 API 密钥")

    if username and password:
        auth = await login(base, username, password, timeout=timeout)
        can_subscribe = bool(auth.get("ok"))
        details.append("用户名密码可登录，能提交订阅" if can_subscribe
                       else str(auth.get("message") or "登录失败"))
    elif username or password:
        details.append("用户名和密码要一起填")

    ok = can_query or can_subscribe
    if ok:
        message = "；".join(details)
    elif not api_key and not username:
        message = "请填写 API 密钥（只读）或用户名 / 密码（可提交订阅），至少填一项"
    else:
        message = "；".join(details)
    return {
        "ok": ok,
        "message": message,
        "can_query": can_query,
        "can_subscribe": can_subscribe,
        "subscribe_count": subscribe_count,
        "version": version,
    }


__all__ = ["login", "list_subscribes", "media_type", "probe", "subscribe"]
