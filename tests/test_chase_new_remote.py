"""追新远程检测：文件指纹快照 diff（P0-2）。

生产实证（P0 回归）：Drive 上季目录 mtime=2026-07-30，但其内新剧集文件
mtime=2026-08-08。旧实现按**目录 mtime**过滤，把这类季目录整个跳过 →
新剧集永远发现不了，管理后台恒显示"上轮发现 0 个新文件"。

新语义：文件级列举拿 (rel_path, size, mod_ts)，与 chase_file_snapshot diff——
快照无记录=新增，size/mod_ts 变化=变更。目录 mtime 不再参与判定。

本文件钉住：
1. 基线：首次对某源列举只建快照、不触发（防部署后扫描风暴）。
2. 新增 / 变更 / 未变三种 diff 结果。
3. 每源每小时最多一次快照列举（last_snapshot_at 门控）。
4. drive_changes 在跑时远程源跳过快照列举（平时靠 Changes API 的 O(Δ)）。
5. cli 模式 / 未启用 / 不存在的挂载安静跳过。
6. 仍走 mounts 公共通道（build_provider → list_dir，吃缓存/限流/追新小名额）。

全部用内存 SQLite + fake rclone RC，不碰网络与生产库。
"""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models as base_models
from backend.emby_server import change_watcher as cw
from backend.emby_server import drive_changes
from backend.emby_server import models as em
from backend.emby_server import mount_rclone
from backend.emby_server import mounts as mount_lib


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    base_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clean_cache():
    mount_lib.invalidate_list_cache()
    yield
    mount_lib.invalidate_list_cache()


def _mount(db, mid=3, mode="rc", enabled=True):
    m = em.StorageMount(
        id=mid, name=f"m{mid}", mount_type="rclone",
        config='{"mode":"%s","rc_url":"http://rclone:5572","fs":"MP:"}' % mode,
        is_enabled=enabled)
    db.add(m)
    db.commit()
    return m


def _lib(db):
    lib = em.Library(guid="g-chase-remote", name="测试库",
                     collection_type="movies", paths="mount://3/MP2")
    db.add(lib)
    db.commit()
    return lib


def _install_tree(monkeypatch, tree: dict, calls: list):
    """把远端目录树装到 rclone RC 上（key 是相对 fs 根的 remote 路径）"""

    def fake_rc(rc_url, path, payload, username="", password="", **kwargs):
        remote = payload["remote"]
        calls.append(remote)
        return {"list": tree.get(remote, [])}

    monkeypatch.setattr(mount_rclone, "rc_call", fake_rc)


def _backdate_snapshot(db, hours=2):
    """把快照时间拨到 N 小时前，绕过「每源每小时一次」的门控。"""
    st = db.get(em.ChaseSourceState, "mount://3/MP2")
    assert st is not None and st.last_snapshot_at is not None
    st.last_snapshot_at = datetime.now(timezone.utc) - timedelta(hours=hours)
    db.commit()
    mount_lib.invalidate_list_cache()  # 目录缓存也要清，否则列举命中旧缓存


# ---------------------------------------------------------------------------
# 基础：mount:// 路径解析（未变，保留）
# ---------------------------------------------------------------------------

def test_library_mount_sources_parses_mount_paths():
    lib = SimpleNamespace(paths="mount://3/MoviePilot/电影/华语电影", mount_ids="")
    assert cw._library_mount_sources(lib, None) == [(3, "/MoviePilot/电影/华语电影")]


def test_library_mount_sources_skips_non_mount_paths():
    lib = SimpleNamespace(paths="/data/local/movies,/nonexistent", mount_ids="")
    assert cw._library_mount_sources(lib, None) == []


# ---------------------------------------------------------------------------
# 快照 diff 三种结果 + 基线
# ---------------------------------------------------------------------------

