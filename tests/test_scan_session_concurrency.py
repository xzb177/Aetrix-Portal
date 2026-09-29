"""扫描 Session 并发崩溃回归测试。

## 事故（2026-09-29 生产）
动漫库（02:59）、国产剧库（02:08）扫描失败，错误都是：

    InvalidRequestError: This session is provisioning a new connection;
    concurrent operations are not permitted

## 根因（两层）
1. **触发器**：`scan_queue` 按挂载串行化扫描（`_MOUNT_OWNER`），但互斥依据
   `task.mount_ids` 只来自 `Library.mount_ids` 字段。改用
   `paths=mount://3/...` 后该字段为空，互斥被双向绕过——同挂载的两个库
   在同一秒被派发、同一 worker 进程里并发扫描。
2. **崩溃点**：扫描 Session 默认 `expire_on_commit=True`，每次
   `commit_batch()` 后 ctx 里缓存的 series/season ORM 对象全部过期；
   进程级 `_SCAN_POOL` 的 IO 线程若此时碰到这些对象或 Session，就会撞车。

## 修复
- `LibrarySnapshot.of()`：`mount_ids` 计入 `paths` 里的 `mount://<id>/...`，
  恢复串行化。
- `_run_task`：扫描 Session 用 `expire_on_commit=False`，消除过期-懒加载竞态。
"""
import os
import threading
import types

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest

from backend.emby_server import scan_queue
from backend.emby_server.scanner import LibrarySnapshot


def _fake_library(lib_id, name, paths, mount_ids=""):
    lib = types.SimpleNamespace(
        id=lib_id,
        name=name,
        collection_type="tvshows",
        paths=paths,
        scrape_policy="missing_only",
        mount_ids=mount_ids,
    )
    return lib


# ---------- 修复 1：快照 mount_ids 计入 paths ----------

def test_snapshot_mount_ids_include_mount_paths():
    """mount_ids 字段为空、只用 paths=mount://3/... 的库，快照也要带上挂载 3。"""
    lib = _fake_library(22, "国产剧", "mount://3/MoviePilot/剧集/国产剧", mount_ids="")
    snap = LibrarySnapshot.of(lib)
    assert snap.mount_ids == (3,), snap.mount_ids


def test_snapshot_mount_ids_merge_field_and_paths():
    """字段和 paths 都有时合并去重（对应生产动漫库：字段 '3' + paths mount://3）。"""
    lib = _fake_library(21, "动漫", "mount://3/MoviePilot/剧集/动漫", mount_ids="3")
    snap = LibrarySnapshot.of(lib)
    assert snap.mount_ids == (3,)


def test_snapshot_mount_ids_local_only_empty():
    """纯本机路径的库不受影响：mount_ids 仍为空，可以并行。"""
    lib = _fake_library(99, "本地库", "/media/movies", mount_ids="")
    snap = LibrarySnapshot.of(lib)
    assert snap.mount_ids == ()


def test_snapshot_mount_ids_multiple_mounts():
    """多个挂载都计入。"""
    lib = _fake_library(
        100, "混合库", "mount://3/a,mount://5/b,/media/c", mount_ids="7"
    )
    snap = LibrarySnapshot.of(lib)
    assert snap.mount_ids == (3, 5, 7)


# ---------- 修复 1：队列按挂载串行化 ----------

def test_queue_serializes_same_mount_from_paths():
    """两个库同用 mount 3（一个走字段、一个走 paths）：第二个必须排队等挂载。"""
    scan_queue.reset_for_tests()
    try:
        lib_a = _fake_library(21, "动漫", "mount://3/动漫", mount_ids="3")
        lib_b = _fake_library(22, "国产剧", "mount://3/国产剧", mount_ids="")
        snap_a = LibrarySnapshot.of(lib_a)
        snap_b = LibrarySnapshot.of(lib_b)

        task_a = scan_queue.ScanTask(
            library_id=21, name="动漫", trigger="manual",
            mount_ids=tuple(snap_a.mount_ids), snapshot=snap_a,
        )
        task_b = scan_queue.ScanTask(
            library_id=22, name="国产剧", trigger="manual",
            mount_ids=tuple(snap_b.mount_ids), snapshot=snap_b,
        )
        # 模拟：任务 A 已被派发（占住挂载 3）
        with scan_queue._COND:
            scan_queue._MOUNT_OWNER[3] = 21
            # 任务 B 此时应判定为"在等挂载 3"，不能被派发
            assert scan_queue._conflicts_locked(task_b) == (3,)
            scan_queue._MOUNT_OWNER.pop(3, None)
            # 挂载释放后不再冲突
            assert scan_queue._conflicts_locked(task_b) == ()
    finally:
        scan_queue.reset_for_tests()


# ---------- SQLAlchemy 并发行为（文档化，修完不崩的依据） ----------

def test_concurrent_session_use_raises():
    """双线程同时用一个 Session 必崩——确定性复现生产报错。

    做法：让线程 1 在 Session 获取新连接时（PROVISIONING_CONNECTION 状态）
    卡住，此时线程 2 再碰同一个 Session，必抛 InvalidRequestError。
    这正是生产 "provisioning a new connection; concurrent operations
    are not permitted" 的触发条件。
    """
    import tempfile
    from unittest import mock
    from sqlalchemy import create_engine, Column, Integer, String, text
    from sqlalchemy.exc import InvalidRequestError
    from sqlalchemy.orm import sessionmaker, declarative_base

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        Base = declarative_base()

        class Item(Base):
            __tablename__ = "t_item"
            id = Column(Integer, primary_key=True)
            name = Column(String(64))

        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        entered = threading.Event()   # 线程 1 已进入 provisioning
        release = threading.Event()   # 主线程放行
        real_connect = engine.connect

        def slow_connect(*a, **k):
            entered.set()
            assert release.wait(timeout=15), "release 超时"
            return real_connect(*a, **k)

        errors = []

        def thread1_use():
            # 触发一次新连接获取（会被 slow_connect 卡住）
            try:
                with mock.patch.object(engine, "connect", slow_connect):
                    session.execute(text("SELECT 1"))
            except Exception as exc:  # noqa: BLE001
                errors.append(("t1", exc))

        t1 = threading.Thread(target=thread1_use)
        t1.start()
        assert entered.wait(timeout=15), "线程 1 没进入 provisioning"
        # 此时 Session 卡在 PROVISIONING_CONNECTION，线程 2 再碰它必崩
        with pytest.raises(InvalidRequestError, match="concurrent"):
            session.execute(text("SELECT 1"))
        release.set()
        t1.join(timeout=15)
        assert not [e for w, e in errors if w == "t1"], errors
    finally:
        os.unlink(path)


def test_expire_on_commit_false_keeps_attributes():
    """expire_on_commit=False：提交后对象属性不失效，不会触发跨线程懒加载。"""
    import tempfile
    from sqlalchemy import create_engine, Column, Integer, String
    from sqlalchemy.orm import sessionmaker, declarative_base

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{path}")
        Base = declarative_base()

        class Item(Base):
            __tablename__ = "t_item2"
            id = Column(Integer, primary_key=True)
            name = Column(String(64))

        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()
        try:
            item = Item(name="hello")
            session.add(item)
            session.commit()
            # 默认 expire_on_commit=True 时这里会触发一次 SELECT（重载）；
            # 关掉后直接读内存值，不碰连接——也就不会有"provisioning"竞态。
            assert item.name == "hello"
            assert item.id is not None
        finally:
            session.close()
    finally:
        os.unlink(path)
