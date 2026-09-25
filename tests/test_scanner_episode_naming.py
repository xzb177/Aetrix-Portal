"""剧集命名：只有季号、没有集号时不能崩

真实起因：网盘里混进了 ``某剧 Season 2.mkv`` 这类**只解析出季号**的文件，
扫描器拼名字时写死 ``f"... S{season_no:02d}E{ep_no:02d}"``，而 ``ep_no`` 是 ``None``：

    TypeError: unsupported format string passed to NoneType.__format__

整个媒体库的扫描在这一行崩掉，前面已经扫完的批次全部白跑 —— 而触发它的可能只是
887 个目录里的任意一个文件。

这里钉住三件事：

- 正常 S01E02 不受影响；
- 只有季号时退化成 ``片名 S02``，**不猜集号、不填 0**；
- 解析层确实会产出 ``episode=None``（不是理论上的不可能），把这条也钉住。
"""
from backend.emby_server.scanner import _episode_display_name, parse_media_filename


def test_normal_episode_name_unchanged():
    assert _episode_display_name("3月的狮子", 1, 2) == "3月的狮子 S01E02"
    assert _episode_display_name("86-不存在的战区", 2, 13) == "86-不存在的战区 S02E13"


def test_season_only_does_not_crash():
    """这条就是回归本体：ep_no=None 时不能做 :02d 格式化"""
    assert _episode_display_name("某剧", 2, None) == "某剧 S02"
    assert _episode_display_name("某剧", 10, None) == "某剧 S10"


def test_missing_season_falls_back_to_episode_only():
    assert _episode_display_name("某剧", None, 3) == "某剧 E03"


def test_both_missing_returns_base_name():
    assert _episode_display_name("某剧", None, None) == "某剧"


def test_empty_base_name_still_safe():
    assert _episode_display_name("", 1, 2) == " S01E02"


# ==================== 解析层真的会产出 episode=None ====================


def test_parser_returns_none_episode_for_season_only_files():
    parsed = parse_media_filename("某剧 Season 2.mkv", "tvshows")
    assert parsed["season"] == 2
    assert parsed["episode"] is None


def test_parser_returns_none_episode_for_bare_s_number():
    parsed = parse_media_filename("某剧.S09.mkv", "tvshows")
    assert parsed["season"] == 9
    assert parsed["episode"] is None


def test_parsed_season_only_can_be_named_without_raising():
    parsed = parse_media_filename("某剧 Season 2.mkv", "tvshows")
    # 旧实现在这一行抛 TypeError
    name = _episode_display_name(parsed["name"], parsed["season"], parsed["episode"])
    assert "S02" in name
