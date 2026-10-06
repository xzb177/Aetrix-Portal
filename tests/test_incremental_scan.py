"""增量扫描测试（v2.50.0）。

验证：
1. 第一次扫描：全量入库
2. 第二次扫描（mtime 未变）：全部跳过，skipped_unchanged == 文件数
3. 第三次扫描（一个文件 mtime 变更）：只处理变更的 1 个
"""
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
    lib = em.Library(
        name=f"增量测试库_{_guid()[:8]}",
        collection_type="movies",
        paths=["mount://1/test"],
    )
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


def _cleanup(db, lib):
    item_ids = [r[0] for r in db.query(em.MediaItem.id).filter(
        em.MediaItem.library_id == lib.id).all()]
    if item_ids:
        db.query(em.MediaStream).filter(
            em.MediaStream.item_id.in_(item_ids)).delete(
                synchronize_session=False)
    db.query(em.MediaItem).filter(
        em.MediaItem.library_id == lib.id).delete(synchronize_session=False)
    db.query(em.Library).filter(em.Library.id == lib.id).delete()
    db.commit()


def _files(mtime_base, count=3):
    """生成测试文件清单"""
    return [
        FastScanFile(
            path=f"mount://1/test/movie{i}.mkv",
            name=f"movie{i}.mkv",
            size=1000 + i,
            mtime=mtime_base + i,
        )
        for i in range(count)
    ]


class _FakeSnapshot:
    paths = ("mount://1/test",)


def _fake_parse(path, lib_type):
    # 简单解析：从文件名提取 name
    name = os.path.basename(path).rsplit(".", 1)[0]
    return {"name": name, "year": 2024, "season": None, "episode": None}


def _fake_guid(s):
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()


def test_incremental_scan_skips_unchanged(db):
    """两次扫描：第二次 mtime 未变，全部跳过"""
    lib = _make_lib(db)
    try:
        mtime_base = time.time()

        # 第一次扫描：3 个文件全量入库
        files1 = _files(mtime_base)
        with mock.patch.object(
            fast_scanner, "_collect_files", return_value=files1
        ), mock.patch(
            "backend.emby_server.scanner.parse_media_filename",
            side_effect=_fake_parse,
        ), mock.patch(
            "backend.emby_server.scanner.item_guid", side_effect=_fake_guid
        ):
            stats1 = fast_scanner.scan_library_fast(db, lib, _FakeSnapshot())

        assert stats1["added"] == 3, f"第一次应入库 3 个，实际 {stats1}"
        assert stats1.get("skipped_unchanged", 0) == 0

        # 第二次扫描：mtime 未变，应全部跳过
        files2 = _files(mtime_base)  # 相同 mtime
        with mock.patch.object(
            fast_scanner, "_collect_files", return_value=files2
        ), mock.patch(
            "backend.emby_server.scanner.parse_media_filename",
            side_effect=_fake_parse,
        ), mock.patch(
            "backend.emby_server.scanner.item_guid", side_effect=_fake_guid
        ):
            stats2 = fast_scanner.scan_library_fast(db, lib, _FakeSnapshot())

        assert stats2["added"] == 0, f"第二次不应新增，实际 {stats2}"
        assert stats2.get("skipped_unchanged", 0) == 3, (
            f"第二次应跳过 3 个未变更，实际 {stats2}"
        )
    finally:
        _cleanup(db, lib)


def test_incremental_scan_processes_changed(db):
    """第三次扫描：1 个文件 mtime 变更，只处理这 1 个"""
    lib = _make_lib(db)
    try:
        mtime_base = time.time()

        # 第一次：全量
        files1 = _files(mtime_base)
        with mock.patch.object(
            fast_scanner, "_collect_files", return_value=files1
        ), mock.patch(
            "backend.emby_server.scanner.parse_media_filename",
            side_effect=_fake_parse,
        ), mock.patch(
            "backend.emby_server.scanner.item_guid", side_effect=_fake_guid
        ):
            fast_scanner.scan_library_fast(db, lib, _FakeSnapshot())

        # 第三次：只有 movie1 的 mtime 变了（+100 秒）
        files3 = _files(mtime_base)
        files3[1] = FastScanFile(
            path="mount://1/test/movie1.mkv",
            name="movie1.mkv",
            size=1001,  # size 不变
            mtime=mtime_base + 1 + 100,  # mtime 变了
        )
        with mock.patch.object(
            fast_scanner, "_collect_files", return_value=files3
        ), mock.patch(
            "backend.emby_server.scanner.parse_media_filename",
            side_effect=_fake_parse,
        ), mock.patch(
            "backend.emby_server.scanner.item_guid", side_effect=_fake_guid
        ):
            stats3 = fast_scanner.scan_library_fast(db, lib, _FakeSnapshot())

        assert stats3["added"] == 0
        assert stats3["updated"] == 1, f"应只更新 1 个，实际 {stats3}"
        assert stats3.get("skipped_unchanged", 0) == 2, (
            f"应跳过 2 个未变更，实际 {stats3}"
        )

        # 验证 DB 里 mtime 已更新
        item = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib.id,
            em.MediaItem.file_path == "mount://1/test/movie1.mkv",
        ).first()
        assert item is not None
        assert abs(item.file_mtime - (mtime_base + 1 + 100)) < 1.0
    finally:
        _cleanup(db, lib)


def test_incremental_scan_new_file(db):
    """新增文件能被发现并入库"""
    lib = _make_lib(db)
    try:
        mtime_base = time.time()

        files1 = _files(mtime_base, count=2)
        with mock.patch.object(
            fast_scanner, "_collect_files", return_value=files1
        ), mock.patch(
            "backend.emby_server.scanner.parse_media_filename",
            side_effect=_fake_parse,
        ), mock.patch(
            "backend.emby_server.scanner.item_guid", side_effect=_fake_guid
        ):
            fast_scanner.scan_library_fast(db, lib, _FakeSnapshot())

        # 新增第 3 个文件
        files2 = _files(mtime_base, count=3)
        with mock.patch.object(
            fast_scanner, "_collect_files", return_value=files2
        ), mock.patch(
            "backend.emby_server.scanner.parse_media_filename",
            side_effect=_fake_parse,
        ), mock.patch(
            "backend.emby_server.scanner.item_guid", side_effect=_fake_guid
        ):
            stats2 = fast_scanner.scan_library_fast(db, lib, _FakeSnapshot())

        assert stats2["added"] == 1, f"应新增 1 个，实际 {stats2}"
        assert stats2.get("skipped_unchanged", 0) == 2
    finally:
        _cleanup(db, lib)
