"""新片入库通知：配置 / 新增查询 / 消息组装 / 失败隔离"""
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, "/opt/aetrix-portal")

from backend import models as base_models
from backend.emby_server import models as emby_models
from backend.emby_server import new_media_notify as nmn


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    base_models.Base.metadata.create_all(engine)
    emby_models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_config(db, key, value):
    db.add(base_models.SystemConfig(key=key, value=value))
    db.commit()


def _add_staff(db, username="admin"):
    u = base_models.WebUser(username=username, password_hash="x",
                            is_staff=True, is_active=True)
    db.add(u)
    db.commit()
    return u


def _add_item(db, name, item_type, date_added, series_id=None, library_id=1):
    item = emby_models.MediaItem(
        guid=f"g-{name}-{item_type}",
        library_id=library_id,
        item_type=item_type,
        name=name,
        series_id=series_id,
        date_added=date_added,
    )
    db.add(item)
    db.commit()
    return item


# ---------- 配置 ----------

def test_config_defaults(db):
    enabled, channels = nmn._get_config(db)
    assert enabled is True
    assert channels == ["telegram"]


def test_config_disabled(db):
    _add_config(db, nmn.CONFIG_ENABLED, "0")
    enabled, _ = nmn._get_config(db)
    assert enabled is False


def test_config_custom_channels(db):
    _add_config(db, nmn.CONFIG_CHANNELS, "telegram, email")
    _, channels = nmn._get_config(db)
    assert channels == ["telegram", "email"]


def test_config_empty_channels_falls_back(db):
    _add_config(db, nmn.CONFIG_CHANNELS, " , ")
    _, channels = nmn._get_config(db)
    assert channels == ["telegram"]


# ---------- 新增汇总 ----------

def test_summarize_only_this_round(db):
    start = datetime.now()
    old = start - timedelta(hours=2)
    _add_item(db, "老剧", "series", old)
    _add_item(db, "新剧A", "series", start + timedelta(seconds=1))
    _add_item(db, "新电影B", "movie", start + timedelta(seconds=2))
    s = _add_item(db, "老剧2", "series", old)
    _add_item(db, "S01E11", "episode", start + timedelta(seconds=3), series_id=s.id)
    _add_item(db, "第2季", "season", start + timedelta(seconds=4), series_id=s.id)  # 季不通知

    summary = nmn._summarize_new_items(db, 1, start)
    assert summary is not None
    assert summary["series_movie_total"] == 2
    assert sorted(summary["series_movie_names"]) == ["新剧A", "新电影B"]
    assert summary["episode_groups"] == [("老剧2", 1)]


def test_summarize_other_library_excluded(db):
    start = datetime.now()
    _add_item(db, "别库的剧", "series", start + timedelta(seconds=1), library_id=99)
    assert nmn._summarize_new_items(db, 1, start) is None


def test_summarize_nothing_new_returns_none(db):
    assert nmn._summarize_new_items(db, 1, datetime.now()) is None


# ---------- 消息组装 ----------

def _summary(names=(), ep_groups=()):
    return {
        "series_movie_total": len(names),
        "series_movie_names": list(names),
        "episode_groups": list(ep_groups),
    }


def test_build_message_new_series_and_movies():
    title, content = nmn._build_message("动漫库", _summary(["新剧A", "新电影B"]))
    assert "动漫库" in title
    assert "新增 2 部" in content
    assert "《新剧A》" in content and "《新电影B》" in content
    assert "overview" not in content.lower()  # 只列标题，不剧透


def test_build_message_episodes_grouped_by_series():
    _, content = nmn._build_message("动漫库", _summary(ep_groups=[("老剧", 2)]))
    assert "《老剧》新增 2 集" in content


def test_build_message_truncates():
    names = [f"剧{i:02d}" for i in range(15)]
    _, content = nmn._build_message(
        "动漫库",
        {"series_movie_total": 15, "series_movie_names": names[:10],
         "episode_groups": []},
    )
    assert "新增 15 部" in content and "等 15 部" in content
    assert "《剧09》" in content and "《剧10》" not in content  # 只列前 10


def test_build_message_episode_groups_truncate():
    groups = [(f"剧{i:02d}", 1) for i in range(15)]
    _, content = nmn._build_message("动漫库", _summary(ep_groups=groups))
    assert "等 15 部剧" in content


# ---------- 入口与失败隔离 ----------

def test_maybe_notify_no_added_no_thread(monkeypatch):
    started = []

    def fake_thread(*a, **k):
        started.append(True)
        return None

    monkeypatch.setattr(nmn.threading, "Thread", fake_thread)
    nmn.maybe_notify_new_media(1, "动漫库", datetime.now(), 0)
    assert started == []


def test_maybe_notify_spawns_daemon_thread(monkeypatch):
    created = {}

    class FakeThread:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def start(self):
            created["started"] = True

    monkeypatch.setattr(nmn.threading, "Thread", FakeThread)
    nmn.maybe_notify_new_media(1, "动漫库", datetime.now(), 5)
    assert created.get("started") is True
    assert created.get("daemon") is True


