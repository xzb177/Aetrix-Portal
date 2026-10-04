"""排除清单同时管追新 **和** inotify（§九：后端/前端/定时扫描/实时监听同一语义）

钉住两件事：

1. **同一份排除清单**。``fs_watcher.sync_from_db`` 必须读
   ``change_watcher.resolve_excluded``（含旧包含清单的一次性迁移），不能自己另写一套。
   被排除的库既不进追新轮询，也不该被 inotify 监听——之前它只看
   ``is_enabled``/``fs_watch``，于是用户「关掉」的库仍在被文件变动触发扫描。
2. **改完立即生效**。``save_config`` 保存后要重建监听，不用等容器重启；
   且重建必须幂等（不能叠出第二个 observer）。

不碰真实 inotify：``WATCHDOG_AVAILABLE`` 与 ``Observer`` 都被替换掉，只验证
「选了哪些库去watch」这一层决策。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import change_watcher as cw
from backend.emby_server import fs_watcher as fw
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


class _FakeWatch:
    def __init__(self):
        self.unscheduled = []

    def unschedule(self, handle):
        self.unscheduled.append(handle)


class _FakeObserver:
    def __init__(self):
        self.scheduled = []
        self.unscheduled = []

    def schedule(self, handler, path, recursive=False):
        self.scheduled.append(path)
        return f"watch:{path}"

    def unschedule(self, handle):
        self.unscheduled.append(handle)


@pytest.fixture()
def watched(monkeypatch, tmp_path, db):
    """装一套假 observer，暴露「实际给哪些库 / 哪些目录挂了 watch」"""
    libdir = tmp_path / "mnt"
    libdir.mkdir()
    observer = _FakeObserver()
    monkeypatch.setattr(fw, "WATCHDOG_AVAILABLE", True)
    monkeypatch.setattr(fw, "_OBSERVER", observer)
    monkeypatch.setattr(fw, "_LIBRARY_PATHS", {})
    monkeypatch.setattr(fw, "_DEGRADED", {})
    monkeypatch.setattr(fw, "_WATCHES", {})
    monkeypatch.setattr(fw, "_LAST_TRIGGER", {})
    monkeypatch.setattr(fw, "_PENDING", {})
    monkeypatch.setattr(fw, "_mountinfo_cache", (1e18, [(str(libdir), "ext4"), ("/", "ext4")]))

    import backend.database as database
    monkeypatch.setattr(database, "SessionLocal", lambda: _SessionProxy(db))
    return observer


class _SessionProxy:
    """``sync_from_db`` 会 ``SessionLocal()`` 然后 ``db.close()``。

    直接把测试的 session 交出去会被它关掉（后面的断言就废了），所以包一层：
    其它方法全转发到真 session（``resolve_excluded`` 会用到 query/execute 等），
    只把 ``close`` 吃掉。
    """

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        # close 被本类显式定义，不会走到这里
        return getattr(self._s, name)

    def close(self):
        pass


def _lib(db, lib_id, name, paths, *, enabled=True, fs_watch=True):
    row = em.Library(guid=f"g{lib_id}", name=name, collection_type="movies",
                     paths=paths, storage_backends="", is_enabled=enabled,
                     fs_watch=fs_watch)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _set_excluded(db, raw):
    """写排除清单（upsert：同一个 key 可能要改两次）"""
    row = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == cw.CONFIG_EXCLUDED).first()
    if row:
        row.value = raw
    else:
        db.add(models.SystemConfig(key=cw.CONFIG_EXCLUDED, value=raw))
    db.commit()


def test_excluded_library_is_not_watched(watched, db, tmp_path):
    """被排除的库：不挂 watch —— 与追新轮询同一口径"""
    a = _lib(db, 1, "在听", str(tmp_path / "mnt"))
    b_dir = tmp_path / "mnt_b"
    b_dir.mkdir()
    b = _lib(db, 2, "排除", str(b_dir))
    _set_excluded(db, str(b.id))

    fw.sync_from_db()

    assert set(fw._LIBRARY_PATHS) == {a.id}
    assert b.id not in fw._LIBRARY_PATHS


def test_empty_excluded_means_watch_everything(watched, db, tmp_path):
    """空排除清单 = 全部监听（与 §九 语义一致），不能反过来解释成“全都不听”"""
    a = _lib(db, 1, "A", str(tmp_path / "mnt"))
    b_dir = tmp_path / "mnt_b"
    b_dir.mkdir()
    b = _lib(db, 2, "B", str(b_dir))
    _set_excluded(db, "")

    fw.sync_from_db()

    assert set(fw._LIBRARY_PATHS) == {a.id, b.id}


def test_unwatched_when_excluded_after_being_watched(watched, db, tmp_path):
    """先把两个库都挂上，再排除其中一个 → 旧的 watch 必须被拆掉，不能留着继续跑"""
    a = _lib(db, 1, "A", str(tmp_path / "mnt"))
    b_dir = tmp_path / "mnt_b"
    b_dir.mkdir()
    b = _lib(db, 2, "B", str(b_dir))
    _set_excluded(db, "")
    fw.sync_from_db()
    assert set(fw._LIBRARY_PATHS) == {a.id, b.id}

    _set_excluded(db, str(b.id))
    fw.sync_from_db()

    assert b.id not in fw._LIBRARY_PATHS
    assert any("mnt_b" in str(u) for u in watched.unscheduled), "被排除的 watch 没有被 unschedule"


def test_save_config_refreshes_watcher_immediately(db, monkeypatch):
    """改完排除清单立即重建监听，不等重启"""
    calls = []
    monkeypatch.setattr(fw, "sync_from_db", lambda: calls.append(1) or {"watched": 0})
    db.add(models.SystemConfig(key=cw.CONFIG_ENABLED, value="1"))
    db.commit()

    cw.save_config(db, enabled=True, interval=10, excluded="1,2")

    assert calls, "save_config 没有刷新 fs_watcher"
    assert cw.resolve_excluded(db) == [1, 2]


def test_save_config_refresh_failure_does_not_lose_the_save(db, monkeypatch):
    """刷新监听失败不能把「已保存」变成「保存失败”——配置已落库，下次生效即可"""
    def _boom():
        raise RuntimeError("watcher 炸了")

    monkeypatch.setattr(fw, "sync_from_db", _boom)
    db.add(models.SystemConfig(key=cw.CONFIG_ENABLED, value="1"))
    db.commit()

    cfg = cw.save_config(db, enabled=True, interval=10, excluded="7")

    assert cfg["excluded"] == "7"          # 配置真的写进去了
    assert cw.resolve_excluded(db) == [7]


def test_legacy_include_list_migrates_for_the_watcher_too(watched, db, tmp_path):
    """老配置（包含清单）迁移后，fs_watcher 看到的是迁移后的排除语义

    老配置把 B 列为包含 → 实际监听范围是 {A, B} → 排除清单应为空。
    这里反着验：老配置只包含 A，而 B 不在里面 → B 应被排除。
    """
    a = _lib(db, 1, "A", str(tmp_path / "mnt"))
    b_dir = tmp_path / "mnt_b"
    b_dir.mkdir()
    b = _lib(db, 2, "B", str(b_dir))
    # 老语义：包含清单 = {a}；不设新键 → 触发一次性迁移
    db.add(models.SystemConfig(key=cw.CONFIG_LIBRARIES, value=str(a.id)))
    db.commit()  # 只写旧键、不写新键，触发一次性迁移

    fw.sync_from_db()

    assert set(fw._LIBRARY_PATHS) == {a.id}
    assert b.id not in fw._LIBRARY_PATHS
    # 迁移只做一次：新键写好后旧键清空
    assert cw.resolve_excluded(db) == [b.id]
    assert cw._get_config(db, cw.CONFIG_LIBRARIES, "") == ""


def test_disabled_library_still_not_watched(watched, db, tmp_path):
    """停用的库本来就不听（老行为不能因为加了排除清单而回退）"""
    d_dir = tmp_path / "mnt_d"
    d_dir.mkdir()
    d = _lib(db, 3, "停用", str(d_dir), enabled=False)
    _set_excluded(db, "")

    fw.sync_from_db()

    assert d.id not in fw._LIBRARY_PATHS