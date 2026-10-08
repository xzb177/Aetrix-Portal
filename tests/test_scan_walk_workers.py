"""SCAN_WALK_WORKERS 并发数解析：默认 8，非法值回退，不炸扫描。

2026-10 从 16 降到 8：生产 rclone 请求风暴（24h 5.2 万条报错）的修复之一。
2026-10 接入 cpu_budget：手动配置的值按 CPU 上限截断（核数-1），永远给前台留一核。
"""
import os

import pytest

from backend.emby_server import mounts as mount_lib
from backend.emby_server import cpu_budget


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SCAN_WALK_WORKERS", raising=False)
    # 固定 16 核，隔离测试环境（避免 CI 机器核数不同导致截断）
    try:
        cpu_budget.cpu_count.cache_clear()
    except AttributeError:
        pass
    monkeypatch.setattr(cpu_budget, "cpu_count", lambda: 16)
    yield
    monkeypatch.delenv("SCAN_WALK_WORKERS", raising=False)


def test_default_8(monkeypatch):
    """默认必须是 8：16 个线程同时打 rclone RC 是请求风暴的一半来源"""
    monkeypatch.delenv("SCAN_WALK_WORKERS", raising=False)
    assert mount_lib.walk_workers_limit() == 8


def test_custom_value(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "4")
    assert mount_lib.walk_workers_limit() == 4


def test_custom_value_capped_by_cpu(monkeypatch):
    """手动配置超过核数-1 时被截断（永远给前台留一核）"""
    monkeypatch.setattr(cpu_budget, "cpu_count", lambda: 4)
    monkeypatch.setenv("SCAN_WALK_WORKERS", "8")
    assert mount_lib.walk_workers_limit() == 3


def test_empty_falls_back(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "")
    assert mount_lib.walk_workers_limit() == 8


def test_garbage_falls_back(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "abc")
    assert mount_lib.walk_workers_limit() == 8


def test_zero_or_negative_clamped_to_1(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "0")
    assert mount_lib.walk_workers_limit() == 1
    monkeypatch.setenv("SCAN_WALK_WORKERS", "-5")
    assert mount_lib.walk_workers_limit() == 1
