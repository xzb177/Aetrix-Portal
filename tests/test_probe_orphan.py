"""P0-5 回归测试：默认配置（layered+inline）下远程探测不应该是孤儿。

背景：
- SCAN_PROBE_MODE 默认 "inline"，SCAN_LAYERED 默认开启
- layered+inline+远程文件：扫描 L1 不探测，enrich_worker 把 probe_status 置 pending
- 但 probe_worker.enabled() 只看 PROBE_BACKGROUND，默认 False，worker 不启动
- 结果：pending 任务永远无人消费，元数据（时长/分辨率）永远填不上

修复：enabled() 在 SCAN_LAYERED 开启时也返回 True。
"""
import os
import tempfile
import uuid
from datetime import datetime
from unittest import mock

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
_fd, _tmppath = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmppath}"
from backend import database as _dbmod
from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker as _sm
_dbmod.engine = _ce(os.environ["DATABASE_URL"])
_dbmod.SessionLocal = _sm(bind=_dbmod.engine)

import pytest

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import probe_worker
from backend.emby_server import scanner as _sc

init_db()


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        s.query(em.MediaStream).delete()
        s.query(em.MediaItem).delete()
        s.commit()
        yield s
    finally:
        s.close()


def _make_pending_item(db, **kw):
    """模拟 enrich_worker  deferred 的远程文件：probe_status='pending'"""
    it = em.MediaItem(
        guid=uuid.uuid4().hex,
        library_id=1,
        item_type=kw.pop("item_type", "movie"),
        name=kw.pop("name", "测试电影"),
        file_path=kw.pop("file_path", "/mnt/remote/movie.mkv"),
        probe_status="pending",
        probe_priority=kw.pop("probe_priority", 100),
        probe_attempts=0,
        probe_next_retry_at=None,
        date_added=datetime.now(),
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def test_enabled_layered_inline_not_orphan():
    """layered+inline（默认配置）下 worker 必须启用，否则 pending 成孤儿（P0-5）"""
    # 模拟默认配置：inline 模式（PROBE_BACKGROUND=False）+ layered 开启
    with mock.patch.object(_sc, "PROBE_BACKGROUND", False), \
         mock.patch.object(_sc, "SCAN_LAYERED", True):
        # 修复前：enabled() 返回 False → worker 不启动 → pending 孤儿
        # 修复后：enabled() 必须为 True
        assert probe_worker.enabled() is True


def test_enabled_background_mode():
    """background 模式下 worker 启用（原有行为保持）"""
    with mock.patch.object(_sc, "PROBE_BACKGROUND", True):
        assert probe_worker.enabled() is True


def test_enabled_fully_disabled():
    """background 关闭且 layered 关闭时，worker 才不启用"""
    with mock.patch.object(_sc, "PROBE_BACKGROUND", False), \
         mock.patch.object(_sc, "SCAN_LAYERED", False):
        assert probe_worker.enabled() is False


def test_enabled_matches_production_default():
    """生产默认配置下 enabled() 为 True（集成验证，不依赖具体 env 值）"""
    # 直接读当前模块的实际值，验证修复逻辑与生产配置一致
    # 生产：SCAN_PROBE_MODE=inline（PROBE_BACKGROUND=False），SCAN_LAYERED=True
    # 修复逻辑：PROBE_BACKGROUND or SCAN_LAYERED → True or True → True
    expected = bool(_sc.PROBE_BACKGROUND or _sc.SCAN_LAYERED)
    assert probe_worker.enabled() == expected
    # 生产默认（layered 开启）下必须为 True
    if _sc.SCAN_LAYERED:
        assert probe_worker.enabled() is True


def test_claim_batch_picks_up_enrich_deferred(db):
    """enrich_worker deferred 的 pending 任务能被 probe_worker 抢到"""
    item = _make_pending_item(db)
    ids = probe_worker._claim_batch(db, limit=10)
    assert item.id in ids
    # 抢占后状态变为 probing
    db.refresh(item)
    assert item.probe_status == "probing"


def test_apply_probe_result_fills_metadata(db):
    """_apply_probe_result 正确填写元数据并标 done"""
    item = _make_pending_item(db)
    item.probe_status = "probing"
    db.commit()

    info = {
        "size": 2048,
        "duration_ticks": 54000000000,
        "bitrate": 5000,
        "width": 1280,
        "height": 720,
        "video_codec": "hevc",
        "audio_codec": "ac3",
        "audio_languages": "chi",
        "subtitle_languages": "chi,eng",
    }
    probe_worker._apply_probe_result(db, item, info)
    db.refresh(item)

    assert item.probe_status == "done"
    assert item.duration_ticks == 54000000000
    assert item.width == 1280
    assert item.height == 720
    assert item.video_codec == "hevc"
    assert item.probe_attempts == 0
    assert item.probe_next_retry_at is None
    assert item.last_probed_at is not None
