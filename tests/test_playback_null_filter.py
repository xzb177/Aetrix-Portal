"""PlaybackInfo DTO 递归 null 过滤测试（P0-3b）。

iOS 客户端（Lenna/SenPlayer）对 null 字段敏感，DTO 里出现 null 会导致
"数据解析错误"。本测试验证 _strip_nulls / _stream_dto / _media_source
的 null 过滤行为。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.emby_server.api import _strip_nulls


def _has_null(obj):
    """递归检查是否还有 None 值"""
    if obj is None:
        return True
    if isinstance(obj, dict):
        return any(_has_null(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_null(v) for v in obj)
    return False


class TestStripNulls:
    def test_removes_top_level_none(self):
        result = _strip_nulls({"a": 1, "b": None, "c": "x"})
        assert result == {"a": 1, "c": "x"}
        assert not _has_null(result)

    def test_removes_nested_none(self):
        result = _strip_nulls({
            "outer": {"inner": None, "keep": 1},
            "list": [{"x": None, "y": 2}, {"z": 3}],
        })
        assert result == {"outer": {"keep": 1}, "list": [{"y": 2}, {"z": 3}]}
        assert not _has_null(result)

    def test_empty_dict_and_list(self):
        assert _strip_nulls({}) == {}
        assert _strip_nulls([]) == []
        assert _strip_nulls({"a": {}}) == {"a": {}}
        assert _strip_nulls({"a": []}) == {"a": []}

    def test_preserves_falsy_non_none(self):
        # 0 / False / "" 不是 None，必须保留
        result = _strip_nulls({"zero": 0, "false": False, "empty": "", "none": None})
        assert result == {"zero": 0, "false": False, "empty": ""}

    def test_preserves_list_none_elements(self):
        # 数组中的 None 元素保留（避免打乱索引语义）
        result = _strip_nulls({"arr": [1, None, 3]})
        assert result == {"arr": [1, None, 3]}

    def test_non_container_passthrough(self):
        assert _strip_nulls(42) == 42
        assert _strip_nulls("x") == "x"
        assert _strip_nulls(None) is None

    def test_deeply_nested_media_source_shape(self):
        # 模拟 MediaSource 结构：含 null 的 MediaStreams
        dto = {
            "Id": "abc",
            "Container": None,
            "Size": None,
            "RunTimeTicks": None,
            "Bitrate": None,
            "DefaultSubtitleStreamIndex": None,
            "MediaStreams": [
                {
                    "Index": 0, "Type": "Video", "Codec": "h264",
                    "Language": None, "Title": None,
                    "Channels": None, "BitRate": None,
                    "IsDefault": True,
                },
                {
                    "Index": 1, "Type": "Subtitle", "Codec": None,
                    "Language": "chi", "Title": None,
                    "IsDefault": False,
                },
            ],
        }
        result = _strip_nulls(dto)
        assert not _has_null(result)
        # 关键字段保留
        assert result["Id"] == "abc"
        assert len(result["MediaStreams"]) == 2
        assert result["MediaStreams"][0]["Codec"] == "h264"
        assert result["MediaStreams"][1]["Language"] == "chi"
        # null 字段被去掉
        assert "Container" not in result
        assert "Language" not in result["MediaStreams"][0]

    def test_playback_info_shape(self):
        # 模拟 PlaybackInfo 响应：ErrorCode 为 None 必须被去掉
        dto = {
            "MediaSources": [{"Id": "x", "Path": None}],
            "PlaySessionId": "deadbeef",
            "ErrorCode": None,
        }
        result = _strip_nulls(dto)
        assert not _has_null(result)
        assert "ErrorCode" not in result
        assert result["PlaySessionId"] == "deadbeef"
