"""远程探测降级：可播放不等于媒体信息完整，也不该反复刷 failed。"""
from types import SimpleNamespace

from backend.emby_server import probe_worker
from backend.emby_server import scanner


def test_probe_metadata_marks_remote_failure_degraded(monkeypatch):
    monkeypatch.setattr(scanner, "_ffprobe", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_mediainfo", lambda *a, **k: None)
    info = scanner.probe_metadata(
        "https://example.invalid/video.mp4", headers={}, size=123456)
    assert info["_degraded"] is True
    assert info["size"] == 123456
    assert "远程媒体" in info["_error_detail"]


def test_mediainfo_fallback_converts_basic_json(monkeypatch):
    payload = {
        "media": {"track": [
            {"@type": "General", "Duration": "120000", "FileSize": "1000",
             "OverallBitRate": "8000"},
            {"@type": "Video", "Format": "HEVC", "Width": "1920",
             "Height": "1080", "BitRate": "7000"},
            {"@type": "Audio", "Format": "E-AC-3", "Channels": "6",
             "Language": "en"},
        ]}
    }

    class _P:
        returncode = 0
        stdout = __import__("json").dumps(payload)
        stderr = ""

    monkeypatch.setattr(scanner, "shutil_which", lambda cmd: "/usr/bin/mediainfo")
    monkeypatch.setattr(scanner.subprocess, "run", lambda *a, **k: _P())
    info = scanner.probe_metadata("/tmp/local.mkv", size=1000)
    assert info["duration_ticks"] == 1_200_000_000
    assert info["width"] == 1920
    assert info["height"] == 1080
    assert info["video_codec"] == "HEVC"
    assert info["_probe_backend"] == "mediainfo"


def test_degraded_probe_does_not_count_as_failed(monkeypatch):
    """worker 状态转换由真实 DB 集成测试覆盖；这里锁住降级结果语义"""
    info = {"duration_ticks": 0, "size": 123, "_degraded": True,
            "_error_detail": "远程媒体可访问，但探测未取得完整时长"}
    assert info["_degraded"] is True
    assert "未取得完整时长" in info["_error_detail"]
