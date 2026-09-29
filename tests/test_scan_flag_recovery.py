"""扫描卡死状态必须能自动复位。

## 生产事故

部署打断扫描后，两个库永远停在 `is_scanning=1 / scan_status='running'`，
后台刷新一直显示「扫描中」。

## 根因

`reset_stale_scan_flags` 判定「这轮扫描是什么时候开始的」用的是
``lib.updated_at``——但进度刷盘 ``scan_queue.flush_once`` 每几秒写一次
``scan_progress``，ORM 的 ``onupdate`` 会连带刷新 ``updated_at``。于是它永远是
「刚刚」，超时判定恒不成立，**卡死状态自我维持**，永远复位不了。

修法：新增 ``scan_started_at``（扫描开始时一次性写入，之后任何写入都不碰它），
复位只认这个字段。
"""
import importlib
import os
import tempfile
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
_fd, _tmp = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"

from backend import database as _dbmod  # noqa: E402
from sqlalchemy import create_engine as _ce  # noqa: E402
from sqlalchemy.orm import sessionmaker as _sm  # noqa: E402

_dbmod.engine = _ce(os.environ["DATABASE_URL"])
_dbmod.configure_session_local(_sm(bind=_dbmod.engine))

from backend.database import init_db  # noqa: E402

init_db()

import pytest  # noqa: E402

from backend.emby_server import models as em  # noqa: E402


def _mt():
    return importlib.import_module("backend.emby_server.maintenance")


@pytest.fixture()
def db():
    from backend import models as base_models
    engine = _ce("sqlite:///:memory:")
    original = _dbmod.SessionLocal
    _dbmod.configure_session_local(_sm(bind=engine))
    base_models.Base.metadata.create_all(bind=engine)
    em.Base.metadata.create_all(bind=engine)
    session = _dbmod.SessionLocal()
    try:
        yield session
    finally:
        session.close()
        _dbmod.configure_session_local(original)
        engine.dispose()


def _stuck(db, started_hours_ago, updated_now=False):
    lib = em.Library(guid="L" * 32, name="库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    lib.is_scanning = True
    lib.scan_status = "running"
    lib.scan_started_at = datetime.now() - timedelta(hours=started_hours_ago)
    lib.updated_at = datetime.now() if updated_now else datetime.now() - timedelta(
        hours=started_hours_ago)
    db.commit()
    return lib


def test_resets_when_started_long_ago_even_if_updated_now(db, monkeypatch):
    """核心回归：updated_at 一直被刷新，也不能阻止复位"""
    mt = _mt()
    monkeypatch.setattr("backend.emby_server.scanner.is_scan_active", lambda i: False)
    _stuck(db, 10, updated_now=True)  # 扫描 10 小时前开始，但 updated_at 是刚刚
    n = mt.reset_stale_scan_flags(db, stale_hours=6)
    db.commit()
    assert n == 1, "updated_at 刷新的卡死库必须被复位"


def test_keeps_recent_scan(db, monkeypatch):
    """刚开始不久的不能碰（可能正在另一台机器上扫）"""
    mt = _mt()
    monkeypatch.setattr("backend.emby_server.scanner.is_scan_active", lambda i: False)
    lib = _stuck(db, 1)
    assert mt.reset_stale_scan_flags(db, stale_hours=6) == 0
    db.commit()
    assert lib.is_scanning is True


def test_skip_active_scan_in_this_process(db, monkeypatch):
    """本进程真的在扫的库：绝不碰"""
    mt = _mt()
    monkeypatch.setattr("backend.emby_server.scanner.is_scan_active", lambda i: True)
    _stuck(db, 20)
    assert mt.reset_stale_scan_flags(db, stale_hours=6) == 0


def test_legacy_row_without_started_at(db, monkeypatch):
    """老数据没有 scan_started_at：退回 updated_at，至少能复位"""
    mt = _mt()
    monkeypatch.setattr("backend.emby_server.scanner.is_scan_active", lambda i: False)
    lib = em.Library(guid="M" * 32, name="老库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    lib.is_scanning = True
    lib.scan_status = "running"
    lib.scan_started_at = None
    lib.updated_at = datetime.now() - timedelta(hours=20)
    db.commit()
    assert mt.reset_stale_scan_flags(db, stale_hours=6) == 1
    db.commit()
    assert lib.is_scanning is False
    assert lib.scan_status == "failed"


def test_resets_immediately_when_redis_says_nobody_claimed(db, monkeypatch):
    """队列可读且没人领 → 立即复位，不再等 6 小时阈值

    这是部署卡死的真凶：每部署一次，进行中的扫描被 SIGTERM 杀死，
    库永远停在「扫描中」。生产实测每次部署后都有库卡住。
    """
    mt = _mt()
    monkeypatch.setattr("backend.emby_server.scanner.is_scan_active", lambda i: False)
    monkeypatch.setattr(mt, "_redis_queue_readable", lambda: True)
    monkeypatch.setattr(mt, "_library_claimed_elsewhere", lambda i: False)
    lib = _stuck(db, 0.01, updated_now=True)  # 刚"开始"，但队列里没人领
    assert mt.reset_stale_scan_flags(db, stale_hours=6) == 1
    db.commit()
    assert lib.is_scanning is False


def test_does_not_reset_when_claimed_in_redis(db, monkeypatch):
    """库还在 Redis 队列里 → 有 worker 领了，别碰（多机部署）"""
    mt = _mt()
    monkeypatch.setattr("backend.emby_server.scanner.is_scan_active", lambda i: False)
    monkeypatch.setattr(mt, "_redis_queue_readable", lambda: True)
    monkeypatch.setattr(mt, "_library_claimed_elsewhere", lambda i: True)
    _stuck(db, 20)
    assert mt.reset_stale_scan_flags(db, stale_hours=6) == 0


def test_redis_unreadable_falls_back_to_time_threshold(db, monkeypatch):
    """Redis 读不到时退回时间判定：老的才复位，保守不误伤"""
    mt = _mt()
    monkeypatch.setattr("backend.emby_server.scanner.is_scan_active", lambda i: False)
    monkeypatch.setattr(mt, "_redis_queue_readable", lambda: False)
    recent = _stuck(db, 1)
    assert mt.reset_stale_scan_flags(db, stale_hours=6) == 0
    db.commit()
    assert recent.is_scanning is True
