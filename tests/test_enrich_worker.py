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
# 必须走 configure_session_local：直接赋值会把 SessionLocal 代理顶掉，
# 之后各模块 import 到的是被冻结的真 factory，又会查旧库。
_dbmod.configure_session_local(_sm(bind=_dbmod.engine))

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
    """字幕落库：外挂字幕写入 MediaStream，旧字幕先清

    条目预置 tmdb_id + overview：未刮干净的条目现在会退回 pending（可重试），
    这条只验字幕，故给它完整元数据以走 done 分支。
    """
    it = _make_item(db, item_type="movie", tmdb_id="999", overview="已有简介")
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
    # v2.42.9 第 4 批：熔断快照 + 租约配置必须出现在进度里（管理端靠它定位坏挂载）
    assert "mount_breakers" in p
    assert p["claim_lease_sec"] == enrich_worker.ENRICH_CLAIM_LEASE_SEC
    assert p["mount_breakers"]["open"] == []


# ==================== claim 租约 + janitor（v2.42.9）====================


def test_claim_batch_sets_claimed_at(db):
    """抢单时写 claim 租约（janitor 判定僵尸行的依据）"""
    it = _make_item(db)
    claimed = enrich_worker._claim_batch(db, 10)
    assert len(claimed) == 1
    assert claimed[0].id == it.id
    assert claimed[0].enrich_status == "enriching"
    assert claimed[0].enrich_claimed_at is not None
    # 租约时刻应该就是刚刚
    delta = (datetime.now() - claimed[0].enrich_claimed_at).total_seconds()
    assert -5 < delta < 30


def test_enrich_apply_clears_claimed_at(db):
    """补全完成释放租约：enriching 停留期间之外不占着 claim 时间戳"""
    it = _make_item(db, item_type="movie", tmdb_id="999", overview="已有简介",
                    enrich_status="enriching", enrich_claimed_at=datetime.now())
    fetched = {"poster": None, "fanart": None, "external_subs": [],
               "nfo_data": None, "tmdb_hit": None, "tmdb_details": None,
               "ok": True}
    with mock.patch("backend.emby_server.tmdb.tmdb_client"):
        enrich_worker._enrich_apply(db, it, fetched)
    db.commit()
    assert it.enrich_claimed_at is None
    assert it.enrich_status == "done"


def test_mark_failed_clears_claimed_at(db):
    """失败（含转 failed）也释放租约，避免 janitor 重复回收同一行"""
    it = _make_item(db, enrich_status="enriching",
                    enrich_claimed_at=datetime.now())
    enrich_worker._mark_failed(db, it.id, 0, "boom")
    db.refresh(it)
    assert it.enrich_claimed_at is None
    assert it.enrich_status == "pending"


def test_recover_crashed_clears_claimed_at(db):
    """启动恢复：enriching → pending 且清空租约"""
    _make_item(db, enrich_status="enriching", enrich_claimed_at=datetime.now())
    n = enrich_worker._recover_crashed(db)
    assert n == 1
    row = db.query(em.MediaItem).first()
    assert row.enrich_status == "pending"
    assert row.enrich_claimed_at is None


def test_reclaim_stale_reclaims_expired_leases(db):
    """janitor：租约过期的 enriching 打回 pending；新鲜租约与 pending 不动。

    - 行 A：20 分钟前抢的 → 回收（清租约、状态 pending，attempts/next_retry 不动）；
    - 行 B：刚抢的 → 保留 enriching；
    - 行 C：老库升级上来的历史行（claimed_at=NULL、date_modified 很老）→ 回收；
    - 行 D：老格式但 date_modified 很新 → 保留（不误伤老代码正在处理的行）；
    - 行 E：pending → 不关 janitor 的事。
    """
    now = datetime.now()
    a = _make_item(db, enrich_status="enriching",
                   enrich_claimed_at=now - timedelta(seconds=enrich_worker.ENRICH_CLAIM_LEASE_SEC + 60),
                   enrich_attempts=1)
    b = _make_item(db, enrich_status="enriching", enrich_claimed_at=now)
    c = _make_item(db, enrich_status="enriching", enrich_claimed_at=None,
                   date_modified=now - timedelta(hours=2))
    d = _make_item(db, enrich_status="enriching", enrich_claimed_at=None,
                   date_modified=now)
    e = _make_item(db, enrich_status="pending")
    n = enrich_worker._reclaim_stale(db)
    assert n == 2
    db.refresh(a); db.refresh(b); db.refresh(c); db.refresh(d); db.refresh(e)
    assert a.enrich_status == "pending" and a.enrich_claimed_at is None
    assert a.enrich_attempts == 1          # 回收不是失败：attempts 不涨
    assert b.enrich_status == "enriching" and b.enrich_claimed_at is not None
    assert c.enrich_status == "pending" and c.enrich_claimed_at is None
    assert d.enrich_status == "enriching"
    assert e.enrich_status == "pending"


