"""
worker 心跳线程测试

回归背景：worker 进程实际在工作（enrich/probe 日志正常），但管理后台显示
no_heartbeat。根因是心跳由主线程在**整个启动流程走完之后**才写——主线程要按
顺序启动十几个后台任务，任何一步卡死（如 fs_watcher 建 inotify 监听），主循环
的心跳就永远写不出去。

修复：拿到单实例锁后尽早起一个独立 daemon 心跳线程（worker-heartbeat），
进程活着即心跳不断，不依赖主线程的启动进度。
"""
import importlib.util
import json
import os
import threading
import time
import unittest


def _load_worker():
    """隔离加载 backend/worker.py（避免 backend 包的重量级导入）"""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    mod_path = os.path.join(repo_root, "backend", "worker.py")
    spec = importlib.util.spec_from_file_location(
        "worker_under_test",
        mod_path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StubRedis:
    """最小 Redis stub：只实现心跳用到的 setex。"""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def setex(self, key, ttl, value):
        with self._lock:
            self.calls.append((key, ttl, value))


class TestWriteHeartbeat(unittest.TestCase):
    def setUp(self):
        self.w = _load_worker()

    def test_format_and_ttl(self):
        r = StubRedis()
        self.w._write_heartbeat(r)
        self.assertEqual(len(r.calls), 1)
        key, ttl, value = r.calls[0]
        self.assertEqual(key, "aetrix:worker:heartbeat")
        # TTL 60s，写入间隔 30s：间隔必须小于 TTL，否则监控端误判 stale
        self.assertEqual(ttl, 60)
        self.assertLess(self.w._HEARTBEAT_INTERVAL_SEC, ttl)
        hb = json.loads(value)
        self.assertEqual(hb["role"], "worker")
        self.assertGreater(hb["pid"], 0)
        self.assertGreater(hb["updated_at"], 0)
        self.assertLessEqual(hb["started_at"], hb["updated_at"])

    def test_redis_failure_does_not_raise(self):
        class BoomRedis:
            def setex(self, *a, **k):
                raise ConnectionError("redis down")

        # 写心跳失败只记日志，绝不能把调用线程杀死
        self.w._write_heartbeat(BoomRedis())


class TestHeartbeatThread(unittest.TestCase):
    def setUp(self):
        self.w = _load_worker()
        self.w._shutdown_event.clear()

    def tearDown(self):
        self.w._shutdown_event.clear()
        self.w._heartbeat_thread = None

    def test_start_heartbeat_thread(self):
        r = StubRedis()
        t = self.w._start_heartbeat_thread(r)
        try:
            self.assertTrue(t.daemon)
            self.assertEqual(t.name, "worker-heartbeat")
            self.assertTrue(t.is_alive())
            # loop 入口立即写一次，不用等 30s
            deadline = time.time() + 5
            while not r.calls and time.time() < deadline:
                time.sleep(0.05)
            self.assertGreaterEqual(len(r.calls), 1)
            key, _, value = r.calls[0]
            self.assertEqual(key, "aetrix:worker:heartbeat")
            json.loads(value)  # 合法 JSON
        finally:
            self.w._shutdown_event.set()
            t.join(timeout=5)
        self.assertFalse(t.is_alive())

    def test_start_idempotent(self):
        r = StubRedis()
        t1 = self.w._start_heartbeat_thread(r)
        try:
            t2 = self.w._start_heartbeat_thread(r)
            self.assertIs(t1, t2)  # 重复调用不另起线程
        finally:
            self.w._shutdown_event.set()
            t1.join(timeout=5)
        self.assertFalse(t1.is_alive())

    def test_loop_writes_periodically_and_stops_on_shutdown(self):
        r = StubRedis()
        t = threading.Thread(
            target=self.w._heartbeat_loop, args=(r, 0.05), daemon=True,
        )
        t.start()
        try:
            time.sleep(0.25)
            n_before = len(r.calls)
            self.assertGreaterEqual(n_before, 2)  # 0.05s 间隔
            self.w._shutdown_event.set()
            t.join(timeout=5)
            self.assertFalse(t.is_alive())
            n_after = len(r.calls)
            time.sleep(0.15)
            self.assertEqual(len(r.calls), n_after)  # 停后不再写
        finally:
            self.w._shutdown_event.set()
            t.join(timeout=5)

    def test_loop_survives_redis_errors(self):
        class FlakyRedis:
            def __init__(self):
                self.calls = 0
                self._lock = threading.Lock()

            def setex(self, *a, **k):
                with self._lock:
                    self.calls += 1
                    n = self.calls
                if n % 2 == 1:
                    raise ConnectionError("boom")

        r = FlakyRedis()
        t = threading.Thread(
            target=self.w._heartbeat_loop, args=(r, 0.05), daemon=True,
        )
        t.start()
        try:
            time.sleep(0.25)
            self.w._shutdown_event.set()
            t.join(timeout=5)
            self.assertFalse(t.is_alive())
            # 偶数次成功、奇数次抛异常：线程没被异常杀死
            self.assertGreaterEqual(r.calls, 2)
        finally:
            self.w._shutdown_event.set()
            t.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
