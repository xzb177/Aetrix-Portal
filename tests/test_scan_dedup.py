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
from backend.emby_server import mounts as _mounts  # noqa: F401 -- 必须先于 mount_cloud 导入，避免循环导入
from backend.emby_server import mount_cloud
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
    return scanner.ScanFile(
        stored_path=str(path), name=path.name,
        local_dir=str(path.parent), size=64, container="mp4",
    )


def test_duplicate_files_do_not_break_scan(tmp_path, monkeypatch):
    """遍历器产出同一文件两次：扫描不抛异常、只落库一条、文件不丢。"""
    monkeypatch.setattr(scanner, "PROBE_BACKGROUND", True)
    monkeypatch.setattr(
        scanner, "probe_metadata",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("background 模式不应探测")))

    movie = tmp_path / "Dup Movie (2024).mp4"
    movie.write_bytes(b"\x00" * 64)
    sf = _scanfile(movie)

    def fake_sources(snap, library, db, failed_roots, report=None):
        # 同一个文件出现两次 = 遍历器重复产出（生产事故的复现）
        yield "test", iter([sf, _scanfile(movie)])

    monkeypatch.setattr(scanner, "iter_scan_sources", fake_sources)

    db = SessionLocal()
    lib = em.Library(guid=_guid(), name="去重测试库",
                     collection_type="movies", paths=str(tmp_path))
    db.add(lib)
    db.commit()
    try:
        scanner.scan_library_sync(db, lib)  # 旧代码在这里抛 IntegrityError
        rows = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib.id).all()
        assert len(rows) == 1, f"重复文件应只落库一条，实际 {len(rows)} 条"
        # 文件没丢：正常入库，且清理阶段没把它当孤儿删掉
        assert rows[0].file_path == str(movie)
        # 重复被计数进扫描统计
        lib_row = db.query(em.Library).filter(em.Library.id == lib.id).one()
        stats = scanner.decode_scan_stats(lib_row.scan_stats)
        assert stats.get("duplicate_files") == 1
        assert stats.get("added") == 1
    finally:
        _cleanup(db, lib)
        db.close()


def test_duplicate_files_across_batches(tmp_path, monkeypatch):
    """重复出现在后面的批次：同样只处理一次（seen_guids 跨批次有效）。"""
    monkeypatch.setattr(scanner, "PROBE_BACKGROUND", True)
    monkeypatch.setattr(
        scanner, "probe_metadata",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("background 模式不应探测")))
    monkeypatch.setattr(scanner, "SCAN_BATCH", 1)  # 每个文件一批

    movie = tmp_path / "Dup Movie 2 (2024).mp4"
    movie.write_bytes(b"\x00" * 64)
    sf = _scanfile(movie)

    def fake_sources(snap, library, db, failed_roots, report=None):
        yield "test", iter([sf, _scanfile(movie)])

    monkeypatch.setattr(scanner, "iter_scan_sources", fake_sources)

    db = SessionLocal()
    lib = em.Library(guid=_guid(), name="去重跨批次测试库",
                     collection_type="movies", paths=str(tmp_path))
    db.add(lib)
    db.commit()
    try:
        scanner.scan_library_sync(db, lib)
        n = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib.id).count()
        assert n == 1
        lib_row = db.query(em.Library).filter(em.Library.id == lib.id).one()
        stats = scanner.decode_scan_stats(lib_row.scan_stats)
        assert stats.get("duplicate_files") == 1
    finally:
        _cleanup(db, lib)
        db.close()


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

    files = list(mount_cloud._CloudMount.walk_media(_Stub(), root="/"))
    assert [f.rel for f in files] == ["/dir/a.mkv"]
