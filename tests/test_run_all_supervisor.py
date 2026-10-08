"""S5：run_all 看护——worker 退避重启、稳定后计数清零、worker 永不拉停容器；
worker 启动时 Redis 不可用会等待而不是退出。"""
import os
import threading
import time

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend import run_all


class _Proc:
    def __init__(self, rc=None):
        self.rc = rc

    def poll(self):
        return self.rc


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _sup(monkeypatch, critical=("api", "ea")):
    clock = _Clock()
    started = []
    procs = {}

    def starter(name):
        started.append((name, clock.t))
        procs[name] = _Proc()

    sup = run_all.Supervisor(critical, starter=starter, clock=clock)
    return sup, clock, started, procs


def test_restart_delay_is_exponential_and_capped(monkeypatch):
    monkeypatch.setattr(run_all, "RESTART_BASE", 5)
    monkeypatch.setattr(run_all, "RESTART_MAX", 300)
    assert [run_all.restart_delay(n) for n in (1, 2, 3, 4, 5, 6, 7, 8)] == \
        [5, 10, 20, 40, 80, 160, 300, 300]


def test_worker_crash_loop_never_exits_container(monkeypatch):
    monkeypatch.setattr(run_all, "STABLE_SECONDS", 600)
    sup, clock, started, procs = _sup(monkeypatch)
    procs.update(api=_Proc(), ea=_Proc(), worker=_Proc())
    for n in procs:
        sup.started(n)
    delays = []
    for attempt in range(10):  # 旧实现第 4 次就 sys.exit(1)
        procs["worker"].rc = 1
        clock.t += 1
        assert sup.tick(procs) is None
        due = sup.pending["worker"]
        delays.append(due - clock.t)
        clock.t = due
        assert sup.tick(procs) is None
        assert started[-1][0] == "worker"
    assert delays[:4] == [5, 10, 20, 40]
    assert max(delays) == 300
    assert procs["api"].poll() is None and procs["ea"].poll() is None


def test_counter_resets_after_stable_uptime(monkeypatch):
    monkeypatch.setattr(run_all, "STABLE_SECONDS", 600)
    sup, clock, started, procs = _sup(monkeypatch)
    procs["worker"] = _Proc()
    sup.started("worker")
    for _ in range(3):  # 连续崩 3 次 → 第 3 次退避 20s
        procs["worker"].rc = 1
        clock.t += 1
        sup.tick(procs)
        clock.t = sup.pending["worker"]
        sup.tick(procs)
    assert sup.attempts["worker"] == 3
    clock.t += 700  # 稳定跑了 700s 再崩
    procs["worker"].rc = 1
    sup.tick(procs)
    assert sup.attempts["worker"] == 1
    assert sup.pending["worker"] - clock.t == run_all.RESTART_BASE


def test_critical_exit_still_exits(monkeypatch):
    sup, clock, started, procs = _sup(monkeypatch)
    procs.update(api=_Proc(), ea=_Proc(rc=1))
    assert sup.tick(procs) == "exit"


def test_worker_waits_for_redis_instead_of_exiting(monkeypatch):
    from backend import database as dbmod
    from backend import worker

    class _Good:
        def ping(self):
            return True

    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("redis starting")
        return _Good()

    monkeypatch.setattr(dbmod, "REDIS_ENABLED", True)
    monkeypatch.setattr(dbmod, "redis_client", None)
    monkeypatch.setattr(dbmod, "_make_redis_client", lambda: _BadThenGood(factory))
    monkeypatch.setattr(worker, "_REDIS_WAIT_MAX_SEC", 0.05)
    monkeypatch.setattr(worker, "_shutdown_event", threading.Event())
    # 退避从 1s 起：把 wait 缩短
    real_wait = worker._shutdown_event.wait
    monkeypatch.setattr(worker._shutdown_event, "wait", lambda d: real_wait(min(d, 0.01)))
    client = worker._wait_for_redis(max_wait=5)
    assert client is not None and len(attempts) >= 3
    assert dbmod.redis_client is client


class _BadThenGood:
    def __init__(self, factory):
        self._client = factory()

    def ping(self):
        return self._client.ping()


def test_worker_wait_stops_on_shutdown(monkeypatch):
    from backend import database as dbmod
    from backend import worker

    def boom():
        raise ConnectionError("down")

    ev = threading.Event()
    monkeypatch.setattr(dbmod, "REDIS_ENABLED", True)
    monkeypatch.setattr(dbmod, "redis_client", None)
    monkeypatch.setattr(dbmod, "_make_redis_client", boom)
    monkeypatch.setattr(worker, "_shutdown_event", ev)
    threading.Timer(0.2, ev.set).start()
    t0 = time.monotonic()
    assert worker._wait_for_redis() is None
    assert time.monotonic() - t0 < 3


def test_worker_redis_disabled_is_config_error(monkeypatch):
    from backend import database as dbmod
    from backend import worker

    monkeypatch.setattr(dbmod, "REDIS_ENABLED", False)
    assert worker._wait_for_redis(max_wait=0) is None
