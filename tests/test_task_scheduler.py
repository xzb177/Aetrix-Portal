"""
统一任务调度器测试（v2.54.1）

验证降并发让路调度策略：
1. 无扫描等待时，enrich 正常开工（全部线程）
2. 有可派发扫描等待时，enrich 降并发（只 N 个线程干活，其余让路）
3. 总开关关闭时，永不让路
4. 扫描优先配置关闭时，永不让路
5. 调度器异常时，fail-safe 继续刮削
6. 熔断器：连续让路超阈值 / 队列长时间无变化 → 自动恢复
7. 只统计可派发扫描（被挂载挡住的不计入）
8. get_unified_status 返回完整结构
"""
import sys
import threading
import time
import types
import unittest
from unittest import mock


def _load_scheduler():
    """隔离加载 task_scheduler（避免 backend 包的重量级导入）"""
    import importlib.util
    import os

    # 用测试文件位置推导仓库路径，不硬编码
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    mod_path = os.path.join(
        repo_root, "backend", "emby_server", "task_scheduler.py"
    )
    spec = importlib.util.spec_from_file_location(
        "task_scheduler_under_test",
        mod_path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patch_scheduler_flags(ts, enabled=True, preempt=True):
    """同时 patch 两个开关的 context manager"""
    return mock.patch.multiple(
        ts, TASK_SCHEDULER_ENABLED=enabled, SCAN_PREEMPT_ENRICH=preempt
    )


class TestAcquireEnrichPermit(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()
        # 每个测试前复位熔断器状态与信号量，避免测试间污染
        with self.ts._CIRCUIT_LOCK:
            self.ts._circuit_yielding_since = None
            self.ts._circuit_last_queue_len = 0
            self.ts._circuit_queue_len_since = None
            self.ts._circuit_open = False
        # 排空信号量后重新填满（恢复初始状态）
        while self.ts._REDUCED_SEMAPHORE.acquire(blocking=False):
            pass
        for _ in range(self.ts.ENRICH_PREEMPT_MIN_THREADS):
            self.ts._REDUCED_SEMAPHORE.release()

    def tearDown(self):
        # 确保信号量恢复（防止测试泄漏名额）
        while self.ts._REDUCED_SEMAPHORE.acquire(blocking=False):
            pass
        for _ in range(self.ts.ENRICH_PREEMPT_MIN_THREADS):
            self.ts._REDUCED_SEMAPHORE.release()

    def test_no_scan_work_normally(self):
        """没有可派发扫描 → 正常开工（limited=False，无需释放）"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=0):
            with _patch_scheduler_flags(self.ts, True, True):
                permit = self.ts.acquire_enrich_permit()
                self.assertIsNotNone(permit)
                self.assertFalse(permit.limited)
                self.ts.release_enrich_permit(permit)  # 无害

    def test_scheduler_disabled_never_yields(self):
        """总开关关闭 → 永不让路（回退旧行为）"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=11):
            with _patch_scheduler_flags(self.ts, False, True):
                permit = self.ts.acquire_enrich_permit()
                self.assertIsNotNone(permit)
                self.assertFalse(permit.limited)

    def test_preempt_disabled_never_yields(self):
        """扫描优先配置关闭 → 永不让路"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=11):
            with _patch_scheduler_flags(self.ts, True, False):
                permit = self.ts.acquire_enrich_permit()
                self.assertIsNotNone(permit)
                self.assertFalse(permit.limited)

    def test_reduced_concurrency(self):
        """有可派发扫描 → 降并发：只有 MIN_THREADS 个线程能拿到名额"""
        n_threads = self.ts.ENRICH_PREEMPT_MIN_THREADS
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=3):
            with _patch_scheduler_flags(self.ts, True, True):
                permits = []
                for _ in range(n_threads):
                    p = self.ts.acquire_enrich_permit()
                    self.assertIsNotNone(p)
                    self.assertTrue(p.limited)
                    permits.append(p)
                # 第 N+1 个拿不到 → 让路
                self.assertIsNone(self.ts.acquire_enrich_permit())
                # 归还一个后又能拿到
                self.ts.release_enrich_permit(permits.pop())
                p = self.ts.acquire_enrich_permit()
                self.assertIsNotNone(p)
                self.assertTrue(p.limited)
                permits.append(p)
                for p in permits:
                    self.ts.release_enrich_permit(p)

    def test_permit_never_raises(self):
        """acquire_enrich_permit 永不抛异常（fail-safe）"""
        with mock.patch.object(
            self.ts, "dispatchable_scan_count", side_effect=RuntimeError("boom")
        ):
            with _patch_scheduler_flags(self.ts, True, True):
                permit = self.ts.acquire_enrich_permit()
                self.assertIsNotNone(permit)
                self.assertFalse(permit.limited)

    def test_release_none_safe(self):
        """release(None) 不抛异常"""
        self.ts.release_enrich_permit(None)

    def test_circuit_breaker_max_yield(self):
        """熔断器：连续让路超过阈值 → 自动恢复（不再让路）"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=5):
            with _patch_scheduler_flags(self.ts, True, True):
                # 把熔断阈值调到极小，加速触发
                with mock.patch.object(self.ts, "ENRICH_PREEMPT_MAX_YIELD_MIN", 0):
                    # MAX_YIELD_MIN=0 → max(1, 0)... 注意模块加载时已计算，
                    # 这里直接改模块变量不影响已计算的常量；改为直接操纵状态
                    pass
                # 直接模拟：yielding_since 设为 31 分钟前
                with self.ts._CIRCUIT_LOCK:
                    self.ts._circuit_yielding_since = time.monotonic() - 31 * 60
                    self.ts._circuit_last_queue_len = 5
                    self.ts._circuit_queue_len_since = time.monotonic()
                permit = self.ts.acquire_enrich_permit()
                # 熔断器触发 → 正常开工（limited=False）
                self.assertIsNotNone(permit)
                self.assertFalse(permit.limited)
                self.assertTrue(self.ts._circuit_is_open())

    def test_circuit_breaker_queue_stall(self):
        """熔断器：队列长度长时间无变化 → 自动恢复"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=5):
            with _patch_scheduler_flags(self.ts, True, True):
                with self.ts._CIRCUIT_LOCK:
                    self.ts._circuit_yielding_since = time.monotonic()
                    self.ts._circuit_last_queue_len = 5
                    # 队列长度 11 分钟无变化
                    self.ts._circuit_queue_len_since = time.monotonic() - 11 * 60
                permit = self.ts.acquire_enrich_permit()
                self.assertIsNotNone(permit)
                self.assertFalse(permit.limited)
                self.assertTrue(self.ts._circuit_is_open())

    def test_circuit_resets_when_queue_empty(self):
        """队列排空 → 熔断器复位"""
        with self.ts._CIRCUIT_LOCK:
            self.ts._circuit_open = True
            self.ts._circuit_yielding_since = time.monotonic() - 3600
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=0):
            with _patch_scheduler_flags(self.ts, True, True):
                permit = self.ts.acquire_enrich_permit()
                self.assertIsNotNone(permit)
                self.assertFalse(self.ts._circuit_is_open())


class TestDispatchableScanCount(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()

    def test_exception_returns_zero(self):
        """scan_queue 导入失败 → 返回 0，不抛异常"""
        with mock.patch.dict(sys.modules, {"backend": None}):
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name.startswith("backend"):
                    raise ImportError("mocked")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=fake_import):
                self.assertEqual(self.ts.dispatchable_scan_count(), 0)

    def test_uses_dispatchable_api(self):
        """优先使用 scan_queue.waiting_dispatchable_count（P1-1）"""
        fake_sq = types.SimpleNamespace()
        fake_sq.waiting_dispatchable_count = mock.MagicMock(return_value=2)

        fake_backend = types.ModuleType("backend")
        fake_emby = types.ModuleType("backend.emby_server")
        fake_emby.scan_queue = fake_sq
        fake_backend.emby_server = fake_emby

        with mock.patch.dict(
            sys.modules,
            {"backend": fake_backend, "backend.emby_server": fake_emby},
        ):
            self.assertEqual(self.ts.dispatchable_scan_count(), 2)
            fake_sq.waiting_dispatchable_count.assert_called_once()


class TestScanWaitingCountCompat(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()

    def test_local_queue_count(self):
        """进程内队列有任务 → 返回队列长度（兼容旧 API）"""
        fake_sq = types.SimpleNamespace()
        fake_sq._LOCK = mock.MagicMock()
        fake_sq._LOCK.__enter__ = mock.MagicMock(return_value=None)
        fake_sq._LOCK.__exit__ = mock.MagicMock(return_value=False)
        fake_sq._QUEUE = [1, 2, 3]  # 3 个等待

        fake_backend = types.ModuleType("backend")
        fake_emby = types.ModuleType("backend.emby_server")
        fake_emby.scan_queue = fake_sq
        fake_backend.emby_server = fake_emby

        with mock.patch.dict(
            sys.modules,
            {"backend": fake_backend, "backend.emby_server": fake_emby},
        ):
            self.assertEqual(self.ts.scan_waiting_count(), 3)


class TestUnifiedStatus(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()

    def test_status_structure(self):
        """get_unified_status 返回完整结构，即使 DB 不可用"""
        status = self.ts.get_unified_status()
        self.assertIn("scheduler_enabled", status)
        self.assertIn("scan_preempt_enrich", status)
        self.assertIn("preempt_active", status)
        self.assertIn("circuit_open", status)
        self.assertIn("min_threads_when_preempted", status)
        self.assertIn("scan", status)
        self.assertIn("enrich", status)
        self.assertIn("waiting", status["scan"])
        self.assertIn("dispatchable", status["scan"])
        self.assertIn("running", status["scan"])
        self.assertIn("pending", status["enrich"])
        self.assertIn("enriching", status["enrich"])
        self.assertIsInstance(status["preempt_active"], bool)


class TestYieldLogThrottle(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()
        # 复位节流状态
        with self.ts._YIELD_LOG_LOCK:
            self.ts._last_yield_log_at = 0.0

    def test_log_throttled(self):
        """60 秒内只记一条让路日志"""
        with mock.patch.object(self.ts.logger, "info") as mock_info:
            with mock.patch.object(
                self.ts, "dispatchable_scan_count", return_value=5
            ):
                self.ts.note_enrich_yielded()
                self.ts.note_enrich_yielded()
                self.ts.note_enrich_yielded()
        # 只调用一次（节流）
        self.assertEqual(mock_info.call_count, 1)

    def test_log_throttle_thread_safe(self):
        """多线程同时打日志节流不崩（P2-1）"""
        errors = []

        def hammer():
            try:
                for _ in range(50):
                    self.ts.note_enrich_yielded()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        with mock.patch.object(
            self.ts, "dispatchable_scan_count", return_value=5
        ):
            threads = [threading.Thread(target=hammer) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])


class TestPreemptWaitJitter(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()

    def test_jitter_range(self):
        """等待时间 = 基础值 + 0~2s 抖动（P2-2）"""
        base = self.ts.ENRICH_PREEMPT_WAIT_SEC
        for _ in range(20):
            w = self.ts.preempt_wait_with_jitter()
            self.assertGreaterEqual(w, base)
            self.assertLessEqual(w, base + 2.0)

    def test_jitter_varies(self):
        """多次调用结果不完全相同（真随机）"""
        vals = {self.ts.preempt_wait_with_jitter() for _ in range(20)}
        self.assertGreater(len(vals), 1)


class TestShouldEnrichYieldCompat(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()
        with self.ts._CIRCUIT_LOCK:
            self.ts._circuit_open = False
            self.ts._circuit_yielding_since = None

    def test_no_scan_no_yield(self):
        """没有可派发扫描 → 不让路"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=0):
            with _patch_scheduler_flags(self.ts, True, True):
                self.assertFalse(self.ts.should_enrich_yield())

    def test_scan_waiting_yields(self):
        """有可派发扫描 → 让路（简化判断）"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=3):
            with _patch_scheduler_flags(self.ts, True, True):
                self.assertTrue(self.ts.should_enrich_yield())

    def test_scheduler_disabled_never_yields(self):
        """总开关关闭 → 永不让路"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=11):
            with _patch_scheduler_flags(self.ts, False, True):
                self.assertFalse(self.ts.should_enrich_yield())

    def test_circuit_open_no_yield(self):
        """熔断器已触发 → 不让路"""
        with mock.patch.object(self.ts, "dispatchable_scan_count", return_value=11):
            with _patch_scheduler_flags(self.ts, True, True):
                with self.ts._CIRCUIT_LOCK:
                    self.ts._circuit_open = True
                self.assertFalse(self.ts.should_enrich_yield())
                with self.ts._CIRCUIT_LOCK:
                    self.ts._circuit_open = False


if __name__ == "__main__":
    unittest.main()
