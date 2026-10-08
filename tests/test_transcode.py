# -*- coding: utf-8 -*-
"""Tests for on-demand transcode (transcode.py): cache, slot limit.

2026-10：删除服务端三档转码，码率/分辨率由客户端指定。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from fastapi import HTTPException

from backend.emby_server import transcode as tc


# ---------- clamp_to_source ----------

def test_clamp_to_source_no_pointless_upscale():
    # 480p 源要 1080p 也只给 480p
    assert tc.clamp_to_source(1080, 480) == 480
    assert tc.clamp_to_source(1080, 720) == 720
    assert tc.clamp_to_source(1080, 1080) == 1080
    # 源分辨率未知时按请求走
    assert tc.clamp_to_source(1080, None) == 1080
    assert tc.clamp_to_source(None, 480) is None


# ---------- cache_key ----------

def test_cache_key_deterministic():
    k1 = tc.cache_key("guid-1", 2500000, 720, "fp-1")
    k2 = tc.cache_key("guid-1", 2500000, 720, "fp-1")
    assert k1 == k2
    assert len(k1) == 32


def test_cache_key_sensitive_to_inputs():
    base = tc.cache_key("guid-1", 2500000, 720, "fp-1")
    assert tc.cache_key("guid-2", 2500000, 720, "fp-1") != base
    assert tc.cache_key("guid-1", 5000000, 720, "fp-1") != base
    assert tc.cache_key("guid-1", 2500000, 1080, "fp-1") != base
    assert tc.cache_key("guid-1", 2500000, 720, "fp-2") != base
    # 源文件被替换（指纹变）→ 缓存键变 → 旧缓存自动失效
    assert tc.cache_key("guid-1", 2500000, 720, None) != base


# ---------- find_cache ----------

def _make_cache_dir(root, key, valid=True, with_segments=True):
    path = os.path.join(root, key)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "master.m3u8"), "w") as fh:
        fh.write("#EXTM3U\n" if valid else "")
    if with_segments:
        with open(os.path.join(path, "seg00000.ts"), "wb") as fh:
            fh.write(b"\x47" * 188)
    return path


def test_find_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    key = tc.cache_key("g1", 2500000, 720, "f1")
    _make_cache_dir(str(tmp_path), key)
    assert tc.find_cache("g1", 2500000, 720, "f1") == os.path.join(str(tmp_path), key)


def test_find_cache_miss_no_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    assert tc.find_cache("g1", 2500000, 720, "f1") is None


def test_find_cache_miss_empty_playlist(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    key = tc.cache_key("g1", 2500000, 720, "f1")
    _make_cache_dir(str(tmp_path), key, valid=False)
    assert tc.find_cache("g1", 2500000, 720, "f1") is None


def test_find_cache_miss_no_segments(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    key = tc.cache_key("g1", 2500000, 720, "f1")
    _make_cache_dir(str(tmp_path), key, with_segments=False)
    assert tc.find_cache("g1", 2500000, 720, "f1") is None


def test_find_cache_miss_fingerprint_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    key = tc.cache_key("g1", 2500000, 720, "f1")
    _make_cache_dir(str(tmp_path), key)
    # 文件被替换后指纹变化，旧缓存不再命中
    assert tc.find_cache("g1", 2500000, 720, "f2") is None


# ---------- register_cache_session ----------

class _FakeStreaming:
    def __init__(self):
        self._TRANSCODE_PROCS = {}

    def active_transcode_ids(self):
        return list(self._TRANSCODE_PROCS.keys())

    def get_transcode(self, sid):
        return self._TRANSCODE_PROCS.get(sid)

    # S6：ensure_slot_or_503 满员时先让闲置会话让位（这里的假会话都视为活跃）
    def transcode_idle_seconds(self):
        return 120.0

    def reap_idle_transcodes(self, idle_limit=None):
        return 0


def test_register_cache_session(monkeypatch):
    fake = _FakeStreaming()
    monkeypatch.setattr(tc, "_streaming", lambda: fake)
    sid = tc.register_cache_session("/cache/abc", user_id=7,
                                    item_guid="g1",
                                    video_bitrate=2500000, height=720)
    info = fake.get_transcode(sid)
    assert info is not None
    assert info["dir"] == "/cache/abc"
    assert info["proc"] is None
    assert info["cached"] is True
    assert info["user_id"] == 7
    assert info["video_bitrate"] == 2500000
    assert info["height"] == 720


# ---------- ensure_slot_or_503 ----------

class _FakeProc:
    def __init__(self, running=True):
        self._running = running

    def poll(self):
        return None if self._running else 0


def _fake_streaming_with(n_running):
    fake = _FakeStreaming()
    for i in range(n_running):
        fake._TRANSCODE_PROCS[f"s{i}"] = {"proc": _FakeProc(True)}
    # 一个已退出的不占路数，一个缓存复用的不占路数
    fake._TRANSCODE_PROCS["done"] = {"proc": _FakeProc(False)}
    fake._TRANSCODE_PROCS["cache"] = {"proc": None, "cached": True}
    return fake


def _mock_8_cpus(monkeypatch):
    from backend.emby_server import cpu_budget
    # 先清 lru_cache，再 mock（mock 后就没有 cache_clear 了）
    try:
        cpu_budget.cpu_count.cache_clear()
    except AttributeError:
        pass
    monkeypatch.setattr(cpu_budget, "cpu_count", lambda: 8)


def test_slot_ok_when_under_limit(monkeypatch):
    _mock_8_cpus(monkeypatch)
    monkeypatch.setattr(tc, "_streaming", lambda: _fake_streaming_with(1))
    monkeypatch.setenv("TRANSCODE_MAX_CONCURRENT", "2")
    tc.ensure_slot_or_503()  # 不抛异常


def test_slot_503_when_full(monkeypatch):
    _mock_8_cpus(monkeypatch)
    monkeypatch.setattr(tc, "_streaming", lambda: _fake_streaming_with(2))
    monkeypatch.setenv("TRANSCODE_MAX_CONCURRENT", "2")
    with pytest.raises(HTTPException) as exc_info:
        tc.ensure_slot_or_503()
    assert exc_info.value.status_code == 503


def test_slot_limit_env_override(monkeypatch):
    _mock_8_cpus(monkeypatch)
    monkeypatch.setattr(tc, "_streaming", lambda: _fake_streaming_with(3))
    monkeypatch.setenv("TRANSCODE_MAX_CONCURRENT", "4")
    tc.ensure_slot_or_503()  # 4 路上限，3 路在跑 → 放行


# ---------- maybe_promote_to_cache ----------

def _session_dir(root, name="sess"):
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "master.m3u8"), "w") as fh:
        fh.write("#EXTM3U\n#EXT-X-VERSION:3\n")
    with open(os.path.join(path, "seg00000.ts"), "wb") as fh:
        fh.write(b"\x47" * 188)
    return path


class _ProcStub:
    def __init__(self, returncode):
        self._rc = returncode

    def poll(self):
        return self._rc


def _promote_info(src_dir, returncode=0, start_seconds=0, key="k" * 32):
    return {
        "proc": _ProcStub(returncode),
        "dir": src_dir,
        "video_bitrate": 2500000,
        "height": 720,
        "cache_key": key,
        "fingerprint": "f1",
        "item_guid": "g1",
        "start_seconds": start_seconds,
    }


def test_promote_success(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    src = _session_dir(str(tmp_path), "sess")
    info = _promote_info(src)
    assert tc.maybe_promote_to_cache("s1", info) is True
    dst = os.path.join(str(tmp_path), "k" * 32)
    assert os.path.isdir(dst)
    assert not os.path.exists(src)  # 原目录已搬走
    assert info["dir"] == dst
    assert info["cached"] is True
    assert os.path.isfile(os.path.join(dst, "cache.json"))


def test_promote_skips_failed_transcode(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    src = _session_dir(str(tmp_path), "sess")
    info = _promote_info(src, returncode=1)
    assert tc.maybe_promote_to_cache("s1", info) is False
    assert os.path.isdir(src)


def test_promote_skips_seek_session(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    src = _session_dir(str(tmp_path), "sess")
    info = _promote_info(src, start_seconds=120)
    assert tc.maybe_promote_to_cache("s1", info) is False
    assert os.path.isdir(src)


def test_promote_skips_no_proc(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    src = _session_dir(str(tmp_path), "sess")
    info = _promote_info(src)
    info["proc"] = None
    assert tc.maybe_promote_to_cache("s1", info) is False


def test_promote_skips_missing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    src = _session_dir(str(tmp_path), "sess")
    info = _promote_info(src, key=None)
    assert tc.maybe_promote_to_cache("s1", info) is False


def test_promote_skips_already_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBY_TRANSCODE_CACHE_DIR", str(tmp_path))
    src = _session_dir(str(tmp_path), "sess")
    info = _promote_info(src)
    info["cached"] = True
    assert tc.maybe_promote_to_cache("s1", info) is False
    assert os.path.isdir(src)
