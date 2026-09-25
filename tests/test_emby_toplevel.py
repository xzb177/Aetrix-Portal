"""顶层保护回归测试：季 / 单集不得出现在顶层浏览与搜索结果里。

用户要求（2026-09-25）：首页各分区、媒体库网格、搜索结果只允许
series/movie 级别卡片；season / episode 卡片只出现在剧集详情页内
（专用端点 /Shows/{id}/Seasons、/Shows/{id}/Episodes，或显式
IncludeItemTypes）。

覆盖 _query_items 的三条默认口径：
1. 媒体库浏览（ParentId=媒体库，无显式类型）→ 只有 movie/series；
2. 全局搜索（SearchTerm，无 ParentId，无显式类型）→ 只有 movie/series；
3. 显式 IncludeItemTypes → 尊重调用方（详情页/第三方客户端不受影响）；
4. ParentId=剧集（无显式类型）→ 子项（季/集）照常返回，不误伤详情页。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import api as emby_api

init_db()


def _guid():
    return uuid.uuid4().hex


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def seed(db):
    """一个媒体库：1 电影 + 1 剧集（含 1 季 2 集）。返回 guid 字典。"""
    lib = em.Library(guid=_guid(), name="测试库", collection_type="tvshows")
    db.add(lib)
    db.flush()

    def mk(item_type, name, **kw):
        it = em.MediaItem(guid=_guid(), library_id=lib.id,
                          item_type=item_type, name=name, **kw)
        db.add(it)
        db.flush()
        return it

    movie = mk("movie", "测试电影搜A")
    series = mk("series", "测试剧集搜A")
    season = mk("season", "Season 01", series_id=series.id, season_number=1)
    ep1 = mk("episode", "测试剧集搜A S01E01", series_id=series.id,
             parent_id=season.id, season_number=1, episode_number=1)
    ep2 = mk("episode", "测试剧集搜A S01E02", series_id=series.id,
             parent_id=season.id, season_number=1, episode_number=2)
    db.commit()
    data = {"lib": lib.guid, "movie": movie.guid, "series": series.guid,
            "season": season.guid, "ep1": ep1.guid, "ep2": ep2.guid}
    yield data
    # 清理：先删条目再删库（外键 parent_id/series_id 自引用）
    ids = [r[0] for r in db.query(em.MediaItem.id)
           .filter(em.MediaItem.library_id == lib.id).all()]
    if ids:
        db.query(em.MediaItem).filter(em.MediaItem.id.in_(ids)).delete(
            synchronize_session=False)
    db.query(em.Library).filter(em.Library.id == lib.id).delete()
    db.commit()


def _req(params: dict) -> Request:
    from urllib.parse import urlencode
    scope = {"type": "http", "method": "GET",
             "query_string": urlencode(params).encode(), "headers": []}
    return Request(scope)


def _types(db, params: dict):
    user = SimpleNamespace(id=0)
    res = emby_api._query_items(_req(params), user, db, "http://t")
    return {i["Type"] for i in res["Items"]}, res["TotalRecordCount"], res["Items"]


def test_library_browse_defaults_to_toplevel(db, seed):
    types, total, _ = _types(db, {"ParentId": seed["lib"], "Recursive": "true"})
    assert types <= {"Movie", "Series"}, types
    assert total == 2, total  # 1 电影 + 1 剧集，季/集被过滤


def test_library_browse_explicit_types_respected(db, seed):
    types, total, _ = _types(db, {"ParentId": seed["lib"], "Recursive": "true",
                                  "IncludeItemTypes": "Season,Episode"})
    assert types == {"Season", "Episode"}, types
    assert total == 3, total


def test_global_search_defaults_to_toplevel(db, seed):
    types, _, items = _types(db, {"SearchTerm": "测试剧集搜A", "Recursive": "true"})
    assert types <= {"Movie", "Series"}, types
    # 剧集命中；两集单集不应出现在顶层搜索结果里
    names = [i["Name"] for i in items]
    assert not any("S01E" in n for n in names), names


def test_global_search_explicit_episode_ok(db, seed):
    types, total, _ = _types(db, {"SearchTerm": "测试剧集搜A", "Recursive": "true",
                                  "IncludeItemTypes": "Episode"})
    assert types == {"Episode"}, types
    assert total == 2, total


def test_series_children_unaffected(db, seed):
    """ParentId=剧集（详情页子项口径）：季/集照常返回，不被顶层保护误伤。"""
    types, total, _ = _types(db, {"ParentId": seed["series"], "Recursive": "true"})
    assert "Episode" in types or "Season" in types, types
    assert total >= 3, total
