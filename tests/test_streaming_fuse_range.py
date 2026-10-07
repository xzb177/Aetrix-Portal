"""Regression: FUSE Range 响应不能预先声明 Content-Length。

背景：rclone FUSE 挂载（/mnt/mp、/mnt/paul）的读可能因 Drive 配额/网络抖动
中途失败。旧实现里 serve_file 对 Range 响应按 os.path.getsize() 声明
Content-Length，读失败提前结束时 uvicorn 抛
"Response content shorter than Content-Length"，播放器报加载失败。

修复：FUSE 路径的 Range 响应不声明 Content-Length（走 chunked），读失败时
优雅截断；OSError 做有限退避重试。本地磁盘路径保持原行为。
"""
import asyncio
import os
import tempfile

from fastapi import Request

from backend.emby_server import streaming
from backend.emby_server.streaming import is_fuse_path, serve_file


def _collect(resp):
    async def _go():
        out = b""
        async for chunk in resp.body_iterator:
            out += chunk
        return out

    return asyncio.run(_go())


def _req(range_header=None):
    headers = []
    if range_header:
        headers.append((b"range", range_header.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/emby/Videos/x/stream",
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 54321),
    }
    return Request(scope)


def _tmpfile(size, fuse=False):
    if fuse:
        d = "/tmp/fake_mnt_mp"
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "v.mkv")
    else:
        fd, p = tempfile.mkstemp(suffix=".mkv")
        os.close(fd)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


def test_is_fuse_path():
    assert is_fuse_path("/mnt/mp/nastool/a.mkv")
    assert is_fuse_path("/mnt/paul/video/b.mkv")
    assert not is_fuse_path("/data/images/c.jpg")
    assert not is_fuse_path("")
    assert not is_fuse_path("/mnt/other/d.mkv")


def test_fuse_range_no_content_length(monkeypatch):
    """FUSE 路径 Range 响应：无 Content-Length，有 Content-Range（206 必需）。"""
    monkeypatch.setattr(streaming, "FUSE_PREFIXES", ("/tmp/fake_mnt_mp/",))
    p = _tmpfile(1024 * 1024, fuse=True)
    try:
        resp = serve_file(p, _req("bytes=0-999"))
        assert resp.status_code == 206
        assert "content-length" not in {k.lower() for k in resp.headers}
        assert resp.headers["Content-Range"] == "bytes 0-999/1048576"
        body = _collect(resp)
        assert len(body) == 1000
    finally:
        os.unlink(p)


def test_local_range_keeps_content_length():
    """本地磁盘路径：保持原行为，声明 Content-Length。"""
    p = _tmpfile(1024 * 1024, fuse=False)
    try:
        resp = serve_file(p, _req("bytes=0-999"))
        assert resp.status_code == 206
        assert resp.headers["Content-Length"] == "1000"
        assert resp.headers["Content-Range"] == "bytes 0-999/1048576"
    finally:
        os.unlink(p)


def test_fuse_mid_read_failure_truncates_gracefully(monkeypatch):
    """模拟 rclone 中途失败（读返回空）：生成器优雅结束，不抛异常。

    关键：因为没声明 Content-Length，这种截断不会触发 uvicorn 的
    "Response content shorter than Content-Length"。
    """
    monkeypatch.setattr(streaming, "FUSE_PREFIXES", ("/tmp/fake_mnt_mp/",))
    p = _tmpfile(1024 * 1024, fuse=True)

    real_open = open

    class FlakyFile:
        """读满 2 个 CHUNK 后返回空，模拟 Drive 403 后 rclone 放弃。"""

        def __init__(self, *a, **k):
            self._f = real_open(*a, **k)
            self._reads = 0

        def seek(self, *a, **k):
            return self._f.seek(*a, **k)

        def read(self, n=-1):
            self._reads += 1
            if self._reads > 2:
                return b""
            return self._f.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._f.__exit__(*a)

    monkeypatch.setattr("builtins.open", FlakyFile)
    try:
        resp = serve_file(p, _req("bytes=0-1048575"))
        assert "content-length" not in {k.lower() for k in resp.headers}
        # 生成器必须正常结束（不抛），即使字节不足
        body = _collect(resp)
        assert 0 < len(body) < 1048576
    finally:
        monkeypatch.undo()
        os.unlink(p)


def test_fuse_oserror_retries_then_gives_up(monkeypatch):
    """OSError 抖动：重试指定次数后放弃，不无限卡死。"""
    monkeypatch.setattr(streaming, "FUSE_PREFIXES", ("/tmp/fake_mnt_mp/",))
    monkeypatch.setattr(streaming, "_FUSE_READ_RETRIES", 2)
    monkeypatch.setattr(streaming, "_FUSE_READ_RETRY_DELAY", 0.001)
    p = _tmpfile(1024, fuse=True)

    real_open = open

    class AlwaysFailFile:
        def __init__(self, *a, **k):
            self._f = real_open(*a, **k)

        def seek(self, *a, **k):
            return self._f.seek(*a, **k)

        def read(self, n=-1):
            raise OSError("simulated FUSE hiccup")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._f.__exit__(*a)

    monkeypatch.setattr("builtins.open", AlwaysFailFile)
    try:
        resp = serve_file(p, _req("bytes=0-1023"))
        body = _collect(resp)
        assert body == b""
    finally:
        monkeypatch.undo()
        os.unlink(p)
