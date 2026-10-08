"""P4：热点列表端点改 orjson 直出后，字节与 FastAPI 默认（jsonable_encoder + JSONResponse）一致。

- 路由注册的是包装版（返回 FastJSONResponse，FastAPI 原样发送、跳过 jsonable_encoder）；
- 模块里的函数名仍返回 dict / list（其它模块与测试的直接调用不受影响）。
"""
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend.emby_server import api, fastjson
from backend.emby_server import models as em
from tests.test_items_dedup_sql import _req, seeded  # noqa: F401  复用独立种子库


def _route_endpoint(path):
    for r in api.emby_router.routes:
        if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError(f"路由不存在: {path}")


def _legacy_bytes(payload):
    return JSONResponse(jsonable_encoder(payload)).body


def test_hot_routes_registered_with_fast_json():
    for path in ("/emby/Users/{user_id}/Items", "/Users/{user_id}/Items",
                 "/emby/Users/{user_id}/Items/Resume", "/emby/Users/{user_id}/Items/Latest",
                 "/emby/Users/{user_id}/Items/{item_id}", "/emby/Items/{item_id}",
                 "/emby/Shows/{item_id}/Seasons", "/emby/Shows/{item_id}/Episodes",
                 "/emby/Shows/NextUp", "/Users/{user_id}/Shows/NextUp"):
        assert getattr(_route_endpoint(path), "__fast_json__", False), path
    # 模块属性仍是原函数（直接调用返回 dict）
    assert not getattr(api.get_items, "__fast_json__", False)


def test_route_order_unchanged():
    paths = [getattr(r, "path", "") for r in api.emby_router.routes]
    assert paths.index("/emby/Users/{user_id}/Items") < paths.index("/emby/Users/{user_id}/Items/Resume")
    assert paths.index("/emby/Users/{user_id}/Items/Latest") < paths.index("/emby/Users/{user_id}/Items/{item_id}")


def test_bytes_identical_on_real_endpoints(seeded):  # noqa: F811
    db, user = seeded.db, seeded.user
    series = db.query(em.MediaItem).filter(em.MediaItem.item_type == "series").first()
    season = db.query(em.MediaItem).filter(em.MediaItem.item_type == "season",
                                           em.MediaItem.series_id == series.id).first()
    movie = db.query(em.MediaItem).filter(em.MediaItem.item_type == "movie").first()
    calls = [
        (api.get_items, "/emby/Users/{user_id}/Items",
         dict(request=_req({"Recursive": "true", "Limit": 200, "Fields": "Overview,Genres"}))),
        (api.get_items, "/emby/Users/{user_id}/Items",
         dict(request=_req({"Recursive": "true", "IncludeItemTypes": "Episode", "Limit": 200}))),
        (api.get_latest, "/emby/Users/{user_id}/Items/Latest", dict(request=_req({"Limit": 16}))),
        (api.get_resume, "/emby/Users/{user_id}/Items/Resume", dict(request=_req({"Limit": 12}))),
        (api.get_next_up, "/emby/Shows/NextUp", dict(request=_req({"Limit": 24}))),
        (api.get_seasons, "/emby/Shows/{item_id}/Seasons",
         dict(item_id=series.guid, request=_req({}))),
        (api.get_episodes, "/emby/Shows/{item_id}/Episodes",
         dict(item_id=series.guid, request=_req({"SeasonId": season.guid}))),
        (api.get_item_detail, "/emby/Users/{user_id}/Items/{item_id}",
         dict(item_id=movie.guid, request=_req({}))),
    ]
    import backend.emby_server.api as A
    orig_scope = A._library_scope
    A._library_scope = lambda db, user: None
    try:
        for fn, path, kw in calls:
            payload = fn(user=user, db=db, **kw)
            resp = _route_endpoint(path)(user=user, db=db, **kw)
            assert isinstance(resp, fastjson.FastJSONResponse), path
            assert resp.body == _legacy_bytes(payload), path
            assert resp.headers["content-type"] == "application/json"
    finally:
        A._library_scope = orig_scope


def test_fallback_types_and_edge_values():
    payload = {
        "dt": datetime(2026, 1, 2, 3, 4, 5, 678901),
        "dtz": datetime(2026, 1, 2, tzinfo=timezone.utc),
        "dec": Decimal("1.50"),
        "set": {3},
        "tuple": (1, "二"),
        "int_key": {1: "a"},
        "uuid": uuid.UUID(int=5),
        "nested": [{"中文": "值", "ctrl": "a\nb\t\u0001", "slash": "a/b", "big": 2 ** 53}],
        "float": [0.1, 7.0, 1.7777777777777777, -0.0],
        "none": None, "bool": True,
    }
    assert fastjson.dumps(payload) == _legacy_bytes(payload)
    assert json.loads(fastjson.dumps({"nan": float("nan")})) == {"nan": None}
