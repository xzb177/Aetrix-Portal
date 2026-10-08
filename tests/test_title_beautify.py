"""分集标题美化单元测试（纯函数，无 DB/网络）。"""
import sys
sys.path.insert(0, "/opt/aetrix-portal")

from backend.emby_server.title_beautify import beautify_episode_title as b


def test_garbage_name_rebuilt():
    assert b("Season 01 S01", "/x/Show.S01E05.mkv", 1, 5, "Show") == "第5集"
    assert b("60 S19", "/x/Show.S19E60.mkv", 19, 60, "Show") == "第60集"


def test_placeholder_with_desc():
    out = b("第5集", "/x/Show.S01E05.The.Secret.Mission.1080p.WEB-DL.mkv", 1, 5, "Show")
    assert out == "第5集 · The Secret Mission", out


def test_placeholder_without_desc():
    assert b("第13集", "/x/Running.Man.S04E13.1080p.mkv", 4, 13, "Running Man") == "第13集"


def test_real_title_untouched():
    assert b("血色婚礼", "/x/Show.S03E09.mkv", 3, 9, "Show") == "血色婚礼"


def test_empty_name():
    out = b("", "/x/Show.S02E03.Pilot.720p.mkv", 2, 3, "Show")
    assert out == "第3集 · Pilot", out


def test_english_placeholder():
    assert b("Episode 7", "/x/Show.S01E07.mkv", 1, 7, "Show") == "第7集"


def test_no_episode_number_keeps_raw():
    # 集号无效时不强行改写
    assert b("Season 01 S01", "/x/Show.mkv", 1, None, "Show") == "Season 01 S01"
