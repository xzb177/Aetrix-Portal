"""补全 worker（v2.40.0）集成测试：原子抢单 / 重试退避 / 防洪峰 / 字幕落库 / 进度。

- 全部在隔离临时 SQLite 里跑，不连生产库；
- 不测真实 TMDB 网络（mock _enrich_fetch）。
"""
import os
import tempfile

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
_fd, _tmppath = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmppath}"
from backend import database as _dbmod
from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker as _sm
_dbmod.engine = _ce(os.environ["DATABASE_URL"])
_dbmod.SessionLocal = _sm(bind=_dbmod.engine)

import uuid
from datetime import datetime, timedelta
from unittest import mock

import pytest

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import enrich_worker

init_db()


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        # 每个测试前清空（隔离，避免测试间污染）
        s.query(em.MediaStream).delete()
        s.query(em.MediaItem).delete()
        s.commit()
        yield s
    finally:
        s.close()


def _make_item(db, **kw):
    it = em.MediaItem(
        guid=uuid.uuid4().hex,
        library_id=1,
        item_type=kw.pop("item_type", "movie"),
        name=kw.pop("name", "测试"),
        file_path=kw.pop("file_path", "/tmp/x.mp4"),
        enrich_status=kw.pop("enrich_status", "pending"),
        **kw,
    )
    db.add(it)
    db.commit()
    return it


def test_suppress_flood_marks_scraped_old_data_done(db):
    """防洪峰：有 last_scraped_at / tmdb_id 的老数据（无指纹）直接标 done"""
    _make_item(db, file_fingerprint=None, last_scraped_at=datetime.now())
    _make_item(db, file_fingerprint=None, tmdb_id="123")
    _make_item(db, file_fingerprint=None)  # 真需要补的，保留 pending
    _make_item(db, file_fingerprint="abc", enrich_status="pending")  # L1 新数据不动
    n = enrich_worker._suppress_flood(db)
    assert n == 2
    statuses = sorted(
        r[0] for r in db.query(em.MediaItem.enrich_status).all())
    assert statuses == ["done", "done", "pending", "pending"]


def test_claim_batch_skips_not_yet_due(db):
    """未到重试时间的 pending 不被抢走"""
    future = datetime.now() + timedelta(hours=1)
    _make_item(db, enrich_next_retry_at=future)
    _make_item(db, enrich_next_retry_at=None)
    claimed = enrich_worker._claim_batch(db, 10)
    assert len(claimed) == 1
    assert claimed[0].enrich_next_retry_at is None
    # 抢到的已标 enriching
    assert claimed[0].enrich_status == "enriching"


def test_mark_failed_backoff_and_failed(db):
    """失败指数退避：1次后 pending+60s，5次后转 failed"""
    it = _make_item(db, enrich_attempts=0)
    enrich_worker._mark_failed(db, it.id, 0, "boom")
    db.refresh(it)
    assert it.enrich_status == "pending"
    assert it.enrich_attempts == 1
    assert it.enrich_next_retry_at is not None
    delta = (it.enrich_next_retry_at - datetime.now()).total_seconds()
    assert 30 < delta <= 90  # 基数 60s 退避

    enrich_worker._mark_failed(db, it.id, 4, "boom")
    db.refresh(it)
    assert it.enrich_status == "failed"
    assert it.enrich_attempts == 5
    assert it.enrich_next_retry_at is None


def test_recover_crashed(db):
    """崩溃残留的 enriching 打回 pending"""
    _make_item(db, enrich_status="enriching")
    _make_item(db, enrich_status="enriching")
    n = enrich_worker._recover_crashed(db)
    assert n == 2
    assert db.query(em.MediaItem).filter(
        em.MediaItem.enrich_status == "enriching").count() == 0


def test_enrich_apply_writes_subtitles(db):
    """字幕落库：外挂字幕写入 MediaStream，旧字幕先清"""
    it = _make_item(db, item_type="movie")
    # 先放一条旧字幕
    db.add(em.MediaStream(item_id=it.id, stream_index=0,
                          stream_type="Subtitle", is_external=True,
                          external_path="/old.srt", language="eng"))
    # 再放一条内嵌字幕（不能被误删）
    db.add(em.MediaStream(item_id=it.id, stream_index=1,
                          stream_type="Subtitle", is_external=False,
                          language="eng"))
    db.commit()
    fetched = {
        "poster": None, "fanart": None,
        "external_subs": [("chi", "/new_chi.srt"), ("eng", "/new_eng.srt")],
        "nfo_data": None, "tmdb_hit": None, "tmdb_details": None,
        "ok": True,
    }
    with mock.patch("backend.emby_server.tmdb.tmdb_client") as _m:
        enrich_worker._enrich_apply(db, it, fetched)
    db.commit()
    subs = db.query(em.MediaStream).filter(
        em.MediaStream.item_id == it.id,
        em.MediaStream.stream_type == "Subtitle").order_by(
            em.MediaStream.stream_index).all()
    ext_paths = [s.external_path for s in subs if s.is_external]
    assert ext_paths == ["/new_chi.srt", "/new_eng.srt"]
    # 内嵌字幕保留
    assert any(not s.is_external for s in subs)
    assert it.enrich_status == "done"


def test_get_progress(db):
    """进度接口：各状态计数 + 重试中 + probe"""
    _make_item(db, enrich_status="pending")
    _make_item(db, enrich_status="pending",
               enrich_next_retry_at=datetime.now() + timedelta(minutes=5))
    _make_item(db, enrich_status="failed")
    _make_item(db, enrich_status="done")
    p = enrich_worker.get_progress()
    assert p["enrich"]["pending"] == 2
    assert p["enrich"]["retrying"] == 1
    assert p["enrich"]["failed"] == 1
    assert p["enrich"]["done"] == 1
    assert p["workers"] == enrich_worker.ENRICH_WORKERS
