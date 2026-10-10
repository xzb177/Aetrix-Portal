"""追新 .strm 增量扫描能力

背景：.strm 通用化之后，全部 11 个生产库的路径都是 /strm/...（本地目录，
里面全是 .strm 文件）。但追新的 VIDEO_EXTS 里没有 .strm——strm_gen 产出新
.strm（比如新分集）之后，追新永远发现不了，只能等手动扫描或每日定时扫描。

本文件覆盖：
1. .strm 开关开（默认）时，新 .strm 文件被检测到
2. .strm 开关关时，.strm 被忽略、视频文件照常检测
3. find 超时走 scandir 兜底时，扩展名口径一致
4. get_config / save_config 透传 strm_enabled
5. 远程逐层列举（_walk_files）同样受开关控制

全部用内存 SQLite + 临时目录，不碰网络与生产库。
"""
import os
import subprocess
import time

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import change_watcher as cw
from backend.emby_server import models as em
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


def _new_files(tmp_path, names):
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    return time.time() - 60  # since：1 分钟前


# ==================== 扩展名口径 ====================

def test_strm_detected_when_enabled(db, tmp_path):
    since = _new_files(tmp_path, ["new.strm", "new.mkv", "notes.txt"])
    exts = cw._tracked_exts(db)  # 默认开关开
    assert ".strm" in exts
    found = cw._find_new_videos([str(tmp_path)], since, exts)
    names = [os.path.basename(p) for p in found]
    assert "new.strm" in names, ".strm 开关开时新 .strm 必须被发现"
    assert "new.mkv" in names
    assert "notes.txt" not in names


def test_strm_ignored_when_disabled(db, tmp_path):
    cw.save_config(db, enabled=True, interval=10, strm_enabled=False)
    since = _new_files(tmp_path, ["new.strm", "new.mkv"])
    exts = cw._tracked_exts(db)
    assert ".strm" not in exts
    found = cw._find_new_videos([str(tmp_path)], since, exts)
    names = [os.path.basename(p) for p in found]
    assert "new.strm" not in names, ".strm 开关关时 .strm 必须被忽略"
    assert "new.mkv" in names, "视频文件不受 .strm 开关影响"


def test_strm_defaults_on_for_legacy_deployments(db):
    """.strm 开关没配过（老部署升级）时默认开——和 get_config 的默认一致。"""
    assert cw._tracked_exts(db) >= {".strm"}
    assert cw.get_config(db)["strm_enabled"] is True


def test_scandir_fallback_respects_strm_switch(db, tmp_path, monkeypatch):
    """find 超时走 scandir 兜底时，.strm 口径必须和主路径一致。"""
    since = _new_files(tmp_path, ["new.strm"])

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="find", timeout=10)

    monkeypatch.setattr(subprocess, "run", boom)

    on_exts = cw._tracked_exts(db)
    assert any(p.endswith("new.strm")
               for p in cw._find_new_videos([str(tmp_path)], since, on_exts))

    cw.save_config(db, enabled=True, interval=10, strm_enabled=False)
    off_exts = cw._tracked_exts(db)
    assert not any(p.endswith("new.strm")
                   for p in cw._find_new_videos([str(tmp_path)], since, off_exts))


# ==================== 配置透传 ====================

def test_config_round_trips_strm_enabled(db):
    cfg = cw.save_config(db, enabled=True, interval=10, strm_enabled=False)
    assert cfg["strm_enabled"] is False
    assert cw.get_config(db)["strm_enabled"] is False

    cfg = cw.save_config(db, enabled=True, interval=10, strm_enabled=True)
    assert cfg["strm_enabled"] is True
    assert cw.get_config(db)["strm_enabled"] is True


def test_save_config_defaults_strm_on(db):
    """老调用方（不传 strm_enabled）保存后，.strm 监听保持开。"""
    cfg = cw.save_config(db, enabled=True, interval=10)
    assert cfg["strm_enabled"] is True


def test_strm_none_keeps_existing_value(db):
    """strm_enabled=None（老前端没这个字段）时，不许把现有值悄悄改掉。"""
    cw.save_config(db, enabled=True, interval=10, strm_enabled=False)
    assert cw.get_config(db)["strm_enabled"] is False
    # 模拟老前端：没传 strm_enabled
    cfg = cw.save_config(db, enabled=True, interval=10, strm_enabled=None)
    assert cfg["strm_enabled"] is False, "None 必须保持现有值，不能被默认 True 覆盖"
    assert cw.get_config(db)["strm_enabled"] is False


# ==================== 远程列举 ====================

