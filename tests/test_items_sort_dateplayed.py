"""S9 回归：``SortBy=DatePlayed`` / ``PlayCount`` 未带播放类筛选时不再 500。

旧实现只在 Filters 含 IsPlayed/IsFavorite/... 时才外连接 UserMediaData，排序映射却
直接引用 ``UserMediaData.last_played_at`` → SQLite ``no such column`` / PG
``missing FROM-clause entry``。修复后按需外连接，没有用户数据的条目排在最后。
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


class _QP(dict):
    def getlist(self, key):
        v = self.get(key)
        return [v] if v else []


@pytest.fixture
def scene():
    path = os.path.join(tempfile.mkdtemp(), "sortplayed.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        lib = em.Library(guid="S" * 32, name="电影库", collection_type="movies", paths="")
        db.add(lib)
        db.flush()
        items = []
        for i in range(4):
            it = em.MediaItem(
                guid=uuid.uuid4().hex[:32], library_id=lib.id, item_type="movie",
                name=f"电影{i}", sort_name=f"电影{i}", is_hidden=False,
                date_added=datetime.now(), file_path=f"/mnt/v/电影{i}.mkv",
                tmdb_id=str(1000 + i),
            )
            db.add(it)
            items.append(it)
        user = core.WebUser(username="u_sort", password_hash="x")
        other = core.WebUser(username="u_other", password_hash="x")
        db.add_all([user, other])
        db.flush()
        now = datetime.now()
        # 电影1 最近播放、电影3 较早播放；电影0/2 无用户数据
        db.add(em.UserMediaData(user_id=user.id, item_id=items[1].id, played=True,
                                play_count=1, last_played_at=now))
        db.add(em.UserMediaData(user_id=user.id, item_id=items[3].id, played=True,
                                play_count=5, last_played_at=now - timedelta(days=3)))
        # 另一个用户的数据不得影响本用户的排序，也不得让条目重复
        db.add(em.UserMediaData(user_id=other.id, item_id=items[0].id, played=True,
                                play_count=9, last_played_at=now + timedelta(days=1)))
        db.commit()
        yield SimpleNamespace(db=db, user=user)


def _names(scene, **params):
    req = SimpleNamespace(query_params=_QP(params))
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(api, "_library_scope", lambda db, user: None)
        mp.setattr(api, "_prefetch_list_data", lambda *a, **k: None)
        mp.setattr(api, "_item_dto", lambda e, base, uid, db: {"Name": e.name})
        res = api._query_items(req, scene.user, scene.db, "http://test")
    return [i["Name"] for i in res["Items"]], res["TotalRecordCount"]


def test_dateplayed_desc_without_filter(scene):
    names, total = _names(scene, SortBy="DatePlayed", SortOrder="Descending")
    assert total == 4
    assert names[:2] == ["电影1", "电影3"]
    assert sorted(names[2:]) == ["电影0", "电影2"]  # 无记录的排在最后


def test_dateplayed_asc_nulls_still_last(scene):
    names, _ = _names(scene, SortBy="DatePlayed,SortName", SortOrder="Ascending")
    assert names == ["电影3", "电影1", "电影0", "电影2"]


def test_playcount_sort(scene):
    names, total = _names(scene, SortBy="PlayCount", SortOrder="Descending")
    assert total == 4
    assert names[:2] == ["电影3", "电影1"]


def test_dateplayed_with_isplayed_filter_still_works(scene):
    names, total = _names(scene, SortBy="DatePlayed", SortOrder="Descending",
                          Filters="IsPlayed")
    assert names == ["电影1", "电影3"]
    assert total == 2


def test_dateplayed_no_total_branch(scene):
    names, total = _names(scene, SortBy="DatePlayed", SortOrder="Descending",
                          EnableTotalRecordCount="false", Limit="2")
    assert names == ["电影1", "电影3"]
    assert total == 2
