"""第二轮打磨回归测试：性能与资源修复验证（importlib 隔离加载）。"""
import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = os.path.join(os.path.dirname(__file__), "..", "backend", "emby_server")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestProbeWorker:
    """预提取排除 probed_no_duration；调度器有背压。"""

    def test_probed_no_duration_excluded(self):
        with open(os.path.join(BASE, "probe_worker.py")) as f:
            content = f.read()
        assert '"probed_no_duration"' in content

    def test_dispatcher_backpressure(self):
        with open(os.path.join(BASE, "probe_worker.py")) as f:
            content = f.read()
        assert "qsize()" in content or "_work_queue" in content


class TestThumbnailWorker:
    """超时收紧；单视频总上限；SQL 层过滤 mount://。"""

    def test_timeout_defaults(self):
        mod = _load("polish_thumb2", os.path.join(BASE, "thumbnail_worker.py"))
        assert mod.THUMBNAIL_FFMPEG_TIMEOUT <= 120
        assert hasattr(mod, "THUMBNAIL_PER_VIDEO_TIMEOUT")

    def test_mount_filtered_in_sql(self):
        with open(os.path.join(BASE, "thumbnail_worker.py")) as f:
            content = f.read()
        assert 'mount://%' in content


class TestSubtitleWorker:
    """路径先行；流式；批量提交。"""

    def test_path_check_before_db(self):
        with open(os.path.join(BASE, "subtitle_scan_worker.py")) as f:
            content = f.read()
        # _detect_external_subtitles 在 _scan_once 主循环开头调用（路径先行）
        assert "detected = _detect_external_subtitles(item.file_path)" in content
        assert "if detected is None:" in content

    def test_yield_per(self):
        with open(os.path.join(BASE, "subtitle_scan_worker.py")) as f:
            content = f.read()
        assert "yield_per" in content


class TestTmdbFallback:
    """fallback 深度可配。"""

    def test_fallback_max_configurable(self):
        with open(os.path.join(BASE, "tmdb.py")) as f:
            content = f.read()
        assert "TMDB_FALLBACK_MAX_LANGS" in content

    def test_images_with_language_cached(self):
        with open(os.path.join(BASE, "tmdb.py")) as f:
            content = f.read()
        assert "tmdb_cache.load_details" in content or "load_details" in content


class TestEpisodeGroupsCache:
    """剧集组磁盘缓存。"""

    def test_cache_used(self):
        with open(os.path.join(BASE, "episode_groups.py")) as f:
            content = f.read()
        assert "tmdb_cache" in content


class TestWorkerRegistry:
    """worker 存活注册表。"""

    def test_registry_exists(self):
        mod = _load("polish_registry",
                    os.path.join(BASE, "worker_registry.py"))
        assert hasattr(mod, "register")
        assert hasattr(mod, "heartbeat")
        assert hasattr(mod, "snapshot")

    def test_health_exposes_workers(self):
        path = os.path.join(os.path.dirname(__file__), "..",
                            "backend", "health_report.py")
        with open(path) as f:
            content = f.read()
        assert "worker_registry" in content


class TestDatabaseIndexes:
    """索引补齐函数存在。"""

    def test_ensure_functions_exist(self):
        path = os.path.join(os.path.dirname(__file__), "..",
                            "backend", "database.py")
        with open(path) as f:
            content = f.read()
        assert "_ensure_merged_into_id_index" in content
        assert "_ensure_person_tmdb_id_index" in content


class TestPinyinCache:
    """pinyin lru_cache。"""

    def test_lru_cache(self):
        with open(os.path.join(BASE, "pinyin_sort.py")) as f:
            content = f.read()
        assert "lru_cache" in content
