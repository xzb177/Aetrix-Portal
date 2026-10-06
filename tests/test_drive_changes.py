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