def test_reclaim_stale_custom_lease(db):
    """janitor 支持自定义租约（测试 / 运维调参用）"""
    now = datetime.now()
    _make_item(db, enrich_status="enriching",
               enrich_claimed_at=now - timedelta(seconds=120))
    assert enrich_worker._reclaim_stale(db, lease_sec=60) == 1
    assert db.query(em.MediaItem).filter(
        em.MediaItem.enrich_status == "enriching").count() == 0


# ==================== 挂载熔断：打回 pending 而非 failed（v2.42.9）====================


@pytest.fixture()
def clean_breaker():
    from backend.emby_server import mounts as mnt
    mnt.breaker_reset()
    yield mnt
    mnt.breaker_reset()


def test_process_item_breaker_open_requeues_pending(db, clean_breaker):
    """熔断中的挂载：条目在 IO 前就被打回 pending + 长退避，不碰网络、不烧 attempts"""
    mnt = clean_breaker
    it = _make_item(db, file_path="mount://9/Movies/a.mkv",
                    enrich_status="enriching", enrich_claimed_at=datetime.now())

    def boom(item):
        raise AssertionError("熔断中的条目不允许进 IO")

    with mock.patch.object(enrich_worker, "_enrich_fetch", boom), \
            mock.patch.object(mnt, "mount_breaker_open", lambda mid: True):
        outcome = enrich_worker._process_item(db, it)
    assert outcome == "breaker"
    db.refresh(it)
    assert it.enrich_status == "pending"          # 不是 failed
    assert it.enrich_attempts == 0                # attempts 不涨
    assert it.enrich_claimed_at is None           # 租约释放
    assert it.enrich_next_retry_at is not None    # 长 next_retry_at
    delta = (it.enrich_next_retry_at - datetime.now()).total_seconds()
    assert mnt.MOUNT_BREAKER_RETRY_SEC - 120 < delta <= mnt.MOUNT_BREAKER_RETRY_SEC


def test_process_item_mount_error_requeues_not_failed(db, clean_breaker):
    """IO 中抛 MountError（挂载不可用）：打回 pending + 长退避，不走 _mark_failed"""
    mnt = clean_breaker
    it = _make_item(db, file_path="mount://7/Movies/b.mkv",
                    enrich_status="enriching", enrich_claimed_at=datetime.now())

    def dead_mount(item):
        raise mnt.MountError("网盘连接超时（测试用）")

    with mock.patch.object(enrich_worker, "_enrich_fetch", dead_mount):
        outcome = enrich_worker._process_item(db, it)
    assert outcome == "breaker"
    db.refresh(it)
    assert it.enrich_status == "pending"
    assert it.enrich_attempts == 0
    assert it.enrich_next_retry_at is not None


def test_process_item_non_mount_error_still_fails_normally(db, clean_breaker):
    """非挂载异常（如 TMDB 之外的真实 bug）仍走原有 attempts/退避路径"""
    it = _make_item(db, file_path="/tmp/local.mp4")

    def broken(item):
        raise RuntimeError("非挂载错误（测试用）")

    with mock.patch.object(enrich_worker, "_enrich_fetch", broken):
        outcome = enrich_worker._process_item(db, it)
    assert outcome == "retry"
    db.refresh(it)
    assert it.enrich_attempts == 1
    assert it.enrich_status == "pending"


def test_mount_id_of():
    assert enrich_worker._mount_id_of("mount://12/Movies/a.mkv") == 12
    assert enrich_worker._mount_id_of("mount://12") == 12
    assert enrich_worker._mount_id_of("/media/movies") is None
    assert enrich_worker._mount_id_of(None) is None
    assert enrich_worker._mount_id_of("mount://abc/x") is None