def test_remote_baseline_builds_silently(db, monkeypatch):
    """P0-2：首次对某源列举只建快照、返回空——部署后第一轮不能把全库当新增
    触发扫描风暴。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib = _lib(db)
    tree = {"MP2": [
        {"Path": "x.mkv", "Name": "x.mkv", "IsDir": False,
         "ModTime": _iso(now - 60), "Size": 100},
        {"Path": "y.mkv", "Name": "y.mkv", "IsDir": False,
         "ModTime": _iso(now - 60), "Size": 200},
    ]}
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    found, listed = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")

    assert found == []
    assert listed == 2
    rows = db.query(em.ChaseFileSnapshot).filter(
        em.ChaseFileSnapshot.library_id == lib.id).all()
    assert len(rows) == 2
    st = db.get(em.ChaseSourceState, "mount://3/MP2")
    assert st is not None and st.last_snapshot_at is not None
    assert st.consec_failures == 0


def test_remote_snapshot_detects_new_file(db, monkeypatch):
    """P0 回归：老剧顶层目录 mtime 很旧、但 Season 里出了新集——文件级 diff
    必须检出（旧实现按目录 mtime 整个跳过，永远漏检）。"""
    now = datetime.now(timezone.utc).timestamp()
    fresh = now - 60
    old = now - 10 * 86400
    _mount(db)
    lib = _lib(db)
    tree = {
        # 顶层 mtime 很旧：新集只改了 Season/ 的 mtime，顶层不动
        "MP2": [
            {"Path": "老剧 (2019)", "Name": "老剧 (2019)", "IsDir": True,
             "ModTime": _iso(old), "Size": 0},
        ],
        "MP2/老剧 (2019)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True,
             "ModTime": _iso(fresh), "Size": 0},
        ],
        "MP2/老剧 (2019)/Season 01": [
            {"Path": "E98.mkv", "Name": "E98.mkv", "IsDir": False,
             "ModTime": _iso(old), "Size": 100},
        ],
    }
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    found, _ = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")
    assert found == []  # 基线

    # 新出一集 E99（只有 Season/ 的 mtime 变了，顶层目录 mtime 还是旧的）
    tree["MP2/老剧 (2019)/Season 01"].append(
        {"Path": "E99.mkv", "Name": "E99.mkv", "IsDir": False,
         "ModTime": _iso(fresh), "Size": 120})
    _backdate_snapshot(db)

    found, listed = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")

    assert found == ["mount://3/MP2/老剧 (2019)/Season 01/E99.mkv"], found
    assert listed == 2


def test_remote_snapshot_detects_changed_file(db, monkeypatch):
    """size 或 mod_ts 变化 = 变更（比如重压制覆盖了同名文件）。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib = _lib(db)
    tree = {"MP2": [
        {"Path": "x.mkv", "Name": "x.mkv", "IsDir": False,
         "ModTime": _iso(now - 60), "Size": 100},
    ]}
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)
    assert cw._find_new_videos_remote(db, lib.id, 3, "/MP2")[0] == []

    tree["MP2"][0]["Size"] = 999
    _backdate_snapshot(db)

    found, _ = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")
    assert found == ["mount://3/MP2/x.mkv"], found


def test_remote_snapshot_ignores_unchanged(db, monkeypatch):
    """快照一致 → 返回空，不触发扫描。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib = _lib(db)
    tree = {"MP2": [
        {"Path": "x.mkv", "Name": "x.mkv", "IsDir": False,
         "ModTime": _iso(now - 60), "Size": 100},
    ]}
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)
    assert cw._find_new_videos_remote(db, lib.id, 3, "/MP2")[0] == []
    _backdate_snapshot(db)

    found, listed = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")
    assert found == []
    assert listed == 1


def test_remote_snapshot_walks_nested_dirs(db, monkeypatch):
    """季目录里还有一层（特别篇 / 压制组）时也要能挖到。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib = _lib(db)
    tree = {
        "MP2": [
            {"Path": "剧 (2020)", "Name": "剧 (2020)", "IsDir": True,
             "ModTime": _iso(now - 60), "Size": 0},
        ],
        "MP2/剧 (2020)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True,
             "ModTime": _iso(now - 60), "Size": 0},
        ],
        "MP2/剧 (2020)/Season 01": [
            {"Path": "Specials", "Name": "Specials", "IsDir": True,
             "ModTime": _iso(now - 60), "Size": 0},
        ],
        "MP2/剧 (2020)/Season 01/Specials": [
            {"Path": "SP01.mkv", "Name": "SP01.mkv", "IsDir": False,
             "ModTime": _iso(now - 60), "Size": 50},
        ],
    }
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)
    # 基线
    assert cw._find_new_videos_remote(db, lib.id, 3, "/MP2")[0] == []
    _backdate_snapshot(db)

    # Specials 里加一个新特别篇
    tree["MP2/剧 (2020)/Season 01/Specials"].append(
        {"Path": "SP02.mkv", "Name": "SP02.mkv", "IsDir": False,
         "ModTime": _iso(now - 10), "Size": 60})
    _backdate_snapshot(db)

    found, _ = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")
    assert found == ["mount://3/MP2/剧 (2020)/Season 01/Specials/SP02.mkv"], found


# ---------------------------------------------------------------------------
# 成本控制：hourly 门控 / drive_changes 避让
# ---------------------------------------------------------------------------

