"""重试失败探测：把存量误判为 failed 的条目拉回队列（v2.42.14 配套）

修正分类只阻止**新增**失败。生产里已经堆了几万条被误判的 ``failed``
（实测 2.6 万，93% 在 MoviePilot 目录，报错全是「ffprobe 未返回有效时长」），
它们得靠这个动作捞回来——重新探测后大多落到 ``probed_no_duration``。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models as web_models
from backend.emby_server import models as em
from backend.emby_server import probe_worker as pw


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    web_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(em.Library(guid="lib-1", name="电影"))
    session.commit()
    yield session
    session.close()


def _item(db, name, status, attempts=5):
    row = em.MediaItem(
        guid=f"guid-{name}", library_id=db.query(em.Library).first().id,
        item_type="movie", name=name, file_path=f"/media/{name}", container="mp4",
        probe_status=status, probe_attempts=attempts,
    )
    db.add(row)
    db.commit()
    return row


def test_retry_requeues_only_failed(db):
    failed_a = _item(db, "a.mkv", "failed")
    failed_b = _item(db, "b.mkv", "failed")
    untouched = [
        _item(db, "done.mkv", "done", attempts=0),
        _item(db, "degraded.mkv", "degraded", attempts=0),
        _item(db, "nodur.mkv", pw.STATUS_NO_DURATION, attempts=0),
        _item(db, "pending.mkv", "pending", attempts=2),
    ]

    n = pw.retry_failed(db)

    assert n == 2, "只该捞回 failed 的条目"
    db.expire_all()
    for row in (failed_a, failed_b):
        got = db.query(em.MediaItem).filter(em.MediaItem.id == row.id).first()
        assert got.probe_status == "pending"
        assert got.probe_attempts == 0, "重新入队必须把失败计数清零"
        assert got.probe_next_retry_at is None
    for row in untouched:
        got = db.query(em.MediaItem).filter(em.MediaItem.id == row.id).first()
        assert got.probe_status == row.probe_status, "已探完的条目不该被重探"
        assert got.probe_attempts == row.probe_attempts


def test_retry_is_idempotent_and_bounded(db):
    for i in range(5):
        _item(db, f"f{i}.mkv", "failed")

    assert pw.retry_failed(db, limit=2) == 2, "limit 必须真的限住批量"
    # 第二轮把那 3 条也捞回（limit 够大时）
    assert pw.retry_failed(db, limit=100) == 3
    # 全部已回队，再跑一次应当无事可做
    assert pw.retry_failed(db, limit=100) == 0


def test_retry_on_empty_table_is_zero(db):
    assert pw.retry_failed(db) == 0


def test_retry_handles_more_rows_than_sqlite_variable_limit(db):
    """分块是真需求，不是保险：``id IN (...)`` 会把每个 id 变成一个绑定变量

    SQLite 老版本上限 999。生产实测要捞回的是 2.6 万条，不分块就会在某些部署上
    直接报「too many SQL variables」。这里造 1200 条跨过那根线。
    """
    lib_id = db.query(em.Library).first().id
    db.bulk_save_objects([
        em.MediaItem(
            guid=f"g-bulk-{i}", library_id=lib_id, item_type="movie",
            name=f"bulk{i}.mkv", file_path=f"/media/bulk{i}.mkv", container="mp4",
            probe_status="failed", probe_attempts=5,
        )
        for i in range(1200)
    ])
    db.commit()

    assert pw.retry_failed(db, limit=2000) == 1200
    db.expire_all()
    left = (db.query(em.MediaItem)
            .filter(em.MediaItem.probe_status == "failed").count())
    assert left == 0
    assert (db.query(em.MediaItem)
            .filter(em.MediaItem.probe_status == "pending",
                    em.MediaItem.probe_attempts == 0).count()) == 1200


# ---------- v2.42.16：探测手段变了，旧结论要能重新跑一遍 ----------
#
# 双 Range 头尾读取上线后，已经被 2.42.14 擑回队列的条目会停在
# ``probed_no_duration`` / ``degraded``——它们是「当时确实读不出时长」这个结论下的
# 终态。不把它们重新入队，新逻辑对这几万条就是永远不生效。


def test_retry_with_statuses_also_requeues_no_duration_and_degraded(db):
    failed = _item(db, "a.mp4", "failed")
    no_dur = _item(db, "b.mp4", pw.STATUS_NO_DURATION, attempts=3)
    degraded = _item(db, "c.mp4", "degraded", attempts=2)
    done = _item(db, "d.mp4", "done", attempts=0)

    n = pw.retry_failed(db, statuses=("failed", "degraded", pw.STATUS_NO_DURATION))

    assert n == 3, "failed / degraded / probed_no_duration 都要重新入队"
    db.expire_all()
    for row in (failed, no_dur, degraded):
        got = db.query(em.MediaItem).filter(em.MediaItem.id == row.id).first()
        assert got.probe_status == "pending"
        assert got.probe_attempts == 0, "重新入队必须把失败计数清零"
        assert got.probe_next_retry_at is None
    still_done = db.query(em.MediaItem).filter(em.MediaItem.id == done.id).first()
    assert still_done.probe_status == "done", "已探完的不该被重探"


def test_retry_default_still_only_requeues_failed(db):
    """默认行为不能变：否则每次点这个接口都会把已探完的条目重烧一遍"""
    _item(db, "a.mp4", "failed")
    _item(db, "b.mp4", "degraded", attempts=2)
    _item(db, "c.mp4", pw.STATUS_NO_DURATION, attempts=3)
    assert pw.retry_failed(db) == 1


def test_retry_with_empty_statuses_is_a_noop(db):
    """全传空 / 只传逗号时不能变成「拈所有状态」"""
    _item(db, "a.mp4", "failed")
    assert pw.retry_failed(db, statuses=()) == 0
    assert pw.retry_failed(db, statuses=("", "  ")) == 0


def test_retry_with_statuses_still_chunks(db):
    """分块不能因为多传状态就失效（SQLite 变量上限 999）"""
    lib_id = db.query(em.Library).first().id
    db.bulk_save_objects([
        em.MediaItem(
            guid=f"g-chunk-{i}", library_id=lib_id, item_type="movie",
            name=f"chunk{i}.mp4", file_path=f"/media/chunk{i}.mp4", container="mp4",
            probe_status="degraded", probe_attempts=4,
        )
        for i in range(1200)
    ])
    db.commit()

    assert pw.retry_failed(db, limit=2000, statuses=("degraded",)) == 1200
    db.expire_all()
    assert (db.query(em.MediaItem)
            .filter(em.MediaItem.probe_status == "pending",
                    em.MediaItem.probe_attempts == 0).count()) == 1200


# ---------- 接口层：逗号分隔的 statuses 要正确解析 ----------


def test_endpoint_parses_statuses_query(db, monkeypatch):
    """``?statuses=failed,degraded,probed_no_duration`` → 元组，且能穿过空项与空格"""
    from types import SimpleNamespace

    from backend.api import admin_scrape
    from backend.emby_server import probe_worker as pw_lazy  # 端点里是延迟导入的

    seen = {}
    monkeypatch.setattr(pw_lazy, "retry_failed",
                        lambda d, limit=5000, statuses=None: seen.update(
                            {"limit": limit, "statuses": statuses}) or 0)
    admin_scrape.retry_failed_probes(
        SimpleNamespace(), db, limit=42,
        statuses="failed, degraded , ,probed_no_duration")
    assert seen["statuses"] == ("failed", "degraded", "probed_no_duration")
    assert seen["limit"] == 42


def test_endpoint_blank_statuses_keeps_default(db, monkeypatch):
    """空字符串 / 全空白 → None → 底层回落到默认的只处理 failed"""
    from types import SimpleNamespace

    from backend.api import admin_scrape
    from backend.emby_server import probe_worker as pw_lazy

    seen = {}
    monkeypatch.setattr(pw_lazy, "retry_failed",
                        lambda d, limit=5000, statuses=None: seen.update(
                            {"statuses": statuses}) or 0)
    for raw in ("", "   ", ",,,"):
        admin_scrape.retry_failed_probes(SimpleNamespace(), db, limit=5000, statuses=raw)
        assert seen["statuses"] is None, f"statuses={raw!r} 应回落到默认"
