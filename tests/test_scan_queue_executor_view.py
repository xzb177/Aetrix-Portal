"""扫描队列面板：执行扫描的不是本进程时，两列从库里合成。

真实背景（v2.41 拆分扫描 + #244 修好角色注入之后暴露）：

* v2.41 把扫描从 API 进程搬到 worker 执行，`enqueue()` 在 API 角色下改成推 Redis；
* 于是 API 进程里的 `_RUNNING` / `_HISTORY` **结构上永远是空的**——
  管理端「扫描队列」面板的「正在扫描」「最近完成」两列整片空白，
  空闲时连整个卡片都不显示（只剩 Redis 的「排队中」）；
* 而库里的 `Library.scan_status` / `scan_progress` / `last_scan_at` 是跨进程的：
  worker 每 `SCAN_PROGRESS_FLUSH_SECONDS` 秒刷进度、结束时写结果。

这里钉住四件事：

1. API 角色 + Redis 桥接可用时，`running` / `history` 从库里合成（`via="db"`）；
2. 本进程就是执行者（单体 / worker）时**不查库**，仍以进程内队列为准——
   否则同一轮扫描会显示两遍、历史会被库里的行顶成两倍长；
3. Redis 排队项补上库名（Redis 里只存 library_id / trigger）；
4. 读库失败时退化返回，不让每 3 秒一次的轮询接口 500。
"""
import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.emby_server import models as em
from backend.emby_server import scan_queue
from backend.emby_server import scan_queue_redis as rq


# ==================== 替身 ====================

class FakeRedis:
    """只用得到 lrange / llen 的排队队列替身"""

    def __init__(self, items=()):
        self.lists = {rq.REDIS_SCAN_QUEUE_KEY: list(items)}

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    def llen(self, key):
        return len(self.lists.get(key, []))


@pytest.fixture()
def sessions(monkeypatch, tmp_path):
    """独立 sqlite + 只打桩 `scan_queue.SessionLocal`（不动全局 engine）"""
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    em.Library.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scan_queue, "SessionLocal", factory)
    yield factory
    engine.dispose()
    scan_queue.reset_for_tests()


@pytest.fixture()
def as_api(monkeypatch):
    """把本进程伪装成 API 角色 + Redis 桥接可用（执行扫描的是 worker）"""
    monkeypatch.setattr(scan_queue, "AETRIX_ROLE", "api")
    monkeypatch.setattr(rq, "_redis", lambda: FakeRedis())
    return scan_queue


def _library(db, name, **kwargs):
    lib = em.Library(guid=f"guid-{name}", name=name, paths="", **kwargs)
    db.add(lib)
    db.commit()
    return lib


def _running_progress(processed=120, phase="processing"):
    return json.dumps({
        "library_id": 0, "phase": phase, "phase_label": "处理条目",
        "enumerated": 400, "processed": processed, "current": "/media/剧集",
        "elapsed_ms": 12_000, "started_at": "2026-10-01T03:00:00",
        "remote_lists": 7, "remote_reused": 3,
    }, ensure_ascii=False)


# ==================== 1. API 进程：两列从库里合成 ====================

def test_running_and_history_come_from_db_in_api_role(sessions, as_api):
    with sessions() as db:
        _library(
            db, "云海电影",
            scan_status="running",
            scan_started_at=datetime.now() - timedelta(seconds=90),
            scan_progress=_running_progress(),
            is_scanning=True,
        )
        _library(
            db, "已完成电影",
            scan_status="success",
            last_scan_at=datetime.now() - timedelta(minutes=5),
            scan_stats=json.dumps({"duration_ms": 65_000}),
        )
        _library(
            db, "失败剧集",
            scan_status="failed",
            scan_error="WebDAV 超时",
            last_scan_at=datetime.now() - timedelta(minutes=1),
            scan_stats=json.dumps({"duration_ms": 3_000}),
        )
        # 从没扫过的库不该出现在任何一列
        _library(db, "还没扫过")

    data = as_api.snapshot()

    assert data["view"] == "db", "API 进程看不到 worker 的内存队列，必须标成库里合成"
    assert [t["name"] for t in data["running"]] == ["云海电影"]
    running = data["running"][0]
    assert running["state"] == "running"
    assert running["via"] == "db"
    # 进度快照原样带过去：阶段 / 已处理 / 当前目录 / 本轮远程请求
    assert running["progress"]["phase_label"] == "处理条目"
    assert running["progress"]["processed"] == 120
    assert running["progress"]["current"] == "/media/剧集"
    assert running["remote_lists"] == 7 and running["remote_reused"] == 3
    assert running["duration_ms"] >= 90_000

    # 最近完成：按完成时间倒序（失败的那条在前），结果/耗时/原因都从库里来
    assert [t["name"] for t in data["history"]] == ["失败剧集", "已完成电影"]
    failed, done = data["history"]
    assert failed["state"] == "failed" and failed["result"] == "failed"
    assert failed["error"] == "WebDAV 超时"
    assert done["state"] == "done" and done["result"] == "success"
    assert done["duration_ms"] == 65_000
    assert all(t["via"] == "db" for t in data["history"])
    # 库里不留触发方：面板显示「—」，不编一个
    assert data["history"][0]["trigger"] == ""


