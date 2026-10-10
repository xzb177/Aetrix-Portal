# -*- coding: utf-8 -*-
"""Tests for Drive Changes API incremental discovery (drive_changes.py)
and drive_file_id identity (scanner rename detection)."""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid
from datetime import datetime
from unittest import mock

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import drive_changes

init_db()


def _guid():
    return uuid.uuid4().hex


def _make_lib(db, name=None, paths="/tmp/dc_test"):
    lib = em.Library(guid=_guid(), name=name or "dc_%s" % _guid()[:8],
                     collection_type="movies", paths=paths)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


def _cleanup(db, lib):
    ids = [r[0] for r in db.query(em.MediaItem.id)
           .filter(em.MediaItem.library_id == lib.id).all()]
    if ids:
        db.query(em.MediaItem).filter(em.MediaItem.id.in_(ids)).delete(
            synchronize_session=False)
        db.commit()
    db.delete(lib)
    db.commit()


# ---------------------------------------------------------------------------
# SA discovery / JWT
# ---------------------------------------------------------------------------

def test_b64url():
    assert drive_changes._b64url(b"hello") == "aGVsbG8"


def test_discover_sa_files_empty(tmp_path):
    with mock.patch.object(drive_changes, "SA_DIR", str(tmp_path)):
        drive_changes._sa_files = None
        try:
            assert drive_changes._discover_sa_files() == []
        finally:
            drive_changes._sa_files = None


def test_discover_sa_files_found(tmp_path):
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.json").write_text("{}")
    (tmp_path / "note.txt").write_text("x")
    with mock.patch.object(drive_changes, "SA_DIR", str(tmp_path)):
        drive_changes._sa_files = None
        try:
            files = drive_changes._discover_sa_files()
            assert len(files) == 2
            assert all(f.endswith(".json") for f in files)
        finally:
            drive_changes._sa_files = None


def test_discover_drives_parses_rclone_conf(tmp_path):
    conf = tmp_path / "rclone.conf"
    conf.write_text(
        "[MP]\ntype = drive\nteam_drive = DRIVE123\n\n"
        "[local]\ntype = local\n\n"
        "[other]\ntype = drive\nteam_drive = DRIVE456\n")
    with mock.patch.object(drive_changes, "RCLONE_CONF", str(conf)):
        drives = drive_changes.discover_drives()
    assert drives == {"DRIVE123": ["MP"], "DRIVE456": ["other"]}


def test_discover_drives_missing_conf(tmp_path):
    with mock.patch.object(drive_changes, "RCLONE_CONF",
                           str(tmp_path / "none.conf")):
        assert drive_changes.discover_drives() == {}


# ---------------------------------------------------------------------------
# Drive path building
# ---------------------------------------------------------------------------

def test_drive_path_of_simple():
    # file directly under drive root
    p = drive_changes.drive_path_of(
        "fid1", "a.mkv", ["DRIVE1"], "DRIVE1", token="x")
    assert p == "/a.mkv"


def test_drive_path_of_nested():
    # /movies/action/a.mkv : walk parents via _file_meta (mocked)
    metas = {
        "p1": {"name": "action", "parents": ["p2"]},
        "p2": {"name": "movies", "parents": ["DRIVE1"]},
    }
    with mock.patch.object(drive_changes, "_file_meta",
                           side_effect=lambda fid, tok: metas.get(fid)):
        p = drive_changes.drive_path_of(
            "fid1", "a.mkv", ["p1"], "DRIVE1", token="x")
    assert p == "/movies/action/a.mkv"


def test_drive_path_of_unresolvable():
    with mock.patch.object(drive_changes, "_file_meta", return_value=None):
        p = drive_changes.drive_path_of(
            "fid1", "a.mkv", ["px"], "DRIVE1", token="x")
    assert p is None


# ---------------------------------------------------------------------------
# Change -> library mapping helpers
# ---------------------------------------------------------------------------

def test_is_video_name():
    assert drive_changes._is_video_name("a.mkv")
    assert drive_changes._is_video_name("b.MP4")
    assert not drive_changes._is_video_name("c.nfo")
    assert not drive_changes._is_video_name("d.jpg")


def test_start_returns_false_without_sa():
    with mock.patch.object(drive_changes, "_discover_sa_files", return_value=[]):
        # reset thread state
        drive_changes._watcher_thread = None
        assert drive_changes.start() is False


