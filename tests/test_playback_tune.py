"""开箱即用播放优化的回归测试。

覆盖 backend/emby_server/playback_tune.py 的四个能力：
1. rclone 挂载参数默认值
2. SA 自动轮换
3. 单文件并发 Range 限流
4. 移动端 4K 透明降级
"""
import configparser
import threading
import time
from pathlib import Path

import pytest

from backend.emby_server import playback_tune as pt


# ---------------------------------------------------------------- 1. 挂载参数
def test_default_mount_args_contain_perf_tuning():
    args = pt.build_rclone_mount_args()
    joined = " ".join(args)
    for flag, val in [
        ("--vfs-read-chunk-size", "32M"),
        ("--vfs-read-chunk-size-limit", "256M"),
        ("--vfs-read-ahead", "128M"),
        ("--buffer-size", "32M"),
    ]:
        assert flag in args, f"缺默认参数 {flag}"
        idx = args.index(flag)
        assert args[idx + 1] == val, f"{flag} 默认值应为 {val}"
    assert "--vfs-cache-mode" in args


def test_user_args_override_defaults():
    args = pt.build_rclone_mount_args(["--vfs-read-chunk-size", "64M"])
    idx = args.index("--vfs-read-chunk-size")
    assert args[idx + 1] == "64M"
    # 只出现一次，不重复
    assert args.count("--vfs-read-chunk-size") == 1


def test_build_mount_cmd():
    cmd = pt.build_rclone_mount_cmd("MP:", "/mnt/mp", config="/x/rclone.conf")
    assert cmd[:3] == ["rclone", "mount", "MP:"]
    assert "/mnt/mp" in cmd
    assert "--config" in cmd
    assert "--vfs-read-chunk-size" in cmd


# ---------------------------------------------------------------- 2. SA 轮换
def _write_conf(path: Path, body: str):
    path.write_text(body, encoding="utf-8")


def test_sa_rotation_dir_mode(tmp_path, monkeypatch):
    # 伪造 rclone >= 1.55
    monkeypatch.setattr(pt, "rclone_version_tuple", lambda bin_path="rclone": (1, 66, 0))
    sa_dir = tmp_path / "sa"
    sa_dir.mkdir()
    (sa_dir / "a.json").write_text("{}")
    (sa_dir / "b.json").write_text("{}")
    conf = tmp_path / "rclone.conf"
    _write_conf(conf, "[MP]\ntype = drive\nservice_account_file = /old/a.json\n")
    r = pt.ensure_sa_rotation(conf, sa_dir)
    assert r["mode"] == "dir"
    assert r["changed"] is True
    cfg = configparser.ConfigParser()
    cfg.read(conf, encoding="utf-8")
    assert not cfg.has_option("MP", "service_account_file")
    assert cfg.get("MP", "service_account_file_path").rstrip("/") == str(sa_dir.resolve())


def test_sa_rotation_single_sa(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "rclone_version_tuple", lambda bin_path="rclone": (1, 66, 0))
    sa_dir = tmp_path / "sa"
    sa_dir.mkdir()
    (sa_dir / "only.json").write_text("{}")
    conf = tmp_path / "rclone.conf"
    _write_conf(conf, "[MP]\ntype = drive\nservice_account_file = /old/a.json\n")
    r = pt.ensure_sa_rotation(conf, sa_dir)
    assert r["mode"] == "single"
    cfg = configparser.ConfigParser()
    cfg.read(conf, encoding="utf-8")
    assert cfg.get("MP", "service_account_file").endswith("only.json")


def test_sa_rotation_old_rclone_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "rclone_version_tuple", lambda bin_path="rclone": (1, 53, 3))
    sa_dir = tmp_path / "sa"
    sa_dir.mkdir()
    (sa_dir / "a.json").write_text("{}")
    (sa_dir / "b.json").write_text("{}")
    conf = tmp_path / "rclone.conf"
    _write_conf(conf, "[MP]\ntype = drive\nservice_account_file = /old/a.json\n")
    r = pt.ensure_sa_rotation(conf, sa_dir)
    # 老版本不支持目录轮换，降级单 SA + 告警
    assert r["mode"] == "single"
    assert r["warning"] and "1.55" in r["warning"]


def test_sa_rotation_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "rclone_version_tuple", lambda bin_path="rclone": (1, 66, 0))
    sa_dir = tmp_path / "sa"
    sa_dir.mkdir()
    conf = tmp_path / "rclone.conf"
    _write_conf(conf, "[MP]\ntype = drive\nservice_account_file = /old/a.json\n")
    r = pt.ensure_sa_rotation(conf, sa_dir)
    assert r["changed"] is False
    assert r["warning"]


