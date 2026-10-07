"""回归测试：中转零拷贝优化（perf/relay-zero-copy）。

1. 纯 ASGI 中间件行为与原来的 @app.middleware("http") 版本一致：
   安全头正确、分片路径跳过 no-store、body 分块原样透传、413/429 短路。
2. streaming.py 读块为 1MB（READ_CHUNK），降低每秒线程池提交与 FUSE 系统调用。
"""
import asyncio
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_mw_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "asgi_mw", str(REPO_ROOT / "emby_api" / "asgi_middleware.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scope(path="/emby/Videos/abc/stream", headers=None):
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "client": ("1.2.3.4", 12345),
    }


async def _fake_stream_app(scope, receive, send):
    await send({
        "type": "http.response.start",
        "status": 206,
        "headers": [(b"content-type", b"video/mp4")],
    })
    for chunk in (b"A" * 100, b"B" * 100, b"C" * 100):
        await send({"type": "http.response.body", "body": chunk, "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def _run(mw, scope):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        messages.append(msg)

    await mw(scope, receive, send)
    return messages


def _run_coro(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def mw():
    return _load_mw_module()


def test_security_headers_stream_path(mw):
    msgs = _run_coro(_run(mw.SecurityHeadersMiddleware(_fake_stream_app), _scope()))
    hdrs = {k.lower(): v for k, v in msgs[0]["headers"]}
    assert hdrs[b"x-content-type-options"] == b"nosniff"
    assert hdrs[b"x-frame-options"] == b"DENY"
    assert hdrs[b"referrer-policy"] == b"strict-origin-when-cross-origin"
    # 分片路径跳过 no-store（PR #387 口径）
    assert b"cache-control" not in hdrs
    bodies = b"".join(m.get("body", b"") for m in msgs[1:])
    assert bodies == b"A" * 100 + b"B" * 100 + b"C" * 100


def test_security_headers_non_stream_emby_path(mw):
    msgs = _run_coro(_run(
        mw.SecurityHeadersMiddleware(_fake_stream_app), _scope("/emby/Users/1/Items")))
    hdrs = {k.lower(): v for k, v in msgs[0]["headers"]}
    assert hdrs.get(b"cache-control") == b"no-store"


def test_security_headers_non_emby_path(mw):
    msgs = _run_coro(_run(
        mw.SecurityHeadersMiddleware(_fake_stream_app), _scope("/api/health")))
    hdrs = {k.lower(): v for k, v in msgs[0]["headers"]}
    assert b"cache-control" not in hdrs
    assert hdrs[b"x-content-type-options"] == b"nosniff"


def test_body_limit_rejects_oversize(mw):
    scope = _scope("/api/x", [(b"content-length", b"999999999")])
    msgs = _run_coro(_run(mw.EaBodyLimitMiddleware(_fake_stream_app), scope))
    assert msgs[0]["status"] == 413


def test_body_limit_passthrough(mw):
    msgs = _run_coro(_run(mw.EaBodyLimitMiddleware(_fake_stream_app), _scope("/api/x")))
    assert msgs[0]["status"] == 206


def test_rate_limit_stream_passthrough(mw):
    # /emby/Videos/stream 无匹配规则：放行，不碰 Redis
    msgs = _run_coro(_run(mw.EaRateLimitMiddleware(_fake_stream_app), _scope()))
    assert msgs[0]["status"] == 206


def test_ensure_header_setdefault(mw):
    raw = [(b"cache-control", b"public")]
    mw._ensure_header(raw, b"cache-control", b"no-store")
    assert raw == [(b"cache-control", b"public")]
    mw._ensure_header(raw, b"x-foo", b"bar")
    assert (b"x-foo", b"bar") in raw


def test_read_chunk_is_1mb():
    """读块 1MB：降低中转每秒的线程池提交与 FUSE 系统调用。"""
    src = (REPO_ROOT / "backend" / "emby_server" / "streaming.py").read_text()
    assert "READ_CHUNK = 1024 * 1024" in src
    # FUSE 读与远程中转都用大块；默认 Range 区间仍用 CHUNK（别混用）
    assert "f.read(min(READ_CHUNK, remaining))" in src
    assert "resp.aiter_bytes(READ_CHUNK)" in src
    assert "CHUNK * 200" in src  # 默认区间计算不动