def test_notify_worker_swallows_exceptions(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("tg 炸了")

    monkeypatch.setattr(nmn, "_do_notify", boom)
    # 不抛异常就是成功：通知失败绝不能影响扫描
    nmn._notify_worker(1, "动漫库", datetime.now())


def test_do_notify_disabled_sends_nothing(db, monkeypatch):
    _add_config(db, nmn.CONFIG_ENABLED, "0")
    _add_staff(db)
    monkeypatch.setattr(nmn, "SessionLocal", lambda: db)

    async def fake_send(*a, **k):
        raise AssertionError("禁用时不该发送")

    monkeypatch.setattr(nmn, "_send_to_staff", fake_send)
    nmn._do_notify(1, "动漫库", datetime.now())  # 不抛异常即通过


def test_do_notify_no_new_items_sends_nothing(db, monkeypatch):
    _add_staff(db)
    monkeypatch.setattr(nmn, "SessionLocal", lambda: db)

    async def fake_send(*a, **k):
        raise AssertionError("无新增时不该发送")

    monkeypatch.setattr(nmn, "_send_to_staff", fake_send)
    nmn._do_notify(1, "动漫库", datetime.now())


def test_do_notify_no_staff_sends_nothing(db, monkeypatch):
    start = datetime.now()
    _add_item(db, "新剧", "series", start + timedelta(seconds=1))
    monkeypatch.setattr(nmn, "SessionLocal", lambda: db)

    async def fake_send(*a, **k):
        raise AssertionError("无管理员时不该发送")

    monkeypatch.setattr(nmn, "_send_to_staff", fake_send)
    nmn._do_notify(1, "动漫库", start)


def test_do_notify_no_start_time_sends_nothing(db, monkeypatch):
    _add_staff(db)
    monkeypatch.setattr(nmn, "SessionLocal", lambda: db)

    async def fake_send(*a, **k):
        raise AssertionError("started_at 为空时不该发送")

    monkeypatch.setattr(nmn, "_send_to_staff", fake_send)
    nmn._do_notify(1, "动漫库", None)


def test_do_notify_happy_path(db, monkeypatch):
    start = datetime.now()
    _add_item(db, "新剧A", "series", start + timedelta(seconds=1))
    staff = _add_staff(db)
    staff_id = staff.id  # _do_notify 会 close session，先取值
    monkeypatch.setattr(nmn, "SessionLocal", lambda: db)

    sent = {}

    async def fake_send(staff_ids, title, content, channels):
        sent["staff_ids"] = staff_ids
        sent["title"] = title
        sent["content"] = content
        sent["channels"] = channels

    monkeypatch.setattr(nmn, "_send_to_staff", fake_send)
    nmn._do_notify(1, "动漫库", start)
    assert sent["staff_ids"] == [staff_id]
    assert "动漫库" in sent["title"]
    assert "《新剧A》" in sent["content"]
    assert sent["channels"] == ["telegram"]


# ---------- scan_queue 接线 ----------
# 策略：让 maybe_notify_new_media 的真实 guard 跑（added<=0 直接返回），
# 只把 _notify_worker 和 Thread 打桩，避免真起线程/真查库。

def _run_task_with_mocks(monkeypatch, scan_result):
    """跑一次 _run_task（扫描逻辑全打桩），返回 (task, worker_calls)。"""
    import types
    from backend.emby_server import scan_queue
    from backend.emby_server import scanner as _scanner
    from backend.emby_server import new_media_notify as _nmn
    from backend.emby_server import scan_progress as _progress

    worker_calls = []
    monkeypatch.setattr(_nmn, "_notify_worker",
                        lambda *a: worker_calls.append(a))

    class SyncThread:
        def __init__(self, target=None, args=(), **kwargs):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(_nmn.threading, "Thread", SyncThread)

    if isinstance(scan_result, Exception):
        def _raise(*a, **k):
            raise scan_result
        monkeypatch.setattr(_scanner, "scan_library_sync", _raise)
        scan_status = "failed"
    else:
        monkeypatch.setattr(_scanner, "scan_library_sync",
                            lambda *a, **k: scan_result)
        scan_status = "success"

    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return types.SimpleNamespace(id=7, name="动漫库",
                                         scan_status=scan_status)

    class _FakeSession:
        def query(self, *a, **k):
            return _FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(scan_queue, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(_progress, "begin_scan", lambda *a, **k: None)
    monkeypatch.setattr(_progress, "end_scan", lambda *a, **k: None)
    monkeypatch.setattr(_progress, "remote_stats",
                        lambda: {"lists": 0, "reused": 0})
    monkeypatch.setattr(scan_queue, "clear_progress", lambda *a, **k: None)

    task = scan_queue.ScanTask(library_id=7, name="动漫库",
                               trigger="manual", snapshot=object())
    task.started_at = datetime.now()
    scan_queue._run_task(task)
    return task, worker_calls


def test_run_task_triggers_notify_on_success_with_added(monkeypatch):
    task, worker_calls = _run_task_with_mocks(monkeypatch, {"added": 3})
    assert task.result == "success"
    assert len(worker_calls) == 1
    lib_id, lib_name, started_at = worker_calls[0]
    assert lib_id == 7 and lib_name == "动漫库" and started_at is not None


def test_run_task_no_notify_when_nothing_added(monkeypatch):
    task, worker_calls = _run_task_with_mocks(
        monkeypatch, {"added": 0, "updated": 5})
    assert task.result == "success"
    assert worker_calls == [], "无新增时不该打扰管理员"


def test_run_task_no_notify_on_failure(monkeypatch):
    task, worker_calls = _run_task_with_mocks(
        monkeypatch, RuntimeError("扫描炸了"))
    assert task.result == "failed"
    assert worker_calls == [], "扫描失败不该发入库通知"
