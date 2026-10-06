"""文件名元数据解析：从视频文件名提取分辨率 / 编码 / 来源。

设计原则：**零 Drive 调用**。后台探测器（ffprobe 批量探测）已被证明在
Google Drive 配额下不可行（见 #334 讨论），这里只做纯字符串解析，
不读文件、不调任何外部 API，可在扫描热路径里对每个文件调用。

支持的命名示例：
    Movie.2020.1080p.WEB-DL.x264.mkv
    Show.S01E01.2160p.BluRay.x265.10bit.HDR.DTS.mkv
    drama ep03 720p HDTV aac.mp4
"""

from __future__ import annotations

import re

# 分辨率：按从高到低的顺序匹配，4K/UHD 归一为 2160p
_RESOLUTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"2160p|4k|uhd", re.IGNORECASE), "2160p"),
    (re.compile(r"1080p|1080i|fhd", re.IGNORECASE), "1080p"),
    (re.compile(r"720p", re.IGNORECASE), "720p"),
    (re.compile(r"480p", re.IGNORECASE), "480p"),
]

# 分辨率 -> (宽, 高)
_RESOLUTION_WH: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "2160p": (3840, 2160),
}

# 视频编码：别名 -> 规范名
_VIDEO_CODEC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"x265|h265|hevc", re.IGNORECASE), "H.265"),
    (re.compile(r"x264|h264|avc", re.IGNORECASE), "H.264"),
]

# 音频编码：别名 -> 规范名
_AUDIO_CODEC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"truehd", re.IGNORECASE), "TrueHD"),
    (re.compile(r"dts[\-_ ]?hd|dtshd", re.IGNORECASE), "DTS-HD"),
    (re.compile(r"dts", re.IGNORECASE), "DTS"),
    (re.compile(r"eac3|dd\+", re.IGNORECASE), "E-AC3"),
    (re.compile(r"ac3", re.IGNORECASE), "AC3"),
    (re.compile(r"flac", re.IGNORECASE), "FLAC"),
    (re.compile(r"aac", re.IGNORECASE), "AAC"),
    (re.compile(r"mp3", re.IGNORECASE), "MP3"),
]

# 发行来源：别名 -> 规范名
_SOURCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"web[\-_ ]?dl", re.IGNORECASE), "WEB-DL"),
    (re.compile(r"web[\-_ ]?rip", re.IGNORECASE), "WEBRip"),
    (re.compile(r"blu[\-_ ]?ray|bdrip|bd[\-_ ]?remux", re.IGNORECASE), "BluRay"),
    (re.compile(r"hdtv", re.IGNORECASE), "HDTV"),
    (re.compile(r"dvd[\-_ ]?rip", re.IGNORECASE), "DVDRip"),
]


def _first_match(patterns: list[tuple[re.Pattern, str]], name: str) -> str | None:
    for pat, value in patterns:
        if pat.search(name):
            return value
    return None


def parse_filename(filename: str) -> dict:
    """从文件名解析视频元数据（纯字符串操作，不读文件）。

    Args:
        filename: 文件名（带或不带路径均可，只看 basename）。

    Returns:
        dict，可能包含以下键（解析不到的键直接省略）：
        - resolution: "480p" / "720p" / "1080p" / "2160p"
        - video_codec: "H.264" / "H.265"
        - audio_codec: "AAC" / "DTS" / "AC3" / "FLAC" / "MP3" / ...
        - source: "WEB-DL" / "BluRay" / "HDTV" / "DVDRip" / "WEBRip"
    """
    # 只看文件名本身：路径里的目录名（如 ".../1080p/..."）不可靠
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    result: dict = {}
    resolution = _first_match(_RESOLUTION_PATTERNS, name)
    if resolution:
        result["resolution"] = resolution
    video_codec = _first_match(_VIDEO_CODEC_PATTERNS, name)
    if video_codec:
        result["video_codec"] = video_codec
    audio_codec = _first_match(_AUDIO_CODEC_PATTERNS, name)
    if audio_codec:
        result["audio_codec"] = audio_codec
    source = _first_match(_SOURCE_PATTERNS, name)
    if source:
        result["source"] = source
    return result


def resolution_to_wh(resolution: str | None) -> tuple[int, int]:
    """分辨率字符串 -> (宽, 高)。未知时返回 (0, 0)。"""
    if not resolution:
        return (0, 0)
    return _RESOLUTION_WH.get(resolution.lower(), (0, 0))
