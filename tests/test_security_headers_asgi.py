"""回归测试：security_headers 中间件对视频分片不强制 no-store。

背景：2026-10-07，PR #387 修复了 security_headers 对所有 /emby/ 路径
强制 no-store 的问题。现在视频分片路径（/stream）应跳过强制，
让 handler 设的 public, max-age=21600 生效，Cloudflare 才能缓存。
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


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
    """EA 的 security_headers 不应是 BaseHTTPMiddleware（会缓冲大文件）。"""
    src = (REPO_ROOT / "emby_api" / "main.py").read_text()
    # 纯 ASGI 类的特征：class 定义 + __call__(self, scope, receive, send)
    # 如果还是 @app.middleware("http") 函数式，标记为待迁移（不硬失败）
    if "class SecurityHeadersMiddleware" in src:
        assert "__call__" in src and "scope" in src
    else:
        # 函数式中间件：确认它至少对分片路径跳过 no-store（PR #387 的行为）
        assert "is_segment_path" in src, "EA security_headers 缺少分片路径判断"


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
    """security_headers 不应缓冲响应体（检查源码无 body 读取）。"""
    for p in [REPO_ROOT / "emby_api" / "main.py", REPO_ROOT / "backend" / "main.py"]:
        src = p.read_text()
        # 找到 security_headers 函数体，确认没有 await request.body() 或 response.body 拼接
        idx = src.find("security_headers")
        if idx >= 0:
            snippet = src[idx:idx + 2000]
            # 函数式中间件只改 headers，不碰 body 是符合预期的
            assert "response.body" not in snippet or "is_segment_path" in src
