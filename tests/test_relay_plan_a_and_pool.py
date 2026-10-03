"""方案 A + 中转连接复用 回归测试

**方案 A**：file id 来自「路径 → id」缓存（秒开那套）时，不能再盲 302。
302 之后字节不经本机，服务器永远看不到那个 404，自愈就不会触发，而缓存也不
会被清——于是每次重试都是同一个死地址，客户端永远转圈。所以缓存来的 id 一律
改走代理：代理路径带 404 重试，失效时能自动重解析并把新 id 写回。

**连接复用**：代理客户端改成进程内共享，每个 Range 请求不再重做 TCP+TLS 握手。
要钉住两件容易做错的事：共享的 client **绝不能**被单个请求关掉（会把其它并发
请求一起炸掉），以及连接上限是定住的（否则人一多就把源站连接打满）。

不碰网络、不碰生产库。
"""
import asyncio
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest

from backend.emby_server import streaming
from backend.emby_server import mounts as mount_lib


def _run(coro):
    return asyncio.run(coro)


# ==================== 方案 A：标记本身 ====================


def test_play_target_default_is_not_from_cache():
    """所有既有提供者与既有构造行为不变：默认就是 False（照旧 302）"""
    t = mount_lib.PlayTarget("url", "https://x/f.mp4")
    assert t.from_file_id_cache is False


def test_play_target_flag_does_not_break_existing_construction():
    """老的三参构造逐字不变（direct 仍是可选第四参）"""
    t = mount_lib.PlayTarget("url", "https://x/f.mp4", {"Authorization": "Bearer t"},
                             "https://x/direct")
    assert t.value == "https://x/f.mp4"
    assert t.direct == "https://x/direct"
    assert t.from_file_id_cache is False


