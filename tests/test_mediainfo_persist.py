# -*- coding: utf-8 -*-
"""Tests for mediainfo_persist.py (StrmAssistant #13 移植：媒体信息持久化)."""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
# 测试用隔离目录，不污染生产默认路径
os.environ.setdefault("MEDIAINFO_JSON_DIR", "/tmp/test_mediainfo_json")

import json
import shutil
import uuid
from datetime import datetime

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import mediainfo_persist as persist

init_db()


def _guid():
    return uuid.uuid4().hex


def _make_lib(db, name=None):
    lib = em.Library(guid=_guid(), name=name or f"persist_{_guid()[:8]}",
                     collection_type="movies", paths="/tmp/persist_test")
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


def _make_item(db, lib, video_codec="h264", width=1920, height=1080,
               file_mtime=1700000000.0, size=12345678):
    item = em.MediaItem(
        guid=_guid(), library_id=lib.id, name=f"item_{_guid()[:8]}",
        item_type="movie", file_path="/tmp/persist_test/a.mkv",
        video_codec=video_codec, audio_codec="aac",
        width=width, height=height, bitrate=8000000,
        duration_ticks=54000000000, container="mp4",
        file_mtime=file_mtime, size=size,
        probe_status="done", date_added=datetime.now(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def setup_function(_):
    shutil.rmtree("/tmp/test_mediainfo_json", ignore_errors=True)


def test_serialize_and_deserialize_roundtrip():
    """落盘 → 清空 DB 字段 → 恢复，零探测。"""
    db = SessionLocal()
    try:
        lib = _make_lib(db)
        item = _make_item(db, lib)
        item_id = item.id
        guid = item.guid

        # 1. 落盘
        assert persist.serialize(db, item) is True
        path = persist.get_json_path(item)
        assert path and os.path.isfile(path)

        # 2. 模拟 DB 丢失（重建后）：清空媒体信息
        item.video_codec = None
        item.audio_codec = None
        item.width = 0
        item.height = 0
        item.probe_status = "pending"
        db.commit()

        # 3. 恢复（零探测）
        assert persist.deserialize(db, item) is True
        assert item.video_codec == "h264"
        assert item.audio_codec == "aac"
        assert item.width == 1920
        assert item.height == 1080
        assert item.probe_status == "done"
        assert guid == item.guid  # guid 未变
    finally:
        db.close()


def test_deserialize_skipped_when_file_changed():
    """源文件变更（mtime 变了）→ JSON 过期，不用。"""
    db = SessionLocal()
    try:
        lib = _make_lib(db)
        item = _make_item(db, lib, file_mtime=1700000000.0)
        assert persist.serialize(db, item) is True

        # 文件被替换了：mtime 大变
        item.file_mtime = 1800000000.0
        item.video_codec = None
        db.commit()

        assert persist.deserialize(db, item) is False
        assert item.video_codec is None  # 没被过期 JSON 污染
    finally:
        db.close()


def test_serialize_skipped_without_mediainfo():
    """没有媒体信息的条目不落盘。"""
    db = SessionLocal()
    try:
        lib = _make_lib(db)
        item = _make_item(db, lib, video_codec=None, width=0, height=0)
        assert persist.serialize(db, item) is False
        assert persist.get_json_path(item) is None or not os.path.isfile(
            persist.get_json_path(item))
    finally:
        db.close()


def test_deserialize_rejects_guid_mismatch():
    """JSON guid 对不上 → 拒绝使用（防张冠李戴）。"""
    db = SessionLocal()
    try:
        lib = _make_lib(db)
        item = _make_item(db, lib)
        assert persist.serialize(db, item) is True
        path = persist.get_json_path(item)

        # 篡改 JSON 里的 guid
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["item_guid"] = "deadbeef" * 4
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        item.video_codec = None
        db.commit()
        assert persist.deserialize(db, item) is False
        assert item.video_codec is None
    finally:
        db.close()


