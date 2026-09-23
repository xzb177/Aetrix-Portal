import asyncio
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from backend.emby_server import api
from backend.emby_server.mounts import PlayTarget
from backend.emby_server.streaming import can_redirect_direct


def test_strm_public_url_can_redirect_without_forwarded_credentials():
    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    assert can_redirect_direct(target) is True


def test_remote_target_with_auth_headers_must_be_proxied():
    target = PlayTarget("url", "https://storage.example/movie.mkv", {
        "Authorization": "Bearer secret",
        "User-Agent": "server",
    })
    assert can_redirect_direct(target) is False


def test_local_file_is_not_a_redirect_target():
    assert can_redirect_direct(PlayTarget("local", "/media/movie.mkv")) is False


def _request(query: str = ""):
    scope = {"type": "http", "method": "GET", "path": "/Videos/item/stream",
             "raw_path": b"/Videos/item/stream", "query_string": query.encode(),
             "headers": [], "scheme": "http", "server": ("testserver", 80),
             "client": ("testclient", 50000), "root_path": ""}
    return Request(scope)


def _stub_gates(monkeypatch):
    """本文件只测「重定向 / 代理」这一层：付费墙与客户端策略各自有自己的用例，

    这里都按放行处理（否则每个用例都要造一个真数据库会话）。
    """
    monkeypatch.setattr(api, "ensure_playback_allowed", lambda db, user: None)
    monkeypatch.setattr(api.playback_policy, "ensure_client_allowed", lambda db, user, ua: None)


def test_video_stream_redirects_safe_url_when_direct_true(monkeypatch):
    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    monkeypatch.setattr(api, "_require_item", lambda db, item_id: SimpleNamespace(container="mp4"))
    _stub_gates(monkeypatch)
    monkeypatch.setattr(api, "_play_target", lambda db, item: target)
    monkeypatch.setattr(api, "serve_remote_async", lambda *args: None)

    response = asyncio.run(api.video_stream("item", _request("direct=true"), object(), object()))

    assert response.status_code == 302
    assert response.headers["location"] == target.value
    assert response.headers["cache-control"] == "no-store"


def test_video_stream_proxies_when_direct_not_requested(monkeypatch):
    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    monkeypatch.setattr(api, "_require_item", lambda db, item_id: SimpleNamespace(container="mp4"))
    _stub_gates(monkeypatch)
    monkeypatch.setattr(api, "_play_target", lambda db, item: target)
    proxy = object()

    async def fake_proxy(url, request, headers, media_type):
        assert (url, headers, media_type) == (target.value, target.headers, "video/mp4")
        return proxy

    monkeypatch.setattr(api, "serve_remote_async", fake_proxy)
    response = asyncio.run(api.video_stream("item", _request(), object(), object()))
    assert response is proxy
