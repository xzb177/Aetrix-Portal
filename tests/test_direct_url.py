"""Google Drive 直链 302 的单元测试。

全部用 mock / 临时文件，不碰真实 rclone、不碰真实 Google API、
不写任何真实密码或 token。
"""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.emby_server import direct_url
from backend.emby_server.direct_url import (
    build_direct_url,
    direct_url_enabled,
    get_access_token,
    get_direct_url,
    get_file_id,
    parse_rclone_url,
    try_google_direct_url,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """token 缓存与直链缓存都是进程级的，每个测试前清空，避免相互污染。"""
    direct_url._token_cache.clear()
    direct_url._url_cache.clear()
    yield
    direct_url._token_cache.clear()
    direct_url._url_cache.clear()


# ---------------- parse_rclone_url ----------------

def test_parse_rclone_url_decodes_path():
    url = ("http://rclone:5572/[paul_emby:]/video/"
           "%E5%89%A7%E9%9B%86/%E8%8B%B1%E7%BE%8E%E5%89%A7/file.mkv")
    assert parse_rclone_url(url) == ("paul_emby:", "video/剧集/英美剧/file.mkv")


def test_parse_rclone_url_fullwidth_chars():
    url = "http://rclone:5572/[paul_emby:]/video/%E6%97%A5%E9%9F%A9%E5%89%A7/D.P%EF%BC%9A%E9%80%83.mkv"
    fs, path = parse_rclone_url(url)
    assert fs == "paul_emby:"
    assert path == "video/日韩剧/D.P：逃.mkv"


def test_parse_rclone_url_rejects_non_rclone():
    assert parse_rclone_url("https://cdn.example/movie.mkv") is None
    assert parse_rclone_url("http://rclone:5572/video/no-brackets.mkv") is None
    assert parse_rclone_url("") is None
    assert parse_rclone_url(None) is None


def test_parse_rclone_url_strips_query():
    url = "http://rclone:5572/[paul_emby:]/video/a.mkv?foo=bar"
    assert parse_rclone_url(url) == ("paul_emby:", "video/a.mkv")


# ---------------- build_direct_url ----------------

def test_build_direct_url_format():
    url = build_direct_url("FILEID123", "TOKEN456")
    assert url == "https://www.googleapis.com/drive/v3/files/FILEID123?alt=media&access_token=TOKEN456"


# ---------------- direct_url_enabled ----------------

def test_direct_url_enabled_default_true(monkeypatch):
    monkeypatch.delenv("ENABLE_DIRECT_URL", raising=False)
    assert direct_url_enabled() is True


@pytest.mark.parametrize("val", ["false", "0", "no", "off", "FALSE"])
def test_direct_url_enabled_false_values(monkeypatch, val):
    monkeypatch.setenv("ENABLE_DIRECT_URL", val)
    assert direct_url_enabled() is False


@pytest.mark.parametrize("val", ["true", "1", "yes", ""])
def test_direct_url_enabled_true_values(monkeypatch, val):
    monkeypatch.setenv("ENABLE_DIRECT_URL", val)
    assert direct_url_enabled() is True


# ---------------- get_file_id（mock httpx） ----------------

class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """替代 httpx.AsyncClient 的最小 fake，支持 async 上下文协议。"""

    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return self._handler(url, kwargs)


def _patch_async_client(monkeypatch, handler):
    monkeypatch.setattr(
        direct_url.httpx, "AsyncClient", lambda **kwargs: _FakeClient(handler)
    )


def _rc_env(monkeypatch):
    monkeypatch.setenv("RCLONE_RC_URL", "http://rclone:5572")
    monkeypatch.setenv("RCLONE_RC_USER", "testuser")
    monkeypatch.setenv("RCLONE_RC_PASS", "testpass")


def test_get_file_id_success(monkeypatch):
    _rc_env(monkeypatch)

    def handler(url, kwargs):
        assert url == "http://rclone:5572/operations/stat"
        assert kwargs["json"] == {"fs": "paul_emby:", "remote": "video/a.mkv"}
        return _FakeResp(200, {"item": {"ID": "FILEID123", "Name": "a.mkv"}})

    _patch_async_client(monkeypatch, handler)
    assert run(get_file_id("paul_emby:", "video/a.mkv")) == "FILEID123"


def test_get_file_id_stat_404_returns_none(monkeypatch):
    _rc_env(monkeypatch)
    _patch_async_client(monkeypatch, lambda url, kwargs: _FakeResp(404))
    assert run(get_file_id("paul_emby:", "video/missing.mkv")) is None


def test_get_file_id_no_item_id_returns_none(monkeypatch):
    _rc_env(monkeypatch)
    _patch_async_client(monkeypatch, lambda url, kwargs: _FakeResp(200, {"item": {}}))
    assert run(get_file_id("paul_emby:", "video/a.mkv")) is None


def test_get_file_id_network_error_returns_none(monkeypatch):
    _rc_env(monkeypatch)

    def handler(url, kwargs):
        raise ConnectionError("boom")

    _patch_async_client(monkeypatch, handler)
    assert run(get_file_id("paul_emby:", "video/a.mkv")) is None


def test_get_file_id_missing_rc_credentials_returns_none(monkeypatch):
    monkeypatch.delenv("RCLONE_RC_USER", raising=False)
    monkeypatch.delenv("RCLONE_RC_PASS", raising=False)
    # 不应发起任何请求：handler 若被调用直接抛错
    def handler(url, kwargs):
        raise AssertionError("should not be called")

    _patch_async_client(monkeypatch, handler)
    assert run(get_file_id("paul_emby:", "video/a.mkv")) is None


# ---------------- get_access_token（临时 rclone.conf） ----------------

def _write_conf(tmp_path, token_dict, client_id="cid", client_secret="csec", remote="paul_emby"):
    conf = (
        f"[{remote}]\n"
        f"type = drive\n"
        f"client_id = {client_id}\n"
        f"client_secret = {client_secret}\n"
        f"scope = drive\n"
        f"token = {json.dumps(token_dict)}\n"
    )
    p = tmp_path / "rclone.conf"
    p.write_text(conf, encoding="utf-8")
    return str(p)


def _future_expiry():
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _past_expiry():
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def test_get_access_token_valid_cached_token(monkeypatch, tmp_path):
    token = {"access_token": "VALID123", "refresh_token": "r",
             "expiry": _future_expiry()}
    monkeypatch.setenv("RCLONE_CONF_PATH", _write_conf(tmp_path, token))
    # token 有效时不应触发刷新：fake client 若被调用就抛错
    def handler(url, kwargs):
        raise AssertionError("refresh should not be called")

    _patch_async_client(monkeypatch, handler)
    assert run(get_access_token("paul_emby:")) == "VALID123"


def test_get_access_token_expired_refreshes(monkeypatch, tmp_path):
    token = {"access_token": "OLD", "refresh_token": "REFRESH1",
             "expiry": _past_expiry()}
    monkeypatch.setenv("RCLONE_CONF_PATH", _write_conf(tmp_path, token))

    def handler(url, kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        assert kwargs["data"]["refresh_token"] == "REFRESH1"
        assert kwargs["data"]["grant_type"] == "refresh_token"
        return _FakeResp(200, {"access_token": "NEW456", "expires_in": 3600})

    _patch_async_client(monkeypatch, handler)
    assert run(get_access_token("paul_emby:")) == "NEW456"


def test_get_access_token_refresh_failure_returns_none(monkeypatch, tmp_path):
    token = {"access_token": "OLD", "refresh_token": "REFRESH1",
             "expiry": _past_expiry()}
    monkeypatch.setenv("RCLONE_CONF_PATH", _write_conf(tmp_path, token))
    _patch_async_client(monkeypatch, lambda url, kwargs: _FakeResp(400))
    assert run(get_access_token("paul_emby:")) is None


def test_get_access_token_missing_conf_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("RCLONE_CONF_PATH", str(tmp_path / "nope.conf"))
    assert run(get_access_token("paul_emby:")) is None


def test_get_access_token_wrong_section_returns_none(monkeypatch, tmp_path):
    token = {"access_token": "VALID123", "refresh_token": "r",
             "expiry": _future_expiry()}
    monkeypatch.setenv("RCLONE_CONF_PATH", _write_conf(tmp_path, token, remote="other"))
    assert run(get_access_token("paul_emby:")) is None


# ---------------- get_direct_url / try_google_direct_url ----------------

def test_get_direct_url_combines_all_steps(monkeypatch):
    monkeypatch.setattr(direct_url, "get_file_id",
                        lambda fs, path: _coro("FILEID123"))
    monkeypatch.setattr(direct_url, "get_access_token",
                        lambda fs: _coro("TOKEN456"))
    url = run(get_direct_url("paul_emby:", "video/a.mkv"))
    assert url == ("https://www.googleapis.com/drive/v3/files/FILEID123"
                   "?alt=media&access_token=TOKEN456")


def _coro(value):
    async def _inner():
        return value
    return _inner()


def test_get_direct_url_file_id_failure_returns_none(monkeypatch):
    monkeypatch.setattr(direct_url, "get_file_id", lambda fs, path: _coro(None))
    monkeypatch.setattr(direct_url, "get_access_token", lambda fs: _coro("TOKEN456"))
    assert run(get_direct_url("paul_emby:", "video/a.mkv")) is None


def test_get_direct_url_token_failure_returns_none(monkeypatch):
    monkeypatch.setattr(direct_url, "get_file_id", lambda fs, path: _coro("FILEID123"))
    monkeypatch.setattr(direct_url, "get_access_token", lambda fs: _coro(None))
    assert run(get_direct_url("paul_emby:", "video/a.mkv")) is None


def test_try_google_direct_url_non_rclone_returns_none(monkeypatch):
    # 非 rclone URL 直接返回 None，不应调 get_direct_url
    def _boom(fs, path):
        raise AssertionError("should not be called")

    monkeypatch.setattr(direct_url, "get_direct_url", _boom)
    assert run(try_google_direct_url("https://cdn.example/movie.mkv")) is None


def test_try_google_direct_url_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("ENABLE_DIRECT_URL", "false")

    def _boom(fs, path):
        raise AssertionError("should not be called")

    monkeypatch.setattr(direct_url, "get_direct_url", _boom)
    url = "http://rclone:5572/[paul_emby:]/video/a.mkv"
    assert run(try_google_direct_url(url)) is None


def test_try_google_direct_url_success(monkeypatch):
    async def _fake(fs, path):
        assert fs == "paul_emby:"
        assert path == "video/a.mkv"
        return "https://www.googleapis.com/drive/v3/files/X?alt=media&access_token=Y"

    monkeypatch.setattr(direct_url, "get_direct_url", _fake)
    url = "http://rclone:5572/[paul_emby:]/video/a.mkv"
    assert run(try_google_direct_url(url)).startswith("https://www.googleapis.com/")


def test_try_google_direct_url_exception_returns_none(monkeypatch):
    async def _boom(fs, path):
        raise RuntimeError("boom")

    monkeypatch.setattr(direct_url, "get_direct_url", _boom)
    url = "http://rclone:5572/[paul_emby:]/video/a.mkv"
    assert run(try_google_direct_url(url)) is None


# ---------------- video_stream 集成 ----------------
# 只测「直链 302 / 回退代理」这一层：鉴权与客户端策略按放行处理。

def _video_stream_request():
    from starlette.requests import Request
    scope = {"type": "http", "method": "GET", "path": "/Videos/item/stream",
             "raw_path": b"/Videos/item/stream", "query_string": b"",
             "headers": [], "scheme": "http", "server": ("testserver", 80),
             "client": ("testclient", 50000), "root_path": ""}
    return Request(scope)


def _stub_video_stream(monkeypatch, target):
    from types import SimpleNamespace
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget  # noqa: F401
    monkeypatch.setattr(api, "_require_item",
                        lambda db, item_id: SimpleNamespace(container="mkv"))
    monkeypatch.setattr(api, "ensure_playback_allowed", lambda db, user: None)
    monkeypatch.setattr(api.playback_policy, "ensure_client_allowed",
                        lambda db, user, ua: None)
    monkeypatch.setattr(api, "_play_target", lambda db, item: target)
    return api


def test_video_stream_uses_google_direct_url_when_available(monkeypatch):
    pytest.importorskip("starlette")
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget
    target = PlayTarget("url", "http://rclone:5572/[paul_emby:]/video/a.mkv",
                        {"Authorization": "Basic xyz"})
    _stub_video_stream(monkeypatch, target)

    async def _fake_direct(url):
        assert url == target.value
        return "https://www.googleapis.com/drive/v3/files/X?alt=media&access_token=Y"

    monkeypatch.setattr(api, "try_google_direct_url", _fake_direct)

    def _boom(*args, **kwargs):
        raise AssertionError("proxy should not be called when direct url works")

    monkeypatch.setattr(api, "serve_remote_async", _boom)
    response = run(api.video_stream("item", _video_stream_request(), object(), object()))
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://www.googleapis.com/")
    assert response.headers["cache-control"] == "no-store"


def test_video_stream_falls_back_to_proxy_when_no_direct_url(monkeypatch):
    pytest.importorskip("starlette")
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget
    target = PlayTarget("url", "http://rclone:5572/[paul_emby:]/video/a.mkv",
                        {"Authorization": "Basic xyz"})
    _stub_video_stream(monkeypatch, target)

    async def _fake_none(url):
        return None

    monkeypatch.setattr(api, "try_google_direct_url", _fake_none)
    proxy = object()

    async def fake_proxy(url, request, headers, media_type, cache_control=None):
        assert (url, headers, media_type) == (target.value, target.headers, "video/mkv")
        # 分片响应带可缓存头（CDN 边缘缓存用）
        assert cache_control == "public, max-age=300, s-maxage=21600"
        return proxy

    monkeypatch.setattr(api, "serve_remote_async", fake_proxy)
    response = run(api.video_stream("item", _video_stream_request(), object(), object()))
    assert response is proxy


# ---------------- 直链缓存（DIRECT_URL_CACHE_TTL）----------------

def test_get_direct_url_caches_success(monkeypatch):
    """同一个路径连续两次请求，只应该 stat 一次。"""
    calls = []

    async def _file_id(fs, path):
        calls.append((fs, path))
        return "FILEID123"

    monkeypatch.setattr(direct_url, "get_file_id", _file_id)
    monkeypatch.setattr(direct_url, "get_access_token", lambda fs: _coro("TOKEN456"))

    first = run(get_direct_url("paul_emby:", "video/a.mkv"))
    second = run(get_direct_url("paul_emby:", "video/a.mkv"))
    assert first == second
    assert first == ("https://www.googleapis.com/drive/v3/files/FILEID123"
                     "?alt=media&access_token=TOKEN456")
    assert len(calls) == 1, f"第二次应命中缓存，实际 stat 了 {len(calls)} 次"


def test_get_direct_url_caches_failure(monkeypatch):
    """失败也要缓存：否则播放器一路 seek 就会刷一屏 warning。"""
    calls = []

    async def _file_id(fs, path):
        calls.append(path)
        return None

    monkeypatch.setattr(direct_url, "get_file_id", _file_id)
    assert run(get_direct_url("MP:", "video/a.mkv")) is None
    assert run(get_direct_url("MP:", "video/a.mkv")) is None
    assert len(calls) == 1, "失败结果没有进缓存，仍在重复 stat"


def test_get_direct_url_cache_key_includes_path(monkeypatch):
    """不同路径不能共用同一条缓存。"""
    seen = []

    async def _file_id(fs, path):
        seen.append(path)
        return "ID_" + path.split("/")[-1]

    monkeypatch.setattr(direct_url, "get_file_id", _file_id)
    monkeypatch.setattr(direct_url, "get_access_token", lambda fs: _coro("T"))
    run(get_direct_url("paul_emby:", "video/a.mkv"))
    run(get_direct_url("paul_emby:", "video/b.mkv"))
    assert seen == ["video/a.mkv", "video/b.mkv"]


def test_get_direct_url_cache_ttl_zero_disables(monkeypatch):
    """TTL 设为 0 时缓存关闭，每次都重新解析。"""
    monkeypatch.setenv("DIRECT_URL_CACHE_TTL", "0")
    calls = []

    async def _file_id(fs, path):
        calls.append(path)
        return "ID"

    monkeypatch.setattr(direct_url, "get_file_id", _file_id)
    monkeypatch.setattr(direct_url, "get_access_token", lambda fs: _coro("T"))
    run(get_direct_url("paul_emby:", "video/a.mkv"))
    run(get_direct_url("paul_emby:", "video/a.mkv"))
    assert len(calls) == 2, "TTL=0 时不应该缓存"


def test_get_direct_url_cache_expires(monkeypatch):
    """TTL 到期后重新解析。"""
    monkeypatch.setenv("DIRECT_URL_CACHE_TTL", "0.05")
    calls = []

    async def _file_id(fs, path):
        calls.append(path)
        return "ID"

    monkeypatch.setattr(direct_url, "get_file_id", _file_id)
    monkeypatch.setattr(direct_url, "get_access_token", lambda fs: _coro("T"))
    run(get_direct_url("paul_emby:", "video/a.mkv"))
    time.sleep(0.12)
    run(get_direct_url("paul_emby:", "video/a.mkv"))
    assert len(calls) == 2, "TTL 到期后应重新 stat"


def test_get_direct_url_cache_bounded(monkeypatch):
    """缓存表有上限，不会被大量不同路径撑爆。"""
    monkeypatch.setattr(direct_url, "get_file_id",
                        lambda fs, path: _coro("ID_" + path))
    monkeypatch.setattr(direct_url, "get_access_token", lambda fs: _coro("T"))
    for i in range(direct_url._URL_CACHE_MAX + 50):
        run(get_direct_url("paul_emby:", f"video/{i}.mkv"))
    assert len(direct_url._url_cache) <= direct_url._URL_CACHE_MAX
