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
