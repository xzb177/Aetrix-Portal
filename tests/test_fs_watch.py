"""本机目录实时监听（inotify）与扫描开关（v2.44.0）

盯住的是**会真出事**的几条，不是实现细节：

1. **只监听本机路径**：``mount://`` / ``115:/`` / ``rclone:`` 这些远程来源拿不到可靠
   事件源，绝不能去监听（watchdog 对它们只会报错，或者更糟——静默什么都不发生）。
2. **1 秒防抖**：转场一个目录会产生成百上千个事件，必须合并成**一次**入队。
3. **限流**：磁盘抖动导致事件断断续续时，不能把扫描队列灌满。
4. **降级可见**：路径不可读要记成 degraded 并给出人话原因——默默不工作比报错更糟。
5. **开关真的生效**：``fs_watch=false`` 的库不入监听；``incremental_scan=false``
   的库这一轮不做指纹秒跳；``force_full`` 只影响那一轮。
"""
import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest

from backend.emby_server import fs_watcher as fw
from backend.emby_server import scanner


@pytest.fixture(autouse=True)
def _reset_watcher():
    fw.stop_fs_watcher()
    fw._LIBRARY_PATHS.clear()
    fw._DEGRADED.clear()
    fw._PENDING.clear()
    fw._LAST_TRIGGER.clear()
    for key in fw._STATS:
        fw._STATS[key] = 0
    yield
    fw.stop_fs_watcher()


def _lib(**kw):
    kw.setdefault("paths", "")
    return SimpleNamespace(**kw)


# ==================== 只监听本机路径 ====================

def test_local_paths_skips_remote_sources():
    lib = _lib(paths="/mnt/mp/电影,/mnt/paul/剧集,mount://3/x,115:/0,rclone:gdrive/M")

    assert fw.local_paths_for_library(lib) == ("/mnt/mp/电影", "/mnt/paul/剧集")


def test_local_paths_dedupes_and_strips_trailing_slash():
    assert fw.local_paths_for_library(_lib(paths="/mnt/mp/ ,/mnt/mp")) == ("/mnt/mp",)


def test_local_paths_empty_when_all_remote():
    assert fw.local_paths_for_library(_lib(paths="mount://3/a,115:/0")) == ()


def test_is_watchable_rejects_missing_and_relative(tmp_path):
    assert fw.is_watchable(str(tmp_path)) == (True, "")
    ok, why = fw.is_watchable(str(tmp_path / "nope"))
    assert ok is False and "不存在" in why
    ok, why = fw.is_watchable("relative/dir")
    assert ok is False and "绝对路径" in why
    ok, why = fw.is_watchable("")
    assert ok is False and why


# ==================== 防抖合并 ====================

class _FakeEvent:
    def __init__(self, src_path, is_directory=False):
        self.src_path = src_path
        self.is_directory = is_directory


def test_many_events_in_one_window_collapse_to_single_trigger(monkeypatch, tmp_path):
    """转场 500 个文件 = 500 个事件，但只能触发一次入队"""
    calls = []
    monkeypatch.setattr(fw, "_trigger_scan", lambda lib_id: calls.append(lib_id))
    monkeypatch.setattr(fw, "FS_EVENT_DEBOUNCE_SEC", 0.05)
    handler = fw._CoalescingHandler()
    fw._LIBRARY_PATHS[7] = (str(tmp_path),)

    for i in range(500):
        handler.on_any_event(_FakeEvent(f"{tmp_path}/movie-{i}.mkv"))
    handler.on_any_event(_FakeEvent(f"{tmp_path}/movie-499.mkv"))   # 同一文件重复事件
    # 目录级事件（新建/改名目录）不触发：后面由扫描器发现，不靠监听
    handler.on_any_event(_FakeEvent(f"{tmp_path}/sub/", is_directory=True))

    assert len(fw._PENDING) == 1
    assert fw._STATS["events"] == 501

    import threading
    stop = threading.Event()
    fw._STOP = stop
    thread = threading.Thread(target=fw._drain_loop, args=(stop,), daemon=True)
    thread.start()
    stop.wait(0.4)
    stop.set()
    thread.join(timeout=2)

    assert calls == [7]


