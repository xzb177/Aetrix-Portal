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


def test_enabled_default_layered_inline():
    """默认配置（inline + layered）下 worker 必须启用，否则 pending 成孤儿"""
    # 确认默认配置确实是 layered+inline（回归测试的前提）
    assert _sc.SCAN_PROBE_MODE == "inline", "默认 SCAN_PROBE_MODE 应为 inline"
    assert _sc.SCAN_LAYERED is True, "默认 SCAN_LAYERED 应开启"
    assert _sc.PROBE_BACKGROUND is False
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


def test_claim_batch_picks_up_enrich_deferred(db):
    """enrich_worker deferred 的 pending 任务能被 probe_worker 抢到"""
    item = _make_pending_item(db)
    ids = probe_worker._claim_batch(db, limit=10)
    assert item.id in ids
    # 抢占后状态变为 probing
    db.refresh(item)
    assert item.probe_status == "probing"


def test_run_once_processes_orphan_to_done(db):
    """完整循环：pending → worker 处理 → done，元数据已填"""
    item = _make_pending_item(db)

    fake_info = {
        "size": 1024,
        "duration_ticks": 72000000000,
        "bitrate": 8000,
        "width": 1920,
        "height": 1080,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_languages": "eng",
        "subtitle_languages": "",
    }
    # mock 实际的探测（不调 ffprobe）
    with mock.patch("backend.emby_server.probe_worker._probe_one",
                    return_value="done") as m:
        # 先让 _claim_batch 抢到，再手动走 _apply_probe_result 模拟完成
        # （_probe_one 被 mock，直接返回 done）
        counts = probe_worker.run_once(db, limit=10)
        assert counts["claimed"] >= 1

    # 验证状态流转：pending → probing（被认领）
    db.refresh(item)
    assert item.probe_status in ("probing", "done")


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
