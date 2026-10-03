"""线路选择（play_line）单元测试。

- 纯逻辑用隔离的内存 SQLite，不碰生产库。
- video_stream 决策分支沿用 test_playback_redirect.py 的 monkeypatch 风格。
- 302 直连已下线：这里的重点是“老用户存的 direct 会被迁成 relay”，
  以及任何线路都不会再把播放 302 到 Google。
"""
import asyncio
from types import SimpleNamespace

import pytest

from backend.emby_server.play_line import (
    DEFAULT_LINE,
    LINE_CACHE,
    LINE_CDN,
    LINE_DIRECT,
    LINE_RELAY,
    PLAY_LINES,
    get_play_line,
    normalize,
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


def test_default_is_relay_without_record(db):
    u = _make_user(db, "u1")
    assert get_play_line(db, u.id) == LINE_RELAY
    assert DEFAULT_LINE == LINE_RELAY


def test_set_and_get_relay(db):
    u = _make_user(db, "u2")
    assert set_play_line(db, u.id, LINE_RELAY) == LINE_RELAY
    assert get_play_line(db, u.id) == LINE_RELAY


def test_legacy_direct_pref_is_read_as_relay(db):
    """老用户库里存着 direct：读出来就是 relay（用户看不到失效选项）"""
    from backend import models

    u = _make_user(db, "u3")
    db.add(models.UserPlayLine(user_id=u.id, line=LINE_DIRECT))
    db.commit()
    assert get_play_line(db, u.id) == LINE_RELAY


def test_setting_direct_migrates_the_stored_row(db):
    """老客户端重发 direct：不报错，库里那条老记录顺手迁成 relay"""
    from backend import models

    u = _make_user(db, "u3b")
    db.add(models.UserPlayLine(user_id=u.id, line=LINE_DIRECT))
    db.commit()
    assert set_play_line(db, u.id, LINE_DIRECT) == LINE_RELAY
    assert db.query(models.UserPlayLine).filter(
        models.UserPlayLine.user_id == u.id).first().line == LINE_RELAY


def test_normalize_maps_legacy_and_rejects_unknown():
    assert normalize(LINE_DIRECT) == LINE_RELAY
    assert normalize("DIRECT") == LINE_RELAY          # 大小写 / 空白都归一
    assert normalize("  relay ") == LINE_RELAY
    assert normalize(None) is None
    assert normalize("bogus") is None


def test_set_invalid_raises_and_keeps_default(db):
    u = _make_user(db, "u4")
    with pytest.raises(ValueError):
        set_play_line(db, u.id, "bogus")
    assert get_play_line(db, u.id) == LINE_RELAY


def test_users_are_independent(db):
    a = _make_user(db, "ua")
    b = _make_user(db, "ub")
    set_play_line(db, a.id, LINE_CDN)
    assert get_play_line(db, a.id) == LINE_CDN
    assert get_play_line(db, b.id) == LINE_RELAY


def test_dirty_value_falls_back_to_default(db):
    from backend import models

    u = _make_user(db, "u5")
    db.add(models.UserPlayLine(user_id=u.id, line="bogus"))
    db.commit()
    assert get_play_line(db, u.id) == LINE_RELAY


def test_broken_db_or_no_user_id_falls_back_to_default(db):
    # user_id 为空 / db 异常时不能炸，播放要按默认 relay 走
    assert get_play_line(db, None) == LINE_RELAY

    class BrokenDB:
        def query(self, *a, **k):
            raise RuntimeError("db down")

    assert get_play_line(BrokenDB(), 1) == LINE_RELAY


def test_play_lines_contract():
    # cdn（边缘缓存预留）/ cache（VPS 本地缓存）/ relay（中转，默认）
    # direct 已下线：常量还在（历史数据/统计认它），但不再是可选项
    assert set(PLAY_LINES) == {"cdn", "cache", "relay"}
    assert LINE_DIRECT not in PLAY_LINES
    assert DEFAULT_LINE == LINE_RELAY


def test_set_and_get_cdn(db):
    u = _make_user(db, "ucdn")
    assert set_play_line(db, u.id, LINE_CDN) == LINE_CDN
    assert get_play_line(db, u.id) == LINE_CDN


def test_set_and_get_cache_line(db):
    """本地缓存线路可持久化（选择与读取与其它线路同口径）"""
    u = _make_user(db, "ucache")
    assert set_play_line(db, u.id, LINE_CACHE) == LINE_CACHE
    assert get_play_line(db, u.id) == LINE_CACHE


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


def test_video_stream_relay_proxies_without_google_302(monkeypatch):
    """relay 线路（默认）：走服务器代理，且播放层压根不再持有 Google 直链入口。"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_RELAY)

    assert not hasattr(api, "try_google_direct_url"), (
        "302 直链下线后，播放模块不应再导入 try_google_direct_url")
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


def test_video_stream_never_302s_to_google(monkeypatch):
    """无论哪条线路都不再 302 到 Drive。

    直链可行的话这里会返回一个 302；现在必须走代理。
    """
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CDN)
    proxy = object()

    async def fake_proxy(*a, **k):
        return proxy

    monkeypatch.setattr(api, "serve_remote_async", fake_proxy)
    resp = asyncio.run(api.video_stream("item", _request(), SimpleNamespace(id=7), object()))
    assert resp is proxy


def test_video_stream_cdn_line_proxies(monkeypatch):
    """cdn 线路：与 relay 同口径（服务端代理），CDN 只挡回源流量。"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CDN)
    proxy = object()

    async def fake_proxy(url, request, headers, media_type, cache_control=None):
        assert (url, headers, media_type) == (target.value, target.headers, "video/mp4")
        from backend.emby_server import cdn as cdn_mod
        assert cache_control == cdn_mod.SEGMENT_CACHE_HEADER
        return proxy

    monkeypatch.setattr(api, "serve_remote_async", fake_proxy)
    resp = asyncio.run(api.video_stream("item", _request(), SimpleNamespace(id=7), object()))
    assert resp is proxy


def test_video_stream_cache_line_hit_serves_local_file(monkeypatch):
    """cache 线路命中本机副本：直接 serve_file（不回源、不入队）。"""
    from backend.emby_server import api, local_cache
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CACHE)
    monkeypatch.setattr(local_cache, "lookup", lambda db, item: "/cache/abc123.mkv")

    def boom_enqueue(*a, **k):
        raise AssertionError("命中时不该再入队")

    monkeypatch.setattr(local_cache, "enqueue", boom_enqueue)
    sentinel = object()

    def fake_serve_file(path, request, media_type, cache_control=None):
        assert path == "/cache/abc123.mkv"
        assert media_type == "video/mp4"
        from backend.emby_server import cdn as cdn_mod
        assert cache_control == cdn_mod.SEGMENT_CACHE_HEADER
        return sentinel

    monkeypatch.setattr(api, "serve_file", fake_serve_file)
    resp = asyncio.run(api.video_stream("item", _request(), SimpleNamespace(id=7), object()))
    assert resp is sentinel


