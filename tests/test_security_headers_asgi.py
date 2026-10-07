"""回归测试：security_headers 必须是纯 ASGI 中间件，不能缓冲响应体。

背景：2026-10-07，@app.middleware("http")（BaseHTTPMiddleware）会缓冲整个
响应体，22GB 大文件 Range 流在 Drive 中断时导致
"RuntimeError: Response content shorter than Content-Length"。
改成纯 ASGI 后只改 http.response.start 的头，不碰 body。
"""
import asyncio


def _make_middleware(mod_path, cls_name="SecurityHeadersMiddleware"):
    import importlib.util
    import sys
    import types

    # 构造一个最小化的 app 桩，避免导入整个 FastAPI 应用
    spec = importlib.util.spec_from_file_location("sh_mod", mod_path)
    mod = importlib.util.module_from_spec(spec)
    # 预置 backend.emby_server.cdn.is_segment_path，避免真实导入
    cdn = types.ModuleType("backend.emby_server.cdn")
    cdn.is_segment_path = lambda p: p.endswith("/stream")
    sys.modules.setdefault("backend", types.ModuleType("backend"))
    sys.modules.setdefault("backend.emby_server", types.ModuleType("backend.emby_server"))
    sys.modules["backend.emby_server.cdn"] = cdn
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # 模块级 FastAPI app 初始化可能失败；直接解析源码找类定义
        return None
    return getattr(mod, cls_name, None)


def _run_asgi(app, path="/emby/Videos/x/stream", body_chunks=(b"a" * 10, b"b" * 10)):
    """跑一遍 ASGI，返回 (response.start headers, body bytes)。"""
    scope = {"type": "http", "path": path, "headers": []}
    messages = []

    async def downstream(s, r, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"video/mp4")],
        })
        for chunk in body_chunks:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        messages.append(msg)

    async def main():
        await app(scope, receive, send)

    asyncio.run(main())
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return dict((k.decode(), v.decode()) for k, v in start["headers"]), body


def _load_cls_from_source(path):
    """从源码提取 SecurityHeadersMiddleware 类并 exec（不导入整个 app）。"""
    import ast
    src = open(path).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SecurityHeadersMiddleware":
            seg = ast.get_source_segment(src, node)
            ns = {}
            exec(seg, ns)
            return ns["SecurityHeadersMiddleware"]
    return None


def test_ea_is_pure_asgi_not_basehttp():
    cls = _load_cls_from_source("/tmp/pr-fix/emby_api/main.py")
    assert cls is not None, "EA 的 SecurityHeadersMiddleware 类不存在"
    # 纯 ASGI：__call__(self, scope, receive, send)，不是 (request, call_next)
    import inspect
    params = list(inspect.signature(cls.__call__).parameters)
    assert params == ["self", "scope", "receive", "send"], f"不是纯 ASGI 签名: {params}"


def test_api_is_pure_asgi_not_basehttp():
    cls = _load_cls_from_source("/tmp/pr-fix/backend/main.py")
    assert cls is not None, "API 的 SecurityHeadersMiddleware 类不存在"
    import inspect
    params = list(inspect.signature(cls.__call__).parameters)
    assert params == ["self", "scope", "receive", "send"], f"不是纯 ASGI 签名: {params}"


def test_stream_path_skips_no_store():
    cls = _load_cls_from_source("/tmp/pr-fix/emby_api/main.py")

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"x" * 100, "more_body": False})

    async def receive():
        return {"type": "http.request"}

    sent = []

    async def send(msg):
        sent.append(msg)

    async def main():
        await cls(downstream)({"type": "http", "path": "/emby/Videos/abc/stream"},
                              receive, send)

    asyncio.run(main())
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = dict((k.decode(), v.decode()) for k, v in start["headers"])
    assert "cache-control" not in headers, f"分片路径不应被强制 no-store: {headers}"
    assert headers.get("x-content-type-options") == "nosniff"


def test_non_stream_emby_path_gets_no_store():
    cls = _load_cls_from_source("/tmp/pr-fix/emby_api/main.py")

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"x", "more_body": False})

    async def receive():
        return {"type": "http.request"}

    sent = []

    async def send(msg):
        sent.append(msg)

    async def main():
        await cls(downstream)({"type": "http", "path": "/emby/Users/1/Items"},
                              receive, send)

    asyncio.run(main())
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = dict((k.decode(), v.decode()) for k, v in start["headers"])
    assert headers.get("cache-control") == "no-store"


def test_body_not_buffered():
    """body 必须原样透传（分多块发送也不能被合并/缓冲）。"""
    cls = _load_cls_from_source("/tmp/pr-fix/emby_api/main.py")
    chunks = [b"chunk1", b"chunk2", b"chunk3"]

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 206, "headers": []})
        for c in chunks:
            await send({"type": "http.response.body", "body": c, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {"type": "http.request"}

    sent = []

    async def send(msg):
        sent.append(msg)

    async def main():
        await cls(downstream)({"type": "http", "path": "/emby/Videos/abc/stream"},
                              receive, send)

    asyncio.run(main())
    bodies = [m for m in sent if m["type"] == "http.response.body"]
    # 纯 ASGI 不应合并 body 块：下游发几块，上游就收到几块（+结束块）
    assert len(bodies) == len(chunks) + 1
    assert b"".join(m.get("body", b"") for m in bodies) == b"".join(chunks)
