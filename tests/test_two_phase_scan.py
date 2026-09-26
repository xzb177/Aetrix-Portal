"""两阶段扫描（v2.39.0）：Phase 1 秒扫入库 + Phase 2 后台探测。

- Phase 1（background 模式）：入库不调 ffprobe，需要探测的条目标
  probe_status='pending'（新文件 priority=100）；
- Phase 1（inline 模式，默认）：行为与旧一致，探测完标 done；
- Phase 2 worker：按优先级抢单、成功落库、失败指数退避、超限转 failed；
- 按需插队 boost：pending/failed → 提到队首，done → 不排队；
- 迁移兜底：已有有效探测数据的旧行直接标 done，不发网络请求。
"""
import os
import tempfile

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
# 独立临时 DB：避免与其它测试文件共用导致数据污染。
# 注意：backend.database.engine 是模块级单例，必须重建，否则会沿用先导入文件的 DB。
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
# backend.database.engine 是模块级单例：后导入的测试文件必须重建 engine，
# 否则会沿用先导入文件的 DB，导致测试间污染。只重建 engine/SessionLocal，
# 不 reload 整个模块（避免 models.Base 元数据错乱）。
from backend import database as _dbmod
from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker as _sm
_dbmod.engine = _ce(os.environ["DATABASE_URL"])
_dbmod.SessionLocal = _sm(bind=_dbmod.engine)

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import pytest

from backend.database import SessionLocal, engine, init_db
from backend.emby_server import models as em
from backend.emby_server import probe_worker
from backend.emby_server import scanner

init_db()

VALID_PROBE = {
    "duration_ticks": 3600 * 10_000_000,
    "bitrate": 8000,
    "width": 1920,
    "height": 1080,
    "video_codec": "H264",
    "audio_codec": "AAC",
    "audio_languages": "eng",
    "subtitle_languages": "",
    "size": 12345678,
    "streams": [
        {"stream_index": 0, "stream_type": "Video", "codec": "h264",
         "language": "", "display_title": None, "title": None,
         "channels": None, "bit_rate": 8000},
    ],
}


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _guid():
    return uuid.uuid4().hex


def _make_item(db, priority=0, status="pending", duration=0, item_type="movie"):
    lib = em.Library(guid=_guid(), name="探测测试库", collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    item = em.MediaItem(
        guid=_guid(), library_id=lib.id, item_type=item_type,
        name="测试条目", file_path=f"/tmp/nonexistent_{_guid()}.mp4",
        probe_status=status, probe_priority=priority,
        duration_ticks=duration,
        last_probed_at=datetime.now() if duration else None,
    )
    db.add(item)
    db.flush()
    return lib, item


def _cleanup(db, lib):
    item_ids = [r[0] for r in db.query(em.MediaItem.id).filter(
        em.MediaItem.library_id == lib.id).all()]
    if item_ids:
        db.query(em.MediaStream).filter(
            em.MediaStream.item_id.in_(item_ids)).delete(
                synchronize_session=False)
    db.query(em.MediaItem).filter(em.MediaItem.library_id == lib.id).delete(
        synchronize_session=False)
    db.query(em.Library).filter(em.Library.id == lib.id).delete()
    db.commit()


# ---------- 迁移 ----------

def test_migration_adds_probe_columns_and_index(db):
    from sqlalchemy import inspect

    cols = {c["name"] for c in inspect(engine).get_columns("emby_items")}
    assert {"probe_status", "probe_priority", "probe_attempts",
            "probe_next_retry_at"} <= cols
    idx = {i["name"] for i in inspect(engine).get_indexes("emby_items")}
    assert "idx_item_probe" in idx


# ---------- Phase 1 ----------

def _scan_one_file(tmp_path, monkeypatch, background: bool, probe_impl):
    """在临时目录放一个假电影文件，跑一轮扫描，返回 (item, probe_calls)。"""
    calls = []
    if background:
        def boom(*a, **k):
            calls.append(1)
            raise AssertionError("background 模式不应调用 ffprobe")
        monkeypatch.setattr(scanner, "probe_metadata", boom)
    else:
        def fake_probe(*a, **k):
            calls.append(1)
            return dict(probe_impl)
        monkeypatch.setattr(scanner, "probe_metadata", fake_probe)
    monkeypatch.setattr(scanner, "PROBE_BACKGROUND", background)
    # v2.40 分层扫描默认开启，会推迟探测；这里测的是 v2.39 两阶段契约，显式关闭分层
    monkeypatch.setattr(scanner, "SCAN_LAYERED", False)

    movie = tmp_path / "Test Movie (2024).mp4"
    movie.write_bytes(b"\x00" * 64)
    db = SessionLocal()
    lib = em.Library(guid=_guid(), name="两阶段测试库",
                     collection_type="movies", paths=str(tmp_path))
    db.add(lib)
    db.commit()
    try:
        scanner.scan_library_sync(db, lib)
        item = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib.id,
            em.MediaItem.item_type == "movie").first()
        assert item is not None
        # 快照：finally 里会清库 + 关 session，ORM 对象随后即 detach
        snap = SimpleNamespace(probe_status=item.probe_status,
                               probe_priority=item.probe_priority,
                               duration_ticks=item.duration_ticks or 0,
                               video_codec=item.video_codec)
        return snap, calls
    finally:
        _cleanup(db, lib)
        db.close()