def test_sa_rotation_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "rclone_version_tuple", lambda bin_path="rclone": (1, 66, 0))
    sa_dir = tmp_path / "sa"
    sa_dir.mkdir()
    (sa_dir / "a.json").write_text("{}")
    (sa_dir / "b.json").write_text("{}")
    conf = tmp_path / "rclone.conf"
    _write_conf(conf, "[MP]\ntype = drive\nservice_account_file = /old/a.json\n")
    r1 = pt.ensure_sa_rotation(conf, sa_dir)
    assert r1["changed"] is True
    r2 = pt.ensure_sa_rotation(conf, sa_dir)
    assert r2["changed"] is False  # 第二次幂等


# ---------------------------------------------------------------- 3. 并发限流
def test_range_limiter_allows_max_concurrent():
    lim = pt.RangeConcurrencyLimiter(max_concurrent=2, acquire_timeout=1)
    assert lim.acquire("/x/a.mkv") is True
    assert lim.acquire("/x/a.mkv") is True
    # 第三个拿不到（1 秒超时）
    t0 = time.monotonic()
    assert lim.acquire("/x/a.mkv") is False
    assert time.monotonic() - t0 < 5
    lim.release("/x/a.mkv")
    assert lim.acquire("/x/a.mkv") is True
    lim.release("/x/a.mkv")
    lim.release("/x/a.mkv")


def test_range_limiter_per_file_isolation():
    lim = pt.RangeConcurrencyLimiter(max_concurrent=1, acquire_timeout=1)
    assert lim.acquire("/x/a.mkv") is True
    # 不同文件互不影响
    assert lim.acquire("/x/b.mkv") is True
    lim.release("/x/a.mkv")
    lim.release("/x/b.mkv")


def test_range_limiter_threaded():
    lim = pt.RangeConcurrencyLimiter(max_concurrent=3, acquire_timeout=10)
    entered = []
    lock = threading.Lock()

    def worker():
        if lim.acquire("/x/big.mkv"):
            with lock:
                entered.append(1)
            time.sleep(0.2)
            lim.release("/x/big.mkv")

    threads = [threading.Thread(target=worker) for _ in range(6)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 6 个线程，每个都拿到了名额（排队而非失败），总耗时约 2 轮
    assert len(entered) == 6
    assert time.monotonic() - t0 >= 0.35


# ---------------------------------------------------------------- 4. 移动端降级
def test_is_mobile_client():
    assert pt.is_mobile_client("SenPlayer/1.0 iOS") is True
    assert pt.is_mobile_client("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)") is True
    assert pt.is_mobile_client("VidHub/2.0 Android") is True
    assert pt.is_mobile_client("Mozilla/5.0 (Windows NT 10.0)") is False
    assert pt.is_mobile_client("") is False
    assert pt.is_mobile_client(None) is False


class _FakeItem:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.guid = kw.get("guid", "g1")
        self.name = kw.get("name", "Test Movie")
        self.library_id = kw.get("library_id", 1)
        self.item_type = kw.get("item_type", "movie")
        self.height = kw.get("height")
        self.tmdb_id = kw.get("tmdb_id")
        self.production_year = kw.get("production_year", 2024)


class _FakeQuery:
    def __init__(self, items):
        self._items = items

    def filter(self, *a, **k):
        return self

    def order_by(self, *a):
        return self

    def limit(self, n):
        return self

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return self._items


class _FakeDB:
    def __init__(self, items):
        self._items = items

    def query(self, *a, **k):
        return _FakeQuery(self._items)


def test_downgrade_skips_non_mobile():
    item = _FakeItem(height=2160)
    db = _FakeDB([_FakeItem(height=1080)])
    out = pt.maybe_downgrade_for_client(
        item, "Mozilla/5.0 (Windows NT 10.0)", db)
    assert out is item


def test_downgrade_skips_non_4k():
    item = _FakeItem(height=1080)
    db = _FakeDB([_FakeItem(height=720)])
    out = pt.maybe_downgrade_for_client(item, "SenPlayer/1.0", db)
    assert out is item


def test_downgrade_picks_1080p_for_mobile_4k():
    item = _FakeItem(height=2160, tmdb_id="123")
    small = _FakeItem(id=2, height=1080, tmdb_id="123")
    db = _FakeDB([small])
    out = pt.maybe_downgrade_for_client(item, "SenPlayer iOS", db)
    assert out is small


def test_downgrade_no_candidate_returns_original():
    item = _FakeItem(height=2160, tmdb_id="123")
    db = _FakeDB([])
    out = pt.maybe_downgrade_for_client(item, "SenPlayer iOS", db)
    assert out is item
