"""一键扫描（POST /scan/all）漏扫未分配节点的库——回归测试

现场：后台新建 .strm 直链库（路径 /strm/...）时节点默认「不分配」（node_id 为空），
单库点「扫描」能扫、定时扫描也会扫，唯独「一键扫描」扫不到：
portal.scan_all_libraries_endpoint 调 server_ops.scan_plan 时没带
include_unassigned=True，scope_libraries 只返回 node_id == 本机节点 的库。
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import models as em
from backend.emby_server import nodes as node_lib
from backend.emby_server import portal, scan_queue, server_ops


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def fake_enqueue(monkeypatch):
    calls: list = []

    def fake(lib, *, trigger="manual", **_kw):
        calls.append(lib.id)
        return {"created": True, "task": {"library_id": lib.id, "state": "queued", "message": ""}}

    monkeypatch.setattr(scan_queue, "enqueue", fake)
    return calls


def _setup(db):
    realm = models.ServerRealm(name="主服", slug="main", is_active=True)
    db.add(realm)
    db.commit()
    server = models.RemoteServer(name="本机", kind="ea", url="http://ea.local:8001",
                                 realm_id=realm.id, node_key="ea-01")
    db.add(server)
    db.commit()
    owned = em.Library(guid="g-owned", name="电影", collection_type="movies",
                       paths="/media/movies", is_enabled=True, realm_id=realm.id,
                       node_id=server.id)
    strm = em.Library(guid="g-strm", name="STRM 剧集", collection_type="tvshows",
                      paths="/strm/tv", is_enabled=True, realm_id=realm.id, node_id=None)
    db.add_all([owned, strm])
    db.commit()
    return server, owned, strm


def test_scan_all_includes_unassigned_strm_library(db, fake_enqueue, monkeypatch):
    server, owned, strm = _setup(db)
    monkeypatch.setenv("NODE_KEY", "ea-01")
    node_lib.reset_cache()
    try:
        res = asyncio.run(portal.scan_all_libraries_endpoint(staff=None, db=db))
    finally:
        node_lib.reset_cache()

    queued_ids = {row["id"] for row in res["queued"]}
    assert strm.id in queued_ids, "未分配节点的 .strm 库必须被一键扫描入队"
    assert owned.id in queued_ids
    assert sorted(fake_enqueue) == sorted([owned.id, strm.id])


def test_scan_plan_without_self_node_does_not_double_enqueue(db, fake_enqueue):
    """面板没配 NODE_KEY（server=None）时，未分配库只推一次"""
    _server, _owned, strm = _setup(db)
    plan = server_ops.scan_plan(db, None, include_unassigned=True)
    assert [row["id"] for row in plan["queued"]] == [strm.id]
    assert fake_enqueue == [strm.id]
