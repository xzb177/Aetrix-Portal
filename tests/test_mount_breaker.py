"""挂载熔断器（v2.42.9）单测：坏挂载快速失败，条目不等 MOUNT_TIMEOUT。

全部走 ``mounts._call_remote`` 这个唯一远程收口，不发真实网络请求。
验收口径（处方 11）：连续失败 → 熔断打开 → 后续调用直接抛 MountBreakerOpen，
补全 worker 据此把条目打回 pending + 长退避（而非 failed）。
"""
from datetime import datetime
from unittest import mock

import pytest

from backend.emby_server import mounts as mnt


class FakeMount:
    def __init__(self, mid=1, mtype="webdav", config='{"url": "http://x"}'):
        self.id = mid
        self.mount_type = mtype
        self.config = config


class RemoteProvider(mnt.MountProvider):
    """最小远程提供者：_call_remote 只拿 mount/config，不真调 list_dir"""

    mount_type = "webdav"


def _provider(mid=1, config='{"url": "http://x"}'):
    return RemoteProvider(FakeMount(mid=mid, config=config))


def _boom(prov, rel):
    raise mnt.MountError("网盘抖动（测试用）")


@pytest.fixture(autouse=True)
def clean_breaker():
    mnt.breaker_reset()
    yield
    mnt.breaker_reset()


# ==================== 打开与快速失败 ====================


def test_opens_after_threshold_consecutive_failures():
    """连续 MountError 达到阈值 → 熔断打开"""
    p = _provider()
    for i in range(mnt.MOUNT_BREAKER_THRESHOLD):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/电影")
    stats = mnt.mount_breaker_stats()
    assert stats["opens"] == 1
    assert len(stats["open"]) == 1
    assert stats["open"][0]["mount_id"] == 1
    assert stats["open"][0]["fails"] == mnt.MOUNT_BREAKER_THRESHOLD
    assert "网盘抖动" in stats["open"][0]["last_error"]


def test_open_breaker_fails_fast_without_touching_network():
    """打开期间：直接抛 MountBreakerOpen，底层一次都不被调用（快速失败）"""
    p = _provider()
    calls = {"n": 0}

    def counting_boom(prov, rel):
        calls["n"] += 1
        raise mnt.MountError("网盘抖动（测试用）")

    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, counting_boom, "/")
    assert calls["n"] == mnt.MOUNT_BREAKER_THRESHOLD
    with pytest.raises(mnt.MountBreakerOpen):
        mnt._call_remote(p, counting_boom, "/")
    with pytest.raises(mnt.MountBreakerOpen):
        mnt._call_remote(p, counting_boom, "/别的目录")
    # 熔断期间底层零调用：这就是「不再逐条等 20s 超时」的验收
    assert calls["n"] == mnt.MOUNT_BREAKER_THRESHOLD
    assert mnt.mount_breaker_stats()["fast_fails"] == 2


def test_success_resets_consecutive_failures():
    """一次成功清零：偶发抖动不触发熔断"""
    p = _provider()
    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD - 1):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/")
    # 仍差一次才熔断；接下来一次成功就把连续失败清零
    assert mnt.mount_breaker_open(1) is False
    ok_calls = {"n": 0}

    def ok(prov, rel):
        ok_calls["n"] += 1
        return [mnt.MountEntry(name="a.mkv", rel="/a.mkv", is_dir=False)]

    entries = mnt._call_remote(p, ok, "/")
    assert entries and entries[0].name == "a.mkv"
    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD - 1):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/")
    assert mnt.mount_breaker_open(1) is False, "成功后连续失败应重新计数"
    with pytest.raises(mnt.MountError):
        mnt._call_remote(p, _boom, "/")
    assert mnt.mount_breaker_open(1) is True


# ==================== 冷却与半开 ====================