@pytest.fixture()
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend import models as web_models
    from backend.emby_server import models as em

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    web_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_gdrive_marks_cache_hits():
    """缓存命中的 resolve 必须打上标记，缓存未命中则不打"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend import models as web_models
    from backend.emby_server import file_id_cache as fic
    from backend.emby_server import models as em
    from backend.emby_server import mount_google
    import time

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    web_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    m = object.__new__(mount_google.GoogleDriveMount)
    m.db = session
    m.mount = type("M", (), {"id": 7})()
    m.api_base = "https://example.invalid/drive/v3"
    m.auth_mode = "oauth"
    m.direct_link = True                      # 配置项保留（已下线，不影响行为）
    m.root_id = ""
    m.drive_id = ""
    m.sa_file = ""
    m.client_id = ""
    m.client_secret = ""
    m.refresh_token = ""
    m._token_value = "tok"
    m._token_exp = time.time() + 3600
    m._drive_root = "root"
    m.config = {}
    m.library = None
    m._headers = lambda: {"Authorization": "Bearer tok"}
    m._locate = lambda rel: {"id": "REAL-FID", "size": 1}

    # 第一次：未命中缓存 → 现解析 → 不打标记
    first = m.resolve("/m/a.mkv")
    assert first.from_file_id_cache is False
    assert first.direct is None  # 302 直链下线，不再给直链

    session.commit()
    assert fic.lookup(session, 7, "/m/a.mkv") == "REAL-FID"

    # 第二次：命中缓存 → 打标记（播放层不再盲 302，两种情况都走代理）
    second = m.resolve("/m/a.mkv")
    assert second.from_file_id_cache is True
    session.close()


# ==================== 方案 A：播放层不改走 302 ====================


def _stream_target(**kw):
    t = mount_lib.PlayTarget("url", "https://src/f.mp4", {"Authorization": "Bearer t"})
    for k, v in kw.items():
        setattr(t, k, v)
    return t


def _req():
    from starlette.requests import Request

    return Request({
        "type": "http", "method": "GET", "path": "/videos/1/stream",
        "raw_path": b"/videos/1/stream", "query_string": b"", "root_path": "",
        "headers": [], "scheme": "http", "server": ("testserver", 80),
        "client": ("1.2.3.4", 5000),
    })


def test_cache_derived_target_still_self_heals_through_proxy(session):
    """方案 A 的落点：缓存来的 id 走代理 → 404 时自愈（与 PR #289 同一条路径）

    前提是真的有**一条缓存行**可删 —— ``invalidate`` 删不到东西就不重试，
    因为那意味着 id 是现解析的、404 是文件真没了。
    """
    from fastapi import HTTPException

    from backend.emby_server import api, file_id_cache as fic

    fic.store(session, 7, "/m/a.mkv", "STALE-FID")
    session.commit()

    seen = []

    async def _serve(url, request, headers=None, media_type="video/mp4", cache_control=None):
        seen.append(url)
        if len(seen) == 1:
            raise HTTPException(status_code=404, detail="源站返回 404")
        return "ok"

    monkey = api.serve_remote_async
    api.serve_remote_async = _serve

    def _resolve(db, item):
        # 真实的重解析会拿到新 id 并写回缓存；这里只验证「重试发生了且缓存被清」
        return _stream_target(value="https://src/FRESH")

    monkey_resolve = api._play_target
    api._play_target = _resolve
    try:
        target = _stream_target(from_file_id_cache=True)
        item = type("I", (), {"file_path": "mount://7/m/a.mkv", "library": None})()
        out = _run(api._serve_remote_retry_on_stale(target, _req(), session, item,
                                                    "video/mp4", None))
        assert out == "ok", "缓存来的 id 走代理后必须能自愈"
        assert seen == ["https://src/f.mp4", "https://src/FRESH"], seen
        session.commit()
        assert fic.lookup(session, 7, "/m/a.mkv") == "", "自愈后旧的那条应被清掉"
    finally:
        api.serve_remote_async = monkey
        api._play_target = monkey_resolve


def test_can_redirect_direct_still_blocks_gdrive_targets():
    """带 Authorization 头的目标（gdrive 原生挂载）本来就不允许裸 302 到无凭据地址"""
    assert streaming.can_redirect_direct(_stream_target()) is False
    assert streaming.can_redirect_direct(_stream_target(direct="https://x")) is False


# ==================== 连接复用 ====================


def test_relay_client_is_shared_across_calls():
    c1 = streaming.get_relay_client()
    c2 = streaming.get_relay_client()
    assert c1 is c2, "每次请求都新建 client 就等于没做连接复用"
    _run(streaming.close_relay_client())


def test_close_relay_client_resets_and_allows_rebuild():
    first = streaming.get_relay_client()
    _run(streaming.close_relay_client())
    second = streaming.get_relay_client()
    assert second is not first
    _run(streaming.close_relay_client())


def test_close_relay_client_is_safe_when_never_created():
    """没建过就关：不能抛（进程退出 / 测试收尾会无条件调它）"""
    _run(streaming.close_relay_client())
    _run(streaming.close_relay_client())


def test_relay_pool_has_bounded_connections():
    """连接数必须定住：不限的话人一多就把源站连接打满，首字节反而更慢"""
    client = streaming.get_relay_client()
    limits = client._transport._pool._max_connections
    assert limits == streaming._RELAY_MAX_CONNECTIONS
    assert limits < 10_000, "等于没设上限"
    _run(streaming.close_relay_client())


def test_relay_pool_limits_are_sane():
    assert streaming._RELAY_MAX_CONNECTIONS >= streaming._RELAY_MAX_KEEPALIVE >= 2


def test_app_shutdown_closes_the_relay_client():
    """关闭时必须把共享连接池关掉

    不关的后果有两个：httpx 报未关闭的客户端；更实际的是它**绑定在创建它的事件
    循环上**，进程重启 / reload 后复用会直接报错。
    """
    import inspect

    from backend.main import lifespan

    src = inspect.getsource(lifespan)
    assert "close_relay_client" in src, "lifespan 关闭段没有关连接池"


def test_serve_remote_async_never_closes_the_shared_client():
    """**最危险的一条**：单个请求把共享 client 关掉，会把其它并发请求一起炸掉"""
    from fastapi import HTTPException

    from starlette.responses import StreamingResponse

    closed = []

    class _Resp:
        status_code = 200
        headers = {"content-type": "video/mp4"}

        async def aiter_bytes(self, n):
            yield b"x"

        async def aclose(self):
            closed.append("resp")

    class _SharedClient:
        """看着像共享 client；被关就会记账"""

        def __init__(self):
            self.closed = False

        def build_request(self, method, url, headers=None):
            class _R:
                pass
            r = _R()
            r.method, r.url, r.headers = method, url, headers or {}
            return r

        async def send(self, req, stream=False):
            return _Resp()

        async def aclose(self):
            self.closed = True

    fake = _SharedClient()
    monkey = streaming.get_relay_client
    streaming.get_relay_client = lambda: fake
    try:
        resp = _run(streaming.serve_remote_async(
            "https://src/f.mp4", _req(), {"Authorization": "Bearer t"}, "video/mp4"))
        assert isinstance(resp, StreamingResponse)
        # 把流读完触发 finally
        _run(_drain(resp))
        assert fake.closed is False, "请求结束时把共享 client 关了"
        assert closed == ["resp"], "只应关响应"
    finally:
        streaming.get_relay_client = monkey


def test_serve_remote_async_error_path_does_not_close_shared_client():
    """错误路径（重定向过多 / 源站 4xx / 不可达）同样不能关共享 client"""
    from fastapi import HTTPException

    class _Resp:
        status_code = 404
        headers = {}

        async def aclose(self):
            pass

    class _SharedClient:
        def __init__(self):
            self.closed = False

        def build_request(self, method, url, headers=None):
            class _R:
                pass
            r = _R()
            r.method, r.url, r.headers = method, url, headers or {}
            return r

        async def send(self, req, stream=False):
            return _Resp()

        async def aclose(self):
            self.closed = True

    fake = _SharedClient()
    monkey = streaming.get_relay_client
    streaming.get_relay_client = lambda: fake
    try:
        with pytest.raises(HTTPException):
            _run(streaming.serve_remote_async(
                "https://src/f.mp4", _req(), {"Authorization": "Bearer t"}, "video/mp4"))
        assert fake.closed is False, "错误路径把共享 client 关了"
    finally:
        streaming.get_relay_client = monkey


async def _drain(resp):
    async for _ in resp.body_iterator:
        pass