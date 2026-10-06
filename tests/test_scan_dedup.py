"""扫描去重回归测试（2026-09-25 生产事故）。

遍历器偶发产出同一文件两次（rclone lsjson 网盘侧重复条目 / 分页异常）时，
旧代码在 ``_prepare_and_prefetch`` 里只做 ``seen_guids.add`` 从不检查，
同一事务内两次 INSERT 同 guid → ``UNIQUE constraint failed: emby_items.guid``
→ 整批回滚、整库扫描 abort（ScanRun 9 failed）。

- ``scanner._prepare_and_prefetch`` 按 guid 去重：重复文件只处理一次；
- ``_CloudMount.walk_media`` 在源头按 rel 去重；
- 重复计数 ``duplicate_files`` 写进扫描统计，方便事后排查。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid

import pytest

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import mounts as _mounts  # noqa: F401 -- 必须先于 scanner 导入，避免循环导入
from backend.emby_server import fast_scanner
from backend.emby_server import scanner
from backend.emby_server.mounts import MountEntry

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


def _cleanup(db, lib):
    item_ids = [r[0] for r in db.query(em.MediaItem.id).filter(
        em.MediaItem.library_id == lib.id).all()]
    if item_ids:
        db.query(em.MediaStream).filter(
            em.MediaStream.item_id.in_(item_ids)).delete(
                synchronize_session=False)
    db.query(em.MediaItem).filter(em.MediaItem.library_id == lib.id).delete(
        synchronize_session=False)
    db.query(em.Library).filter(em.Library.id == lib.id).delete()
    db.commit()


def _scanfile(path):
    return fast_scanner.FastScanFile(
        path=str(path), name=path.name, size=64, mtime=1.0,
    )






def test_cloud_walk_media_dedups_duplicate_listing():
    """单次列举返回同一文件两次：walk_media 只产出一次。"""
    dup = MountEntry(name="a.mkv", rel="/dir/a.mkv", is_dir=False, size=10)

    class _Stub:
        what = "测试挂载"

        def list_dir(self, rel="/"):
            if rel == "/":
                return [MountEntry(name="dir", rel="/dir", is_dir=True)]
            if rel == "/dir":
                return [dup, dup]  # rclone lsjson 偶发的重复条目
            return []

        def _entries(self, rel):
            return self.list_dir(rel)

    files = list(_mounts.RemoteMount.walk_media(_Stub(), root="/"))
    assert [f.rel for f in files] == ["/dir/a.mkv"]
def test_duplicate_files_do_not_break_scan(tmp_path, monkeypatch):
    """rclone 返回同一文件两次：fast_scanner 靠 upsert 只落库一条，不抛异常。"""
    from backend.emby_server.scanner import LibrarySnapshot

    movie = tmp_path / "Dup Movie (2024).mp4"
    movie.write_bytes(b"\x00" * 64)
    sf = _scanfile(movie)

    # 同一个文件出现两次 = rclone 偶发的重复条目
    monkeypatch.setattr(fast_scanner, "_collect_files",
                        lambda paths: [sf, _scanfile(movie)])

    db = SessionLocal()
    lib = em.Library(guid=_guid(), name="去重测试库",
                     collection_type="movies", paths=str(tmp_path))
    db.add(lib)
    db.commit()
    try:
        snap = LibrarySnapshot.of(lib)
        fast_scanner.scan_library_sync(db, lib, snap, trigger="test")
        rows = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib.id).all()
        assert len(rows) == 1, f"重复文件应只落库一条，实际 {len(rows)} 条"
        assert rows[0].file_path == str(movie)
    finally:
        _cleanup(db, lib)
        db.close()


def test_duplicate_files_across_batches(tmp_path, monkeypatch):
    """重复出现在后面的批次：同样只落库一条。"""
    from backend.emby_server.scanner import LibrarySnapshot

    movie = tmp_path / "Dup Movie 2 (2024).mp4"
    movie.write_bytes(b"\x00" * 64)

    monkeypatch.setattr(fast_scanner, "_collect_files",
                        lambda paths: [_scanfile(movie), _scanfile(movie)])
    # 小批量，跨批次重复
    monkeypatch.setattr(fast_scanner, "FAST_SCAN_BATCH", 1)

    db = SessionLocal()
    lib = em.Library(guid=_guid(), name="去重跨批次测试库",
                     collection_type="movies", paths=str(tmp_path))
    db.add(lib)
    db.commit()
    try:
        snap = LibrarySnapshot.of(lib)
        fast_scanner.scan_library_sync(db, lib, snap, trigger="test")
        n = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib.id).count()
        assert n == 1
    finally:
        _cleanup(db, lib)
        db.close()
