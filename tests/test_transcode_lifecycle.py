"""S6 / S7：转码闲置回收按客户端访问时间；ffmpeg 独立进程组、随父进程退出、不留僵尸。"""
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime

import pytest

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from fastapi import HTTPException

from backend.emby_server import streaming, transcode

posix_only = pytest.mark.skipif(os.name != "posix", reason="进程组 / 信号语义仅 POSIX")
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG 仅 Linux")


def _alive(pid: int) -> bool:
    """进程存在且不是僵尸"""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(")")[-1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _wait_dead(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


@pytest.fixture
def procs(monkeypatch):
    table = {}
    monkeypatch.setattr(streaming, "_TRANSCODE_PROCS", table)
    yield table
    for sid in list(table):
        streaming.stop_transcode(sid)


def _register(table, sid, proc, out_dir, last_access_ago=0.0, **extra):
    os.makedirs(out_dir, exist_ok=True)
    table[sid] = {"proc": proc, "dir": str(out_dir), "started": datetime.now(),
                  "user_id": 1, "item_guid": sid,
                  "last_access": time.monotonic() - last_access_ago, **extra}


# ---------------- S6 ----------------

def test_idle_uses_client_access_not_dir_mtime(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "seg00001.ts").write_bytes(b"x")  # ffmpeg 刚写过：目录 mtime = 现在
    info = {"dir": str(d), "last_access": time.monotonic() - 500}
    assert streaming._transcode_idle(info) >= 499  # 旧实现会返回 ≈0


def test_touch_resets_idle(procs, tmp_path):
    _register(procs, "s1", None, tmp_path / "s1", last_access_ago=900, cached=True)
    assert streaming._transcode_idle(procs["s1"]) >= 899
    streaming.touch_transcode("s1")
    assert streaming._transcode_idle(procs["s1"]) < 1


@posix_only
def test_abandoned_transcode_is_killed_and_cleaned(procs, tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_ABANDON", "300")
    monkeypatch.setenv("EMBY_TRANSCODE_IDLE", "120")
    gone = streaming.spawn_ffmpeg(["sleep", "60"])
    kept = streaming.spawn_ffmpeg(["sleep", "60"])
    _register(procs, "gone", gone, tmp_path / "gone", last_access_ago=400)
    _register(procs, "kept", kept, tmp_path / "kept", last_access_ago=10)
    assert streaming.reap_idle_transcodes() == 1
    assert "gone" not in procs and "kept" in procs
    assert _wait_dead(gone.pid)
    assert not (tmp_path / "gone").exists()
    assert kept.poll() is None


@posix_only
def test_slot_check_reclaims_idle_before_503(procs, tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCODE_MAX_CONCURRENT", "1")
    monkeypatch.setenv("EMBY_TRANSCODE_IDLE", "120")
    p = streaming.spawn_ffmpeg(["sleep", "60"])
    _register(procs, "idle", p, tmp_path / "idle", last_access_ago=200)
    transcode.ensure_slot_or_503()  # 闲置会话让位，不再 503
    assert "idle" not in procs
    assert _wait_dead(p.pid)


@posix_only
def test_slot_check_still_503_when_active(procs, tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCODE_MAX_CONCURRENT", "1")
    p = streaming.spawn_ffmpeg(["sleep", "60"])
    _register(procs, "busy", p, tmp_path / "busy", last_access_ago=5)
    with pytest.raises(HTTPException) as ei:
        transcode.ensure_slot_or_503()
    assert ei.value.status_code == 503
    assert p.poll() is None


# ---------------- S7 ----------------

@posix_only
def test_ffmpeg_gets_own_process_group_and_whole_group_is_killed(tmp_path):
    pidfile = tmp_path / "child.pid"
    proc = streaming.spawn_ffmpeg(
        ["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"])
    deadline = time.monotonic() + 5
    while not pidfile.exists() or not pidfile.read_text().strip():
        assert time.monotonic() < deadline
        time.sleep(0.02)
    grandchild = int(pidfile.read_text())
    assert os.getpgid(proc.pid) == proc.pid  # 独立进程组
    assert os.getpgid(proc.pid) != os.getpgid(0)
    streaming.terminate_process_group(proc, grace=2)
    assert proc.returncode is not None  # 已收尸
    assert _wait_dead(grandchild)  # 孙进程（被 sh 包一层的那种）也被带走


@linux_only
def test_ffmpeg_dies_with_parent(tmp_path):
    """父进程被 SIGKILL（模拟崩溃 / OOM）后，PDEATHSIG 让 ffmpeg 跟着退出。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {root!r})
        from backend.emby_server import streaming
        p = streaming.spawn_ffmpeg(["sleep", "60"])
        print(p.pid, flush=True)
        time.sleep(60)
    """)
    parent = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True,
                              env={**os.environ, "DATABASE_TYPE": "sqlite", "REDIS_ENABLED": "false"})
    try:
        child_pid = int(parent.stdout.readline().strip())
        assert _alive(child_pid)
        parent.kill()
        parent.wait(timeout=5)
        assert _wait_dead(child_pid, timeout=5), "ffmpeg 成了孤儿"
    finally:
        if parent.poll() is None:
            parent.kill()


@posix_only
def test_reaper_tick_collects_exited_process(procs, tmp_path):
    p = streaming.spawn_ffmpeg(["sh", "-c", "exit 3"])
    _register(procs, "done", p, tmp_path / "done")
    time.sleep(0.3)
    result = streaming.transcode_reaper_tick()
    assert result["stale"] == 1
    assert "done" not in procs
    assert not _alive(p.pid)  # 不留僵尸


def test_spawn_happens_on_long_lived_thread():
    """PDEATHSIG 跟的是 fork 它的线程：必须是常驻 spawner 线程，而不是会闲置退出的工作线程。"""
    import threading

    names = []
    streaming._get_spawner().submit(lambda: names.append(threading.current_thread().name)).result()
    streaming._get_spawner().submit(lambda: names.append(threading.current_thread().name)).result()
    assert names[0] == names[1] and names[0].startswith("ffmpeg-spawner")
