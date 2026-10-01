"""线路选择（play_line）单元测试。

- 纯逻辑用隔离的内存 SQLite，不碰生产库。
- video_stream 决策分支沿用 test_playback_redirect.py 的 monkeypatch 风格。
"""
import asyncio
from types import SimpleNamespace

import pytest

from backend.emby_server.play_line import (
    DEFAULT_LINE,
    LINE_CDN,
    LINE_DIRECT,
    LINE_RELAY,
    PLAY_LINES,
    get_play_line,
    set_play_line,
)


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend import models

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _make_user(db, username):
    from backend import models

    u = models.WebUser(username=username, password_hash="x")
    db.add(u)
    db.commit()
    return u


def test_default_is_direct_without_record(db):
    u = _make_user(db, "u1")
    assert get_play_line(db, u.id) == LINE_DIRECT
    assert DEFAULT_LINE == LINE_DIRECT


def test_set_and_get_relay(db):
    u = _make_user(db, "u2")
    assert set_play_line(db, u.id, LINE_RELAY) == LINE_RELAY
    assert get_play_line(db, u.id) == LINE_RELAY


def test_set_back_to_direct(db):
    u = _make_user(db, "u3")
    set_play_line(db, u.id, LINE_RELAY)
    set_play_line(db, u.id, LINE_DIRECT)
    assert get_play_line(db, u.id) == LINE_DIRECT


def test_set_invalid_raises_and_keeps_default(db):
    u = _make_user(db, "u4")
    with pytest.raises(ValueError):
        set_play_line(db, u.id, "bogus")
    assert get_play_line(db, u.id) == LINE_DIRECT


def test_users_are_independent(db):
    a = _make_user(db, "ua")
    b = _make_user(db, "ub")
    set_play_line(db, a.id, LINE_RELAY)
    assert get_play_line(db, a.id) == LINE_RELAY
    assert get_play_line(db, b.id) == LINE_DIRECT


def test_dirty_value_falls_back_to_default(db):
    from backend import models

    u = _make_user(db, "u5")
    db.add(models.UserPlayLine(user_id=u.id, line="bogus"))
    db.commit()
    assert get_play_line(db, u.id) == LINE_DIRECT


def test_broken_db_or_no_user_id_falls_back_to_default(db):
    # user_id 为空 / db 异常时不能炸，播放要按默认 direct 走
    assert get_play_line(db, None) == LINE_DIRECT

    class BrokenDB:
        def query(self, *a, **k):
            raise RuntimeError("db down")

    assert get_play_line(BrokenDB(), 1) == LINE_DIRECT


def test_play_lines_contract():
    # cdn 是播放三层第 2/3 层的预留线路：direct（默认）/ cdn / relay
    assert set(PLAY_LINES) == {"direct", "cdn", "relay"}
    assert DEFAULT_LINE == LINE_DIRECT


def test_set_and_get_cdn(db):
    u = _make_user(db, "ucdn")
    assert set_play_line(db, u.id, LINE_CDN) == LINE_CDN
    assert get_play_line(db, u.id) == LINE_CDN


# ---- video_stream 决策分支 ----

def _request(query: str = ""):
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/Videos/item/stream",
             "raw_path": b"/Videos/item/stream", "query_string": query.encode(),
             "headers": [], "scheme": "http", "server": ("testserver", 80),
             "client": ("testclient", 50000), "root_path": ""}
    return Request(scope)


def _stub_common(monkeypatch, api, target):
    monkeypatch.setattr(api, "_require_item",
                        lambda db, item_id: SimpleNamespace(container="mp4"))
    monkeypatch.setattr(api, "ensure_playback_allowed", lambda db, user: None)
    monkeypatch.setattr(api.playback_policy, "ensure_client_allowed",
                        lambda db, user, ua: None)
    monkeypatch.setattr(api, "_play_target", lambda db, item: target)


def test_video_stream_relay_skips_google_302(monkeypatch):
    """relay 线路：跳过 try_google_direct_url，直接走服务器代理。"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_RELAY)

    async def boom(*a, **k):
        raise AssertionError("relay 线路不该调 try_google_direct_url")

    monkeypatch.setattr(api, "try_google_direct_url", boom)
    proxy = object()

    async def fake_proxy(url, request, headers, media_type, cache_control=None):
        assert (url, headers, media_type) == (target.value, target.headers, "video/mp4")
        # relay 也是分片响应：带上可缓存头，让 CDN 边缘缓存回源结果
        from backend.emby_server import cdn as cdn_mod
        assert cache_control == cdn_mod.SEGMENT_CACHE_HEADER
        return proxy

    monkeypatch.setattr(api, "serve_remote_async", fake_proxy)
    user = SimpleNamespace(id=7)
    resp = asyncio.run(api.video_stream("item", _request(), user, object()))
    assert resp is proxy


def test_video_stream_direct_keeps_google_302(monkeypatch):
    """direct 线路：保持现有行为，Google 直链成功则 302。"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_DIRECT)

    async def fake_google(url):
        assert url == target.value
        return "https://www.googleapis.com/drive/v3/files/x?alt=media"

    monkeypatch.setattr(api, "try_google_direct_url", fake_google)
    user = SimpleNamespace(id=7)
    resp = asyncio.run(api.video_stream("item", _request(), user, object()))
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://www.googleapis.com/")
    assert resp.headers["cache-control"] == "no-store"


def test_video_stream_cdn_line_keeps_google_302(monkeypatch):
    """cdn 线路：与 direct 同口径（Google 直链 302 保留，CDN 只挡回源）。"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CDN)

    async def fake_google(url):
        assert url == target.value
        return "https://www.googleapis.com/drive/v3/files/x?alt=media"

    monkeypatch.setattr(api, "try_google_direct_url", fake_google)
    user = SimpleNamespace(id=7)
    resp = asyncio.run(api.video_stream("item", _request(), user, object()))
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://www.googleapis.com/")
    assert resp.headers["cache-control"] == "no-store"


def test_video_stream_relay_local_kind_unchanged(monkeypatch):
    """relay 线路只影响 kind=url；本地文件照走 serve_file。"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("local", "/media/movie.mp4", {})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_RELAY)
    sentinel = object()

    def fake_serve_file(path, request, media_type, cache_control=None):
        from backend.emby_server import cdn as cdn_mod
        assert path == target.value
        # 本机文件也是分片形态：带可缓存头
        assert cache_control == cdn_mod.SEGMENT_CACHE_HEADER
        return sentinel

    monkeypatch.setattr(api, "serve_file", fake_serve_file)
    user = SimpleNamespace(id=7)
    resp = asyncio.run(api.video_stream("item", _request(), user, object()))
    assert resp is sentinel