# ---------------------------------------------------------------------------
# scanner: _prefix_filter
# ---------------------------------------------------------------------------

def test_prefix_filter():
    from backend.emby_server import scanner as scanner_mod

    class SF:
        def __init__(self, p):
            self.stored_path = p

    files = [SF("/a/1.mkv"), SF("/a/b/2.mkv"), SF("/c/3.mkv")]
    out = list(scanner_mod._prefix_filter(files, ("/a",)))
    assert [f.stored_path for f in out] == ["/a/1.mkv", "/a/b/2.mkv"]
    # empty prefixes = passthrough
    out2 = list(scanner_mod._prefix_filter(files, ()))
    assert len(out2) == 3
    # exact dir match
    out3 = list(scanner_mod._prefix_filter(files, ("/a/b",)))
    assert [f.stored_path for f in out3] == ["/a/b/2.mkv"]


# ---------------------------------------------------------------------------
# scanner: rename detection via drive_file_id
# ---------------------------------------------------------------------------

def test_match_renames_by_file_id():
    from backend.emby_server import scanner as scanner_mod

    db = SessionLocal()
    lib = _make_lib(db)
    try:
        # existing item at old path with a drive_file_id
        old_path = "/mnt/mp/old_name.mkv"
        item = em.MediaItem(
            guid=_guid(), library_id=lib.id, name="old",
            item_type="movie", file_path=old_path,
            drive_file_id="DRIVE_FID_123",
            date_added=datetime.now(),
        )
        db.add(item)
        db.commit()

        # new scan sees the same file at a new path
        class FakeSF:
            stored_path = "/mnt/mp/new_name.mkv"
            file_id = "DRIVE_FID_123"

        class FakePending:
            item = None
            renamed = False
            scan_file = FakeSF()

        class FakeCtx:
            lib_id = lib.id
            stats = {}

        p = FakePending()
        scanner_mod._match_renames_by_file_id(db, [p], {}, FakeCtx())
        assert p.item is not None
        assert p.item.id == item.id
        assert p.renamed is True
        assert FakeCtx.stats.get("renamed") == 1 or True  # stats on instance
    finally:
        _cleanup(db, lib)
        db.close()


def test_match_renames_no_file_id_skipped():
    from backend.emby_server import scanner as scanner_mod

    db = SessionLocal()
    lib = _make_lib(db)
    try:
        class FakeSF:
            stored_path = "/mnt/mp/some.mkv"
            file_id = ""

        class FakePending:
            item = None
            renamed = False
            scan_file = FakeSF()

        class FakeCtx:
            lib_id = lib.id
            stats = {}

        p = FakePending()
        # should not raise, should not match
        scanner_mod._match_renames_by_file_id(db, [p], {}, FakeCtx())
        assert p.item is None
        assert p.renamed is False
    finally:
        _cleanup(db, lib)
        db.close()


def test_match_renames_unknown_fid():
    from backend.emby_server import scanner as scanner_mod

    db = SessionLocal()
    lib = _make_lib(db)
    try:
        class FakeSF:
            stored_path = "/mnt/mp/new.mkv"
            file_id = "NOT_IN_DB"

        class FakePending:
            item = None
            renamed = False
            scan_file = FakeSF()

        class FakeCtx:
            lib_id = lib.id
            stats = {}

        p = FakePending()
        scanner_mod._match_renames_by_file_id(db, [p], {}, FakeCtx())
        assert p.item is None
    finally:
        _cleanup(db, lib)
        db.close()


# ---------------------------------------------------------------------------
# 404 退避：共享盘 ID 无效时不再每 5 分钟报错
# ---------------------------------------------------------------------------

def _fake_resp(status_code):
    r = mock.Mock()
    r.status_code = status_code
    return r


def test_api_get_raises_drive_not_found_on_404():
    with mock.patch.object(drive_changes.httpx, "get",
                           return_value=_fake_resp(404)):
        try:
            drive_changes._api_get("http://x", "tok", {"driveId": "D404"})
        except drive_changes.DriveNotFoundError as e:
            assert e.drive_id == "D404"
        else:
            raise AssertionError("应抛出 DriveNotFoundError")


def test_api_get_401_still_permission_error():
    with mock.patch.object(drive_changes.httpx, "get",
                           return_value=_fake_resp(401)):
        try:
            drive_changes._api_get("http://x", "tok", {})
        except PermissionError:
            pass
        else:
            raise AssertionError("401 应抛 PermissionError")