def test_video_stream_cache_line_miss_falls_back_to_source(monkeypatch):
    """cache 线路未命中：回源走代理，并高优先级入队缓存。"""
    from backend.emby_server import api, local_cache
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CACHE)
    monkeypatch.setattr(local_cache, "lookup", lambda db, item: None)
    enqueued = []
    monkeypatch.setattr(local_cache, "enqueue",
                        lambda db, item, priority=0: enqueued.append(priority) or None)
    proxy = object()

    async def fake_proxy(url, request, headers, media_type, cache_control=None):
        return proxy

    monkeypatch.setattr(api, "serve_remote_async", fake_proxy)
    resp = asyncio.run(api.video_stream("item", _request(), SimpleNamespace(id=7), object()))
    assert resp is proxy
    assert enqueued == [local_cache.PLAY_PRIORITY]


def test_video_stream_cache_line_disabled_is_plain_relay(monkeypatch):
    """本地缓存未启用：lookup/enqueue 都是空操作，行为与 relay 一模一样。"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    target = PlayTarget("url", "https://cdn.example/movie.mkv", {"User-Agent": "server"})
    _stub_common(monkeypatch, api, target)
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CACHE)
    proxy = object()

    async def fake_proxy(url, request, headers, media_type, cache_control=None):
        return proxy

    monkeypatch.setattr(api, "serve_remote_async", fake_proxy)
    resp = asyncio.run(api.video_stream("item", _request(), SimpleNamespace(id=7), object()))
    assert resp is proxy


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