class _FakeEntry:
    def __init__(self, name, is_dir=False, rel=""):
        self.name = name
        self.is_dir = is_dir
        self.rel = rel


class _FakeProvider:
    def __init__(self, entries):
        self._entries = entries

    def list_dir(self, _path):
        return self._entries


def test_walk_files_includes_strm_when_enabled(db):
    provider = _FakeProvider([
        _FakeEntry("a.mkv", rel="a.mkv"),
        _FakeEntry("b.strm", rel="b.strm"),
        _FakeEntry("c.txt", rel="c.txt"),
    ])
    found = cw._walk_files(provider, "/", 2, 100, cw._tracked_exts(db))
    names = sorted(e.name for e in found)
    assert names == ["a.mkv", "b.strm"]


def test_walk_files_excludes_strm_when_disabled(db):
    cw.save_config(db, enabled=True, interval=10, strm_enabled=False)
    provider = _FakeProvider([
        _FakeEntry("a.mkv", rel="a.mkv"),
        _FakeEntry("b.strm", rel="b.strm"),
    ])
    found = cw._walk_files(provider, "/", 2, 100, cw._tracked_exts(db))
    assert [e.name for e in found] == ["a.mkv"]


def test_empty_first_round_does_not_swallow_later_files(db):
    """空目录首轮不建基线：之后新文件进来必须上报，不能被「快照仍为空」吞掉。"""
    # 首轮：空
    assert cw._diff_against_snapshot(db, 7, "src", [], baseline_if_empty=True) == []
    # 次轮：新文件（快照依然是空的，但不能再当基线）
    changed = cw._diff_against_snapshot(db, 7, "src", [("/n.strm", 10, 999.0)],
                                        baseline_if_empty=False)
    assert changed == ["/n.strm"]


# ==================== 端到端：_check_once ====================

def test_check_once_enqueues_scan_for_new_strm(db, tmp_path):
    """新 .strm 文件 → _check_once 真实走 find 检测到 → 触发该库的定向扫描。

    注意：每个源第一轮是建基线（不触发扫描，防扫描风暴），所以先跑一轮建基线，
    再放新 .strm 文件跑第二轮。
    """
    from unittest import mock

    lib_dir = tmp_path / "国产剧"
    lib_dir.mkdir()
    row = em.Library(guid="g-strm", name="国产剧", collection_type="tvshows",
                     is_enabled=True, paths=str(lib_dir))
    db.add(row)
    db.commit()
    db.refresh(row)

    cw.save_config(db, enabled=True, interval=10)  # .strm 开关默认开
    enqueued = []

    class _SessionShim:
        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    def _run_once():
        with mock.patch.object(cw, "SessionLocal", lambda: _SessionShim()), \
                mock.patch.object(cw, "_library_mount_sources", lambda lib, _db: []), \
                mock.patch.object(cw.scan_queue, "enqueue_targeted",
                                  lambda lib, prefixes, **kw: enqueued.append(
                                      (lib.id, prefixes, kw.get("trigger")))):
            cw._check_once()

    _run_once()  # 第一轮：建基线，不触发
    assert enqueued == []

    (lib_dir / "新剧集 - S01E01.strm").write_bytes(b"https://example/x")
    _run_once()  # 第二轮：新 .strm 必须被发现

    assert len(enqueued) == 1
    lib_id, prefixes, trigger = enqueued[0]
    assert lib_id == row.id
    assert trigger == "chase-new"
    assert any(str(lib_dir) in p for p in prefixes), \
        f"定向扫描前缀应指向新 .strm 所在目录，实际: {prefixes}"


def test_check_once_ignores_strm_when_disabled(db, tmp_path):
    """.strm 开关关时，新 .strm 文件不应触发扫描。"""
    from unittest import mock

    lib_dir = tmp_path / "国产剧"
    lib_dir.mkdir()
    (lib_dir / "新剧集 - S01E01.strm").write_bytes(b"https://example/x")
    row = em.Library(guid="g-strm2", name="国产剧", collection_type="tvshows",
                     is_enabled=True, paths=str(lib_dir))
    db.add(row)
    db.commit()
    db.refresh(row)

    cw.save_config(db, enabled=True, interval=10, strm_enabled=False)
    enqueued = []

    class _SessionShim:
        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    with mock.patch.object(cw, "SessionLocal", lambda: _SessionShim()), \
            mock.patch.object(cw, "_library_mount_sources", lambda lib, _db: []), \
            mock.patch.object(cw.scan_queue, "enqueue_targeted",
                              lambda lib, prefixes, **kw: enqueued.append(lib.id)):
        cw._check_once()

    assert enqueued == []
