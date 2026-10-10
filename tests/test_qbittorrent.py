"""qBittorrent 连接体检的错误提示测试

用 httpx.MockTransport 模拟各种失败场景，不发真实网络请求。
覆盖：网络异常分类、HTTP 状态码提示、无 SID Cookie 提示、空地址/用户名前置校验。
"""
import asyncio

import httpx

from backend import qbittorrent


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _resp(status=200, text="", sid=None):
    headers = {}
    if sid:
        headers["set-cookie"] = f"SID={sid}; Path=/"
    return httpx.Response(status, text=text, headers=headers)


def run(coro):
    return asyncio.run(coro)


def _ok_login(request):
    return _resp(200, "Ok.", sid="abc123")


# ---------- 成功路径 ----------

def test_login_ok():
    async def go():
        async with _client(_ok_login) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "admin", "x")
    assert run(go())["ok"] is True


# ---------- 新版 qB 会话 Cookie 名（QBT_SID_<port>） ----------

def _resp_cookie(name, value="sess123"):
    def handler(request):
        return httpx.Response(200, text="Ok.",
                              headers={"set-cookie": f"{name}={value}; Path=/"})
    return handler


def test_login_ok_qbt_sid_port_cookie():
    """生产实测：新版 qB 返回 QBT_SID_<port> 而不是 SID，也必须认"""
    async def go():
        async with _client(_resp_cookie("QBT_SID_12354")) as client:
            return await qbittorrent._login(client, "http://167.17.76.115:12354", "admin", "x")
    assert run(go())["ok"] is True


def test_login_ok_sid_prefix_variant():
    async def go():
        async with _client(_resp_cookie("SID_abc")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "admin", "x")
    assert run(go())["ok"] is True


def test_login_ok_cookie_only_in_jar():
    """Cookie 只落在 client jar 里（响应头没带）也要认"""
    async def go():
        async with _client(lambda r: _resp(200, "Ok.")) as client:
            client.cookies.set("QBT_SID_8080", "jar-only", domain="127.0.0.1", path="/")
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "admin", "x")
    assert run(go())["ok"] is True


def test_session_cookie_helper():
    jars = [httpx.Cookies()]
    jars[0].set("QBT_SID_12354", "v1", domain="h", path="/")
    assert qbittorrent._session_cookie_value(*jars) == "v1"
    jars = [httpx.Cookies()]
    jars[0].set("SID", "v2", domain="h", path="/")
    assert qbittorrent._session_cookie_value(*jars) == "v2"
    jars = [httpx.Cookies()]
    jars[0].set("other", "v3", domain="h", path="/")
    assert qbittorrent._session_cookie_value(*jars) is None
    assert qbittorrent._session_cookie_value() is None


# ---------- 网络异常分类 ----------

def _raise(exc):
    def handler(request):
        raise exc
    return handler


def test_connect_refused_hint():
    async def go():
        async with _client(_raise(httpx.ConnectError("[Errno 111] Connection refused"))) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    msg = run(go())["message"]
    assert "拒绝连接" in msg and "是否正在运行" in msg and "Web UI" in msg


def test_dns_failure_hint():
    async def go():
        async with _client(_raise(httpx.ConnectError("[Errno -2] Name or service not known"))) as client:
            return await qbittorrent._login(client, "http://no-such-host:8080", "a", "b")
    assert "域名解析失败" in run(go())["message"]


def test_ssl_hint():
    async def go():
        async with _client(_raise(httpx.ConnectError("[SSL: WRONG_VERSION_NUMBER] wrong version number"))) as client:
            return await qbittorrent._login(client, "https://127.0.0.1:8080", "a", "b")
    assert "HTTPS" in run(go())["message"]


def test_connect_timeout_hint():
    async def go():
        async with _client(_raise(httpx.ConnectTimeout("timed out"))) as client:
            return await qbittorrent._login(client, "http://10.0.0.1:8080", "a", "b")
    msg = run(go())["message"]
    assert "超时" in msg and "防火墙" in msg


def test_read_timeout_hint():
    async def go():
        async with _client(_raise(httpx.ReadTimeout("timed out"))) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    assert "响应超时" in run(go())["message"]


def test_proxy_error_hint():
    async def go():
        async with _client(_raise(httpx.ProxyError("proxy failed"))) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    assert "代理" in run(go())["message"]


# ---------- HTTP 状态码提示 ----------

def test_403_banned():
    async def go():
        async with _client(lambda r: _resp(403, "banned")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    assert "封禁" in run(go())["message"]


def test_404_hint():
    async def go():
        async with _client(lambda r: _resp(404, "not found")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    msg = run(go())["message"]
    assert "404" in msg and "填到端口" in msg


def test_401_hint():
    async def go():
        async with _client(lambda r: _resp(401, "unauthorized")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    assert "反向代理" in run(go())["message"]


def test_502_hint():
    async def go():
        async with _client(lambda r: _resp(502, "bad gateway")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    assert "502" in run(go())["message"]


def test_fails_body():
    async def go():
        async with _client(lambda r: _resp(200, "Fails.")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "wrong")
    assert "用户名或密码不对" in run(go())["message"]


# ---------- 无 SID Cookie（用户本次报的错） ----------

def test_no_sid_cookie_hint():
    async def go():
        async with _client(lambda r: _resp(200, "Ok.")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    msg = run(go())["message"]
    assert "会话 Cookie" in msg
    assert "浏览器打开" in msg  # 给出可操作的排查步骤
    assert "反向代理" in msg


def test_no_sid_empty_body():
    async def go():
        async with _client(lambda r: _resp(200, "")) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:8080", "a", "b")
    assert run(go())["ok"] is False


# ---------- 前置校验 ----------

def test_version_empty_url():
    assert run(qbittorrent.version("", "a", "b"))["message"] == "没有填写 qBittorrent 的地址"


def test_version_empty_username():
    assert run(qbittorrent.version("http://127.0.0.1:8080", "", "b"))["message"] == "没有填写 qBittorrent 的用户名"


def test_add_torrent_empty_url():
    r = run(qbittorrent.add_torrent("", "a", "b", "magnet:?xt=urn:btih:abc"))
    assert r["message"] == "没有填写 qBittorrent 的地址"


def test_invalid_url_hint():
    async def go():
        async with _client(_raise(httpx.InvalidURL("Invalid port"))) as client:
            return await qbittorrent._login(client, "http://127.0.0.1:abc", "a", "b")
    assert "地址格式有误" in run(go())["message"]