def test_remote_hourly_gate_skips_listing(db, monkeypatch):
    """快照未满 1 小时 → 直接返回，不再发起任何列举（全量列举贵）。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib = _lib(db)
    tree = {"MP2": [
        {"Path": "x.mkv", "Name": "x.mkv", "IsDir": False,
         "ModTime": _iso(now - 60), "Size": 100},
    ]}
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)
    cw._find_new_videos_remote(db, lib.id, 3, "/MP2")
    calls.clear()

    found, listed = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")

    assert (found, listed) == ([], 0)
    assert calls == [], calls


def test_remote_skips_when_drive_changes_active(db, monkeypatch):
    """drive_changes 在跑时远程源跳过快照列举——平时靠 Changes API 的 O(Δ)。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib = _lib(db)
    tree = {"MP2": [
        {"Path": "x.mkv", "Name": "x.mkv", "IsDir": False,
         "ModTime": _iso(now - 60), "Size": 100},
    ]}
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)
    monkeypatch.setattr(drive_changes, "is_running", lambda: True)

    found, listed = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")

    assert (found, listed) == ([], 0)
    assert calls == [], calls


# ---------------------------------------------------------------------------
# 挂载不可用时安静跳过
# ---------------------------------------------------------------------------

def test_chase_new_skips_cli_mode_mounts(db, monkeypatch):
    """cli 模式不走这条实现（ModTime 口径不同），应当安静跳过而不是抛错。"""
    _mount(db, mode="cli")
    lib = _lib(db)
    calls: list[str] = []
    _install_tree(monkeypatch, {}, calls)

    found, listed = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")

    assert (found, listed) == ([], 0)
    assert calls == []


def test_chase_new_skips_disabled_mount(db, monkeypatch):
    _mount(db, enabled=False)
    lib = _lib(db)
    calls: list[str] = []
    _install_tree(monkeypatch, {}, calls)

    found, listed = cw._find_new_videos_remote(db, lib.id, 3, "/MP2")

    assert (found, listed) == ([], 0)
    assert calls == []


def test_remote_missing_mount(db, monkeypatch):
    """挂载不存在 → 空结果，不抛错。"""
    lib = _lib(db)
    calls: list[str] = []
    _install_tree(monkeypatch, {}, calls)

    found, listed = cw._find_new_videos_remote(db, lib.id, 999, "/MP2")

    assert (found, listed) == ([], 0)
    assert calls == []


# ---------------------------------------------------------------------------
# 仍走 mounts 公共通道（缓存 / 限流 / 追新小名额）
# ---------------------------------------------------------------------------

def test_chase_new_goes_through_public_channel(db, monkeypatch):
    """同一目录短时间内再问一次应当命中目录缓存（不再打网络）——
    这是「走了公共通道」的直接证据。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib = _lib(db)
    tree = {"MP2": [
        {"Path": "x.mkv", "Name": "x.mkv", "IsDir": False,
         "ModTime": _iso(now - 60), "Size": 100},
    ]}
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    cw._find_new_videos_remote(db, lib.id, 3, "/MP2")  # 基线
    after_first = len(calls)
    assert after_first == 1, calls
    # 绕过 hourly 门控，但**不清目录缓存**（缓存还在 TTL 内）
    st = db.get(em.ChaseSourceState, "mount://3/MP2")
    st.last_snapshot_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()

    cw._find_new_videos_remote(db, lib.id, 3, "/MP2")

    assert len(calls) == after_first, calls


def test_two_libraries_on_same_mount_both_get_snapshotted(db, monkeypatch):
    """同一挂载（生产全部库都在 mount://3 下）上的第二个库不能被第一个库的
    「每源每小时一次」门控挡住——否则只有第一个库能追到新片。"""
    now = datetime.now(timezone.utc).timestamp()
    _mount(db)
    lib_a = _lib(db)
    lib_b = em.Library(guid="g-chase-remote-b", name="测试库B",
                       collection_type="movies", paths="mount://3/TV")
    db.add(lib_b)
    db.commit()
    tree = {
        "MP2": [{"Path": "MP2/a.mkv", "Name": "a.mkv", "IsDir": False,
                 "ModTime": _iso(now - 60), "Size": 1}],
        "TV": [{"Path": "TV/b.mkv", "Name": "b.mkv", "IsDir": False,
                "ModTime": _iso(now - 60), "Size": 1}],
    }
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    _, n_a = cw._find_new_videos_remote(db, lib_a.id, 3, "/MP2")
    _, n_b = cw._find_new_videos_remote(db, lib_b.id, 3, "/TV")

    assert n_a == 1
    assert n_b == 1, "同挂载第二个库被第一个库的快照门控跳过了"
    assert "TV" in calls
