# -*- coding: utf-8 -*-
"""cpu_budget：后台并发按 CPU 自适应，永远给前台留一核"""
import os


def _reload(monkeypatch, **env):
    import importlib
    from backend.emby_server import cpu_budget
    for k in ("SCAN_WORKERS", "PROBE_WORKERS", "THUMBNAIL_WORKERS", "ENRICH_WORKERS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # 固定核数为 4，隔离测试环境
    monkeypatch.setattr(cpu_budget, "cpu_count", lambda: 4)
    return importlib.reload(cpu_budget)


def test_default_is_half_cpus(monkeypatch):
    cb = _reload(monkeypatch)
    assert cb.background_workers("SCAN_WORKERS") == 2  # 4 // 2


def test_manual_capped_at_cpus_minus_one(monkeypatch):
    cb = _reload(monkeypatch, SCAN_WORKERS="8")
    assert cb.background_workers("SCAN_WORKERS") == 3  # min(8, 4-1)


def test_manual_small_value_kept(monkeypatch):
    cb = _reload(monkeypatch, SCAN_WORKERS="2")
    assert cb.background_workers("SCAN_WORKERS") == 2


def test_invalid_value_falls_back_to_default(monkeypatch):
    cb = _reload(monkeypatch, SCAN_WORKERS="abc")
    assert cb.background_workers("SCAN_WORKERS") == 2


def test_single_core_still_gets_one(monkeypatch):
    import importlib
    from backend.emby_server import cpu_budget
    monkeypatch.delenv("SCAN_WORKERS", raising=False)
    monkeypatch.setattr(cpu_budget, "cpu_count", lambda: 1)
    cb = importlib.reload(cpu_budget)
    assert cb.background_workers("SCAN_WORKERS") == 1


def test_max_cap_respected(monkeypatch):
    import importlib
    from backend.emby_server import cpu_budget
    monkeypatch.delenv("SCAN_WORKERS", raising=False)
    monkeypatch.setattr(cpu_budget, "cpu_count", lambda: 64)
    cb = importlib.reload(cpu_budget)
    assert cb.background_workers("SCAN_WORKERS") == 16  # 默认上限 16
    monkeypatch.setenv("SCAN_WORKERS", "100")
    cb = importlib.reload(cpu_budget)
    assert cb.background_workers("SCAN_WORKERS") == 16
