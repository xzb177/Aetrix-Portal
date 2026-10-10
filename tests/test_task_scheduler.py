"""
统一任务调度器测试（v2.54.0）

验证扫描优先于刮削的调度策略：
1. 无扫描等待时，enrich 不让路
2. 有扫描等待时，enrich 让路
3. 总开关关闭时，永不让路
4. 扫描优先配置关闭时，永不让路
5. 调度器异常时，scan_waiting_count 返回 0（不阻断刮削）
6. get_unified_status 返回完整结构
"""
import sys
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


class TestShouldEnrichYield(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()

    def test_no_scan_waiting_no_yield(self):
        """没有扫描等待 → 不让路"""
        with mock.patch.object(self.ts, "scan_waiting_count", return_value=0):
            with mock.patch.object(self.ts, "TASK_SCHEDULER_ENABLED", True):
                with mock.patch.object(self.ts, "SCAN_PREEMPT_ENRICH", True):
                    self.assertFalse(self.ts.should_enrich_yield())

    def test_scan_waiting_yields(self):
        """有扫描等待 → 让路"""
        with mock.patch.object(self.ts, "scan_waiting_count", return_value=3):
            with mock.patch.object(self.ts, "TASK_SCHEDULER_ENABLED", True):
                with mock.patch.object(self.ts, "SCAN_PREEMPT_ENRICH", True):
                    self.assertTrue(self.ts.should_enrich_yield())

    def test_scheduler_disabled_never_yields(self):
        """总开关关闭 → 永不让路（回退旧行为）"""
        with mock.patch.object(self.ts, "scan_waiting_count", return_value=11):
            with mock.patch.object(self.ts, "TASK_SCHEDULER_ENABLED", False):
                with mock.patch.object(self.ts, "SCAN_PREEMPT_ENRICH", True):
                    self.assertFalse(self.ts.should_enrich_yield())

    def test_preempt_disabled_never_yields(self):
        """扫描优先配置关闭 → 永不让路"""
        with mock.patch.object(self.ts, "scan_waiting_count", return_value=11):
            with mock.patch.object(self.ts, "TASK_SCHEDULER_ENABLED", True):
                with mock.patch.object(self.ts, "SCAN_PREEMPT_ENRICH", False):
                    self.assertFalse(self.ts.should_enrich_yield())


class TestScanWaitingCount(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()

    def test_exception_returns_zero(self):
        """scan_queue 导入失败 → 返回 0，不抛异常"""
        with mock.patch.dict(sys.modules, {"backend": None}):
            # 让 from backend.emby_server import scan_queue 抛 ImportError
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name.startswith("backend"):
                    raise ImportError("mocked")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=fake_import):
                self.assertEqual(self.ts.scan_waiting_count(), 0)

    def test_local_queue_count(self):
        """进程内队列有任务 → 返回队列长度"""
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
        self.assertIn("scan", status)
        self.assertIn("enrich", status)
        self.assertIn("waiting", status["scan"])
        self.assertIn("running", status["scan"])
        self.assertIn("pending", status["enrich"])
        self.assertIn("enriching", status["enrich"])
        self.assertIsInstance(status["preempt_active"], bool)


class TestYieldLogThrottle(unittest.TestCase):
    def setUp(self):
        self.ts = _load_scheduler()

    def test_log_throttled(self):
        """60 秒内只记一条让路日志"""
        with mock.patch.object(self.ts.logger, "info") as mock_info:
            with mock.patch.object(self.ts, "scan_waiting_count", return_value=5):
                self.ts.note_enrich_yielded(5)
                self.ts.note_enrich_yielded(5)
                self.ts.note_enrich_yielded(5)
        # 只调用一次（节流）
        self.assertEqual(mock_info.call_count, 1)


if __name__ == "__main__":
    unittest.main()
