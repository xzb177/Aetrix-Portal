"""Suggestions（首页推荐）回归测试。

背景：Rex 播放器首页顶部横幅调 /emby/Users/{id}/Suggestions，我们返回 404
导致横幅空白。本实现用「最新入库 + 全站热门」拼推荐位，对齐官方 Emby
Suggestions 的 BaseItemDtoQueryResult 口径 (Items/TotalRecordCount/StartIndex)。

同时覆盖 /emby/Users/{id}/Shows/NextUp 兼容路由（Rex 调了带 user 前缀的
错误 URL，之前 404；正确的 /emby/Shows/NextUp 一直是 200）。
"""
import os
import tempfile
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models as core  # noqa: F401
from backend.database import Base
from backend.emby_server import api, models as em


@pytest.fixture
def db():
    path = os.path.join(tempfile.mkdtemp(), "suggestions.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s


def _mk(db, lib, item_type, name, date_added=None, guid=None, series=None):
    it = em.MediaItem(
        guid=(guid or uuid.uuid4().hex[:32]),
        library_id=lib.id,
        item_type=item_type,
        name=name,
        sort_name=name,
        series_id=series.id if series else None,
        is_hidden=False,
        date_added=date_added or datetime.now(),
    )
    db.add(it)
    db.flush()
    return it


@pytest.fixture
def scene(db):
    lib = em.Library(guid="L" * 32, name="电影库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    now = datetime.now()
    # 3 部电影，入库时间递增
    m1 = _mk(db, lib, "movie", "老电影", date_added=now - timedelta(days=30))
    m2 = _mk(db, lib, "movie", "新电影", date_added=now - timedelta(days=1))
    m3 = _mk(db, lib, "movie", "最新电影", date_added=now)
    # 1 部剧
    s1 = _mk(db, lib, "series", "热门剧", date_added=now - timedelta(days=10))
    user = core.WebUser(username="u1", password_hash="x")
    db.add(user)
    db.flush()
    # 老电影被播放 10 次 → 热门第一
    db.add(em.UserMediaData(user_id=user.id, item_id=m1.id, played=True, play_count=10))
    # 热门剧被播放 5 次 → 热门第二
    db.add(em.UserMediaData(user_id=user.id, item_id=s1.id, played=True, play_count=5))
    db.commit()
    return SimpleNamespace(db=db, user=user, m1=m1, m2=m2, m3=m3, s1=s1)


def _call_suggestions(db, user, limit=20):
    req = SimpleNamespace(query_params={"Limit": str(limit)})
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(api, "_base_url", lambda request: "http://test")
        mp.setattr(api, "_prefetch_list_data", lambda *a, **k: None)
        mp.setattr(api, "_library_scope", lambda db, user: None)
        mp.setattr(api, "_item_dto",
                   lambda e, base, uid, db: {"Id": e.guid, "Name": e.name,
                                             "ServerId": "test-server",
                                             "Type": e.item_type})
        return api.get_suggestions("1", req, user, db)


def test_suggestions_returns_items(scene):
    res = _call_suggestions(scene.db, scene.user)
    assert "Items" in res
    assert "TotalRecordCount" in res
    assert "StartIndex" in res
    assert res["TotalRecordCount"] == len(res["Items"])
    assert res["TotalRecordCount"] > 0


def test_suggestions_latest_first(scene):
    res = _call_suggestions(scene.db, scene.user)
    names = [i["Name"] for i in res["Items"]]
    # 最新入库的排在前面
    assert names[0] == "最新电影"


def test_suggestions_has_server_id(scene):
    res = _call_suggestions(scene.db, scene.user)
    for item in res["Items"]:
        assert item["ServerId"] == "test-server"
        assert item["Id"]
        assert item["Name"]


def test_suggestions_limit(scene):
    res = _call_suggestions(scene.db, scene.user, limit=2)
    assert len(res["Items"]) <= 2


def test_suggestions_no_duplicates(scene):
    res = _call_suggestions(scene.db, scene.user)
    ids = [i["Id"] for i in res["Items"]]
    assert len(ids) == len(set(ids))


def test_suggestions_empty_db(db):
    lib = em.Library(guid="E" * 32, name="空库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    user = core.WebUser(username="u2", password_hash="x")
    db.add(user)
    db.commit()
    res = _call_suggestions(db, user)
    assert res["Items"] == []
    assert res["TotalRecordCount"] == 0


def test_nextup_user_prefixed_route_registered():
    # 路由必须注册上，否则 Rex 调 /emby/Users/{id}/Shows/NextUp 会 404
    paths = set()
    for route in api.emby_router.routes:
        p = getattr(route, "path", "")
        if p:
            paths.add(p)
    assert "/emby/Users/{user_id}/Shows/NextUp" in paths
    assert "/Users/{user_id}/Shows/NextUp" in paths


def test_suggestions_route_registered():
    paths = set()
    for route in api.emby_router.routes:
        p = getattr(route, "path", "")
        if p:
            paths.add(p)
    assert "/emby/Users/{user_id}/Suggestions" in paths
    assert "/Users/{user_id}/Suggestions" in paths