def test_phase1_background_marks_pending_without_probe(tmp_path, monkeypatch):
    item, calls = _scan_one_file(tmp_path, monkeypatch, True, VALID_PROBE)
    assert calls == [], "background 模式下 ffprobe 一次都不能调"
    assert item.probe_status == "pending"
    assert item.probe_priority == 100  # 新文件优先
    assert not item.duration_ticks  # Phase 1 不写时长


def test_phase1_inline_probes_like_before(tmp_path, monkeypatch):
    item, calls = _scan_one_file(tmp_path, monkeypatch, False, VALID_PROBE)
    assert len(calls) == 1, "inline 模式应照常探测一次"
    assert item.probe_status == "done"
    assert item.duration_ticks == VALID_PROBE["duration_ticks"]
    assert item.video_codec == "H264"


def test_phase1_tvshow_episode_pending_series_done(tmp_path, monkeypatch):
    """剧集库：集标 pending 进队列，剧/季直接 done（无文件可探测）。"""
    monkeypatch.setattr(scanner, "PROBE_BACKGROUND", True)
    monkeypatch.setattr(scanner, "probe_metadata",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("background 不应探测")))
    show_dir = tmp_path / "测试剧 (2024)" / "Season 01"
    show_dir.mkdir(parents=True)
    (show_dir / "测试剧.S01E01.mp4").write_bytes(b"\x00" * 64)
    db = SessionLocal()
    lib = em.Library(guid=_guid(), name="两阶段剧集库",
                     collection_type="tvshows", paths=str(tmp_path))
    db.add(lib)
    db.commit()
    try:
        scanner.scan_library_sync(db, lib)
        rows = {r.item_type: r.probe_status for r in db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib.id).all()}
        assert rows.get("episode") == "pending"
        assert rows.get("series") == "done"
        assert rows.get("season") == "done"
    finally:
        _cleanup(db, lib)
        db.close()


# ---------- Phase 2 worker ----------

def test_worker_claims_by_priority_desc(db):
    # 注意：CI 里 pytest 之前会先跑一堆 smoke 脚本，共用同一个测试 DB，
    # 它们创建的 MediaItem 也会是 probe_status='pending'。断言只看“自己这 3 条
    # 在抢单结果里的相对顺序”，不假设库里没有残留数据。
    libs_items = [_make_item(db, priority=p) for p in (0, 50, 100)]
    db.commit()
    mine = {item.id for _, item in libs_items}
    try:
        ids = probe_worker._claim_batch(db, 100)
        mine_in_order = [i for i in ids if i in mine]
        assert len(mine_in_order) == 3, "自己的 3 条都应被抢到"
        prios = [db.query(em.MediaItem.probe_priority).filter(
            em.MediaItem.id == i).scalar() for i in mine_in_order]
        assert prios == [100, 50, 0]
        # 自己这 3 条已是 probing：再抢一次，不应再出现它们
        ids2 = probe_worker._claim_batch(db, 100)
        assert not (set(ids2) & mine), "已抢占的不应重复抢到"
    finally:
        for lib, _ in libs_items:
            _cleanup(db, lib)


def test_worker_probe_success_writes_fields_and_streams(db, monkeypatch):
    lib, item = _make_item(db, priority=100)
    db.commit()
    monkeypatch.setattr(probe_worker, "_rate_limiter",
                        SimpleNamespace(acquire=lambda: None))
    monkeypatch.setattr(
        probe_worker, "resolve_play_target",
        lambda path, db: SimpleNamespace(value="http://x/f.mp4", headers={}))
    monkeypatch.setattr(probe_worker, "probe_metadata",
                        lambda *a, **k: dict(VALID_PROBE))
    try:
        db.query(em.MediaItem).filter(em.MediaItem.id == item.id).update(
            {"probe_status": "probing"})
        db.commit()
        assert probe_worker._probe_one(item.id) == "done"
        db.expire_all()
        got = db.query(em.MediaItem).filter(em.MediaItem.id == item.id).first()
        assert got.probe_status == "done"
        assert got.duration_ticks == VALID_PROBE["duration_ticks"]
        assert got.video_codec == "H264"
        assert got.last_probed_at is not None
        n_streams = db.query(em.MediaStream).filter(
            em.MediaStream.item_id == item.id).count()
        assert n_streams == 1
    finally:
        _cleanup(db, lib)


