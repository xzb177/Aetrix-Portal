"""增量扫描测试（v2.50.0）。"""
import os
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
import time
import uuid
from unittest import mock
import pytest
from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import fast_scanner
from backend.emby_server.fast_scanner import FastScanFile
init_db()
def _guid():
    return uuid.uuid4().hex
@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
def _make_lib(db):
    lib = em.Library(guid=_guid(), name=f"t_{_guid()[:8]}", collection_type="movies", paths="mount://1/test")
    db.add(lib); db.commit(); db.refresh(lib)
    return lib
def _cleanup(db, lib):
    ids = [r[0] for r in db.query(em.MediaItem.id).filter(em.MediaItem.library_id == lib.id).all()]
    if ids:
        db.query(em.MediaStream).filter(em.MediaStream.item_id.in_(ids)).delete(synchronize_session=False)
    db.query(em.MediaItem).filter(em.MediaItem.library_id == lib.id).delete(synchronize_session=False)
    db.query(em.Library).filter(em.Library.id == lib.id).delete()
    db.commit()
def _files(mb, count=3):
    return [FastScanFile(path=f"mount://1/test/movie{i}.mkv", name=f"movie{i}.mkv", size=1000+i, mtime=mb+i) for i in range(count)]
class _FakeSnapshot:
    paths = ("mount://1/test",)
def _fake_parse(path, lib_type):
    name = os.path.basename(path).rsplit(".", 1)[0]
    return {"name": name, "year": 2024, "season": None, "episode": None}
def _fake_guid(s):
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()
def _run(db, lib, files):
    with mock.patch.object(fast_scanner, "_collect_files", return_value=files), mock.patch("backend.emby_server.scanner.parse_media_filename", side_effect=_fake_parse), mock.patch("backend.emby_server.scanner.item_guid", side_effect=_fake_guid):
        return fast_scanner.scan_library_fast(db, lib, _FakeSnapshot())
def test_incremental_scan_skips_unchanged(db):
    lib = _make_lib(db)
    try:
        mb = time.time()
        s1 = _run(db, lib, _files(mb))
        assert s1["added"] == 3, f"{s1}"
        assert s1.get("skipped_unchanged", 0) == 0
        s2 = _run(db, lib, _files(mb))
        assert s2["added"] == 0, f"{s2}"
        assert s2.get("skipped_unchanged", 0) == 3, f"{s2}"
    finally:
        _cleanup(db, lib)
def test_incremental_scan_processes_changed(db):
    lib = _make_lib(db)
    try:
        mb = time.time()
        _run(db, lib, _files(mb))
        f3 = _files(mb)
        f3[1] = FastScanFile(path="mount://1/test/movie1.mkv", name="movie1.mkv", size=1001, mtime=mb+1+100)
        s3 = _run(db, lib, f3)
        assert s3["added"] == 0
        assert s3["updated"] == 1, f"{s3}"
        assert s3.get("skipped_unchanged", 0) == 2, f"{s3}"
        item = db.query(em.MediaItem).filter(em.MediaItem.library_id == lib.id, em.MediaItem.file_path == "mount://1/test/movie1.mkv").first()
        assert item is not None
        assert abs(item.file_mtime - (mb+1+100)) < 1.0
    finally:
        _cleanup(db, lib)
def test_incremental_scan_new_file(db):
    lib = _make_lib(db)
    try:
        mb = time.time()
        _run(db, lib, _files(mb, count=2))
        s2 = _run(db, lib, _files(mb, count=3))
        assert s2["added"] == 1, f"{s2}"
        assert s2.get("skipped_unchanged", 0) == 2
    finally:
        _cleanup(db, lib)
