"""本机 / FUSE 探测超时：不再双倍等待

生产实测（2026-10-05）：4 核机器、``/mnt/mp`` 是 fuse.rclone，mediainfo 常驻
D 状态（不可中断 IO）。原实现 ffprobe 90s 超时后还会再跑一次同样 90s 的
MediaInfo 备用探测，单文件最坏 180s，4 个 worker 折算约 1.3 个文件/分钟，
探测积压与补全队列一起被拖住。
"""
import subprocess

import pytest

from backend.emby_server import scanner


class _Result:
    stdout = "{}"
    stderr = ""
    returncode = 0


def test_local_probe_uses_short_timeout(monkeypatch):
    """本机文件（含 FUSE）用短上限，不再等满 90 秒"""
    seen = {}
    monkeypatch.setattr(
        scanner.subprocess, "run",
        lambda cmd, **kw: (seen.update(kw), _Result())[1])
    scanner._ffprobe("/mnt/mp/movie.mkv")
    assert seen["timeout"] == scanner.PROBE_FILE_TIMEOUT
    assert seen["timeout"] < 90, "本机路径不该再等满 90 秒"


def test_remote_probe_keeps_long_timeout(monkeypatch):
    """远端直链维持 90 秒：网络慢是常态，砍时间会误伤真正在下载的大文件"""
    seen = {}
    monkeypatch.setattr(
        scanner.subprocess, "run",
        lambda cmd, **kw: (seen.update(kw), _Result())[1])
    scanner._ffprobe("https://example.com/a.mp4", {"UA": "x"}, size=10)
    assert seen["timeout"] == scanner.PROBE_REMOTE_TIMEOUT


def test_timeout_skips_mediainfo_fallback(monkeypatch, tmp_path):
    """ffprobe 超时 → 不再白等一次同样会超时的 MediaInfo"""
    f = tmp_path / "a.mkv"
    f.write_bytes(b"x")
    calls = []

    def fake_run(cmd, **kw):
        # ffprobe 会被 _io_nice_command 包成 ionice/nice 链，
        # 所以按整条命令里是否含 ffprobe 判断，不能只看 cmd[0]。
        argv = list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)]
        name = next((a for a in argv if a.endswith("ffprobe")), None)
        calls.append("ffprobe" if name else "mediainfo")
        if name:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        class _Empty:
            stdout = "{}"
            stderr = ""
        return _Empty()

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)
    monkeypatch.setattr(scanner, "shutil_which", lambda c: "/usr/bin/mediainfo")

    scanner.probe_metadata(str(f), size=1, container="mkv")

    assert "mediainfo" not in calls, (
        f"ffprobe 已超时，不该再跑一次同样会超时的 MediaInfo：{calls}")


def test_no_timeout_still_tries_mediainfo(monkeypatch, tmp_path):
    """反过来：ffprobe 读完但没数据，仍然要试 MediaInfo（这是它的本职）"""
    f = tmp_path / "b.mkv"
    f.write_bytes(b"x")
    calls = []

    def fake_run(cmd, **kw):
        argv = list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)]
        calls.append("ffprobe" if any(a.endswith("ffprobe") for a in argv) else "mediainfo")
        class _NoFormat:
            stdout = "{}"          # 没有 format → 触发备用探测
            stderr = ""
        return _NoFormat()

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)
    monkeypatch.setattr(scanner, "shutil_which", lambda c: "/usr/bin/mediainfo")

    scanner.probe_metadata(str(f), size=1, container="mkv")

    assert "mediainfo" in calls, "读完了没数据时，MediaInfo 备用探测必须保留"
