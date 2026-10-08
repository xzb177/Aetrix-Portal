"""P2：/Items 去重下推 SQL 之后，结果必须与旧的全量 Python 去重逐条一致。

独立 SQLite 库，种子里刻意放各种重复：
- 同 tmdb（含首尾空白）的电影、跨库同 tmdb（不算重复）
- 无 tmdb、标题只差全角/大小写/标点的电影（归一化后相同）、同名不同年（不算）
- 同 tmdb 的两条 series（集要跨剧合并）、无 tmdb 同名 series
- 同剧同季同集的多份文件、series_id 为空的集、季号/集号为空的集
- 大量同名并列行（检验分页稳定）
- 收藏只打在「非主」版本上（筛选后它自己就是主）

对照基准 = 同一请求强制走旧实现（``_dedup_dropped_ids`` 返回 None）。
"""
import os
import random
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend import models  # noqa: F401  注册全部表
from backend.database import Base
from backend.emby_server import api
from backend.emby_server import models as em


def _g():
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    path = tmp_path_factory.mktemp("dedup") / "items.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    rnd = random.Random(7)
    t0 = datetime(2026, 1, 1)

    libm = em.Library(guid=_g(), name="电影", collection_type="movies", is_enabled=True)
    libm2 = em.Library(guid=_g(), name="电影2", collection_type="movies", is_enabled=True)
    libt = em.Library(guid=_g(), name="剧集", collection_type="tvshows", is_enabled=True)
    db.add_all([libm, libm2, libt])
    db.flush()
    seq = [0]

    def mk(lib, item_type, name, **kw):
        seq[0] += 1
        kw.setdefault("date_added", t0 + timedelta(hours=rnd.randint(0, 500)))
        kw.setdefault("sort_name", name.lower() if name else "")
        kw.setdefault("community_rating", rnd.choice([None, 6.5, 7.0, 7.0, 8.1]))
        it = em.MediaItem(guid=_g(), library_id=lib.id, item_type=item_type, name=name,
                          file_path=f"/m/{seq[0]}.mkv", **kw)
        db.add(it)
        db.flush()
        return it

    m = {}
    m["m1"] = mk(libm, "movie", "Alpha", tmdb_id="100", production_year=2001)
    m["m2"] = mk(libm, "movie", "Alpha 1080p", tmdb_id="100 ", poster_path="/p.jpg", production_year=2001)
    m["m2b"] = mk(libm, "movie", "Alpha 4K", tmdb_id="100", overview="x", production_year=2001)
    m["m3"] = mk(libm2, "movie", "Alpha", tmdb_id="100", production_year=2001)  # 别的库：不合并
    m["m4"] = mk(libm, "movie", "Foo Bar!", production_year=2010)
    m["m5"] = mk(libm, "movie", "ｆｏｏ bar", overview="简介", production_year=2010)
    m["m6"] = mk(libm, "movie", "foo-bar", production_year=2011)            # 不同年
    m["m7"] = mk(libm, "movie", "", production_year=2010)                    # 无键
    m["m8"] = mk(libm, "movie", "  ", tmdb_id="   ", production_year=2010)  # 空白 tmdb → 名字键（空）
    m["m9"] = mk(libm, "movie", "Beta", tmdb_id="\t200", production_year=1999)
    m["m10"] = mk(libm, "movie", "Beta (copy)", tmdb_id="200", primary_image_url="http://x", production_year=1999)
    for i in range(12):
        mk(libm, "movie", "Same", tmdb_id=str(900 + i), production_year=2000)  # 并列行（不重复）
    for i in range(30):
        mk(libm, "movie", f"Movie {i:02d}", tmdb_id=str(1000 + i), production_year=1990 + i % 7)

    s1 = mk(libt, "series", "Show A", tmdb_id="500")
    s2 = mk(libt, "series", "Show A (dup)", tmdb_id="500", poster_path="/s.jpg")
    s3 = mk(libt, "series", "Show B")
    s4 = mk(libt, "series", "show b")
    s5 = mk(libt, "series", "Show C", tmdb_id="501")
    eps = []
    for s in (s1, s2, s5):
        season = mk(libt, "season", "Season 1", series_id=s.id, parent_id=s.id, season_number=1)
        for e in range(1, 6):
            eps.append(mk(libt, "episode", f"{s.name} E{e}", series_id=s.id, parent_id=season.id,
                          season_number=1, episode_number=e))
    eps.append(mk(libt, "episode", "Show A E1 again", series_id=s1.id, season_number=1,
                  episode_number=1, overview="better"))
    for s in (s3, s4):
        eps.append(mk(libt, "episode", f"{s.name} special", series_id=s.id))  # 季/集号为空
    eps.append(mk(libt, "episode", "orphan 1", season_number=1, episode_number=1))
    eps.append(mk(libt, "episode", "orphan 1b", season_number=1, episode_number=1))
    eps.append(mk(libt, "episode", "orphan 2", season_number=1, episode_number=2))

    user = models.WebUser(username="dedup", password_hash="x", is_active=True)
    db.add(user)
    db.flush()
    # 收藏只打在「非主」版本 m1 上；s1 的若干集看过
    db.add(em.UserMediaData(user_id=user.id, item_id=m["m1"].id, is_favorite=True))
    db.add(em.UserMediaData(user_id=user.id, item_id=m["m4"].id, is_favorite=True, played=True))
    for ep in eps[:3]:
        db.add(em.UserMediaData(user_id=user.id, item_id=ep.id, played=True,
                                last_played_at=t0 + timedelta(days=ep.id % 5)))
    db.commit()
    data = SimpleNamespace(db=db, user=SimpleNamespace(id=user.id, is_staff=False),
                           libm=libm.guid, libm2=libm2.guid, libt=libt.guid,
                           s1=s1.guid, s3=s3.guid)
    yield data
    db.close()
    engine.dispose()


