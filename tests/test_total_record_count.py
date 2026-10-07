"""TotalRecordCount 非负回归测试。

背景：_query_items 在 EnableTotalRecordCount=false 时曾返回 TotalRecordCount=-1，
Emby 官方从不返回 -1。第三方播放器用 ``TotalRecordCount > Items.length``
判断是否分页，-1 会导致列表显示不全。修复后跳过总数时返回本页数量
（保证非负），继续加载用 HasMore 判断。
"""
import os
import tempfile
import uuid
from datetime import datetime
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
    """仿 Starlette QueryParams：get + getlist。"""

    def getlist(self, key):
        v = self.get(key)
        return [v] if v else []


@pytest.fixture
def db():
    path = os.path.join(tempfile.mkdtemp(), "totalrc.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s


@pytest.fixture
def scene(db):
    lib = em.Library(guid="T" * 32, name="电影库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    for i in range(5):
        db.add(em.MediaItem(
            guid=uuid.uuid4().hex[:32],
            library_id=lib.id,
            item_type="movie",
            name=f"电影{i:02d}",
            sort_name=f"电影{i:02d}",
            is_hidden=False,
            date_added=datetime.now(),
            file_path=f"/mnt/paul/video/电影{i:02d}.mkv",
        ))
    user = core.WebUser(username="u_total", password_hash="x")
    db.add(user)
    db.flush()
    db.commit()
    return SimpleNamespace(db=db, user=user)


def _call(db, user, **params):
    req = SimpleNamespace(query_params=_QP(params))
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(api, "_library_scope", lambda db, user: None)
        mp.setattr(api, "_prefetch_list_data", lambda *a, **k: None)
        mp.setattr(api, "_item_dto",
                   lambda e, base, uid, db: {"Id": e.guid, "Name": e.name,
                                             "ServerId": "test-server",
                                             "Type": e.item_type})
        return api._query_items(req, user, db, "http://test")


def test_no_total_never_negative_nonrandom(scene):
    """跳过总数时 TotalRecordCount 必须非负，不能是 -1。"""
    res = _call(scene.db, scene.user, EnableTotalRecordCount="false", Limit="2")
    assert res["TotalRecordCount"] >= 0, "Emby 官方从不返回 -1"
    assert res["TotalRecordCount"] != -1


def test_no_total_equals_page_size(scene):
    """跳过总数时返回本页数量：TotalRecordCount == len(Items)。"""
    res = _call(scene.db, scene.user, EnableTotalRecordCount="false", Limit="2")
    assert len(res["Items"]) == 2
    assert res["TotalRecordCount"] == len(res["Items"])
    assert res["HasMore"] is True  # 5 条 > 0+2，还有下一页


def test_no_total_last_page(scene):
    """最后一页：HasMore=False，总数仍非负。"""
    res = _call(scene.db, scene.user, EnableTotalRecordCount="false",
                Limit="2", StartIndex="4")
    assert len(res["Items"]) == 1
    assert res["TotalRecordCount"] == 1
    assert res["HasMore"] is False


def test_no_total_random_branch_nonnegative(scene):
    """随机排序分支跳过总数时也不能返回 -1。"""
    res = _call(scene.db, scene.user, EnableTotalRecordCount="false",
                Limit="2", SortBy="Random")
    assert res["TotalRecordCount"] >= 0, "随机分支也不能返回 -1"
    assert res["TotalRecordCount"] == len(res["Items"])


def test_want_total_still_full_count(scene):
    """默认（要总数）行为不变：返回去重后全量。"""
    res = _call(scene.db, scene.user, Limit="2")
    assert res["TotalRecordCount"] == 5
    assert len(res["Items"]) == 2
    assert "HasMore" not in res


def test_total_record_count_never_negative_matrix(scene):
    """矩阵：各种参数组合下 TotalRecordCount 永远非负。"""
    combos = [
        {"EnableTotalRecordCount": "false", "Limit": "3"},
        {"EnableTotalRecordCount": "0", "Limit": "10"},
        {"EnableTotalRecordCount": "false", "Limit": "3", "SortBy": "Random"},
        {"EnableTotalRecordCount": "false", "Limit": "10", "StartIndex": "100"},
        {},
    ]
    for params in combos:
        res = _call(scene.db, scene.user, **params)
        assert res["TotalRecordCount"] >= 0, f"params={params} 返回了负数"
