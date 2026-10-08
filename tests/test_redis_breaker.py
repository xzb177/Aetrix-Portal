"""S4：Redis 运行期故障——短超时、熔断降级到内存缓存 / 进程内限流、后台重连。"""
import os
import socket
import time

import pytest

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend import database as db


class _BrokenRedis:
    def __init__(self, delay=0.0):
        self.calls = 0
        self.delay = delay

    def _fail(self, *a, **k):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        raise TimeoutError("Timeout reading from socket")

    get = setex = delete = keys = exists = incr = expire = ping = _fail


class _GoodRedis:
    def __init__(self):
        self.store = {}
        self.calls = 0

    def get(self, k):
        self.calls += 1
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.calls += 1
        self.store[k] = v
        return True

    def incr(self, k):
        self.store[k] = int(self.store.get(k, 0)) + 1
        return self.store[k]

    def expire(self, k, ttl):
        return True

    def ping(self):
        return True


@pytest.fixture
def breaker(monkeypatch):
    b = db.RedisBreaker(failures=3, cooldown=0.3)
    monkeypatch.setattr(db, "redis_breaker", b)
    db.CacheManager._memory_cache.clear()
    db.CacheManager._memory_cache_order.clear()
    yield b


def test_breaker_opens_then_half_open_probe_closes(breaker):
    assert breaker.allow() and breaker.state == "closed"
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state == "open" and not breaker.allow()
    time.sleep(0.35)
    assert breaker.state == "half-open"
    assert breaker.allow() is True       # 一次探测
    assert breaker.allow() is False      # 同时只放一个
    breaker.record_success()
    assert breaker.state == "closed" and breaker.allow()


def test_cache_falls_back_to_memory_and_stops_hitting_redis(breaker, monkeypatch):
    broken = _BrokenRedis(delay=0.2)
    monkeypatch.setattr(db, "redis_client", broken)
    db.CacheManager.set("k", "v", ttl=60)        # 失败 → 写内存
    assert db.CacheManager.get("k") == "v"       # 失败 → 读内存
    db.CacheManager.get("k")                     # 第 3 次失败 → 熔断
    assert breaker.state == "open"
    calls = broken.calls
    t0 = time.monotonic()
    for _ in range(200):
        assert db.CacheManager.get("k") == "v"
    # 熔断期间不再碰 Redis：200 次读不付任何超时（旧实现每次 5–10s）
    assert broken.calls == calls
    assert time.monotonic() - t0 < 0.2


def test_cache_recovers_after_cooldown(breaker, monkeypatch):
    monkeypatch.setattr(db, "redis_client", _BrokenRedis())
    for _ in range(3):
        db.CacheManager.get("x")
    assert breaker.state == "open"
    good = _GoodRedis()
    monkeypatch.setattr(db, "redis_client", good)
    time.sleep(0.35)
    db.CacheManager.set("x", "1")                # 半开探测成功
    assert breaker.state == "closed"
    assert good.store["rb:x"] == "1"


def test_rate_limit_uses_memory_while_redis_down(breaker, monkeypatch):
    monkeypatch.setattr(db, "REDIS_ENABLED", True)
    monkeypatch.setattr(db, "redis_client", _BrokenRedis())
    key = f"ratelimit:test:{time.time()}"
    counts = [db.rate_limit_incr(key) for _ in range(5)]
    assert counts == [1, 2, 3, 4, 5]             # 降级期间仍然在限流（进程内计数）


def test_rate_limit_none_when_redis_disabled(breaker, monkeypatch):
    monkeypatch.setattr(db, "REDIS_ENABLED", False)
    monkeypatch.setattr(db, "redis_client", None)
    assert db.rate_limit_incr("ratelimit:off") is None  # 未启用 Redis：不限流（与升级前一致）


def test_rate_limit_uses_redis_when_healthy(breaker, monkeypatch):
    good = _GoodRedis()
    monkeypatch.setattr(db, "REDIS_ENABLED", True)
    monkeypatch.setattr(db, "redis_client", good)
    assert db.rate_limit_incr("ratelimit:a") == 1
    assert db.rate_limit_incr("ratelimit:a") == 2
    assert good.store["ratelimit:a"] == 2


def test_short_socket_timeout_against_blackhole(monkeypatch):
    """服务端接受连接但从不回包：ping 在 ~REDIS_SOCKET_TIMEOUT 内失败（旧值 5s × 重试）。"""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    try:
        monkeypatch.setattr(db, "REDIS_URL", f"redis://127.0.0.1:{port}/0")
        client = db._make_redis_client()
        t0 = time.monotonic()
        with pytest.raises(Exception):
            client.ping()
        assert time.monotonic() - t0 < db.REDIS_SOCKET_TIMEOUT * 2 + 1.0
        assert db.REDIS_SOCKET_TIMEOUT <= 1.0  # 默认值
    finally:
        srv.close()


def test_background_reconnect(monkeypatch, breaker):
    attempts = []
    good = _GoodRedis()

    def factory():
        attempts.append(1)
        return _BrokenRedis() if len(attempts) < 2 else good

    monkeypatch.setattr(db, "redis_client", None)
    monkeypatch.setattr(db, "REDIS_BREAKER_SECONDS", 0.05)
    monkeypatch.setattr(db, "_make_redis_client", factory)
    monkeypatch.setattr(db, "_reconnect_started", False)
    db._start_redis_reconnect()
    deadline = time.monotonic() + 3
    while db.redis_client is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert db.redis_client is good
    assert len(attempts) >= 2


def test_playbackinfo_cache_calls_go_through_threadpool():
    src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "emby_server", "api.py"),
               encoding="utf-8").read()
    assert "await run_db(CacheManager.get, cache_key)" in src
    assert "await run_db(CacheManager.set, cache_key" in src
    assert "hit = CacheManager.get(" not in src
