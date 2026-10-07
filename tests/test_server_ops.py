"""服务器维度媒体运维（backend/emby_server/server_ops.py + 两个路由）单元测试

覆盖需求「把执行动作上移到服务器维度」的实现面：

1. **范围划分**：「归这台节点的库」与「同服里未分配的库」必须分开；
   ``include_unassigned`` 只把后者加进来，不改变「未分配由面板扫」这个语义；
2. **快照**：整服扫描历史跨库合并（带库名）、扫描队列只留这个范围的行、
   刮削补全 / 探测按范围聚合、待修复队列、内容转交标明是**服级**；
3. **一键扫描**：本地入队 / 已在队列不重复推 / 停用与虚拟库跳过并写明原因 /
   归别的节点的库**只计划不执行**（转发是路由层的 await）；
4. **路由边界**：媒体运维只对 EA 开放；非 EA 给出可读原因而不是空面板。

全部用隔离的内存 SQLite，不碰生产库、不发起网络调用（``push_scan`` 与
``scan_queue.enqueue`` 都被替换成假替身）。
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models, realms
from backend.api import servers as servers_api
from backend.emby_server import models as em
from backend.emby_server import nodes as node_lib
from backend.emby_server import scan_queue, scanner, server_ops


@pytest.fixture()
def db():
    # check_same_thread=False：路由是 async 的，同一个 Session 会被 run_in_threadpool
    # 拿到工作线程里去用（SQLite 默认禁止跨线程复用连接）
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ==================== 夹具 ====================

def _realm(db, name="主服"):
    realm = models.ServerRealm(name=name, slug=name.lower(), is_active=True)
    db.add(realm)
    db.commit()
    db.refresh(realm)
    return realm


def _server(db, realm, name="节点甲", kind="ea", node_key=None):
    row = models.RemoteServer(
        name=name, kind=kind, url=f"http://{name}.local:8001",
        realm_id=realm.id, node_key=node_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _library(db, realm, name="电影库", node_id=None, enabled=True, virtual=False,
             paths="/media/movies"):
    lib = em.Library(
        guid=f"guid-{name}-{node_id or 0}", name=name, collection_type="movies",
        paths="" if virtual else paths, is_enabled=enabled,
        is_virtual=virtual, realm_id=realm.id, node_id=node_id,
    )
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


def _run(db, lib, status="success", trigger="manual", minutes_ago=0, **kw):
    row = em.ScanRun(
        library_id=lib.id, status=status, trigger=trigger,
        started_at=datetime.now() - timedelta(minutes=minutes_ago),
        finished_at=datetime.now() - timedelta(minutes=minutes_ago) + timedelta(seconds=5),
        duration_ms=5000, stats="{}", **kw,
    )
    db.add(row)
    db.commit()
    return row


def _item(db, lib, name="条目", enrich="pending", probe="done", repair=False):
    row = em.MediaItem(
        guid=f"guid-item-{name}", library_id=lib.id, item_type="movie", name=name,
        enrich_status=enrich, probe_status=probe, file_path="/media/movies/a.mkv",
    )
    if repair:
        row.repair_requested_at = datetime.now()
    db.add(row)
    db.commit()
    return row


# ==================== 1. 范围划分 ====================

def test_scope_splits_assigned_and_unassigned(db):
    realm = _realm(db)
    server = _server(db, realm)
    mine = _library(db, realm, "我的库", node_id=server.id)
    _library(db, realm, "未分配的库", node_id=None)
    other = _server(db, realm, name="节点乙", node_key="k2")
    _library(db, realm, "别人的库", node_id=other.id)

    targets, unassigned = server_ops.scope_libraries(db, server)

    assert [lib.id for lib in targets] == [mine.id]
    assert [lib.name for lib in unassigned] == ["未分配的库"]


def test_scope_include_unassigned_adds_but_keeps_split(db):
    realm = _realm(db)
    server = _server(db, realm)
    mine = _library(db, realm, "我的库", node_id=server.id)
    free = _library(db, realm, "未分配的库", node_id=None)

    targets, unassigned = server_ops.scope_libraries(db, server, include_unassigned=True)

    assert {lib.id for lib in targets} == {mine.id, free.id}
    # 未分配这一类不能因为被加进来就「变成它的库」
    assert [lib.id for lib in unassigned] == [free.id]


def test_scope_is_scoped_by_realm(db):
    realm_a, realm_b = _realm(db, "甲服"), _realm(db, "乙服")
    server = _server(db, realm_a)
    _library(db, realm_b, "乙服的库", node_id=server.id)

    targets, _ = server_ops.scope_libraries(db, server)

    assert targets == []


# ==================== 2. 快照 ====================

def test_snapshot_merges_scan_runs_across_libraries(db):
    realm = _realm(db)
    server = _server(db, realm)
    first = _library(db, realm, "库一", node_id=server.id)
    second = _library(db, realm, "库二", node_id=server.id)
    _library(db, realm, "别人的库", node_id=_server(db, realm, "节点乙", "k2").id)
    _run(db, first, status="success", minutes_ago=30)
    _run(db, second, status="failed", minutes_ago=10, error="目录不存在")
    _run(db, first, status="partial", minutes_ago=5)

    snapshot = server_ops.ops_snapshot(db, server)

    assert [run["library_name"] for run in snapshot["runs"]] == ["库一", "库二", "库一"]
    assert snapshot["runs"][0]["library_id"] == first.id
    assert snapshot["runs"][0]["added"] == 0
    assert snapshot["runs"][1]["error"] == "目录不存在"


def test_snapshot_runs_limit_is_clamped(db, monkeypatch):
    realm = _realm(db)
    server = _server(db, realm)
    lib = _library(db, realm, "库一", node_id=server.id)
    for i in range(3):
        _run(db, lib, minutes_ago=i)

    assert len(server_ops.ops_snapshot(db, server, runs_limit=2)["runs"]) == 2
    # 超上限要钳到模块上限而不是照着给（面板不该能一次拖走全表）
    snapshot = server_ops.ops_snapshot(db, server, runs_limit=server_ops.MAX_RUNS * 10)
    assert snapshot["scope"]["runs_limit"] == server_ops.MAX_RUNS


def test_snapshot_queue_only_keeps_this_node(db, monkeypatch):
    realm = _realm(db)
    server = _server(db, realm)
    mine = _library(db, realm, "我的库", node_id=server.id)
    _library(db, realm, "别人的库", node_id=_server(db, realm, "节点乙", "k2").id)

    real_snapshot = scan_queue.snapshot

    def fake_snapshot():
        data = real_snapshot()
        return {
            **data,
            "running": [{"library_id": mine.id, "state": "running", "name": "我的库"}],
            "waiting": [{"library_id": 99999, "state": "queued", "name": "别的机器的库"}],
            "history": [],
            "mount_names": {"1": "远端盘"},
        }

    monkeypatch.setattr(scan_queue, "snapshot", fake_snapshot)
    queue = server_ops.ops_snapshot(db, server)["queue"]

    assert [task["library_id"] for task in queue["running"]] == [mine.id]
    assert queue["waiting"] == []
    # 挂载名只带这个范围真的在等的那些
    assert queue["mount_names"] == {}


def test_snapshot_pipeline_counts_only_this_node(db):
    realm = _realm(db)
    server = _server(db, realm)
    mine = _library(db, realm, "我的库", node_id=server.id)
    other_lib = _library(db, realm, "别人的库", node_id=_server(db, realm, "节点乙", "k2").id)
    _item(db, mine, "待补全", enrich="pending")
    _item(db, mine, "已补全", enrich="done")
    _item(db, mine, "待修复", enrich="done", repair=True)
    _item(db, other_lib, "别人的待补全", enrich="pending")

    pipeline = server_ops.ops_snapshot(db, server)["pipeline"]

    assert pipeline["items"] == 3
    assert pipeline["enrich"] == {"pending": 1, "done": 2}
    assert pipeline["repair"]["total"] == 1
    assert pipeline["repair"]["items"][0]["name"] == "待修复"


def test_snapshot_pipeline_without_libraries_says_so(db):
    realm = _realm(db)
    server = _server(db, realm)

    pipeline = server_ops.ops_snapshot(db, server)["pipeline"]

    assert pipeline["items"] == 0
    assert pipeline["note"]
    assert pipeline["repair"]["items"] == []


def test_snapshot_handoff_is_realm_scoped_and_labelled(db):
    realm = _realm(db)
    server = _server(db, realm)
    user = models.WebUser(username="u", password_hash="x", is_active=True)
    db.add(user)
    db.commit()
    mine = models.MovieRequest(
        user_id=user.id, movie_name="流浪地球", status="approved",
        realm_id=realm.id, push_target="moviepilot", push_status="ok",
    )
    other = models.MovieRequest(
        user_id=user.id, movie_name="别的服", status="approved",
        realm_id=None, push_target="qbittorrent", push_status="ok",
    )
    plain = models.MovieRequest(user_id=user.id, movie_name="还没转交", status="pending",
                               realm_id=realm.id)
    db.add_all([mine, other, plain])
    db.commit()

    handoff = server_ops.ops_snapshot(db, server)["handoff"]

    assert handoff["scope"] == "realm"
    assert [row["movie_name"] for row in handoff["items"]] == ["流浪地球"]
    assert handoff["total"] == 1
    # 这一层不是这台机器在跑，面板不能写成「这台服务器在转存」
    assert "EA" in handoff["note"]


def test_snapshot_without_realm_reports_none_scope(db):
    realm = _realm(db)
    server = _server(db, realm)
    server.realm_id = None
    db.commit()

    handoff = server_ops.ops_snapshot(db, server)["handoff"]

    assert handoff["scope"] == "none"
    assert handoff["note"]


def test_snapshot_notes_explain_scope_instead_of_leaving_it_to_the_ui(db):
    realm = _realm(db)
    server = _server(db, realm)
    _library(db, realm, "未分配的库", node_id=None)
    _library(db, realm, "虚拟库", node_id=server.id, virtual=True, paths="")

    notes = " ".join(server_ops.ops_snapshot(db, server)["notes"])

    assert "没分配" in notes          # 未分配不等于归它
    assert "虚拟库" in notes          # 虚拟库不参与扫描
    assert "NODE_KEY" in notes       # 没认领就不能分配库，说清原因


def test_snapshot_library_payload_is_read_only_facts(db):
    realm = _realm(db)
    server = _server(db, realm)
    lib = _library(db, realm, "我的库", node_id=server.id, paths="/a,/b")
    lib.item_count = 42
    db.commit()

    payload = server_ops.ops_snapshot(db, server)["libraries"][0]

    assert payload["id"] == lib.id
    assert payload["paths"] == 2
    assert payload["item_count"] == 42
    assert payload["state"] == "idle"
    # 配置字段只读不改：快照里没有可写入口
    assert "scrape_policy" not in payload


# ==================== 3. 一键扫描计划 ====================

@pytest.fixture()
def fake_enqueue(monkeypatch):
    """假的 ``scan_queue.enqueue``：记录调用并模拟「已在队列」的合并语义"""
    calls: list = []
    seen: dict = {}

    def fake_enqueue(lib, *, trigger="manual"):
        calls.append((lib.id, trigger))
        if lib.id in seen:
            seen[lib.id]["request_count"] += 1
            return {"created": False, "task": dict(seen[lib.id], state="queued")}
        task = {"library_id": lib.id, "name": lib.name, "state": "queued",
                "message": "", "request_count": 1}
        seen[lib.id] = task
        return {"created": True, "task": task}

    monkeypatch.setattr(scan_queue, "enqueue", fake_enqueue)
    return calls


def test_scan_plan_queues_enabled_libraries_once(db, fake_enqueue):
    realm = _realm(db)
    server = _server(db, realm)
    # 未分配的库由面板扫：面板就是执行者，所以是入队而不是转发
    lib = _library(db, realm, "面板代扫", node_id=None)

    first = server_ops.scan_plan(db, server, include_unassigned=True)
    second = server_ops.scan_plan(db, server, include_unassigned=True)

    assert [row["id"] for row in first["queued"]] == [lib.id]
    assert [row["id"] for row in second["already"]] == [lib.id]
    # 合并成一条而不是推两次
    assert [lib_id for lib_id, _ in fake_enqueue] == [lib.id, lib.id]


def test_scan_plan_enqueues_locally_when_panel_is_that_node(db, fake_enqueue, monkeypatch):
    """面板进程就是这台节点时（配了 NODE_KEY），归它的库直接本地入队、不转发"""
    realm = _realm(db)
    server = _server(db, realm, node_key="k1")
    lib = _library(db, realm, "我的库", node_id=server.id)
    monkeypatch.setenv("NODE_KEY", "k1")
    node_lib.reset_cache()
    try:
        plan = server_ops.scan_plan(db, server)
    finally:
        node_lib.reset_cache()

    assert [row["id"] for row in plan["queued"]] == [lib.id]
    assert plan["forward"] == []


def test_scan_plan_skips_disabled_and_virtual_with_reasons(db, fake_enqueue):
    realm = _realm(db)
    server = _server(db, realm)
    _library(db, realm, "停用的库", node_id=server.id, enabled=False)
    _library(db, realm, "虚拟库", node_id=server.id, virtual=True, paths="")

    plan = server_ops.scan_plan(db, server)

    reasons = {row["name"]: row["reason"] for row in plan["skipped"]}
    assert "已停用" in reasons["停用的库"]
    assert "虚拟库" in reasons["虚拟库"]
    assert plan["queued"] == []
    assert fake_enqueue == []


def test_scan_plan_forwards_own_libraries_to_that_node(db, fake_enqueue):
    """归这台节点的库：面板碰不到那些文件，只能「计划」转发（网络调用在路由层 await）"""
    realm = _realm(db)
    server = _server(db, realm, node_key="k1")
    lib = _library(db, realm, "我的库", node_id=server.id)

    plan = server_ops.scan_plan(db, server)

    assert [row["id"] for row in plan["forward"]] == [lib.id]
    assert plan["forward"][0]["node_name"] == server.name
    assert plan["forward"][0]["url"] == server.url
    assert plan["queued"] == []


def test_scan_plan_never_touches_other_nodes_libraries(db, fake_enqueue):
    """在甲的运维页点一键，不应该动乙的库"""
    realm = _realm(db)
    server = _server(db, realm, node_key="k1")
    _library(db, realm, "乙的库", node_id=_server(db, realm, "节点乙", "k2").id)

    plan = server_ops.scan_plan(db, server, include_unassigned=True)

    assert plan["queued"] == [] and plan["forward"] == [] and plan["skipped"] == []
    assert fake_enqueue == []


def test_scan_plan_none_server_matches_nothing(db, fake_enqueue):
    """BUG 文档化：传 server=None 时，node_id 非空的库一个都匹配不上。

    scope_libraries 里 assigned 按 lib.node_id == server.id 过滤，
    server=None 时 server.id 得 None，只有 node_id IS NULL 的库能中。
    生产 10 个库 node_id 全是 1，所以一键扫描返回 0 个库。
    端口（portal.scan_all_libraries_endpoint._plan）已改为传真实本机节点，
    这里锁死「传 None 就是空」这个语义，防止将来有人又传 None。
    """
    realm = _realm(db)
    server = _server(db, realm)
    _library(db, realm, "有归属的库", node_id=server.id)

    plan = server_ops.scan_plan(db, None)

    assert plan["queued"] == []
    assert plan["forward"] == []
    assert fake_enqueue == []


def test_scan_plan_real_self_node_queues_owned_libraries(db, fake_enqueue, monkeypatch):
    """回归：一键扫描必须用 self_node 拿真实本机节点，不能传 None。

    模拟 portal.scan_all_libraries_endpoint._plan 的修复后逻辑：
    node_lib.self_node(db) -> 真实 RemoteServer -> scan_plan 匹配 node_id。
    """
    realm = _realm(db)
    server = _server(db, realm, node_key="ea-01")
    lib = _library(db, realm, "国产剧", node_id=server.id)
    monkeypatch.setenv("NODE_KEY", "ea-01")
    node_lib.reset_cache()
    try:
        real_server = node_lib.self_node(db)
        assert real_server is not None, "NODE_KEY 已配，self_node 不该是 None"
        assert real_server.id == server.id
        plan = server_ops.scan_plan(db, real_server)
    finally:
        node_lib.reset_cache()

    assert [row["id"] for row in plan["queued"]] == [lib.id]
    assert plan["forward"] == []


def test_scan_plan_caps_and_says_so(db, fake_enqueue, monkeypatch):
    realm = _realm(db)
    server = _server(db, realm)
    for i in range(3):
        _library(db, realm, f"库{i}", node_id=None)
    monkeypatch.setattr(server_ops, "MAX_SCAN_LIBS", 2)

    plan = server_ops.scan_plan(db, server, include_unassigned=True)

    assert len(plan["queued"]) == 2
    assert any("上限" in row["reason"] for row in plan["skipped"])


def test_ops_scan_message_says_what_happened():
    message = servers_api._ops_scan_message(
        {"queued": [{"message": "扫描已启动"}], "already": [{"id": 2}], "skipped": []},
        forwarded=[{"id": 3}], failed=[])
    assert "1 个已开始" in message
    assert "已在队列" in message
    assert "转发" in message
    assert servers_api._ops_scan_message(
        {"queued": [], "already": [], "skipped": []}, [], []) == "没有可扫的启用库"


# ==================== 4. 路由边界 ====================

def test_ops_endpoints_reject_non_ea(db):
    realm = _realm(db)
    server = _server(db, realm, name="MoviePilot", kind="moviepilot")

    with pytest.raises(HTTPException) as excinfo:
        servers_api._ops_server(db, server.id)
    assert excinfo.value.status_code == 400
    assert "EA" in excinfo.value.detail


def test_ops_endpoints_404_on_missing_server(db):
    with pytest.raises(HTTPException) as excinfo:
        servers_api._ops_server(db, 424242)
    assert excinfo.value.status_code == 404


def test_snapshot_route_returns_payload_with_server(db):
    realm = _realm(db)
    server = _server(db, realm)
    _library(db, realm, "我的库", node_id=server.id)
    admin = models.WebUser(username="admin", password_hash="x", is_active=True)
    db.add(admin)
    db.commit()

    payload = servers_api.server_ops_snapshot(
        server.id, admin, db, include_unassigned=False, runs_limit=10)

    assert payload["server"]["name"] == server.name
    assert payload["scope"]["libraries"] == 1
    assert [lib["name"] for lib in payload["libraries"]] == ["我的库"]


def test_scan_route_forwards_and_audits(db, monkeypatch):
    realm = _realm(db)
    server = _server(db, realm, node_key="k1")
    remote = _library(db, realm, "归这台扫", node_id=server.id)
    admin = models.WebUser(username="admin", password_hash="x", is_active=True)
    db.add(admin)
    db.commit()
    forwarded: list = []

    async def fake_push_scan(url, library_id, timeout=20.0):
        forwarded.append((url, library_id))
        return {"ok": True, "data": {}}

    monkeypatch.setattr(node_lib, "push_scan", fake_push_scan)

    result = asyncio.run(servers_api.server_ops_scan(
        server.id, servers_api.ServerOpsScanRequest(include_unassigned=False),
        admin, db))

    assert result["success"] is True
    assert [row["id"] for row in result["forwarded"]] == [remote.id]
    assert forwarded and forwarded[0][1] == remote.id
    # 「谁对哪台服务器按了一键扫描」必须留在操作日志里
    logs = db.query(models.AdminLog).filter(
        models.AdminLog.action == "server_ops_scan").all()
    assert logs and logs[0].target_id == server.id
    assert logs[0].details["forwarded"] == 1


def test_scan_route_reports_forward_failure(db, monkeypatch):
    realm = _realm(db)
    server = _server(db, realm, node_key="k1")
    _library(db, realm, "归这台扫", node_id=server.id)
    admin = models.WebUser(username="admin", password_hash="x", is_active=True)
    db.add(admin)
    db.commit()

    async def fake_push_scan(url, library_id, timeout=20.0):
        return {"ok": False, "error": "无法连接节点"}

    monkeypatch.setattr(node_lib, "push_scan", fake_push_scan)

    result = asyncio.run(servers_api.server_ops_scan(
        server.id, None, admin, db))

    assert result["success"] is False
    assert result["failed"][0]["error"] == "无法连接节点"
    assert "1 个转发失败" in result["message"]


# ==================== 5. 跨库取流水的工具函数 ====================

def test_recent_scan_runs_empty_ids_short_circuits(db):
    assert scanner.recent_scan_runs(db, [], limit=10) == []
    assert scanner.recent_scan_runs(db, None, limit=10) == []


def test_recent_scan_runs_carries_library_id(db):
    realm = _realm(db)
    lib = _library(db, realm)
    _run(db, lib, status="success")

    rows = scanner.recent_scan_runs(db, [lib.id], limit=5)

    assert rows[0]["library_id"] == lib.id
    assert rows[0]["status"] == "success"


def test_recent_scan_runs_zero_limit(db):
    realm = _realm(db)
    lib = _library(db, realm)
    _run(db, lib)
    assert scanner.recent_scan_runs(db, [lib.id], limit=0) == []
