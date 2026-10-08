"""第一轮打磨回归测试：P0/P1 bug 修复验证（importlib 隔离加载，不碰 DB）。"""
import importlib.util
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = os.path.join(os.path.dirname(__file__), "..", "backend", "emby_server")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSubtitleMountPath:
    """P0-1：远程 mount:// 条目的合法外挂字幕不能被误删。"""

    @pytest.fixture()
    def worker(self):
        return _load("polish_subtitle_worker",
                     os.path.join(BASE, "subtitle_scan_worker.py"))

    def test_detect_unknown_returns_none(self, worker):
        # mount:// 路径：os.path.isdir 为 False → 应返回 None（未知），不是空集合
        assert worker._detect_external_subtitles("mount://2/电影/xxx.mp4") is None
        # 不存在的本地目录 → None
        assert worker._detect_external_subtitles("/nonexistent-xyz/xxx.mp4") is None

    def test_detect_empty_dir_returns_empty_set(self, worker):
        with tempfile.TemporaryDirectory() as d:
            # 真实存在的空目录 → 空集合（确实没有字幕）
            result = worker._detect_external_subtitles(os.path.join(d, "xxx.mp4"))
            assert result == set()

    def test_has_changed_unknown_is_false(self, worker, monkeypatch):
        # 探测未知时，即使 DB 有字幕也不应判定为"变化"
        monkeypatch.setattr(worker, "_get_db_external_subtitles",
                            lambda db, iid: {"/sub/xxx.srt"})
        monkeypatch.setattr(worker, "_detect_external_subtitles",
                            lambda p: None)
        assert worker.has_external_subtitle_changed(None, 1, "mount://2/x.mp4") is False

    def test_update_skips_when_unknown(self, worker, monkeypatch):
        item = SimpleNamespace(id=1, file_path="mount://2/x.mp4", name="test")
        monkeypatch.setattr(worker, "_detect_external_subtitles", lambda p: None)
        # 未知时直接返回 0，不删 DB
        assert worker.update_external_subtitles(None, item) == 0


class TestMergeGroupKey:
    """P1-1：多版本合并不能跨库、不能跨类型。"""

    @pytest.fixture()
    def worker(self):
        return _load("polish_merge_worker",
                     os.path.join(BASE, "merge_versions_worker.py"))

    def _item(self, library_id, item_type, tmdb_id):
        return SimpleNamespace(
            id=abs(hash((library_id, item_type, tmdb_id))) % 100000,
            library_id=library_id,
            item_type=item_type,
            tmdb_id=tmdb_id,
            imdb_id="",
        )

    def test_cross_library_not_same_key(self, worker):
        a = self._item(1, "movie", "123")
        b = self._item(2, "movie", "123")  # 同 tmdb_id，不同库
        assert worker._provider_key(a) != worker._provider_key(b)

    def test_cross_type_not_same_key(self, worker):
        a = self._item(1, "movie", "123")
        b = self._item(1, "series", "123")  # 同 tmdb_id，不同类型
        assert worker._provider_key(a) != worker._provider_key(b)

    def test_same_library_type_same_key(self, worker):
        a = self._item(1, "movie", "123")
        b = self._item(1, "movie", "123")
        assert worker._provider_key(a) == worker._provider_key(b)

    def test_key_format(self, worker):
        a = self._item(1, "movie", "123")
        assert worker._provider_key(a) == (1, "movie", "tmdb", "123")


class TestTmdbClientSingleton:
    """P0（#403）：tmdb_client 是单例，不能当函数调用。"""

    def test_episode_groups_uses_singleton(self):
        with open(os.path.join(BASE, "episode_groups.py")) as f:
            content = f.read()
        assert "tmdb_client()" not in content


class TestPosterLanguageApi:
    """#10 原语言海报：配置键有管理端读写接口。"""

    def test_admin_endpoints_exist(self):
        path = os.path.join(os.path.dirname(__file__), "..",
                            "backend", "api", "admin_scrape.py")
        with open(path) as f:
            content = f.read()
        assert "/scrape/tmdb-poster-language" in content
        assert "TMDB_POSTER_LANGUAGE_CONFIG_KEY" in content


class TestIntroMarkerApi:
    """#3 片头标记：API 入口存在。"""

    def test_media_routes_endpoints_exist(self):
        with open(os.path.join(BASE, "media_routes.py")) as f:
            content = f.read()
        assert "IntroMarkers" in content
        assert "EpisodeGroups" in content