def test_worker_failure_backoff_then_failed(db, monkeypatch):
    lib, item = _make_item(db)
    db.commit()
    monkeypatch.setattr(probe_worker, "_rate_limiter",
                        SimpleNamespace(acquire=lambda: None))
    monkeypatch.setattr(
        probe_worker, "resolve_play_target",
        lambda path, db: SimpleNamespace(value="http://x/f.mp4", headers={}))
    monkeypatch.setattr(probe_worker, "probe_metadata",
                        lambda *a, **k: {"duration_ticks": 0})  # ffprobe 失败
    monkeypatch.setattr(probe_worker, "PROBE_MAX_ATTEMPTS", 3)
    try:
        for attempt in (1, 2):
            db.query(em.MediaItem).filter(em.MediaItem.id == item.id).update(
                {"probe_status": "probing"})
            db.commit()
            assert probe_worker._probe_one(item.id) == "failed"
            db.expire_all()
            got = db.query(em.MediaItem).filter(
                em.MediaItem.id == item.id).first()
            assert got.probe_status == "pending"
            assert got.probe_attempts == attempt
            assert got.probe_next_retry_at > datetime.now()  # 退避
        # 第三次超限 → failed
        db.query(em.MediaItem).filter(em.MediaItem.id == item.id).update(
            {"probe_status": "probing"})
        db.commit()
        assert probe_worker._probe_one(item.id) == "failed"
        db.expire_all()
        got = db.query(em.MediaItem).filter(em.MediaItem.id == item.id).first()
        assert got.probe_status == "failed"
        assert got.probe_attempts == 3
    finally:
        _cleanup(db, lib)


def test_worker_skips_migrated_rows_with_valid_probe(db, monkeypatch):
    """已有有效探测数据的旧行：直接标 done，不发网络请求。"""
    lib, item = _make_item(db, duration=VALID_PROBE["duration_ticks"])
    db.commit()
    calls = []
    monkeypatch.setattr(probe_worker, "_rate_limiter",
                        SimpleNamespace(acquire=lambda: None))
    monkeypatch.setattr(probe_worker, "probe_metadata",
                        lambda *a, **k: calls.append(1) or dict(VALID_PROBE))
    try:
        db.query(em.MediaItem).filter(em.MediaItem.id == item.id).update(
            {"probe_status": "probing"})
        db.commit()
        assert probe_worker._probe_one(item.id) == "skipped"
        assert calls == []
        db.expire_all()
        got = db.query(em.MediaItem).filter(em.MediaItem.id == item.id).first()
        assert got.probe_status == "done"
    finally:
        _cleanup(db, lib)


def test_reset_stale_probing(db):
    lib, item = _make_item(db, status="probing")
    db.commit()
    try:
        assert probe_worker.reset_stale_probing(db) >= 1
        db.expire_all()
        got = db.query(em.MediaItem).filter(em.MediaItem.id == item.id).first()
        assert got.probe_status == "pending"
    finally:
        _cleanup(db, lib)


# ---------- 按需插队 ----------

def test_boost_probe(db):
    lib, item = _make_item(db, status="failed", priority=0)
    db.query(em.MediaItem).filter(em.MediaItem.id == item.id).update(
        {"probe_attempts": 5,
         "probe_next_retry_at": datetime.now() + timedelta(hours=1)})
    db.commit()
    try:
        assert probe_worker.boost_probe(db, item) is True
        db.expire_all()
        got = db.query(em.MediaItem).filter(em.MediaItem.id == item.id).first()
        assert got.probe_priority == probe_worker.BOOST_PRIORITY
        assert got.probe_status == "pending"
        assert got.probe_attempts == 0
        assert got.probe_next_retry_at is None
    finally:
        _cleanup(db, lib)


def test_boost_probe_done_is_noop(db):
    lib, item = _make_item(db, status="done",
                           duration=VALID_PROBE["duration_ticks"])
    db.commit()
    try:
        assert probe_worker.boost_probe(db, item) is False
    finally:
        _cleanup(db, lib)
