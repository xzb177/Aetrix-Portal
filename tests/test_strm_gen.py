"""Tests for backend/emby_server/strm_gen.py — .strm 生成器内置版。

覆盖：路径映射、视频判定、冲突解决、配置归一化、完整性校验。
不碰网络（Drive API 部分用 monkeypatch 隔离）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.emby_server import strm_gen as sg


class TestStrmRelpath:
    def test_strip_prefix(self):
        assert sg.strm_relpath("MoviePilot/剧集/xx.mkv", "MoviePilot/") == "剧集/xx.strm"

    def test_no_prefix(self):
        assert sg.strm_relpath("电影/xx.mp4", "") == "电影/xx.strm"

    def test_prefix_not_matched(self):
        # 前缀不匹配时保留原路径
        assert sg.strm_relpath("Other/xx.mkv", "MoviePilot/") == "Other/xx.strm"

    def test_nested(self):
        assert sg.strm_relpath(
            "MoviePilot/剧集/国产剧/惊枝 (2026)/Season 1/惊枝 - S01E01.mkv",
            "MoviePilot/",
        ) == "剧集/国产剧/惊枝 (2026)/Season 1/惊枝 - S01E01.strm"


class TestIsVideoPath:
    def test_video(self):
        assert sg.is_video_path("MoviePilot/剧集/xx.mkv")
        assert sg.is_video_path("MoviePilot/电影/xx.MP4")  # 大小写

    def test_not_video(self):
        assert not sg.is_video_path("MoviePilot/剧集/xx.nfo")
        assert not sg.is_video_path("MoviePilot/剧集/xx.jpg")

    def test_skip_hidden(self):
        assert not sg.is_video_path("MoviePilot/.hidden/xx.mkv")
        assert not sg.is_video_path("MoviePilot/剧集/.DS_Store.mkv")

    def test_skip_system_dirs(self):
        assert not sg.is_video_path("MoviePilot/剧集/@eaDir/xx.mkv")
        assert not sg.is_video_path("MoviePilot/剧集/#recycle/xx.mkv")

    def test_all_supported_exts(self):
        for ext in sg.VIDEO_EXTS:
            assert sg.is_video_path(f"a/b{ext}"), ext


class TestDriveUrl:
    def test_format(self):
        url = sg.drive_url("1QALUKEAwNgo1J8y2EipIDTcVDwIrpX_y")
        assert url == ("https://drive.google.com/uc?export=download"
                       "&id=1QALUKEAwNgo1J8y2EipIDTcVDwIrpX_y&confirm=t")


class TestResolveCollision:
    def test_no_collision(self):
        assert sg._resolve_collision("a/b.strm", set()) == "a/b.strm"

    def test_collision(self):
        used = {"a/b.strm"}
        assert sg._resolve_collision("a/b.strm", used) == "a/b-2.strm"

    def test_multiple(self):
        used = {"a/b.strm", "a/b-2.strm"}
        assert sg._resolve_collision("a/b.strm", used) == "a/b-3.strm"


class TestVerifyCompleteness:
    def _videos(self):
        # (rel, fid, size)
        return [
            ("MoviePilot/剧集/A/Season 1/A - S01E01.mkv", "f1", 100),
            ("MoviePilot/剧集/A/Season 1/A - S01E02.mkv", "f2", 100),
            ("MoviePilot/剧集/A/Season 1/A - S01E03.mkv", "f3", 100),
            ("MoviePilot/剧集/B/Season 1/B - S01E01.mkv", "f4", 100),
        ]

    def test_all_complete(self):
        videos = self._videos()
        state = {rel: (fid, size, rel.replace(".mkv", ".strm"))
                 for rel, fid, size in videos}
        result = sg._verify_completeness(videos, state, "MoviePilot/")
        assert result["total_series"] == 2  # A/Season 1, B/Season 1
        assert result["incomplete_series"] == 0

    def test_missing_detected(self):
        videos = self._videos()
        # state 缺了 A 的 E03
        state = {rel: (fid, size, rel.replace(".mkv", ".strm"))
                 for rel, fid, size in videos
                 if "E03" not in rel}
        result = sg._verify_completeness(videos, state, "MoviePilot/")
        assert result["incomplete_series"] == 1
        inc = result["incomplete"][0]
        assert inc["series"] == "剧集/A/Season 1"
        assert inc["missing_count"] == 1
        assert any("E03" in m for m in inc["missing_sample"])


class TestSchedule:
    def test_valid(self):
        assert sg.schedule(_FakeDb({"strm_gen_schedule": "03:00"})) == "03:00"

    def test_invalid(self):
        assert sg.schedule(_FakeDb({"strm_gen_schedule": "25:00"})) == ""
        assert sg.schedule(_FakeDb({"strm_gen_schedule": "abc"})) == ""
        assert sg.schedule(_FakeDb({"strm_gen_schedule": ""})) == ""

    def test_source_dir(self):
        assert sg.source_dir(_FakeDb({"strm_gen_source_dir": "MoviePilot/"})) == "MoviePilot/"
        assert sg.source_dir(_FakeDb({"strm_gen_source_dir": ""})) == ""
        assert sg.source_dir(_FakeDb({})) == "MoviePilot/"  # 默认

    def test_enabled(self):
        assert sg.enabled(_FakeDb({"strm_gen_enabled": "true"}))
        assert not sg.enabled(_FakeDb({"strm_gen_enabled": "false"}))
        assert sg.enabled(_FakeDb({}))  # 默认 true


class _FakeDb:
    """最小 store.get_value 替身。"""

    def __init__(self, values: dict):
        self._values = values


# 给 _db_config 打桩：strm_gen._db_config(db, key, default)
@pytest.fixture(autouse=True)
def _patch_db_config(monkeypatch):
    def fake_db_config(db, key, default=""):
        if isinstance(db, _FakeDb):
            return db._values.get(key, default)
        return default
    monkeypatch.setattr(sg, "_db_config", fake_db_config)
