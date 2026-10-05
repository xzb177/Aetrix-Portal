"""追新轮询：find 超时不再丢掉整个目录

生产实测（2026-10-05）：``/mnt/paul`` 等 FUSE 目录上 ``find`` 60 秒扫不完，
旧实现 ``except TimeoutExpired: 跳过`` —— 该目录的新片**这一轮彻底丢失**。
"""
import os
import subprocess
import time

import pytest

from backend.emby_server import change_watcher as cw


def test_find_timeout_falls_back_to_scandir(monkeypatch, tmp_path):
    (tmp_path / "new.mkv").write_bytes(b"x")
    (tmp_path / "old.mkv").write_bytes(b"x")
    old = time.time() - 7200
    os.utime(tmp_path / "old.mkv", (old, old))
    (tmp_path / "notes.txt").write_text("x")

    monkeypatch.setattr(cw, "_FIND_TIMEOUT_SEC", 10)

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="find", timeout=10)

    monkeypatch.setattr(subprocess, "run", boom)

    found = cw._find_new_videos([str(tmp_path)], time.time() - 3600)
    assert any(p.endswith("new.mkv") for p in found), "超时后必须仍能找到新文件"
    assert not any(p.endswith("old.mkv") for p in found), "旧的（mtime 早于阈值）不该被算新"
    assert not any(p.endswith("notes.txt") for p in found), "非视频文件不该被算新"


def test_scandir_survives_unreadable_subdir(monkeypatch, tmp_path):
    """目录里有个读不动的条目，其余条目仍要能找出来"""
    good = tmp_path / "ok.mkv"
    good.write_bytes(b"x")
    bad = tmp_path / "bad.mkv"
    bad.write_bytes(b"x")

    real_scandir = os.scandir

    class _Entry:
        def __init__(self, e, fail):
            self._e = e
            self._fail = fail
        def __getattr__(self, k):
            return getattr(self._e, k)
        def is_file(self, follow_symlinks=False):
            if self._fail:
                raise OSError("读不动")
            return True
        def stat(self, follow_symlinks=False):
            if self._fail:
                raise OSError("读不动")
            return self._e.stat(follow_symlinks=False)

    class _Ctx:
        def __init__(self, it):
            self._it = it
        def __enter__(self):
            return self
        def __exit__(self, *_):
            self._it.close()
            return False
        def __iter__(self):
            for e in self._it:
                yield _Entry(e, e.path == str(bad))

    monkeypatch.setattr(os, "scandir", lambda p, *a, **k: _Ctx(real_scandir(p)))

    found = cw._scandir_new_videos(str(tmp_path), time.time() - 3600)
    assert any(p.endswith("ok.mkv") for p in found), "单个条目读不动不该拖垮整个目录"


def test_normal_find_result_still_used(monkeypatch, tmp_path):
    """不超时的正常路径行为不变"""
    (tmp_path / "a.mkv").write_bytes(b"x")

    class _R:
        returncode = 0
        stdout = f"{tmp_path}/a.mkv\n"
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    found = cw._find_new_videos([str(tmp_path)], time.time() - 3600)
    assert [os.path.basename(p) for p in found] == ["a.mkv"]
