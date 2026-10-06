"""删除保护：来源异常时不得批量删除媒体记录（fast_scanner 版）

事故形状：**挂载断开 → rclone 返回空/残缺清单 → 清理阶段把整库删了**。

fast_scanner.scan_library_fast 内置两道闸（从旧 scanner._removal_budget 移植）：

1. **零结果**：一个文件都没看到而库里有条目 → 一条都不删
2. **数量阈值**：预计要删的量超过「比例 / 绝对数」上限 → 一条都不删

以及「不该拦的时候别拦」：正常删几条（删了一部下架的电影）仍然要真删。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import models as em
from backend.emby_server import fast_scanner
from backend.emby_server import soft_delete
from backend.integrations import store


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    store.invalidate()
    yield session
    store.invalidate()
    session.close()


def _lib(db, paths="mount://1/test"):
    row = em.Library(guid="g1", name="电影库", collection_type="movies",
                     paths=paths, storage_backends="")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _item(db, lib, guid, path=None):
    row = em.MediaItem(guid=guid, library_id=lib.id, item_type="movie",
                       name=guid, file_path=path or f"/mnt/mp/test/{guid}.mp4")
    db.add(row)
    db.commit()
    return row


def _files(*names):
    """造一批 FastScanFile"""
    return [fast_scanner.FastScanFile(
        path=f"/mnt/mp/test/{n}.mp4", name=f"{n}.mp4", size=100, mtime=1.0)
        for n in names]


def _scan(db, lib, files):
    """用 mock 的文件清单跑一轮 fast 扫描，返回 stats"""
    import unittest.mock as mock
    from backend.emby_server.scanner import LibrarySnapshot
    snap = LibrarySnapshot.of(lib)
    with mock.patch.object(fast_scanner, "_collect_files", return_value=files):
        return fast_scanner.scan_library_sync(db, lib, snap, trigger="test")


def _visible_count(db, lib):
    return db.execute(text(
        "SELECT COUNT(*) FROM emby_items WHERE library_id = :l "
        "AND deleted_at IS NULL"), {"l": lib.id}).scalar()


# ==================== 零结果：事故主体 ====================

def test_zero_files_seen_blocks_all_removal(db, monkeypatch):
    """rclone 返回空清单、库里有 30 条 → 全部保住，stats 标记 removal_skipped"""
    lib = _lib(db)
    for i in range(30):
        _item(db, lib, f"m{i:02d}")

    stats = _scan(db, lib, [])

    assert stats.get("removal_skipped") is True
    assert _visible_count(db, lib) == 30, "零结果时不允许删任何条目"
    assert stats.get("failed_roots"), "必须留下拦截原因供排障"


def test_zero_seen_blocks_even_a_tiny_library(db):
    """小库也要拦：库里就 1 条、这轮看到 0 个 —— 那一条也不能删"""
    lib = _lib(db)
    _item(db, lib, "only")

    stats = _scan(db, lib, [])

    assert stats.get("removal_skipped") is True
    assert _visible_count(db, lib) == 1


# ==================== 数量阈值 ====================

def test_mass_loss_beyond_ratio_is_blocked(db):
    """看到 5 条、库里有 100 条（要删 95 条）→ 拦住"""
    lib = _lib(db)
    for i in range(100):
        _item(db, lib, f"m{i:03d}")

    stats = _scan(db, lib, _files(*[f"m{i:03d}" for i in range(5)]))

    assert stats.get("removal_skipped") is True
    assert _visible_count(db, lib) == 100
    assert "阈值" in (stats.get("failed_roots") or [""])[0]


def test_absolute_floor_protects_small_libraries(db, monkeypatch):
    """库里 5 条、看到 1 条（要删 4 条）：比例放到最松也拦得住"""
    monkeypatch.setattr(fast_scanner, "REMOVAL_MAX_RATIO", 0.99)
    monkeypatch.setattr(fast_scanner, "REMOVAL_MAX_ABSOLUTE", 3)
    lib = _lib(db)
    for i in range(5):
        _item(db, lib, f"m{i}")

    stats = _scan(db, lib, _files("m0"))

    assert stats.get("removal_skipped") is True
    assert _visible_count(db, lib) == 5


# ==================== 不能“一刀切地不删” ====================

def test_normal_small_cleanup_still_deletes(db):
    """正常场景要真删：101 条里删 1 条（一部片下架了），必须下架它"""
    lib = _lib(db)
    _item(db, lib, "gone", path="/mnt/mp/test/gone.mp4")
    names = [f"m{i:03d}" for i in range(100)]
    for n in names:
        _item(db, lib, n)

    stats = _scan(db, lib, _files(*names))

    assert not stats.get("removal_skipped")
    assert stats.get("removed") == 1
    # 默认是软删除：行还在、标记 deleted_at
    assert _visible_count(db, lib) == 100
    with soft_delete.include_deleted():
        hidden = db.query(em.MediaItem).filter(
            em.MediaItem.guid == "gone").one()
    assert hidden.deleted_at is not None


def test_empty_library_is_not_blocked(db):
    """库里本来就没条目 → 不该拦也不该报错"""
    lib = _lib(db)
    stats = _scan(db, lib, [])
    assert not stats.get("removal_skipped")
