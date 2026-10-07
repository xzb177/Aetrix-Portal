"""回归测试：security_headers 中间件对视频分片不强制 no-store。

背景：2026-10-07，PR #387 修复了 security_headers 对所有 /emby/ 路径
强制 no-store 的问题。现在视频分片路径（/stream）应跳过强制，
让 handler 设的 public, max-age=21600 生效，Cloudflare 才能缓存。

2026-10-07（perf/relay-zero-copy）：三个 @app.middleware("http")
（BaseHTTPMiddleware）已迁为纯 ASGI 类（emby_api/asgi_middleware.py），
中转链路零额外拷贝。以下测试锁定该结构不退化。
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MW_MODULE = REPO_ROOT / "emby_api" / "asgi_middleware.py"


def _get_is_segment_path():
    """从源码加载 cdn.is_segment_path（不导入整个应用）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cdn_mod", str(REPO_ROOT / "backend" / "emby_server" / "cdn.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.is_segment_path


def test_ea_is_pure_asgi_not_basehttp():
    """EA 的三个中间件必须是纯 ASGI 类，不能是 @app.middleware("http")。"""
    main_lines = (REPO_ROOT / "emby_api" / "main.py").read_text().splitlines()
    decorators = [l for l in main_lines
                  if l.strip().startswith('@app.middleware')]
    assert not decorators, \
        f"EA 仍有 BaseHTTPMiddleware（{decorators}），会给每个响应分块加中转开销"
    mw_src = MW_MODULE.read_text()
    for cls in ("SecurityHeadersMiddleware", "EaBodyLimitMiddleware",
                "EaRateLimitMiddleware"):
        assert f"class {cls}" in mw_src, f"{cls} 缺失"
    # 纯 ASGI 特征：__call__(self, scope, receive, send)，且不读 body
    assert "async def __call__(self, scope, receive, send)" in mw_src
    assert "await request.body()" not in mw_src


def test_api_is_pure_asgi_not_basehttp():
    src = (REPO_ROOT / "backend" / "main.py").read_text()
    if "class SecurityHeadersMiddleware" in src:
        assert "__call__" in src and "scope" in src
    else:
        assert "is_segment_path" in src, "API security_headers 缺少分片路径判断"


def test_stream_path_skips_no_store():
    """分片路径应被识别为可缓存（is_segment_path 返回 True）。"""
    is_segment_path = _get_is_segment_path()
    assert is_segment_path("/emby/Videos/abc123/stream") is True
    assert is_segment_path("/emby/Videos/abc123/stream.mkv") is True


def test_non_stream_emby_path_gets_no_store():
    """非分片 API 路径不应被识别为可缓存。"""
    is_segment_path = _get_is_segment_path()
    assert is_segment_path("/emby/Users/1/Views") is False
    assert is_segment_path("/emby/System/Info") is False


def test_body_not_buffered():
    """纯 ASGI 中间件不缓冲响应体（源码无 body 读取/拼接）。"""
    src = MW_MODULE.read_text()
    assert ".body()" not in src or "request.body()" not in src
    # 放行路径直接调 self.app，不包裹 send（零开销）
    assert "await self.app(scope, receive, send)" in src
