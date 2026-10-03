"""SCAN_WALK_WORKERS 并发数解析：默认 8，非法值回退，不炸扫描。

2026-10 从 16 降到 8：生产 rclone 请求风暴（24h 5.2 万条报错）的修复之一。
"""
import os

import pytest

from backend.emby_server import mount_cloud


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SCAN_WALK_WORKERS", raising=False)
    yield
    monkeypatch.delenv("SCAN_WALK_WORKERS", raising=False)


def test_default_8(monkeypatch):
    """默认必须是 8：16 个线程同时打 rclone RC 是请求风暴的一半来源"""
    monkeypatch.delenv("SCAN_WALK_WORKERS", raising=False)
    assert mount_cloud._walk_workers() == 8


def test_custom_value(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "4")
    assert mount_cloud._walk_workers() == 4


def test_empty_falls_back(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "")
    assert mount_cloud._walk_workers() == 8


def test_garbage_falls_back(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "abc")
    assert mount_cloud._walk_workers() == 8


def test_zero_or_negative_clamped_to_1(monkeypatch):
    monkeypatch.setenv("SCAN_WALK_WORKERS", "0")
    assert mount_cloud._walk_workers() == 1
    monkeypatch.setenv("SCAN_WALK_WORKERS", "-5")
    assert mount_cloud._walk_workers() == 1
