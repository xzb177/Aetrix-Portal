"""健康检查必须反映真实故障，不能永远 healthy。

生产事故：刮削链整条挂掉（3117 个 series 搜不到、worker 刷几千条探测失败），
而「服务健康」页一片绿——``/api/health`` 的 ``status`` 是**硬编码常量**
``"healthy"``。出问题时没人能从页面看到，只能去翻日志。

口径见 backend/health_report.py。三档：ok / warn / down。
"""
import os
import tempfile
from types import SimpleNamespace

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

from backend import health_report  # noqa: E402
from backend.emby_server import models as em  # noqa: E402


@pytest.fixture()
def db():
    """自建库 + 用完还原，不依赖测试执行顺序"""
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


def _items(db, n, item_type="movie", probe="done", enrich="done", lib=None):
    lib = lib or em.Library(guid="L" * 32, name="库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    for i in range(n):
        db.add(em.MediaItem(guid=f"{i:032d}", library_id=lib.id, item_type=item_type,
                            name=f"条目{i}", probe_status=probe, enrich_status=enrich))
    db.flush()


def test_healthy_when_everything_fine(db, monkeypatch):
    monkeypatch.setattr(health_report, "_count", lambda db, t, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "_enrich_count", lambda db, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "library_scan_summary", lambda db: {"failed": 0})
    monkeypatch.setattr("backend.emby_server.maintenance.resource_report",
                        lambda: {"disk_free_percent": 80.0, "transcode_sessions": 0})
    res = health_report.collect(db)
    assert res["level"] == "ok", res
    assert res["status"] == "healthy"
    assert res["issues"] == [], res


def test_warns_on_high_probe_failure_rate(db, monkeypatch):
    """探测大面积失败（今天真实发生过的：ffprobe 刷屏）必须 warn"""
    monkeypatch.setattr(health_report, "_count", lambda db, t, s: 10 if s == "done" else 40)
    monkeypatch.setattr(health_report, "_enrich_count", lambda db, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "library_scan_summary", lambda db: {"failed": 0})
    monkeypatch.setattr("backend.emby_server.maintenance.resource_report",
                        lambda: {"disk_free_percent": 80.0, "transcode_sessions": 0})
    res = health_report.collect(db)
    assert res["level"] == "warn", res
    assert any(i["key"] == "probe" for i in res["issues"]), res


def test_down_on_enqueue_backlog(db, monkeypatch):
    """补全队列堆积到处理不过来 = 核心不可用"""
    counts = {"done": 100, "failed": 0, "pending": 900, "enriching": 100}
    monkeypatch.setattr(health_report, "_count", lambda db, t, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "_enrich_count", lambda db, s: counts.get(s, 0))
    monkeypatch.setattr(health_report, "library_scan_summary", lambda db: {"failed": 0})
    monkeypatch.setattr("backend.emby_server.maintenance.resource_report",
                        lambda: {"disk_free_percent": 80.0, "transcode_sessions": 0})
    res = health_report.collect(db)
    assert res["level"] == "down", res
    assert res["status"] == "unhealthy"
    assert any(i["key"] == "enrich_backlog" for i in res["issues"]), res


def test_warns_on_library_scan_failure(db, monkeypatch):
    """某个库扫描失败要在健康里露出来（今天「动漫」库扫描超时就是这么发现的）"""
    monkeypatch.setattr(health_report, "_count", lambda db, t, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "_enrich_count", lambda db, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "library_scan_summary", lambda db: {
        "failed": 1, "last_failed": [{"name": "动漫", "error": "timed out"}]})
    monkeypatch.setattr("backend.emby_server.maintenance.resource_report",
                        lambda: {"disk_free_percent": 80.0, "transcode_sessions": 0})
    res = health_report.collect(db)
    assert res["level"] == "warn", res
    assert any("动漫" in i["message"] for i in res["issues"]), res


def test_small_sample_does_not_warn(db, monkeypatch):
    """刚开机样本少时不该误报"""
    monkeypatch.setattr(health_report, "_count", lambda db, t, s: 3 if s == "failed" else 1)
    monkeypatch.setattr(health_report, "_enrich_count", lambda db, s: 1 if s == "done" else 0)
    monkeypatch.setattr(health_report, "library_scan_summary", lambda db: {"failed": 0})
    monkeypatch.setattr("backend.emby_server.maintenance.resource_report",
                        lambda: {"disk_free_percent": 80.0, "transcode_sessions": 0})
    res = health_report.collect(db)
    assert res["level"] == "ok", res


def test_collect_never_raises_on_broken_db():
    """健康检查本身不能抛 —— 它是最该一直可用的一环"""
    class _Broken:
        def query(self, *a, **k):
            raise RuntimeError("db down")

        def execute(self, *a, **k):
            raise RuntimeError("db down")

    res = health_report.collect(_Broken())
    assert res["level"] in ("warn", "down"), res
    assert res["issues"], res


def _backlog_items(db, n_pending, recent_touch=True):
    """造 n_pending 条积压；recent_touch=True 时 date_modified 为现在（模拟 worker 在干活）"""
    from datetime import datetime, timedelta
    lib = em.Library(guid="B" * 32, name="积压库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    touched = datetime.now() if recent_touch else datetime.now() - timedelta(hours=2)
    for i in range(n_pending):
        item = em.MediaItem(guid=f"b{i:032d}", library_id=lib.id, item_type="movie",
                            name=f"积压{i}", probe_status="done", enrich_status="pending")
        db.add(item)
        db.flush()
        # date_modified 有 onupdate 但 bulk 场景下显式赋值更可靠
        item.date_modified = touched
    db.flush()
    # 必须 commit：health_report.collect() 内部会调 db.rollback()
    #（status_snapshot 的自保），不提交测试数据会被回滚掉。
    # 生产环境 worker 都是 commit 后才可见，这里模拟的是已提交状态。
    db.commit()


def test_no_false_stall_when_worker_is_active(db, monkeypatch):
    """worker 在干活（DB 最近有更新）时，即使积压大也不应报 enrich_stalled。

    回归：旧实现用进程内 throughput() 计数器，/api/health 跑在 api 进程、
    worker 跑在 worker 进程，跨进程永远读到 0，导致恒误报。
    """
    counts = {"done": 100, "failed": 0, "pending": 900, "enriching": 100}
    monkeypatch.setattr(health_report, "_count", lambda db, t, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "_enrich_count", lambda db, s: counts.get(s, 0))
    monkeypatch.setattr(health_report, "library_scan_summary", lambda db: {"failed": 0})
    monkeypatch.setattr("backend.emby_server.maintenance.resource_report",
                        lambda: {"disk_free_percent": 80.0, "transcode_sessions": 0})
    _backlog_items(db, 100, recent_touch=True)
    res = health_report.collect(db)
    # 积压本身仍是 down（阈值设计如此），但不能再有“没在跑”的误报
    assert not any(i["key"] in ("enrich_stalled", "enrich_no_progress") for i in res["issues"]), res
    assert res["metrics"]["enrich_done_per_min"] > 0, res["metrics"]


def test_stalled_when_db_silent(db, monkeypatch):
    """DB 近 10 分钟无任何更新 + 大积压 = 真卡死，应报 enrich_stalled（down）"""
    counts = {"done": 100, "failed": 0, "pending": 900, "enriching": 100}
    monkeypatch.setattr(health_report, "_count", lambda db, t, s: 20 if s == "done" else 0)
    monkeypatch.setattr(health_report, "_enrich_count", lambda db, s: counts.get(s, 0))
    monkeypatch.setattr(health_report, "library_scan_summary", lambda db: {"failed": 0})
    monkeypatch.setattr("backend.emby_server.maintenance.resource_report",
                        lambda: {"disk_free_percent": 80.0, "transcode_sessions": 0})
    _backlog_items(db, 100, recent_touch=False)
    res = health_report.collect(db)
    assert res["level"] == "down", res
    assert any(i["key"] == "enrich_stalled" for i in res["issues"]), res