def _req(params):
    return Request({"type": "http", "method": "GET",
                    "query_string": urlencode(params).encode(), "headers": []})


_REAL_DROPPED = api._dedup_dropped_ids


def _run(seeded, params, legacy, monkeypatch):
    calls = []
    real = _REAL_DROPPED

    def spy(query, db):
        out = None if legacy else real(query, db)
        calls.append(out)
        return out

    monkeypatch.setattr(api, "_dedup_dropped_ids", spy)
    res = api._query_items(_req(params), seeded.user, seeded.db, "http://t")
    return res, calls


def _cases(seeded):
    out = []
    for lib in (seeded.libm, seeded.libm2, seeded.libt):
        for sort, order in (("SortName", "Ascending"), ("SortName", "Descending"),
                            ("DateCreated", "Descending"), ("ProductionYear,SortName", "Ascending"),
                            ("CommunityRating", "Descending")):
            base = {"ParentId": lib, "Recursive": "true", "SortBy": sort, "SortOrder": order}
            out.append({**base, "Limit": 200})
            for start in range(0, 60, 7):
                out.append({**base, "StartIndex": start, "Limit": 7})
            out.append({**base, "StartIndex": 5, "Limit": 9, "EnableTotalRecordCount": "false"})
    out += [
        {"Recursive": "true", "IncludeItemTypes": "Episode", "Limit": 500},
        {"Recursive": "true", "IncludeItemTypes": "Episode", "StartIndex": 4, "Limit": 5},
        {"Recursive": "true", "IncludeItemTypes": "Episode,Season", "SortBy": "SortName", "Limit": 100},
        {"Recursive": "true", "IncludeItemTypes": "Movie", "Limit": 100},
        {"Recursive": "true", "IncludeItemTypes": "Movie,Series", "Limit": 100, "SortBy": "DateCreated",
         "SortOrder": "Descending"},
        {"Recursive": "true", "Filters": "IsFavorite", "Limit": 100},
        {"Recursive": "true", "Filters": "IsPlayed", "IncludeItemTypes": "Episode", "Limit": 100},
        {"Recursive": "true", "Filters": "IsUnplayed", "IncludeItemTypes": "Episode", "Limit": 100},
        {"ParentId": seeded.s1, "Recursive": "true", "Limit": 100},
        {"ParentId": seeded.s1, "Recursive": "true", "IncludeItemTypes": "Episode", "StartIndex": 2,
         "Limit": 3},
        {"ParentId": seeded.s3, "Recursive": "true", "Limit": 100},
        {"Recursive": "false", "Limit": 100},
        {"Recursive": "true", "Years": "2010", "Limit": 100},
        {"Recursive": "true", "EnableTotalRecordCount": "false", "Limit": 4, "StartIndex": 8},
    ]
    return out


def test_sql_dedup_matches_legacy_on_seeded_data(seeded, monkeypatch):
    used_fast = 0
    for params in _cases(seeded):
        new, calls_new = _run(seeded, params, legacy=False, monkeypatch=monkeypatch)
        old, calls_old = _run(seeded, params, legacy=True, monkeypatch=monkeypatch)
        assert new == old, params
        if calls_new and calls_new[0] is not None:
            used_fast += 1
    assert used_fast > 50  # 确认确实走了新路径


def test_dedup_actually_drops_expected_rows(seeded, monkeypatch):
    res, calls = _run(seeded, {"ParentId": seeded.libm, "Recursive": "true", "Limit": 500},
                      legacy=False, monkeypatch=monkeypatch)
    names = [i["Name"] for i in res["Items"]]
    assert calls and calls[0] is not None and len(calls[0]) >= 4
    assert "Alpha 1080p" in names and "Alpha" not in names and "Alpha 4K" not in names
    assert "ｆｏｏ bar" in names and "Foo Bar!" not in names and "foo-bar" in names
    assert "Beta (copy)" in names and "Beta" not in names
    assert names.count("Same") == 12
    # 收藏筛选：只有非主版本 m1 被收藏 → 它自己成为主
    fav, _ = _run(seeded, {"Recursive": "true", "Filters": "IsFavorite", "Limit": 50},
                  legacy=False, monkeypatch=monkeypatch)
    assert {i["Name"] for i in fav["Items"]} == {"Alpha", "Foo Bar!"}


def test_pages_are_disjoint_and_cover_everything(seeded, monkeypatch):
    params = {"ParentId": seeded.libm, "Recursive": "true", "SortBy": "SortName"}
    full, _ = _run(seeded, {**params, "Limit": 500}, legacy=False, monkeypatch=monkeypatch)
    ids = []
    for start in range(0, full["TotalRecordCount"], 5):
        page, _ = _run(seeded, {**params, "StartIndex": start, "Limit": 5}, legacy=False,
                       monkeypatch=monkeypatch)
        ids += [i["Id"] for i in page["Items"]]
    assert ids == [i["Id"] for i in full["Items"]]
    assert len(set(ids)) == len(ids)


def test_falls_back_when_too_many_duplicates(seeded, monkeypatch):
    monkeypatch.setattr(api, "_DEDUP_MAX_DROPPED", 1)
    params = {"ParentId": seeded.libm, "Recursive": "true", "Limit": 500}
    out = _REAL_DROPPED
    seen = []
    monkeypatch.setattr(api, "_dedup_dropped_ids", lambda q, db: seen.append(out(q, db)) or seen[-1])
    res = api._query_items(_req(params), seeded.user, seeded.db, "http://t")
    assert seen == [None]
    assert "Alpha 1080p" in [i["Name"] for i in res["Items"]]
