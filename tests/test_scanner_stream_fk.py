"""扫描时新条目的轨道必须先拿到 item 主键

真实起因（`NOT NULL constraint failed: emby_media_streams.item_id`）：

    db.add(emby_models.MediaItem(guid=guid, library_id=ctx.lib_id))   # 还没 flush
    ...
    db.add(emby_models.MediaStream(item_id=item.id, ...))             # item.id 是 None

新条目刚 ``db.add``、还没落库时 ``item.id`` 为 ``None``，于是轨道带着
``item_id=None`` 进 session；后面某处 ``db.flush()`` 批量 INSERT 时撞 NOT NULL 约束，
**整库扫描在这一行崩掉**，前面已经扫完的批次全部白跑。

旧条目（之前轮次已入库）本来就有 id，所以这个 bug 只在**首次扫描**时暴露——上线时
小库可能因为刚好走了旧条目而侥幸通过，换个全新库就炸。这里把两种情况都钉住。
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import models as core  # noqa: F401  确保 Base 元数据已注册
from backend.database import Base
from backend.emby_server import models as em


@pytest.fixture
def session():
    path = os.path.join(tempfile.mkdtemp(), "stream-fk.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        yield db


def _probe_streams():
    return [{"stream_index": 0, "stream_type": "Video", "codec": "h264",
             "language": "", "display_title": None, "title": None,
             "channels": None, "bit_rate": 0}]


def test_new_item_stream_flush_raises_without_fix(session):
    """回归本体：新条目没 flush 就拿 item.id 建轨道 → 落库时炸 NOT NULL"""
    session.add(em.Library(guid="L" * 32, name="库", collection_type="movies", paths=""))
    session.commit()
    lib = session.query(em.Library).first()

    item = em.MediaItem(guid="M" * 32, library_id=lib.id, item_type="movie", name="片")
    session.add(item)
    assert item.id is None, "新建对象未落库时 id 应为 None"

    for s in _probe_streams():
        session.add(em.MediaStream(item_id=item.id, **s))

    with pytest.raises(Exception) as exc:
        session.flush()
    assert "NOT NULL" in str(exc.value) or "item_id" in str(exc.value)
    session.rollback()


def test_flush_item_first_gives_valid_stream_fk(session):
    """修复后的顺序：先 flush 拿主键，再建轨道 → 正常落库且外键有值"""
    session.add(em.Library(guid="L" * 32, name="库", collection_type="movies", paths=""))
    session.commit()
    lib = session.query(em.Library).first()

    item = em.MediaItem(guid="M" * 32, library_id=lib.id, item_type="movie", name="片")
    session.add(item)
    if item.id is None:            # ← 修复：先落库拿主键
        session.flush()
    assert item.id is not None

    for s in _probe_streams():
        session.add(em.MediaStream(item_id=item.id, **s))
    session.commit()

    saved = session.query(em.MediaStream).filter_by(item_id=item.id).all()
    assert len(saved) == 1 and saved[0].stream_type == "Video"


def test_existing_item_id_is_not_re_flushed(session):
    """旧条目本来就有 id，不该因为这个修复多一次无谓 flush"""
    session.add(em.Library(guid="L" * 32, name="库", collection_type="movies", paths=""))
    session.commit()
    lib = session.query(em.Library).first()

    item = em.MediaItem(guid="M" * 32, library_id=lib.id, item_type="movie", name="片")
    session.add(item)
    session.commit()               # 已入库

    flushes = []
    event.listen(session, "before_flush", lambda *a: flushes.append(1), once=True)
    if item.id is None:            # 旧条目这里为 False，不触发
        session.flush()
    assert flushes == [] and item.id is not None
