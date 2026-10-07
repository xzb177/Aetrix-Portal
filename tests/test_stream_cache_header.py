"""Regression: security_headers middleware must not force no-store on video segment paths.

Background: Cloudflare Cache Rules were configured for /emby/Videos/*/stream*,
but origin returned `Cache-Control: no-store` (set by security_headers middleware
for all /emby/ paths), causing `cf-cache-status: BYPASS`.

Fix: middleware skips the forced no-store when cdn.is_segment_path(path) is True.
"""
from backend.emby_server.cdn import is_segment_path


def _middleware_would_set_nostore(path: str) -> bool:
    """Mirror the middleware decision logic (kept in sync with emby_api/main.py
    and backend/main.py security_headers)."""
    if path.startswith("/emby/"):
        if not is_segment_path(path):
            return True
    return False


def test_stream_path_not_forced_nostore():
    # direct stream: cacheable, middleware must NOT force no-store
    assert _middleware_would_set_nostore("/emby/Videos/abc123/stream") is False
    assert _middleware_would_set_nostore("/emby/Videos/abc123/stream?static=true") is False
    assert _middleware_would_set_nostore("/emby/videos/x/stream.mkv") is False


def test_hls_segment_not_forced_nostore():
    assert _middleware_would_set_nostore("/emby/videos/abc/1.ts") is False
    assert _middleware_would_set_nostore("/emby/videos/abc/seg.m4s?session=x") is False


def test_api_path_still_nostore():
    # API / playlist paths: must still get no-store
    assert _middleware_would_set_nostore("/emby/Users/abc") is True
    assert _middleware_would_set_nostore("/emby/videos/x/main.m3u8") is True
    assert _middleware_would_set_nostore("/emby/Items") is True


def test_middleware_source_contains_guard():
    # lock the fix in place: both entry points must consult is_segment_path
    for rel in ("emby_api/main.py", "backend/main.py"):
        with open(rel) as f:
            src = f.read()
        assert "is_segment_path" in src, f"{rel} missing is_segment_path guard"
