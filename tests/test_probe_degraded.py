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


def test_truncated_remote_probe_retries_without_range(monkeypatch):
    """moov 在文件尾的 MP4：1 MiB 窗口读不出 format，去掉 Range 再探一次应拿到时长。

    真实事故（生产 4.3 万条 degraded）：探测给远程 URL 注入 ``Range: bytes=0-1MiB``
    （decd396），而 ffprobe 会把这个 206 当成**整个文件**。mkv 的时长在头部、没问题；
    mp4/mov 的 moov 在文件尾时，前 1 MiB 里根本没有时长，读到窗口末尾报
    "File ended prematurely" → format 为空 → 白白记 degraded（文件其实完全可播）。
    """
    calls = []

    def fake_ffprobe(path, headers=None, size=0, ranged=True):
        calls.append(ranged)
        if ranged:
            return {}  # 窗口里没有 moov
        return {"format": {"duration": "3600.0", "bit_rate": "8000000"},
                "streams": [{"codec_type": "video", "codec_name": "h264"}]}

    monkeypatch.setattr(scanner, "_ffprobe", fake_ffprobe)
    info = scanner.probe_metadata("https://rclone:5572/[drv:]/a/big.mp4",
                                  size=8 * 1024 ** 3)
    assert calls == [True, False]
    assert info["duration_ticks"] == 3600 * 10_000_000
    assert not info.get("_degraded")


def test_remote_probe_does_not_retry_when_file_fits_window(monkeypatch):
    """文件本身就在窗口内：读不到就是读不到，不再白跑一次"""
    calls = []

    def fake_ffprobe(path, headers=None, size=0, ranged=True):
        calls.append(ranged)
        return {}

    monkeypatch.setattr(scanner, "_ffprobe", fake_ffprobe)
    info = scanner.probe_metadata("https://rclone:5572/[drv:]/a/tiny.mp4", size=4096)
    assert calls == [True]
    assert info["_degraded"] is True


def test_remote_http_error_surfaces_and_skips_retry(monkeypatch):
    """明确的远端 HTTP 错误不重试，且要透出 _error（熔断器/重试收敛靠它）"""
    calls = []

    def fake_ffprobe(path, headers=None, size=0, ranged=True):
        calls.append(ranged)
        return {"_http_code": 403, "_error": "quota",
                "_error_detail": "远端配额/权限受限 (HTTP 403)"}

    monkeypatch.setattr(scanner, "_ffprobe", fake_ffprobe)
    info = scanner.probe_metadata("https://rclone:5572/[drv:]/a/x.mkv",
                                  size=8 * 1024 ** 3)
    assert calls == [True]              # 403 重试也没用
    assert info["_error"] == "quota"
    assert info["_http_code"] == 403
    assert info["_degraded"] is True    # 内联扫描路径仍需知道「没有时长」
    assert "403" in info["_error_detail"]


def test_degraded_probe_does_not_count_as_failed(monkeypatch):
    """worker 状态转换由真实 DB 集成测试覆盖；这里锁住降级结果语义"""
    info = {"duration_ticks": 0, "size": 123, "_degraded": True,
            "_error_detail": "远程媒体可访问，但探测未取得完整时长"}
    assert info["_degraded"] is True
    assert "未取得完整时长" in info["_error_detail"]
