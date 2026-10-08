"""播放路径（play_line）单元测试（2026-10 简化版）。

只有一条播放路径：中转。本模块保留仅为兼容历史数据与老客户端。
- 纯逻辑用隔离的内存 SQLite，不碰生产库。
"""
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


def test_default_is_relay(db):
    u = _make_user(db, "u1")
    assert get_play_line(db, u.id) == LINE_RELAY
    assert DEFAULT_LINE == LINE_RELAY


def test_set_is_noop_always_relay(db):
    u = _make_user(db, "u2")
    assert set_play_line(db, u.id, LINE_RELAY) == LINE_RELAY
    assert set_play_line(db, u.id, LINE_CDN) == LINE_RELAY
    assert set_play_line(db, u.id, LINE_CACHE) == LINE_RELAY
    assert get_play_line(db, u.id) == LINE_RELAY


def test_legacy_values_normalize_to_relay(db):
    """老用户库里存着 direct/cdn/cache：读出来都是 relay"""
    from backend import models

    for i, old in enumerate([LINE_DIRECT, LINE_CDN, LINE_CACHE]):
        u = _make_user(db, f"u3_{i}")
        db.add(models.UserPlayLine(user_id=u.id, line=old))
        db.commit()
        assert get_play_line(db, u.id) == LINE_RELAY


def test_normalize_maps_everything_to_relay():
    assert normalize(LINE_DIRECT) == LINE_RELAY
    assert normalize(LINE_CDN) == LINE_RELAY
    assert normalize(LINE_CACHE) == LINE_RELAY
    assert normalize("DIRECT") == LINE_RELAY
    assert normalize("  relay ") == LINE_RELAY
    assert normalize(None) is None
    assert normalize("bogus") is None


def test_play_lines_only_has_relay():
    assert PLAY_LINES == (LINE_RELAY,)
