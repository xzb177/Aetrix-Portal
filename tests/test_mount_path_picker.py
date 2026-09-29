"""挂载路径选择器 API 测试：路径规范化 + 目录过滤。"""
import pytest

from backend.emby_server.portal_mount_routes import _normalize_browse_path


class TestNormalizeBrowsePath:
    def test_root(self):
        assert _normalize_browse_path(None) == "/"
        assert _normalize_browse_path("") == "/"
        assert _normalize_browse_path("/") == "/"

    def test_normal(self):
        assert _normalize_browse_path("/MoviePilot/剧集") == "/MoviePilot/剧集"
        assert _normalize_browse_path("MoviePilot/剧集/") == "/MoviePilot/剧集"

    def test_dot_segments(self):
        assert _normalize_browse_path("/a/./b") == "/a/b"

    def test_parent_rejected(self):
        with pytest.raises(ValueError):
            _normalize_browse_path("/a/../b")
        with pytest.raises(ValueError):
            _normalize_browse_path("..")
        with pytest.raises(ValueError):
            _normalize_browse_path("/a/b/../../c")

    def test_backslash(self):
        assert _normalize_browse_path("\\a\\b") == "/a/b"

    def test_whitespace(self):
        assert _normalize_browse_path("  /a/b  ") == "/a/b"