def test_events_outside_watched_paths_are_ignored(tmp_path):
    fw._LIBRARY_PATHS[7] = (str(tmp_path / "a"),)
    handler = fw._CoalescingHandler()

    handler.on_any_event(_FakeEvent(f"{tmp_path}/elsewhere/x.mkv"))

    assert fw._PENDING == {}


def test_trigger_is_rate_limited(monkeypatch):
    """事件断断续续时不能把队列灌满：同一库 60 秒内只入队一次"""
    calls = []
    monkeypatch.setattr(fw, "FS_EVENT_MIN_INTERVAL_SEC", 60.0)
    monkeypatch.setattr(fw, "SessionLocal", None, raising=False)
    import backend.database as dbmod

    class _Lib:
        id = 5
        name = "电影库"
        is_enabled = True
        fs_watch = True

    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _Lib()

    class _FakeSession:
        def query(self, *a, **k):
            return _FakeQuery()

        def close(self):
            calls.append("close")

    monkeypatch.setattr(dbmod, "SessionLocal", _FakeSession)
    monkeypatch.setattr("backend.emby_server.scan_queue.enqueue",
                        lambda lib, trigger=None, **kw: calls.append(trigger))

    fw._trigger_scan(5)
    fw._trigger_scan(5)
    fw._trigger_scan(5)

    assert calls.count("fs-event") == 1
    assert fw._STATS["coalesced"] == 2


def test_trigger_skips_disabled_library(monkeypatch):
    calls = []
    import backend.database as dbmod

    class _Lib:
        id = 6
        name = "关掉的库"
        is_enabled = True
        fs_watch = False          # 用户关了监听 → 不该被事件触发

    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _Lib()

    class _FakeSession:
        def query(self, *a, **k):
            return _FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(dbmod, "SessionLocal", _FakeSession)
    monkeypatch.setattr(fw, "FS_EVENT_MIN_INTERVAL_SEC", 0.0)
    monkeypatch.setattr("backend.emby_server.scan_queue.enqueue",
                        lambda lib, trigger=None, **kw: calls.append(lib.id))

    fw._trigger_scan(6)

    assert calls == []


# ==================== 降级可见 ====================

def test_unwatchable_path_is_recorded_as_degraded(tmp_path, monkeypatch):
    """监听失败必须留下人话原因：默默不工作比报错更糟"""
    fw._OBSERVER = SimpleNamespace(
        schedule=lambda handler, path, recursive: SimpleNamespace(),
        unschedule=lambda handle: None,
    )
    fw._watch_now(1, (str(tmp_path), str(tmp_path / "gone")))

    assert 1 in fw._DEGRADED
    assert "gone" in fw._DEGRADED[1]
    assert "不存在" in fw._DEGRADED[1]
    assert 1 in fw._WATCHES   # 可读的那个仍然在监听（部分失败不影响其余路径）


def test_watcher_status_exposes_degradation(tmp_path, monkeypatch):
    fw._OBSERVER = SimpleNamespace(
        schedule=lambda handler, path, recursive: SimpleNamespace(),
        unschedule=lambda handle: None,
    )
    fw._watch_now(2, (str(tmp_path / "nope"),))

    status = fw.watcher_status()

    assert status["available"] is True
    assert "2" in status["degraded"]
    assert status["degraded"]["2"]


# ==================== 每库开关 ====================

def test_incremental_on_requires_global_and_library_switch():
    on = SimpleNamespace(force_full=False, incremental_scan=True)
    off = SimpleNamespace(force_full=False, incremental_scan=False)
    ctx = SimpleNamespace(snap=on)

    assert fw._STATS is not None
    assert scanner._incremental_on(ctx) is True
    assert scanner._incremental_on(SimpleNamespace(snap=off)) is False
    # force_full 只影响这一轮
    assert scanner._incremental_on(SimpleNamespace(
        snap=SimpleNamespace(force_full=True, incremental_scan=True))) is False


def test_snapshot_captures_incremental_switch():
    lib = SimpleNamespace(id=1, name="库", collection_type="movies", paths="",
                          scrape_policy=None, mount_ids="", incremental_scan=False)
    assert scanner.LibrarySnapshot.of(lib).incremental_scan is False

    lib2 = SimpleNamespace(id=2, name="库", collection_type="movies", paths="",
                           scrape_policy=None, mount_ids="")
    # 老对象没有这一列时按 True（保持升级前的行为）
    assert scanner.LibrarySnapshot.of(lib2).incremental_scan is True