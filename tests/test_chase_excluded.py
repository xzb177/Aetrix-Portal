"""追新改为「排除清单」（v2.45.0）

改的是语义：以前是**包含清单**（空 = 全部监听），所以想关掉 A 库必须先去 B 库打开
开关、让清单被写出来，再回来把 A 删掉——反直觉。现在是**排除清单**（空 = 全部监听），
关掉一个库就是往排除清单里加一行，一次点击到位。

最要紧的不是 UI，是**老配置怎么迁移**：老部署的包含清单如果被直接当成排除清单读，
「只听 A、B」会变成「全都不听、A、B 反而被排除」；如果被忽略，则会从「只听 A、B」
静默变成「全部监听」——后者是一次扫描风暴。这两种都必须挡住。

全部用内存 SQLite，不碰网络与生产库。
"""
import os
from unittest import mock

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


def _lib(db, name, enabled=True):
    row = em.Library(guid=f"g-{name}", name=name, collection_type="movies",
                     is_enabled=enabled, paths="")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ==================== 排除清单的基本语义 ====================

def test_empty_exclusion_means_watch_all(db):
    assert cw.resolve_excluded(db) == []


def test_exclusion_list_round_trips(db):
    _lib(db, "电影")
    lib = _lib(db, "剧集")

    cw.save_config(db, enabled=True, interval=10, excluded=str(lib.id))

    assert cw.resolve_excluded(db) == [lib.id]
    assert cw.get_config(db)["excluded"] == str(lib.id)


def test_excluding_everything_is_allowed(db):
    """包含清单时代「不能全空」是个坑；排除清单下「全排除」是完全合法的配置"""
    a = _lib(db, "A")
    b = _lib(db, "B")

    cw.save_config(db, enabled=True, interval=10, excluded=f"{a.id},{b.id}")

    assert cw.resolve_excluded(db) == [a.id, b.id]


def test_get_config_does_not_hand_a_list_to_old_frontends(db):
    """老前端读 libraries 字段；给它非空值会让它把排除清单当成包含清单，整个反过来"""
    _lib(db, "A")
    lib = _lib(db, "B")

    cfg = cw.save_config(db, enabled=True, interval=10, excluded=str(lib.id))

    assert cfg["libraries"] == ""


# ==================== 老配置迁移（最要紧的一块）====================

def test_legacy_inclusion_list_is_inverted_not_ignored(db):
    """老配置「只听 A、B」→ 排除清单应是「排除其余的」，而不是变成全听或反过来"""
    a = _lib(db, "A")
    b = _lib(db, "B")
    c = _lib(db, "C")
    cw._set_config(db, cw.CONFIG_LIBRARIES, f"{a.id},{b.id}")

    assert cw.resolve_excluded(db) == [c.id]


def test_legacy_migration_persists_and_clears_old_key(db):
    a = _lib(db, "A")
    c = _lib(db, "C")
    cw._set_config(db, cw.CONFIG_LIBRARIES, f"{a.id}")

    cw.resolve_excluded(db)

    assert cw.resolve_excluded(db) == [c.id]
    # 旧键清空：万一还有进程按老口径读，它看到的是「空 = 全部」，与新语义不打架
    assert cw._get_config(db, cw.CONFIG_LIBRARIES, "") == ""
    assert cw._get_config(db, cw.CONFIG_EXCLUDED, "") == str(c.id)


def test_migration_runs_only_once(db):
    a = _lib(db, "A")
    c = _lib(db, "C")
    cw._set_config(db, cw.CONFIG_LIBRARIES, f"{a.id}")

    assert cw.resolve_excluded(db) == [c.id]
    # 新键已经在了：再调一次不会重算（否则新加的库会被重新塞进排除清单）
    d = _lib(db, "D")
    assert cw.resolve_excluded(db) == [c.id]
    assert d.id not in cw.resolve_excluded(db)


def test_disabled_libraries_are_not_turned_into_exclusions(db):
    """迁移只看**启用**的库：已停用的库本来就不扫，不该因此被排除（会显得配置很脏）"""
    a = _lib(db, "A")
    off = _lib(db, "停用的", enabled=False)
    cw._set_config(db, cw.CONFIG_LIBRARIES, f"{a.id}")

    assert off.id not in cw.resolve_excluded(db)


def test_empty_legacy_value_needs_no_migration(db):
    _lib(db, "A")
    cw._set_config(db, cw.CONFIG_LIBRARIES, "")

    assert cw.resolve_excluded(db) == []
    # 空=全部监听在新旧语义下含义一致，不该写任何东西
    assert cw._config_exists(db, cw.CONFIG_EXCLUDED) is False


# ==================== 旧字段入参（老前端 / 老脚本）====================

def test_legacy_libraries_argument_is_converted(db):
    """老前端发 libraries（包含清单）时必须换算，不能直接当排除清单存"""
    a = _lib(db, "A")
    c = _lib(db, "C")

    cfg = cw.save_config(db, enabled=True, interval=10, libraries=f"{a.id}")

    assert cfg["excluded"] == str(c.id)


def test_new_excluded_argument_wins_over_legacy(db):
    _lib(db, "A")
    lib = _lib(db, "B")

    cfg = cw.save_config(db, enabled=True, interval=10,
                         excluded=str(lib.id), libraries="")

    assert cfg["excluded"] == str(lib.id)


def test_dirty_ids_are_dropped(db):
    lib = _lib(db, "B")

    cfg = cw.save_config(db, enabled=True, interval=10,
                         excluded=f"abc,{lib.id},,-3,99999999999999999999999")

    assert cfg["excluded"] == str(lib.id)


# ==================== 轮询真的按排除清单过滤 ====================

def test_check_once_skips_excluded_libraries(db, tmp_path):
    """被排除的库这一轮不应该被发现新文件（也就是不会被触发扫描）"""
    watched = _lib(db, "监听")
    skipped = _lib(db, "排除")
    (tmp_path / "watched").mkdir()
    (tmp_path / "skipped").mkdir()
    for folder in ("watched", "skipped"):
        (tmp_path / folder / "new.mkv").write_bytes(b"x")
    watched.paths = str(tmp_path / "watched")
    skipped.paths = str(tmp_path / "skipped")
    db.commit()

    cw.save_config(db, enabled=True, interval=10, excluded=str(skipped.id))
    enqueued = []

    class _SessionShim:
        """_check_once 会在 finally 里 close()，不能让它关掉测试自己的 Session"""

        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    with mock.patch.object(cw, "SessionLocal", lambda: _SessionShim()), \
            mock.patch.object(cw, "_find_new_videos",
                              lambda paths, since: ["/fake/new.mkv"]), \
            mock.patch.object(cw, "_library_mount_sources", lambda lib, _db: []), \
            mock.patch.object(cw.scan_queue, "enqueue",
                              lambda lib, **kw: enqueued.append(lib.id)):
        cw._check_once()

    assert enqueued == [watched.id]