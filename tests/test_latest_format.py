"""Latest（最新入库）返回格式回归测试。

背景：/emby/Users/{id}/Items/Latest 曾返回裸 JSON 数组 [...]，
Emby 标准要求 {"Items": [...], "TotalRecordCount": N, "StartIndex": 0}。
SenPlayer 解析失败后不再调用，导致首页无海报行。
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
    path = os.path.join(tempfile.mkdtemp(), "latest.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s


def _mk(db, lib, item_type, name, date_added=None):
    it = em.MediaItem(
        guid=uuid.uuid4().hex[:32],
        library_id=lib.id,
        item_type=item_type,
        name=name,
        sort_name=name,
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
    m1 = _mk(db, lib, "movie", "老电影", date_added=now - timedelta(days=30))
    m2 = _mk(db, lib, "movie", "新电影", date_added=now - timedelta(days=1))
    user = core.WebUser(username="u1", password_hash="x")
    db.add(user)
    db.flush()
    db.commit()
    return SimpleNamespace(db=db, user=user, m1=m1, m2=m2)


def _call_latest(db, user, limit=16):
    req = SimpleNamespace(query_params={"Limit": str(limit)})
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(api, "_base_url", lambda request: "http://test")
        mp.setattr(api, "_prefetch_list_data", lambda *a, **k: None)
        mp.setattr(api, "_library_scope", lambda db, user: None)
        mp.setattr(api, "_item_dto",
                   lambda e, base, uid, db: {"Id": e.guid, "Name": e.name,
                                             "ServerId": "test-server",
                                             "Type": e.item_type})
        return api.get_latest(req, user, db)


def test_latest_returns_query_result_format(scene):
    """必须是 {Items, TotalRecordCount, StartIndex}，不能是裸数组。"""
    res = _call_latest(scene.db, scene.user)
    assert isinstance(res, dict), "必须返回 dict，不能是裸 list"
    assert "Items" in res
    assert "TotalRecordCount" in res
    assert "StartIndex" in res
    assert isinstance(res["Items"], list)
    assert res["TotalRecordCount"] == len(res["Items"])
    assert res["StartIndex"] == 0


def test_latest_not_bare_array(scene):
    """回归：裸数组格式必须消失。"""
    res = _call_latest(scene.db, scene.user)
    assert not isinstance(res, list), "裸数组格式是 bug，见 issue"


def test_latest_newest_first(scene):
    res = _call_latest(scene.db, scene.user)
    names = [i["Name"] for i in res["Items"]]
    assert names[0] == "新电影"


def test_latest_limit(scene):
    res = _call_latest(scene.db, scene.user, limit=1)
    assert len(res["Items"]) <= 1
    assert res["TotalRecordCount"] == len(res["Items"])


def test_latest_empty_db(db):
    user = core.WebUser(username="u2", password_hash="x")
    db.add(user)
    db.flush()
    res = _call_latest(db, user)
    assert res["Items"] == []
    assert res["TotalRecordCount"] == 0
    assert res["StartIndex"] == 0
