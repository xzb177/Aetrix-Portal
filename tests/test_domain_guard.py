"""域名守卫 + CF 真实 IP 中间件的回归测试。

两个都是纯 ASGI 中间件：直接调 ``__call__(scope, receive, send)``，
断言发出的 ASGI 消息，不经过 HTTP 客户端。
"""
import os

import pytest

from backend.domain_guard import (
    CloudflareIPMiddleware,
    DomainGuardMiddleware,
)


def _scope(path="/emby/System/Info", host="stream.example.com", client=("1.2.3.4", 5000)):
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "headers": [(b"host", host.encode("latin-1"))],
        "client": client,
    }


async def _run(mw_cls, scope):
    """跑一遍中间件，返回 (下游是否被调用, 发出的消息列表, 变更后的 scope)。"""
    called = []

    async def app(s, receive, send):
        called.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    messages = []

    async def send(msg):
        messages.append(msg)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await mw_cls(app)(scope, receive, send)
    return bool(called), messages, scope


def _status(messages):
    for m in messages:
        if m["type"] == "http.response.start":
            return m["status"]
    return None


# ---------- DomainGuard ----------

def test_no_env_passthrough(monkeypatch):
    import asyncio
    monkeypatch.delenv("ENFORCE_DOMAIN", raising=False)
    called, msgs, _ = asyncio.run(_run(DomainGuardMiddleware, _scope(host="1.2.3.4")))
    assert called and _status(msgs) == 200


def test_wrong_host_403(monkeypatch):
    import asyncio
    monkeypatch.setenv("ENFORCE_DOMAIN", "stream.example.com")
    called, msgs, _ = asyncio.run(_run(DomainGuardMiddleware, _scope(host="5.6.7.8")))
    assert not called and _status(msgs) == 403


def test_correct_host_passthrough(monkeypatch):
    import asyncio
    monkeypatch.setenv("ENFORCE_DOMAIN", "stream.example.com")
    called, msgs, _ = asyncio.run(_run(DomainGuardMiddleware, _scope(host="stream.example.com")))
    assert called and _status(msgs) == 200


def test_host_with_port_stripped(monkeypatch):
    import asyncio
    monkeypatch.setenv("ENFORCE_DOMAIN", "stream.example.com")
    called, msgs, _ = asyncio.run(_run(DomainGuardMiddleware, _scope(host="stream.example.com:8001")))
    assert called and _status(msgs) == 200


def test_multi_domain(monkeypatch):
    import asyncio
    monkeypatch.setenv("ENFORCE_DOMAIN", "a.example.com, stream.example.com")
    called, msgs, _ = asyncio.run(_run(DomainGuardMiddleware, _scope(host="a.example.com")))
    assert called


def test_health_from_private_ip_allowed(monkeypatch):
    import asyncio
    monkeypatch.setenv("ENFORCE_DOMAIN", "stream.example.com")
    called, msgs, _ = asyncio.run(_run(DomainGuardMiddleware,
             _scope(path="/api/health", host="10.0.0.9", client=("10.0.0.9", 4000))))
    assert called and _status(msgs) == 200


def test_health_from_public_ip_still_blocked(monkeypatch):
    import asyncio
    monkeypatch.setenv("ENFORCE_DOMAIN", "stream.example.com")
    called, msgs, _ = asyncio.run(_run(DomainGuardMiddleware,
             _scope(path="/api/health", host="5.6.7.8", client=("5.6.7.8", 4000))))
    assert not called and _status(msgs) == 403


def test_non_http_passthrough(monkeypatch):
    import asyncio
    monkeypatch.setenv("ENFORCE_DOMAIN", "stream.example.com")
    scope = {"type": "lifespan"}
    called, _, _ = asyncio.run(_run(DomainGuardMiddleware, scope))
    assert called


# ---------- CloudflareIP ----------

def test_cf_ip_disabled_by_default(monkeypatch):
    import asyncio
    monkeypatch.delenv("TRUST_CF_IP", raising=False)
    scope = _scope()
    scope["headers"].append((b"cf-connecting-ip", b"9.9.9.9"))
    _, _, out = asyncio.run(_run(CloudflareIPMiddleware, scope))
    assert out["client"][0] == "1.2.3.4"  # 没动


def test_cf_connecting_ip_preferred(monkeypatch):
    import asyncio
    monkeypatch.setenv("TRUST_CF_IP", "true")
    scope = _scope()
    scope["headers"].append((b"cf-connecting-ip", b"9.9.9.9"))
    scope["headers"].append((b"x-forwarded-for", b"8.8.8.8, 7.7.7.7"))
    _, _, out = asyncio.run(_run(CloudflareIPMiddleware, scope))
    assert out["client"][0] == "9.9.9.9"


def test_xff_fallback(monkeypatch):
    import asyncio
    monkeypatch.setenv("TRUST_CF_IP", "1")
    scope = _scope()
    scope["headers"].append((b"x-forwarded-for", b"8.8.8.8, 7.7.7.7"))
    _, _, out = asyncio.run(_run(CloudflareIPMiddleware, scope))
    assert out["client"][0] == "8.8.8.8"


def test_invalid_proxy_ip_ignored(monkeypatch):
    import asyncio
    monkeypatch.setenv("TRUST_CF_IP", "true")
    scope = _scope()
    scope["headers"].append((b"cf-connecting-ip", b"not-an-ip"))
    _, _, out = asyncio.run(_run(CloudflareIPMiddleware, scope))
    assert out["client"][0] == "1.2.3.4"
