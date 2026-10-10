"""追新快照 diff / 源状态 / 单例锁的单元测试（P0-2 + P1-1 + P1-2）。

全部用内存 SQLite，不碰网络与生产库。
"""
import os
from datetime import datetime, timezone
from unittest import mock

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models as base_models
from backend.emby_server import change_watcher as cw
from backend.emby_server import models as em


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    base_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _rows(db, lib_id=7, skey="mount://3"):
    return db.query(em.ChaseFileSnapshot).filter(
        em.ChaseFileSnapshot.library_id == lib_id,
        em.ChaseFileSnapshot.source_key == skey).all()


# ---------------------------------------------------------------------------
# _diff_against_snapshot
# ---------------------------------------------------------------------------

def test_diff_baseline_inserts_but_returns_empty(db):
    """首次建基线：全量插入但返回空（防部署后扫描风暴）。"""
    changed = cw._diff_against_snapshot(db, 7, "mount://3", [
        ("/a.mkv", 100, 1000.0),
        ("/b.mkv", 200, 2000.0),
    ])
    assert changed == []
    assert len(_rows(db)) == 2


def test_diff_detects_new_changed_and_ignores_unchanged(db):
    """新增 / 变更 / 未变三种情况一次覆盖。"""
    cw._diff_against_snapshot(db, 7, "mount://3", [
        ("/a.mkv", 100, 1000.0),
        ("/b.mkv", 200, 2000.0),
    ])
    changed = cw._diff_against_snapshot(db, 7, "mount://3", [
        ("/a.mkv", 100, 1000.0),   # 未变
        ("/b.mkv", 250, 2000.0),   # size 变化
        ("/c.mkv", 300, 3000.0),   # 新增
    ])
    assert sorted(changed) == ["/b.mkv", "/c.mkv"]
    # b 的快照行已更新
    row = [r for r in _rows(db) if r.rel_path == "/b.mkv"][0]
    assert row.size == 250
    assert len(_rows(db)) == 3


def test_diff_mod_ts_change_detected(db):
    """同名文件被覆盖（size 相同但 mtime 变化）也算变更。"""
    cw._diff_against_snapshot(db, 7, "mount://3", [("/a.mkv", 100, 1000.0)])
    changed = cw._diff_against_snapshot(db, 7, "mount://3", [("/a.mkv", 100, 1001.0)])
    assert changed == ["/a.mkv"]


def test_diff_baseline_disabled_reports_everything(db):
    """baseline_if_empty=False 时首轮即上报（调用方可按需选择）。"""
    changed = cw._diff_against_snapshot(db, 7, "mount://3", [("/a.mkv", 100, 1000.0)],
                                        baseline_if_empty=False)
    assert changed == ["/a.mkv"]


def test_diff_is_per_library(db):
    """快照按 (library_id, source_key) 隔离：两个库共享同一挂载不串味。"""
    cw._diff_against_snapshot(db, 7, "mount://3", [("/a.mkv", 100, 1000.0)])
    changed = cw._diff_against_snapshot(db, 8, "mount://3", [("/a.mkv", 100, 1000.0)])
    assert changed == []  # 库 8 的首次 → 建基线


# ---------------------------------------------------------------------------
# _touch_source_state
# ---------------------------------------------------------------------------

def test_source_state_failure_counts_and_ok_resets(db):
    cw._touch_source_state(db, "mount://3", False, error="boom")
    cw._touch_source_state(db, "mount://3", False, error="boom again")
    st = cw._get_source_state(db, "mount://3")
    assert st.consec_failures == 2
    assert st.last_error == "boom again"

    cw._touch_source_state(db, "mount://3", True)
    st = cw._get_source_state(db, "mount://3")
    assert st.consec_failures == 0
    assert st.last_error == ""
    assert st.last_ok_at is not None


def test_source_state_error_truncated(db):
    cw._touch_source_state(db, "mount://3", False, error="x" * 1000)
    st = cw._get_source_state(db, "mount://3")
    assert len(st.last_error) == 500


def test_source_state_snapshot_now(db):
    cw._touch_source_state(db, "mount://3", True, snapshot_now=True)
    st = cw._get_source_state(db, "mount://3")
    assert st.last_snapshot_at is not None


# ---------------------------------------------------------------------------
# advisory lock（P1-2 单例）
# ---------------------------------------------------------------------------

def test_try_advisory_lock_sqlite_fallback(db):
    """sqlite 没有 pg_try_advisory_lock → 降级为进程内锁：第一次拿到，
    第二次拿不到（非阻塞）。"""
    assert cw._try_advisory_lock(db) is True
    assert cw._try_advisory_lock(db) is False
    # 清理：把降级锁还回去，避免污染别的测试
    cw._LOCAL_ADVISORY_LOCK.release()


def test_try_advisory_lock_pg_path(monkeypatch):
    """PG 路径：pg_try_advisory_lock 返回 True/False 照单全收。"""
    db = mock.MagicMock()
    db.execute.return_value.first.return_value = (True,)
    assert cw._try_advisory_lock(db) is True
    db.execute.return_value.first.return_value = (False,)
    assert cw._try_advisory_lock(db) is False
    # SQL 文本里确实用了 pg_try_advisory_lock
    sql = str(db.execute.call_args[0][0])
    assert "pg_try_advisory_lock" in sql


def test_maybe_check_once_skips_without_lock(monkeypatch):
    """拿不到锁 → _check_once 不跑（api/worker 双容器只跑一份）。"""
    monkeypatch.setattr(cw, "SessionLocal", lambda: mock.MagicMock())
    monkeypatch.setattr(cw, "_try_advisory_lock", lambda db: False)
    check = mock.MagicMock()
    monkeypatch.setattr(cw, "_check_once", check)
    cw._maybe_check_once()
    check.assert_not_called()


def test_maybe_check_once_runs_with_lock(monkeypatch):
    monkeypatch.setattr(cw, "SessionLocal", lambda: mock.MagicMock())
    monkeypatch.setattr(cw, "_try_advisory_lock", lambda db: True)
    check = mock.MagicMock()
    monkeypatch.setattr(cw, "_check_once", check)
    cw._maybe_check_once()
    check.assert_called_once()