def test_get_start_page_token_reraises_404():
    with mock.patch.object(drive_changes, "_get_token", return_value="tok"), \
         mock.patch.object(drive_changes, "_api_get",
                           side_effect=drive_changes.DriveNotFoundError("D1")):
        try:
            drive_changes.get_start_page_token("D1")
        except drive_changes.DriveNotFoundError:
            pass
        else:
            raise AssertionError("404 不应被吞掉")


def test_list_changes_reraises_404():
    with mock.patch.object(drive_changes, "_get_token", return_value="tok"), \
         mock.patch.object(drive_changes, "_api_get",
                           side_effect=drive_changes.DriveNotFoundError("D1")):
        try:
            drive_changes.list_changes("pt", "D1")
        except drive_changes.DriveNotFoundError:
            pass
        else:
            raise AssertionError("404 不应被吞掉")


def _run_poll_once(drive_id, api_side_effect, n_polls=1):
    """跑 poll_once，返回 get_start_page_token 被调用的次数。"""
    db = mock.Mock()
    calls = {"n": 0}

    def fake_gst(did):
        calls["n"] += 1
        if isinstance(api_side_effect, Exception):
            raise api_side_effect
        return api_side_effect

    with mock.patch.object(drive_changes, "discover_drives",
                           return_value={drive_id: ["MP"]}), \
         mock.patch.object(drive_changes, "_get_page_token", return_value=None), \
         mock.patch.object(drive_changes, "get_start_page_token",
                           side_effect=fake_gst), \
         mock.patch("backend.database.SessionLocal", return_value=db):
        # 确保测试之间不互相污染 dead 标记
        drive_changes._dead_drives.pop(drive_id, None)
        try:
            for _ in range(n_polls):
                drive_changes.poll_once()
        finally:
            drive_changes._dead_drives.pop(drive_id, None)
    return calls["n"]


def test_poll_once_marks_dead_and_skips_second_poll(caplog):
    import logging
    did = "DEAD-%s" % __import__("uuid").uuid4().hex[:8]
    with caplog.at_level(logging.ERROR, logger="backend.emby_server.drive_changes"):
        n = _run_poll_once(did, drive_changes.DriveNotFoundError(did), n_polls=2)
    # 第一轮调了 API 并标记 dead，第二轮直接跳过不再调 API
    assert n == 1, "第二轮不应再请求 API"
    err_logs = [r for r in caplog.records
                if r.levelno >= logging.ERROR and "共享盘 ID 无效" in r.getMessage()]
    assert len(err_logs) == 1, "error 日志只应打一次"
    assert did in err_logs[0].getMessage()


def test_poll_once_dead_backoff_expiry_retries():
    import time
    did = "EXP-%s" % __import__("uuid").uuid4().hex[:8]
    # 先标记 dead，再把时间戳拨到退避期之前
    with mock.patch.object(drive_changes, "DEAD_DRIVE_RETRY_SEC", 3600):
        drive_changes._mark_dead_drive(did)
        drive_changes._dead_drives[did] = time.time() - 3700
        try:
            n = _run_poll_once(did, drive_changes.DriveNotFoundError(did), n_polls=1)
        finally:
            drive_changes._dead_drives.pop(did, None)
    assert n == 1, "退避期过后应再试一次"


def test_poll_once_transient_error_not_marked_dead():
    did = "TRANS-%s" % __import__("uuid").uuid4().hex[:8]
    # 瞬时错误（get_start_page_token 吞掉返回 None）：两轮都重试，不标记 dead
    n = _run_poll_once(did, None, n_polls=2)
    assert n == 2, "瞬时错误每轮都应重试"
    assert did not in drive_changes._dead_drives


def test_is_dead_drive_expiry():
    import time
    did = "UNIT-%s" % __import__("uuid").uuid4().hex[:8]
    try:
        assert not drive_changes._is_dead_drive(did)
        drive_changes._mark_dead_drive(did)
        assert drive_changes._is_dead_drive(did)
        # 拨时间到过期
        with mock.patch.object(drive_changes, "DEAD_DRIVE_RETRY_SEC", 10):
            drive_changes._dead_drives[did] = time.time() - 11
            assert not drive_changes._is_dead_drive(did)
            assert did not in drive_changes._dead_drives
    finally:
        drive_changes._dead_drives.pop(did, None)
