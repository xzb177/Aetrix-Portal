"""回归测试：公益到期调度器必须能活过第一次 tick。

历史 bug：backend/welfare_expiry.py 顶部缺少 import time，
_run() 第一次 tick 结束后调用 time.sleep(86400) 抛 NameError，
daemon 线程死亡，之后福利到期检查再也不执行。
"""

import threading

import pytest

from backend import welfare_expiry


class _StopLoop(Exception):
    """在第一次 sleep 时抛出，用于终止调度线程的 while 循环。"""


@pytest.fixture(autouse=True)
def _reset_scheduler_state():
    """每个测试前后重置调度器全局状态，避免污染其他测试。"""
    welfare_expiry._SCHEDULER_STARTED = False
    yield
    welfare_expiry._SCHEDULER_STARTED = False


def test_module_has_time_imported():
    """回归：模块内必须能访问 time.sleep（缺 import 时会 AttributeError）。"""
    assert callable(welfare_expiry.time.sleep)


def test_scheduler_thread_survives_first_tick(monkeypatch):
    """调度线程跑完第一次 tick 并进入 sleep 时不应抛 NameError。"""
    tick_done = threading.Event()
    slept = []
    errors = []
    sessions = []
    calls = {"expiry": 0, "inactive": 0}

    class _FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def _fake_session_local():
        s = _FakeSession()
        sessions.append(s)
        return s

    # mock 掉真实数据库会话工厂
    import backend.database as database

    monkeypatch.setattr(database, "SessionLocal", _fake_session_local)

    def _fake_check_expiry(db):
        calls["expiry"] += 1
        return {"checked": 1, "grace": [], "expired": []}

    def _fake_check_inactive(db):
        calls["inactive"] += 1
        return {"checked": 1, "disabled": []}

    monkeypatch.setattr(welfare_expiry, "check_welfare_expiry", _fake_check_expiry)
    monkeypatch.setattr(welfare_expiry, "check_inactive_users", _fake_check_inactive)

    def _fake_sleep(seconds):
        # 走到 sleep 说明第一次 tick 已完整执行，抛异常结束循环
        slept.append(seconds)
        tick_done.set()
        raise _StopLoop()

    monkeypatch.setattr(welfare_expiry.time, "sleep", _fake_sleep)

    # 捕获线程未处理异常（NameError 会经由 threading.excepthook 上报）
    def _hook(args):
        # _StopLoop 是测试主动抛出、用于终止调度线程 while True 循环的，不算 bug，需过滤
        if isinstance(args.exc_value, _StopLoop):
            return
        errors.append(args.exc_value)

    old_hook = threading.excepthook
    threading.excepthook = _hook
    try:
        assert welfare_expiry.start_welfare_expiry_scheduler() is True
        assert tick_done.wait(timeout=5), "调度线程未能在超时内完成第一次 tick"
    finally:
        threading.excepthook = old_hook
        # 等待调度线程结束（_StopLoop 已终止循环）
        for t in threading.enumerate():
            if t.name == "welfare-expiry-scheduler":
                t.join(timeout=5)

    assert calls["expiry"] == 1
    assert calls["inactive"] == 1
    assert slept == [86400]
    assert sessions and sessions[0].closed is True
    # 关键断言：线程未因缺少 import time 而抛 NameError
    assert errors == []
