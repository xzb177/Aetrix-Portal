"""门户首页「继续观看」（/api/user/emby/resume）回归测试。

口径（2026-10 首页加「继续观看」区块）：
- 有进度、未播完；电影一行，单集按剧聚合（每部剧只留最近在看的那一集）；
- 隐藏条目不出；
- 每行带最近一次播放会话的客户端 / 设备，整页一次批量查询，不随条数增长。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from backend.database import SessionLocal, engine, init_db
from backend.emby_server import models as em
from backend.emby_server import portal
from backend.models import WebUser

init_db()

T = 10_000_000  # 1 秒的 ticks
BASE = datetime(2026, 10, 9, 20, 0, 0)


def _guid():
    return uuid.uuid4().hex


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


class _Seed:
    def __init__(self, db):
        self.db = db
        self.u = WebUser(username="resume_" + _guid()[:8], password_hash="x")
        db.add(self.u)
        db.flush()
        self.lib = em.Library(guid=_guid(), name="续看测试库", collection_type="mixed")
        db.add(self.lib)
        db.flush()

    def item(self, item_type, name, **kw):
        it = em.MediaItem(guid=_guid(), library_id=self.lib.id, item_type=item_type, name=name, **kw)
        self.db.add(it)
        self.db.flush()
        return it

    def progress(self, item, pos, minutes_ago, played=False):
        self.db.add(em.UserMediaData(
            user_id=self.u.id, item_id=item.id, playback_position_ticks=pos, played=played,
            last_played_at=BASE - timedelta(minutes=minutes_ago)))
        self.db.flush()

    def session(self, item, minutes_ago, client, device):
        self.db.add(em.PlaybackSession(
            session_key=_guid(), user_id=self.u.id, item_id=item.id,
            client_name=client, device_name=device,
            last_update_at=BASE - timedelta(minutes=minutes_ago)))
        self.db.flush()


@pytest.fixture()
def seed(db):
    s = _Seed(db)
    series = s.item("series", "续看测试剧", production_year=2025, tmdb_id="1399")
    e1 = s.item("episode", "第一集", series_id=series.id, season_number=1, episode_number=1,
                duration_ticks=2400 * T)
    e2 = s.item("episode", "第二集", series_id=series.id, season_number=1, episode_number=2,
                duration_ticks=2400 * T)
    movie = s.item("movie", "续看测试电影", duration_ticks=6000 * T, tmdb_id="27205")
    done = s.item("movie", "已看完的电影", duration_ticks=6000 * T)
    hidden = s.item("movie", "隐藏电影", duration_ticks=6000 * T, is_hidden=True)

    s.progress(e1, 600 * T, minutes_ago=300)
    s.progress(e2, 1488 * T, minutes_ago=5)        # 最近：剧的第 2 集，62%
    s.progress(movie, 1500 * T, minutes_ago=60)    # 电影 25%
    s.progress(done, 3000 * T, minutes_ago=1, played=True)
    s.progress(hidden, 3000 * T, minutes_ago=2)

    s.session(e2, 400, "Forward", "iPad")          # 更早的一次会话
    s.session(e2, 5, "Infuse", "iPhone")           # 最近一次会话
    s.session(movie, 60, "SenPlayer", "Apple TV")
    db.commit()
    return {"s": s, "series": series, "e1": e1, "e2": e2, "movie": movie}


def _resume(db, seed, limit=12):
    return portal.get_resume_list(seed["s"].u, db, limit=limit)["items"]


def test_episodes_aggregate_to_series_newest_first(db, seed):
    items = _resume(db, seed)
    assert [i["type"] for i in items] == ["series", "movie"]
    row = items[0]
    assert row["id"] == seed["series"].guid
    assert row["name"] == "续看测试剧"
    assert row["episode_id"] == seed["e2"].guid
    assert row["season_number"] == 1 and row["episode_number"] == 2
    assert row["progress"] == 62.0
    assert row["tmdb_id"] == "1399"


def test_rows_carry_latest_session_client_and_device(db, seed):
    items = _resume(db, seed)
    series_row, movie_row = items
    assert (series_row["client"], series_row["device"]) == ("Infuse", "iPhone")
    assert (movie_row["client"], movie_row["device"]) == ("SenPlayer", "Apple TV")
    assert "episode_id" not in movie_row


def test_played_and_hidden_items_excluded(db, seed):
    names = {i["name"] for i in _resume(db, seed)}
    assert "已看完的电影" not in names
    assert "隐藏电影" not in names


def test_no_session_means_no_client_line(db, seed):
    s = seed["s"]
    m = s.item("movie", "没有会话的电影", duration_ticks=6000 * T)
    s.progress(m, 600 * T, minutes_ago=0)
    db.commit()
    row = _resume(db, seed)[0]
    assert row["name"] == "没有会话的电影"
    assert row["client"] is None and row["device"] is None


def test_limit_applies_after_aggregation(db, seed):
    items = _resume(db, seed, limit=1)
    assert len(items) == 1 and items[0]["type"] == "series"


def test_query_count_does_not_grow_with_rows(db, seed):
    """批量取会话：多加几部在看的电影，查询条数不变（没有 N+1）"""
    counter = {"n": 0}

    def _count(*_a, **_k):
        counter["n"] += 1

    def run():
        db.expire_all()
        counter["n"] = 0
        event.listen(engine, "before_cursor_execute", _count)
        try:
            _resume(db, seed)
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        return counter["n"]

    before = run()
    s = seed["s"]
    for k in range(5):
        m = s.item("movie", f"加片{k}", duration_ticks=6000 * T)
        s.progress(m, 600 * T, minutes_ago=100 + k)
        s.session(m, 100 + k, "Infuse", "iPhone")
    db.commit()
    assert run() == before