def test_half_open_probes_after_cooldown_and_reopens_on_failure(monkeypatch):
    """冷却过后自动半开放探测：探测失败 → 立刻重新打开"""
    monkeypatch.setattr(mnt, "MOUNT_BREAKER_COOLDOWN_SEC", 0.02)
    p = _provider()
    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/")
    assert mnt.mount_breaker_open(1) is True
    import time as _t
    _t.sleep(0.05)  # 冷却过期
    # 半开：这次调用会真去探测（抛的是原始 MountError，不是 MountBreakerOpen）
    probed = {"n": 0}

    def still_dead(prov, rel):
        probed["n"] += 1
        raise mnt.MountError("探测失败（测试用）")

    with pytest.raises(mnt.MountError) as ei:
        mnt._call_remote(p, still_dead, "/")
    assert not isinstance(ei.value, mnt.MountBreakerOpen)
    assert probed["n"] == 1
    # 探测失败 → 立即重新熔断，后续继续快速失败
    with pytest.raises(mnt.MountBreakerOpen):
        mnt._call_remote(p, still_dead, "/")
    assert probed["n"] == 1
    assert mnt.mount_breaker_open(1) is True


def test_half_open_probe_success_closes_breaker(monkeypatch):
    """半开探测成功 → 熔断关闭，业务恢复"""
    monkeypatch.setattr(mnt, "MOUNT_BREAKER_COOLDOWN_SEC", 0.02)
    p = _provider()
    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/")
    import time as _t
    _t.sleep(0.05)

    def healed(prov, rel):
        return [mnt.MountEntry(name="b.mkv", rel="/b.mkv", is_dir=False)]

    entries = mnt._call_remote(p, healed, "/")
    assert entries
    assert mnt.mount_breaker_open(1) is False
    stats = mnt.mount_breaker_stats()
    assert stats["open"] == []


# ==================== 键与作用域 ====================


def test_mount_breaker_open_matches_by_mount_id():
    """补全侧只知道 mount:// 的数字 id：按 id 匹配任意配置指纹的键"""
    p_a = _provider(mid=5, config='{"url": "http://a"}')
    p_b = _provider(mid=5, config='{"url": "http://b"}')  # 同 id 换配置 = 不同键
    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p_a, _boom, "/")
    assert mnt.mount_breaker_open(5) is True
    assert mnt.mount_breaker_open(6) is False
    # 另一个指纹键不受影响，但按 id 查询同样报告打开
    assert not mnt._breaker_open_key(mnt._breaker_key(p_b))
    assert mnt.mount_breaker_open(5) is True


def test_local_provider_never_trips_breaker():
    """本机目录不吃熔断：MountError 不记账，也不会挡住远程键"""
    p = _provider(mid=3)
    with mock.patch.object(mnt, "_is_remote_provider", return_value=False):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/")
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/")
    assert mnt.mount_breaker_open(3) is False
    assert mnt.mount_breaker_stats()["tracked"] == 0


def test_non_mount_error_does_not_trip_breaker():
    """只有 MountError 家族才记账：其他异常不该把挂载拉黑"""
    p = _provider()

    def other_bug(prov, rel):
        raise RuntimeError("编程错误（测试用）")

    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD + 2):
        with pytest.raises(RuntimeError):
            mnt._call_remote(p, other_bug, "/")
    assert mnt.mount_breaker_open(1) is False


def test_stats_shape_and_reset():
    """快照字段齐备；breaker_reset 清干净（测试隔离用）"""
    assert mnt.mount_breaker_stats() == {
        "threshold": mnt.MOUNT_BREAKER_THRESHOLD,
        "cooldown_sec": mnt.MOUNT_BREAKER_COOLDOWN_SEC,
        "retry_sec": mnt.MOUNT_BREAKER_RETRY_SEC,
        "fast_fails": 0,
        "opens": 0,
        "tracked": 0,
        "open": [],
    }
    p = _provider(mid=8)
    for _ in range(mnt.MOUNT_BREAKER_THRESHOLD):
        with pytest.raises(mnt.MountError):
            mnt._call_remote(p, _boom, "/")
    stats = mnt.mount_breaker_stats()
    assert stats["tracked"] == 1 and stats["opens"] == 1
    entry = stats["open"][0]
    assert set(entry) == {"mount_id", "mount_type", "opened_at", "fails", "last_error"}
    datetime.fromisoformat(entry["opened_at"])  # 时间可读（进度接口直接展示）
    mnt.breaker_reset()
    assert mnt.mount_breaker_stats()["tracked"] == 0
    assert mnt.mount_breaker_stats()["opens"] == 0
