"""分层扫描（v2.40.0）：文件指纹秒跳 + L1 极简入库。

- 文件指纹：本机=path|size|mtime，远程=path|size；
- 秒跳：指纹命中且 enrich_status='done' → 零 IO，不提交任何预取；
- L1：新文件/指纹变化 → 极简入库，enrich_status='pending'，等后台补全。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import scanner

init_db()


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _guid():
    return uuid.uuid4().hex


def _mkfile(path="/v/x.mp4", size=100, mtime_ns=123):
    return scanner.ScanFile(
        stored_path=path, name=os.path.basename(path),
        local_dir=os.path.dirname(path), size=size, mtime_ns=mtime_ns,
    )


def test_file_fingerprint_local_uses_mtime():
    a = _mkfile("/v/a.mp4", size=100, mtime_ns=111)
    b = _mkfile("/v/a.mp4", size=100, mtime_ns=222)
    c = _mkfile("/v/a.mp4", size=100, mtime_ns=111)
    assert scanner._file_fingerprint(a) != scanner._file_fingerprint(b)
    assert scanner._file_fingerprint(a) == scanner._file_fingerprint(c)


def test_file_fingerprint_remote_no_mtime():
    a = scanner.ScanFile(stored_path="mount://2/a.mp4", name="a.mp4",
                         local_dir=None, size=100, mtime_ns=None)
    b = scanner.ScanFile(stored_path="mount://2/a.mp4", name="a.mp4",
                         local_dir=None, size=200, mtime_ns=None)
    assert scanner._file_fingerprint(a) != scanner._file_fingerprint(b)


def test_fast_skip_no_io(db):
    """指纹命中 + 已补全 → 秒跳：不提交 side/NFO/TMDB/probe"""
    lib = em.Library(name="t", collection_type="movies")
    db.add(lib)
    db.flush()
    sf = _mkfile("/v/x.mp4")
    fp = scanner._file_fingerprint(sf)
    guid = scanner.item_guid(sf.stored_path)
    item = em.MediaItem(guid=guid, library_id=lib.id, item_type="movie",
                        name="x", file_path=sf.stored_path,
                        file_fingerprint=fp, enrich_status="done")
    db.add(item)
    db.commit()

    snap = SimpleNamespace(
        library_id=lib.id, collection_type="movies", scrape_policy="smart")
    ctx = scanner._ScanContext(snap=snap, lib_id=lib.id, stats={})
    with mock.patch.object(scanner, "_dir_fingerprint",
                           side_effect=AssertionError("不应算目录指纹")):
        prepared = scanner._prepare_and_prefetch(db, [sf], ctx, pool=None)
    assert len(prepared) == 1
    p = prepared[0]
    assert p.fast_skipped is True
    assert p.side is None and p.nfo is None and p.tmdb is None
    assert p.probe is None and not p.probe_deferred
    assert ctx.stats.get("unchanged") == 1


def test_fingerprint_mismatch_not_skipped(db):
    """指纹对不上（文件变了）→ 走正常流程"""
    lib = em.Library(name="t", collection_type="movies")
    db.add(lib)
    db.flush()
    sf = _mkfile("/v/y.mp4", size=100, mtime_ns=111)
    guid = scanner.item_guid(sf.stored_path)
    item = em.MediaItem(guid=guid, library_id=lib.id, item_type="movie",
                        name="y", file_path=sf.stored_path,
                        file_fingerprint="stale", enrich_status="done")
    db.add(item)
    db.commit()

    # 文件大小变了 → 指纹变化
    sf2 = _mkfile("/v/y.mp4", size=999, mtime_ns=111)
    snap = SimpleNamespace(
        library_id=lib.id, collection_type="movies", scrape_policy="smart")
    ctx = scanner._ScanContext(snap=snap, lib_id=lib.id, stats={})
    with mock.patch.object(scanner, "SCAN_LAYERED", False):
        prepared = scanner._prepare_and_prefetch(db, [sf2], ctx, pool=None)
    assert len(prepared) == 1
    assert prepared[0].fast_skipped is False


def test_pending_enrich_not_fast_skipped(db):
    """指纹命中但 enrich_status='pending'（L2 没补完）→ 不秒跳，等补全"""
    lib = em.Library(name="t", collection_type="movies")
    db.add(lib)
    db.flush()
    sf = _mkfile("/v/z.mp4")
    fp = scanner._file_fingerprint(sf)
    guid = scanner.item_guid(sf.stored_path)
    item = em.MediaItem(guid=guid, library_id=lib.id, item_type="movie",
                        name="z", file_path=sf.stored_path,
                        file_fingerprint=fp, enrich_status="pending")
    db.add(item)
    db.commit()

    snap = SimpleNamespace(
        library_id=lib.id, collection_type="movies", scrape_policy="smart")
    ctx = scanner._ScanContext(snap=snap, lib_id=lib.id, stats={})
    with mock.patch.object(scanner, "SCAN_LAYERED", False):
        prepared = scanner._prepare_and_prefetch(db, [sf], ctx, pool=None)
    assert prepared[0].fast_skipped is False


def test_layered_new_file_minimal(db):
    """分层 L1：新文件只做极简入库，不提交 IO，enrich_status='pending'"""
    lib = em.Library(name="t", collection_type="movies")
    db.add(lib)
    db.flush()
    sf = _mkfile("/v/new.mp4")
    snap = SimpleNamespace(
        library_id=lib.id, collection_type="movies", scrape_policy="smart")
    ctx = scanner._ScanContext(snap=snap, lib_id=lib.id, stats={})
    # SCAN_LAYERED 默认就是 1，这里显式确认行为
    assert scanner.SCAN_LAYERED is True
    prepared = scanner._prepare_and_prefetch(db, [sf], ctx, pool=None)
    assert len(prepared) == 1
    p = prepared[0]
    assert p.layered is True
    assert p.side is None and p.nfo is None and p.tmdb is None
