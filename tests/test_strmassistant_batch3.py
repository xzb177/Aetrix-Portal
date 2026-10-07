# -*- coding: utf-8 -*-
"""StrmAssistant 第三批测试：#3/#7/#9/#10/#14/#15"""
import sys
import os

sys.path.insert(0, "/tmp/aetrix-main")
sys.path.insert(0, "/tmp/aetrix-main/backend")


class TestFallbackLanguages:
    """#7 备选语言链"""

    def test_chain_starts_with_preferred(self):
        from backend.emby_server.tmdb import language_fallback_chain
        chain = language_fallback_chain()
        assert len(chain) >= 1
        # 首选语言打头
        from backend.emby_server.tmdb import preferred_language
        assert chain[0] == preferred_language()

    def test_chain_no_duplicates(self):
        from backend.emby_server.tmdb import language_fallback_chain
        chain = language_fallback_chain()
        assert len(chain) == len(set(chain)), "fallback 链不应有重复"

    def test_chain_contains_fallbacks(self):
        from backend.emby_server.tmdb import (
            language_fallback_chain,
            MOVIEDB_FALLBACK_LANGUAGES,
        )
        chain = language_fallback_chain()
        # 至少包含备选语言中的几个
        for lang in MOVIEDB_FALLBACK_LANGUAGES:
            assert lang in chain


class TestPosterLanguage:
    """#10 原语言海报"""

    def test_poster_language_default(self):
        from backend.emby_server.tmdb import poster_language
        # 无 DB 时返回默认
        assert poster_language() == "system"

    def test_poster_language_options(self):
        from backend.emby_server.tmdb import TMDB_POSTER_LANGUAGE_OPTIONS
        assert "system" in TMDB_POSTER_LANGUAGE_OPTIONS
        assert "original" in TMDB_POSTER_LANGUAGE_OPTIONS
        assert "zh-CN" in TMDB_POSTER_LANGUAGE_OPTIONS


class TestProxyUtils:
    """#14 代理 URL 校验/解析"""

    def test_valid_proxy_url(self):
        from backend.integrations.proxy import is_valid_proxy_url
        assert is_valid_proxy_url("http://127.0.0.1:8080")
        assert is_valid_proxy_url("https://proxy.example.com:443")
        assert is_valid_proxy_url("http://user:pass@127.0.0.1:8080")
        assert not is_valid_proxy_url("")
        assert not is_valid_proxy_url("not-a-url")
        assert not is_valid_proxy_url("ftp://example.com:21")

    def test_parse_proxy_url(self):
        from backend.integrations.proxy import try_parse_proxy_url
        r = try_parse_proxy_url("http://user:pass@127.0.0.1:8080")
        assert r is not None
        assert r["scheme"] == "http"
        assert r["host"] == "127.0.0.1"
        assert r["port"] == 8080
        assert r["username"] == "user"
        assert r["password"] == "pass"

        r2 = try_parse_proxy_url("https://proxy.example.com")
        assert r2 is not None
        assert r2["port"] == 443  # 默认端口

        assert try_parse_proxy_url("invalid") is None
        assert try_parse_proxy_url("") is None


class TestIntroMarker:
    """#3 片头片尾标记"""

    def test_marker_types(self):
        from backend.emby_server.intro_marker import MARKER_TYPES
        assert "intro" in MARKER_TYPES
        assert "outro" in MARKER_TYPES
        assert "credits" in MARKER_TYPES

    def test_to_chapters(self):
        from backend.emby_server.intro_marker import to_chapters
        markers = [
            {"id": 1, "marker_type": "intro", "start_ms": 0, "end_ms": 90000, "source": "manual"},
        ]
        chapters = to_chapters(markers)
        assert len(chapters) == 1
        assert chapters[0]["StartPositionTicks"] == 0
        assert chapters[0]["EndPositionTicks"] == 90000 * 10000
        assert chapters[0]["MarkerType"] == "intro"


class TestEpisodeGroups:
    """#15 剧集组"""

    def test_config_prefix(self):
        from backend.emby_server.episode_groups import EPISODE_GROUP_CONFIG_PREFIX
        assert EPISODE_GROUP_CONFIG_PREFIX == "tmdb_episode_group_"
