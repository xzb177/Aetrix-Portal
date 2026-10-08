"""S2：远程代理共享连接池——可配置上限、块间读超时、池满快速 503、卡死的上游会被释放。"""
import asyncio
import os
import time
import types

import httpx
import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend.emby_server import streaming


def _req(range_header=None):
    headers = {"range": range_header} if range_header else {}
    return types.SimpleNamespace(headers=headers)


def test_defaults_and_env_clamping(monkeypatch):
    assert streaming._RELAY_MAX_CONNECTIONS >= 4
    # 默认值（未设置环境变量时）
    monkeypatch.delenv("RELAY_MAX_CONNECTIONS", raising=False)
    assert streaming._env_number("RELAY_MAX_CONNECTIONS", 200, 4, 5000, int) == 200
    monkeypatch.setenv("RELAY_MAX_CONNECTIONS", "1")
    assert streaming._env_number("RELAY_MAX_CONNECTIONS", 200, 4, 5000, int) == 4
    monkeypatch.setenv("RELAY_MAX_CONNECTIONS", "abc")
    assert streaming._env_number("RELAY_MAX_CONNECTIONS", 200, 4, 5000, int) == 200
    t = streaming.relay_timeout()
    assert t.read is not None and t.read > 0
    assert t.pool is not None and t.pool <= 60
    assert t.connect is not None


def test_shared_client_uses_finite_timeouts(monkeypatch):
    monkeypatch.setattr(streaming, "_shared_client", None)
    client = streaming.get_relay_client()
    try:
        assert client.timeout.read == streaming._RELAY_READ_TIMEOUT
        assert client.timeout.pool == streaming._RELAY_POOL_TIMEOUT
    finally:
        asyncio.run(streaming.close_relay_client())


def test_pool_timeout_is_clean_503(monkeypatch):
    def handler(request):
        raise httpx.PoolTimeout("pool full", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(streaming, "get_relay_client", lambda: client)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(streaming.serve_remote_async("http://upstream.invalid/v.mkv", _req()))
    assert ei.value.status_code == 503
    assert ei.value.headers.get("Retry-After")


def test_connect_error_still_502(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(streaming, "get_relay_client", lambda: client)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(streaming.serve_remote_async("http://upstream.invalid/v.mkv", _req()))
    assert ei.value.status_code == 502


def test_stalled_upstream_is_released(monkeypatch):
    """源站发了头和一块数据后不再回数据（TCP 不断）：读超时后流结束，连接归还。"""
    monkeypatch.setattr(streaming, "_RELAY_READ_TIMEOUT", 0.5)
    monkeypatch.setattr(streaming, "_RELAY_POOL_TIMEOUT", 0.5)
    monkeypatch.setattr(streaming, "_shared_client", None)

    async def scenario():
        stall = asyncio.Event()

        async def handle(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n"
                         b"Content-Type: video/mp4\r\n\r\n" + b"a" * 1024)
            await writer.drain()
            await stall.wait()  # 卡住：不断开、不再发数据
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            resp = await streaming.serve_remote_async(f"http://127.0.0.1:{port}/v.mp4", _req())
            assert resp.status_code == 200
            got = b""
            t0 = time.monotonic()
            async for chunk in resp.body_iterator:
                got += chunk
            elapsed = time.monotonic() - t0
            assert len(got) <= 1024  # aiter_bytes 按块缓冲，截断时未凑满的块可能丢弃
            assert elapsed < 5, elapsed  # 旧实现 read=None：永远挂着
            client = streaming.get_relay_client()
            pool = client._transport._pool
            busy = [c for c in pool.connections if not (c.is_idle() or c.is_closed())]
            assert busy == []  # 卡死的上游连接已释放，不会把池慢慢耗尽
        finally:
            stall.set()
            server.close()
            await server.wait_closed()
            await streaming.close_relay_client()

    asyncio.run(scenario())
