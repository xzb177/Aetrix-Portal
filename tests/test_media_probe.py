# -*- coding: utf-8 -*-
"""Tests for on-demand media probe (media_probe.py + probe_worker.py)."""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid
from datetime import datetime, timedelta
from unittest import mock

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import media_probe, probe_worker

init_db()


def _guid():
    return uuid.uuid4().hex


def _make_lib(db, name=None):
    lib = em.Library(guid=_guid(), name=name or f"probe_{_guid()[:8]}",
                     collection_type="movies", paths="/tmp/probe_test")
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


def _make_item(db, lib, item_type="movie", video_codec=None, file_path="/tmp/probe_test/a.mkv",
               probe_status="done", probe_attempts=0, probe_priority=0):
    item = em.MediaItem(
        guid=_guid(), library_id=lib.id, name=f"item_{_guid()[:8]}",
        item_type=item_type, file_path=file_path,
        video_codec=video_codec, probe_status=probe_status,
        probe_attempts=probe_attempts, probe_priority=probe_priority,
        date_added=datetime.now(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _cleanup(db, lib):
    ids = [r[0] for r in db.query(em.MediaItem.id)
           .filter(em.MediaItem.library_id == lib.id).all()]
    if ids:
        db.query(em.MediaStream).filter(em.MediaStream.item_id.in_(ids)) \
            .delete(synchronize_session=False)
    db.query(em.MediaItem).filter(em.MediaItem.library_id == lib.id) \
        .delete(synchronize_session=False)
    db.query(em.Library).filter(em.Library.id == lib.id).delete()
    db.commit()


class TestMaybeEnqueue:
    def test_movie_without_codec_enqueued(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, item_type="movie", video_codec=None,
                              probe_status="done")
            assert probe_worker.maybe_enqueue(db, item) is True
            db.refresh(item)
            assert item.probe_status == "pending"
            assert item.probe_priority == 1000
            assert item.probe_next_retry_at is None
        finally:
            _cleanup(db, lib)
            db.close()

    def test_idempotent_when_already_pending(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, probe_status="pending", probe_priority=1000)
            assert probe_worker.maybe_enqueue(db, item) is False
            db.refresh(item)
            assert item.probe_priority == 1000
        finally:
            _cleanup(db, lib)
            db.close()

    def test_pending_low_priority_is_bumped(self):
        """v2.53：已在 pending 队尾（扫描器的 0/100）的，用户打开时插队到 1000。

        旧行为是直接返回 False —— 28 万积压里被用户点开的条目照样排在最后。
        """
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, probe_status="pending", probe_priority=100)
            assert probe_worker.maybe_enqueue(db, item) is True
            db.refresh(item)
            assert item.probe_priority == probe_worker.ONDEMAND_PRIORITY
        finally:
            _cleanup(db, lib)
            db.close()

    def test_skips(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            # 已有 codec + 时长
            i1 = _make_item(db, lib, video_codec="h264")
            i1.duration_ticks = 10 ** 10
            db.commit()
            assert probe_worker.maybe_enqueue(db, i1) is False
            # 季（没有文件）不做；v2.53 起单集要做
            i2 = _make_item(db, lib, item_type="season", video_codec=None)
            assert probe_worker.maybe_enqueue(db, i2) is False
            # 无 file_path
            i3 = _make_item(db, lib, video_codec=None, file_path=None)
            assert probe_worker.maybe_enqueue(db, i3) is False
            # 已达最大尝试次数（failed 不复活）
            i4 = _make_item(db, lib, video_codec=None, probe_status="failed",
                            probe_attempts=media_probe.PROBE_MAX_ATTEMPTS)
            assert probe_worker.maybe_enqueue(db, i4) is False
            # probing 中
            i5 = _make_item(db, lib, video_codec=None, probe_status="probing")
            assert probe_worker.maybe_enqueue(db, i5) is False
        finally:
            _cleanup(db, lib)
            db.close()

    def test_enqueue_does_not_reset_attempts(self):
        """之前失败过 1 次的，入队后 attempts 保留（重试次数有上限，不无限复活）。"""
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="degraded",
                              probe_attempts=1)
            assert probe_worker.maybe_enqueue(db, item) is True
            db.refresh(item)
            assert item.probe_attempts == 1
            assert item.probe_status == "pending"
        finally:
            _cleanup(db, lib)
            db.close()


class TestClaimBatch:
    def test_claim_filters_and_order(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            low = _make_item(db, lib, item_type="movie", video_codec=None,
                             probe_status="pending", probe_priority=100)
            high = _make_item(db, lib, item_type="episode", video_codec=None,
                              probe_status="pending", probe_priority=1000)
            # 不该被抢的
            _make_item(db, lib, item_type="series", video_codec=None,
                       probe_status="pending")                      # 剧集骨架（无文件可探）
            has_info = _make_item(db, lib, item_type="movie", video_codec="h264",
                                  probe_status="pending")           # 有 codec + 时长
            has_info.duration_ticks = 10 ** 10
            db.commit()
            _make_item(db, lib, item_type="movie", video_codec=None,
                       probe_status="done")                         # 非 pending
            future = _make_item(db, lib, item_type="movie", video_codec=None,
                                probe_status="pending")
            future.probe_next_retry_at = datetime.now() + timedelta(hours=1)
            db.commit()

            claimed = probe_worker._claim_batch(db, 10, library_id=lib.id)
            assert claimed == [high.id, low.id], f"优先级排序错误: {claimed}"
            # 抢到的已标 probing
            statuses = {r[0]: r[1] for r in
                        db.query(em.MediaItem.id, em.MediaItem.probe_status)
                        .filter(em.MediaItem.id.in_(claimed)).all()}
            assert all(s == "probing" for s in statuses.values())
        finally:
            _cleanup(db, lib)
            db.close()

    def test_claim_empty_rolls_back(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            assert probe_worker._claim_batch(db, 10, library_id=lib.id) == []
        finally:
            _cleanup(db, lib)
            db.close()


class TestWriteBack:
    def test_write_back_only_nonempty(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing")
            item.duration_ticks = 72000000000  # 已有时长
            item.width = 1920
            db.commit()
            media_probe.write_back(db, item, {
                "video_codec": "hevc", "audio_codec": "aac",
                "width": 0, "height": 1080, "duration_ticks": 0,
                "bitrate": 8000000,
            })
            db.refresh(item)
            assert item.video_codec == "hevc"
            assert item.audio_codec == "aac"
            assert item.width == 1920          # 0 不覆盖已有值
            assert item.height == 1080
            assert item.duration_ticks == 72000000000  # 0 不覆盖
            assert item.bitrate == 8000000
            assert item.probe_status == "done"
            assert item.probe_attempts == 0
            assert item.last_probed_at is not None
        finally:
            _cleanup(db, lib)
            db.close()

    def test_write_back_degraded(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing")
            media_probe.write_back(db, item, {
                "video_codec": "h264", "width": 1280, "height": 720,
                "_degraded": True,
            })
            db.refresh(item)
            assert item.probe_status == "degraded"
            assert item.video_codec == "h264"
        finally:
            _cleanup(db, lib)
            db.close()


class TestRetry:
    def test_retry_backoff_then_failed(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing",
                              probe_attempts=0)
            media_probe.mark_retry(db, item, "boom")
            db.refresh(item)
            assert item.probe_status == "pending"
            assert item.probe_attempts == 1
            delta = (item.probe_next_retry_at - datetime.now()).total_seconds()
            assert 50 <= delta <= 70, delta  # 基数 60s

            item.probe_attempts = media_probe.PROBE_MAX_ATTEMPTS - 1
            item.probe_status = "probing"
            db.commit()
            media_probe.mark_retry(db, item, "boom")
            db.refresh(item)
            assert item.probe_status == "failed"
            assert item.probe_next_retry_at is None
        finally:
            _cleanup(db, lib)
            db.close()

    def test_http_404_fails_fast(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing",
                              probe_attempts=0)
            fake_probe = {"video_codec": "h264", "_http_code": 404,
                          "_error": "not found"}
            with mock.patch.object(media_probe, "probe_metadata",
                                   return_value=fake_probe), \
                 mock.patch.object(media_probe, "resolve_probe_input",
                                   return_value=("/tmp/x.mkv", {}, 0, "")):
                status = media_probe.probe_one(db, item)
            db.refresh(item)
            assert status == "failed"
            assert item.probe_status == "failed"
            assert item.probe_attempts == 0  # 直接判死，不消耗重试次数
        finally:
            _cleanup(db, lib)
            db.close()

    def test_probe_one_success(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing")
            fake_probe = {"video_codec": "hevc", "audio_codec": "aac",
                          "width": 3840, "height": 2160,
                          "duration_ticks": 72000000000, "bitrate": 20000000}
            with mock.patch.object(media_probe, "probe_metadata",
                                   return_value=fake_probe), \
                 mock.patch.object(media_probe, "resolve_probe_input",
                                   return_value=("/tmp/x.mkv", {}, 0, "")):
                status = media_probe.probe_one(db, item)
            db.refresh(item)
            assert status == "done"
            assert item.video_codec == "hevc"
            assert (item.width, item.height) == (3840, 2160)
        finally:
            _cleanup(db, lib)
            db.close()

    def test_probe_one_empty_result_retries(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing",
                              probe_attempts=0)
            with mock.patch.object(media_probe, "probe_metadata",
                                   return_value={"duration_ticks": 0}), \
                 mock.patch.object(media_probe, "resolve_probe_input",
                                   return_value=("/tmp/x.mkv", {}, 0, "")):
                status = media_probe.probe_one(db, item)
            db.refresh(item)
            assert status == "pending"
            assert item.probe_attempts == 1
        finally:
            _cleanup(db, lib)
            db.close()


class TestResolve:
    def test_local_missing_file_returns_none(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, file_path="/tmp/definitely_not_here_xyz.mkv")
            assert media_probe.resolve_probe_input(db, item) is None
        finally:
            _cleanup(db, lib)
            db.close()

    def test_mount_path_missing_mount_returns_none(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, file_path="mount://999999/nope.mkv")
            assert media_probe.resolve_probe_input(db, item) is None
        finally:
            _cleanup(db, lib)
            db.close()

    def test_empty_file_path_returns_none(self):
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, file_path="  ")
            assert media_probe.resolve_probe_input(db, item) is None
        finally:
            _cleanup(db, lib)
            db.close()

    def test_write_back_moov_position(self):
        """P0-1: write_back 把 moov_position 写回数据库"""
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing")
            db.commit()
            media_probe.write_back(db, item, {
                "video_codec": "h264", "width": 1920, "height": 1080,
                "duration_ticks": 72000000000, "moov_position": "front",
            })
            db.refresh(item)
            assert item.moov_position == "front"
            assert item.probe_status == "done"
        finally:
            _cleanup(db, lib)
            db.close()

    def test_write_back_moov_position_back(self):
        """P0-1: moov 在尾部时标记为 back"""
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing")
            db.commit()
            media_probe.write_back(db, item, {
                "video_codec": "h264", "width": 1920, "height": 1080,
                "duration_ticks": 72000000000, "moov_position": "back",
            })
            db.refresh(item)
            assert item.moov_position == "back"
        finally:
            _cleanup(db, lib)
            db.close()

    def test_write_back_no_moov_stays_null(self):
        """P0-1: 非 MP4（无 moov_position）时字段保持 NULL"""
        db = SessionLocal()
        lib = _make_lib(db)
        try:
            item = _make_item(db, lib, video_codec=None, probe_status="probing")
            db.commit()
            # MKV 没有 moov_position
            media_probe.write_back(db, item, {
                "video_codec": "h264", "width": 1920, "height": 1080,
                "duration_ticks": 72000000000,
            })
            db.refresh(item)
            assert item.moov_position is None
        finally:
            _cleanup(db, lib)
            db.close()
