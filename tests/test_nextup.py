"""NextUp（接下来看）回归测试。

真实起因：旧实现直接返回全库未播放单集（按季/集号排序），导致用户端首页
「接下来看」把每部剧的第 1 集平铺展示——单集根本不该出现在首页。

正确口径（对齐 Emby NextUp）：
- 只收录用户已开看的剧集（看过至少一集 / 有播放进度 / 有播放次数）；
- 每部剧只返回第一集未看的单集；
- 按该剧最近播放时间倒序。
"""
import os
import tempfile
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
    path = os.path.join(tempfile.mkdtemp(), "nextup.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s


def _mk(db, lib, item_type, name, series=None, season=None, episode=None, guid=None):
    import uuid
    it = em.MediaItem(
        guid=(guid or uuid.uuid4().hex[:32]),
        library_id=lib.id,
        item_type=item_type,
        name=name,
        sort_name=name,
        series_id=series.id if series else None,
        parent_id=None,
        season_number=season,
        episode_number=episode,
        is_hidden=False,
    )
    db.add(it)
    db.flush()
    return it


@pytest.fixture
def scene(db):
    lib = em.Library(guid="L" * 32, name="动漫剧", collection_type="tvshows", paths="")
    db.add(lib)
    db.flush()
    # 剧 A：3 集，用户看完第 1 集 → 应返回第 2 集
    series_a = _mk(db, lib, "series", "剧A")
    a1 = _mk(db, lib, "episode", "剧A E01", series=series_a, season=1, episode=1)
    a2 = _mk(db, lib, "episode", "剧A E02", series=series_a, season=1, episode=2)
    a3 = _mk(db, lib, "episode", "剧A E03", series=series_a, season=1, episode=3)
    # 剧 B：2 集，用户一集都没看过 → 不应出现在 NextUp
    series_b = _mk(db, lib, "series", "剧B")
    b1 = _mk(db, lib, "episode", "剧B E01", series=series_b, season=1, episode=1)
    b2 = _mk(db, lib, "episode", "剧B E02", series=series_b, season=1, episode=2)
    user = core.WebUser(username="u1", password_hash="x")
    db.add(user)
    db.flush()
    db.add(em.UserMediaData(
        user_id=user.id, item_id=a1.id, played=True,
        play_count=1, last_played_at=datetime.now() - timedelta(hours=1),
    ))
    db.commit()
    return SimpleNamespace(db=db, user=user, a2=a2, series_a=series_a, series_b=series_b)


def _call(db, user, limit=20):
    req = SimpleNamespace(query_params={"Limit": str(limit)})
    with pytest.MonkeyPatch().context() as mp:
        # _item_dto / _prefetch_list_data 依赖请求基地址与图片服务，这里只验证选集逻辑
        mp.setattr(api, "_base_url", lambda request: "http://test")
        mp.setattr(api, "_prefetch_list_data", lambda *a, **k: None)
        mp.setattr(api, "_item_dto", lambda e, base, uid, db: {"Id": e.guid, "Name": e.name})
        return api.get_next_up(req, user, db)


def test_nextup_one_per_started_series(scene):
    res = _call(scene.db, scene.user)
    assert res["TotalRecordCount"] == 1
    assert res["Items"][0]["Name"] == "剧A E02"


def test_nextup_ignores_unstarted_series(scene):
    res = _call(scene.db, scene.user)
    names = [i["Name"] for i in res["Items"]]
    assert not any(n.startswith("剧B") for n in names)


def test_nextup_empty_when_nothing_watched(db):
    lib = em.Library(guid="M" * 32, name="库", collection_type="tvshows", paths="")
    db.add(lib)
    db.flush()
    s = _mk(db, lib, "series", "剧C")
    _mk(db, lib, "episode", "剧C E01", series=s, season=1, episode=1)
    user = core.WebUser(username="u2", password_hash="x")
    db.add(user)
    db.commit()
    res = _call(db, user)
    assert res["TotalRecordCount"] == 0
    assert res["Items"] == []
