# -*- coding: utf-8 -*-
"""cpu_budget：后台并发按 CPU 自适应，永远给前台留一核"""
import os


def _mock_cpus(monkeypatch, n):
    from backend.emby_server import cpu_budget
    # lru_cache 要清掉，否则 mock 不生效
    cpu_budget.cpu_count.cache_clear()
    monkeypatch.setattr(cpu_budget, "cpu_count", lambda: n)
    for k in ("SCAN_WORKERS", "PROBE_WORKERS", "THUMBNAIL_WORKERS", "ENRICH_WORKERS"):
        monkeypatch.delenv(k, raising=False)


def test_default_is_half_cpus(monkeypatch):
    from backend.emby_server import cpu_budget
    _mock_cpus(monkeypatch, 4)
    assert cpu_budget.background_workers("SCAN_WORKERS") == 2  # 4 // 2


def test_manual_capped_at_cpus_minus_one(monkeypatch):
    from backend.emby_server import cpu_budget
    _mock_cpus(monkeypatch, 4)
    monkeypatch.setenv("SCAN_WORKERS", "8")
    assert cpu_budget.background_workers("SCAN_WORKERS") == 3  # min(8, 4-1)


def test_manual_small_value_kept(monkeypatch):
    from backend.emby_server import cpu_budget
    _mock_cpus(monkeypatch, 4)
    monkeypatch.setenv("SCAN_WORKERS", "2")
    assert cpu_budget.background_workers("SCAN_WORKERS") == 2


def test_invalid_value_falls_back_to_default(monkeypatch):
    from backend.emby_server import cpu_budget
    _mock_cpus(monkeypatch, 4)
    monkeypatch.setenv("SCAN_WORKERS", "abc")
    assert cpu_budget.background_workers("SCAN_WORKERS") == 2


def test_single_core_still_gets_one(monkeypatch):
    from backend.emby_server import cpu_budget
    _mock_cpus(monkeypatch, 1)
    assert cpu_budget.background_workers("SCAN_WORKERS") == 1


def test_max_cap_respected(monkeypatch):
    from backend.emby_server import cpu_budget
    _mock_cpus(monkeypatch, 64)
    assert cpu_budget.background_workers("SCAN_WORKERS") == 16  # 默认上限 16
    monkeypatch.setenv("SCAN_WORKERS", "100")
    assert cpu_budget.background_workers("SCAN_WORKERS") == 16


def test_capped_workers_keeps_custom_default(monkeypatch):
    from backend.emby_server import cpu_budget
    _mock_cpus(monkeypatch, 4)
    # 未配置时用自定义默认
    assert cpu_budget.capped_workers("THUMBNAIL_WORKERS", 1, max_cap=3) == 1
    # 手动配置时截断
    monkeypatch.setenv("THUMBNAIL_WORKERS", "8")
    assert cpu_budget.capped_workers("THUMBNAIL_WORKERS", 1, max_cap=3) == 3