def test_history_is_capped_by_queue_history(sessions, as_api):
    """最近完成只保留 SCAN_QUEUE_HISTORY 条（与进程内历史同一个上限）"""
    keep = scan_queue.SCAN_QUEUE_HISTORY
    with sessions() as db:
        for index in range(keep + 5):
            _library(db, f"库{index}",
                     scan_status="success",
                     last_scan_at=datetime.now() - timedelta(minutes=index))

    data = as_api.snapshot()
    assert len(data["history"]) == keep
    assert data["history"][0]["name"] == "库0", "最新的应排在最前"


# ==================== 2. 本进程就是执行者：不查库 ====================

def test_local_executor_ignores_db_view(monkeypatch, sessions):
    """单体 / worker 角色下仍以进程内队列为准：库里同一轮不能被再报一遍"""
    monkeypatch.setattr(scan_queue, "AETRIX_ROLE", "worker")
    with sessions() as db:
        # 库里标着 running / 有完成记录，但本进程正在扫的是另一个库
        _library(db, "别的节点在扫", scan_status="running",
                 scan_started_at=datetime.now(), is_scanning=True)
        _library(db, "上一轮", scan_status="success", last_scan_at=datetime.now())

    task = scan_queue.ScanTask(library_id=1, name="本地在扫", trigger="manual",
                               state=scan_queue.STATE_RUNNING)
    history_task = scan_queue.ScanTask(library_id=2, name="本地刚跑完", trigger="manual",
                                       state=scan_queue.STATE_DONE, result="success")
    with scan_queue._COND:
        scan_queue._RUNNING[1] = task
        scan_queue._HISTORY.append(history_task)

    data = scan_queue.snapshot()
    assert data["view"] == "panel"
    assert [t["library_id"] for t in data["running"]] == [1]
    assert [t["library_id"] for t in data["history"]] == [2]
    assert "via" not in data["running"][0], "进程内任务不该被标成库里合成"


def test_api_role_without_redis_keeps_local_queue(monkeypatch, sessions):
    """API 角色但 Redis 不可用（enqueue 回退进程内队列）：仍以进程内队列为准"""
    monkeypatch.setattr(scan_queue, "AETRIX_ROLE", "api")
    monkeypatch.setattr(rq, "_redis", lambda: None)
    with sessions() as db:
        _library(db, "库里的 running", scan_status="running",
                 scan_started_at=datetime.now())

    data = scan_queue.snapshot()
    assert data["view"] == "panel"
    assert data["running"] == []


# ==================== 3. Redis 排队项补库名 ====================

def test_redis_waiting_items_get_library_names(sessions, monkeypatch):
    """Redis 里只有 library_id / trigger：「排队中」列不能只有位置没有名字"""
    monkeypatch.setattr(scan_queue, "AETRIX_ROLE", "api")
    with sessions() as db:
        lib = _library(db, "排队中的库", scan_status="running",
                       scan_started_at=datetime.now())
        lib_id = lib.id
    payload = json.dumps({"library_id": lib_id, "trigger": "repair"})
    monkeypatch.setattr(rq, "_redis", lambda: FakeRedis([payload]))

    data = scan_queue.snapshot()
    assert len(data["waiting"]) == 1
    waiting = data["waiting"][0]
    assert waiting["name"] == "排队中的库"
    assert waiting["trigger"] == "repair"
    assert waiting["position"] == 1
    assert waiting["via"] == "redis"


# ==================== 4. 读库失败不能把接口打成 500 ====================

def test_db_failure_degrades_instead_of_raising(monkeypatch):
    """库里合成失败 → 两列退化为空，排队项照旧返回"""
    monkeypatch.setattr(scan_queue, "AETRIX_ROLE", "api")
    monkeypatch.setattr(rq, "_redis", lambda: FakeRedis(
        [json.dumps({"library_id": 1, "trigger": "manual"})]))

    def boom():
        raise RuntimeError("数据库暂时不可用")

    monkeypatch.setattr(scan_queue, "SessionLocal", boom)
    data = scan_queue.snapshot()
    assert data["running"] == [] and data["history"] == []
    assert data["view"] == "db"
    assert [t["library_id"] for t in data["waiting"]] == [1]
