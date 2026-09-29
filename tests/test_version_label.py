"""多版本标签对标标准 Emby 的测试。

标准口径（Emby 官方 Wiki "Multiversion movies"）：
" - " 后面的文本原样作为版本名，不拼接大小等其他信息。
"""
from types import SimpleNamespace

from backend.emby_server.api import _version_label


def _item(file_path, height=0, size=0):
    return SimpleNamespace(file_path=file_path, height=height, size=size)


def test_dash_suffix_returned_verbatim():
    # " - " 后缀原样返回，不加大小后缀
    item = _item("/movies/300/300 - 1080p.mkv", height=1080, size=5 * 1024 ** 3)
    assert _version_label(item) == "1080p"


def test_dash_suffix_with_spaces():
    item = _item("/movies/300/300 - directors cut.mp4", height=720, size=1024 ** 3)
    assert _version_label(item) == "directors cut"


def test_dash_suffix_hdr():
    # 用户截图里的 case：HDR 10 不应变成 "HDR 10 · 5.7GB"
    item = _item("/movies/钟馗/钟馗 (2026) - HDR 10.mp4", height=2160, size=int(5.67 * 1024 ** 3))
    assert _version_label(item) == "HDR 10"


def test_no_dash_falls_back_to_resolution():
    assert _version_label(_item("/movies/a/a.mkv", height=2160)) == "4K"
    assert _version_label(_item("/movies/a/a.mkv", height=1080)) == "1080p"
    assert _version_label(_item("/movies/a/a.mkv", height=720)) == "720p"
    assert _version_label(_item("/movies/a/a.mkv", height=480)) == "480p"
    assert _version_label(_item("/movies/a/a.mkv", height=0)) == "480p"


def test_no_size_suffix_in_name():
    # 大小走 Versions[].Size 字段，不塞进 Name
    item = _item("/movies/a/a.mkv", height=1080, size=8 * 1024 ** 3)
    label = _version_label(item)
    assert "GB" not in label
    assert "·" not in label


def test_empty_path():
    assert _version_label(_item("", height=1080)) == "1080p"
    assert _version_label(_item(None, height=0)) == "480p"
