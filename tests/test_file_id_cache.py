"""挂载「路径 → 上游 file id」持久化缓存（播放秒开）回归测试

这个功能的价值全在一件事上：**同一个文件第二次播放时，一次上游 API 都不调**。
所以这里把它当成契约钉住，每条都对应一个「做错了用户仍然要等 1~2 秒」的事故：

1. **命中即零请求**：缓存有 file id 时，``resolve`` 不得碰 Drive（否则秒开没了）。
2. **只缓存 file id，不缓存凭据**：``access_token`` 必须每次现取——落库等于把凭据
   写进磁盘，而且它跟着服务账号轮换池走，存下来必然对不上。
3. **路径归一**：``/a/b`` 与 ``a/b/`` 必须算同一个键，否则缓存存了也永远不命中
   （这类 bug 最难查：看着有数据，命中率恒为 0）。
4. **懒失效**：文件被移动/删除后缓存里的 id 会失效，播放拿到 404 要能自愈并写回新 id。
   但**没有缓存行时不该重试**——那说明 id 是现解析的，404 就是文件真没了。
5. **缓存坏了不能连累播放**：没有 db 会话、查询抛异常，一律降级成「实时解析」。

全部用隔离的内存 SQLite 与桩，不碰网络、不碰生产库。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models as web_models
from backend.emby_server import file_id_cache as fic
from backend.emby_server import models as em


@pytest.fixture()
def db():
    # StaticPool + check_same_thread=False：播放路径的 ``run_db`` 会把同步函数丢进
    # 线程池，而内存 SQLite 默认**每个连接一个独立的库** —— 不锁成单连接的话，
    # 线程里那条连接根本看不到本测试建的表（no such table）。
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    web_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _rows(db):
    return db.query(em.MountFileIdCache).all()


# ==================== 键：归一与区分 ====================


@pytest.mark.parametrize("a,b", [
    ("/a/b", "a/b"),
    ("a/b/", "/a/b"),
    ("/a/b", "  /a/b  "),
])
def test_path_hash_normalizes_equivalent_paths(a, b):
    """路径写法不同但指向同一个文件 —— 必须命中同一条缓存"""
    assert fic.path_hash(1, a) == fic.path_hash(1, b)


def test_path_hash_differs_by_mount():
    assert fic.path_hash(1, "/a") != fic.path_hash(2, "/a")


def test_path_hash_differs_by_path():
    assert fic.path_hash(1, "/a") != fic.path_hash(1, "/b")


def test_path_hash_cannot_be_confused_by_separator():
    """挂载 ID 与路径之间用 \\x00 分隔，构造不出 (1,"/a") == (11,"a") 这类歧义"""
    assert fic.path_hash(1, "/a") != fic.path_hash(11, "a")


def test_rel_path_is_stored_normalized(db):
    fic.store(db, 1, "a/b/", "FID")
    assert _rows(db)[0].rel_path == "/a/b"


# ==================== 基本读写 ====================


def test_miss_returns_empty(db):
    assert fic.lookup(db, 1, "/nope.mkv") == ""


def test_store_then_lookup(db):
    assert fic.store(db, 1, "/m/a.mkv", "FID-1", 123) is True
    assert fic.lookup(db, 1, "/m/a.mkv") == "FID-1"


def test_lookup_works_regardless_of_path_spelling(db):
    """存的时候写成 ``m/a.mkv``，取的时候写 ``/m/a.mkv`` —— 播放路径的拼法本来就不统一"""
    fic.store(db, 1, "m/a.mkv", "FID-1")
    assert fic.lookup(db, 1, "/m/a.mkv") == "FID-1"


def test_repeat_store_updates_in_place(db):
    """同一路径解析出不同 id（文件被移走又换了新 id）→ 就地更新，不堆重复行"""
    fic.store(db, 1, "/a.mkv", "OLD")
    fic.store(db, 1, "/a.mkv", "NEW")
    db.commit()
    assert len(_rows(db)) == 1
    assert fic.lookup(db, 1, "/a.mkv") == "NEW"


def test_lookup_counts_hits_and_updates_last_used(db):
    fic.store(db, 1, "/a.mkv", "FID")
    db.commit()
    before = _rows(db)[0].last_used_at
    fic.lookup(db, 1, "/a.mkv")
    db.commit()
    row = _rows(db)[0]
    assert row.hits == 1
    assert row.last_used_at >= before


def test_store_ignores_empty_file_id(db):
    assert fic.store(db, 1, "/a.mkv", "") is False
    assert _rows(db) == []


# ==================== 失效 ====================


def test_invalidate_removes_the_row(db):
    fic.store(db, 1, "/a.mkv", "FID")
    db.commit()
    assert fic.invalidate(db, 1, "/a.mkv") == 1
    db.commit()
    assert _rows(db) == []


def test_invalidate_returns_zero_when_nothing_cached(db):
    """没有缓存行 = 这次的 id 是现解析出来的 → 上层据此判定「重试没意义」"""
    assert fic.invalidate(db, 1, "/not-cached.mkv") == 0


def test_invalidate_only_touches_one_mount(db):
    fic.store(db, 1, "/a.mkv", "F1")
    fic.store(db, 2, "/a.mkv", "F2")
    db.commit()
    fic.invalidate(db, 1, "/a.mkv")
    db.commit()
    assert [r.file_id for r in _rows(db)] == ["F2"]


def test_invalidate_all_for_mount(db):
    fic.store(db, 1, "/a.mkv", "F1")
    fic.store(db, 1, "/b.mkv", "F1b")
    fic.store(db, 2, "/a.mkv", "F2")
    db.commit()
    assert fic.invalidate_all_for_mount(db, 1) == 2
    db.commit()
    assert [r.mount_id for r in _rows(db)] == [2]


# ==================== 只存 file id，不存凭据 ====================


def test_no_token_anywhere_in_the_cache(db, monkeypatch):
    """**核心安全约束**：缓存里绝不能出现 access_token

    故意让取 token 的桩返回一个可辨识的串，然后确认整张表里没有它。
    """
    secret = "ya29.SECRET-TOKEN-VALUE"  # secret-scan: allow 假的测试探针，用来证明它没被缓存
    monkeypatch.setattr(
        "backend.emby_server.mount_google.GoogleDriveMount._token",
        lambda self: (secret, __import__("time").time() + 3600),
    )
    from backend.emby_server import mount_google

    class _Resp:
        status_code = 200

        def json(self):
            return {}

    mount = object.__new__(mount_google.GoogleDriveMount)
    mount.db = db
    mount.mount = type("M", (), {"id": 7})()
    mount.api_base = "https://example.invalid/drive/v3"
    mount.auth_mode = "oauth"
    mount.root_id = ""
    mount.drive_id = ""
    mount.sa_file = ""
    mount.client_id = ""
    mount.client_secret = ""
    mount.refresh_token = ""
    mount._token_value = ""
    mount._token_exp = 0.0
    mount._drive_root = "root"
    mount.config = {}
    mount.library = None
    mount._headers = lambda: {"Authorization": f"Bearer {secret}"}
    mount._locate = lambda rel: {"id": "FID", "size": 10}

    target = mount.resolve("/m/a.mkv")
    db.commit()

    assert secret in target.headers["Authorization"]      # token 确实取了
    row = _rows(db)[0]
    assert row.file_id == "FID"                            # 缓存里只有 id
    for column in ("file_id", "rel_path", "size"):
        assert secret not in str(getattr(row, column)), column


# ==================== 缓存不可用时必须降级，而不是报错 ====================


def test_lookup_without_db_returns_empty():
    assert fic.lookup(None, 1, "/a.mkv") == ""


def test_store_without_db_returns_false():
    assert fic.store(None, 1, "/a.mkv", "FID") is False


def test_lookup_survives_broken_session(db, monkeypatch):
    """查询抛异常时返回空串 → 调用方走实时解析，绝不能连累播放"""
    def _boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "query", _boom)
    assert fic.lookup(db, 1, "/a.mkv") == ""


def test_store_survives_broken_session(db, monkeypatch):
    monkeypatch.setattr(db, "query", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x")))
    assert fic.store(db, 1, "/a.mkv", "FID") is False


# ==================== 清理与观测 ====================


def test_prune_removes_only_stale_rows(db):
    from datetime import datetime, timedelta

    fic.store(db, 1, "/old.mkv", "F1")
    fic.store(db, 1, "/new.mkv", "F2")
    db.commit()
    stale = _rows(db)[0]
    stale.last_used_at = datetime.now() - timedelta(days=fic.RETENTION_DAYS + 10)
    db.commit()
    assert fic.prune(db) == 1
    assert [r.rel_path for r in _rows(db)] == ["/new.mkv"]


def test_prune_zero_days_is_noop(db):
    fic.store(db, 1, "/a.mkv", "F1")
    db.commit()
    assert fic.prune(db, 0) == 0
    assert len(_rows(db)) == 1


def test_stats_reports_hit_rate(db):
    fic.store(db, 1, "/a.mkv", "F1")
    db.commit()
    fic.lookup(db, 1, "/a.mkv")
    s = fic.stats(db)
    assert s["rows"] == 1
    assert s["hit"] >= 1
    assert s["miss"] >= 1
    assert 0 < s["hit_rate"] <= 1


# ==================== 端到端：命中时零 Drive 请求 ====================


def _gdrive(db, *, hit_cache: bool):
    """造一个 gdrive provider，桩掉一切网络调用，并记录它被调了几次"""
    from backend.emby_server import mount_google

    calls = []

    mount = object.__new__(mount_google.GoogleDriveMount)
    mount.db = db
    mount.mount = type("M", (), {"id": 7})()
    mount.api_base = "https://example.invalid/drive/v3"
    mount.auth_mode = "oauth"
    mount.root_id = ""
    mount.drive_id = ""
    mount.sa_file = ""
    mount.client_id = ""
    mount.client_secret = ""
    mount.refresh_token = ""
    mount._token_value = "tok"
    mount._token_exp = __import__("time").time() + 3600
    mount._drive_root = "root"
    mount.config = {}
    mount.library = None

    def _locate(rel):
        calls.append(rel)
        return {"id": "REAL-FID", "size": 42}

    mount._locate = _locate
    mount._headers = lambda: {"Authorization": "Bearer tok"}
    return mount, calls


def test_first_resolve_resolves_and_caches(db):
    mount, calls = _gdrive(db, hit_cache=False)
    target = mount.resolve("/m/a.mkv")
    db.commit()
    assert calls == ["/m/a.mkv"]                      # 第一次要真解析
    assert "REAL-FID" in target.value
    assert fic.lookup(db, 7, "/m/a.mkv") == "REAL-FID"  # 并已落库


def test_second_resolve_hits_cache_with_zero_drive_calls(db):
    """**这就是秒开的那一条**：第二次播放一次 Drive 都不调"""
    mount, calls = _gdrive(db, hit_cache=False)
    mount.resolve("/m/a.mkv")
    db.commit()
    calls.clear()

    target = mount.resolve("/m/a.mkv")
    assert calls == [], f"命中缓存时不该再解析路径，实际调了 {calls}"
    assert "REAL-FID" in target.value


def test_cache_hit_still_refreshes_token(db):
    """命中缓存不代表跳过取 token——凭据每次现取，绝不从缓存里读

    真正要钉住的是「``_headers()``（内部就是 ``_token()``）在命中缓存时**依然被调用**」。
    只断言最终 header 的值没用——那是桩给的值，证明不了「有没有现取」。
    """
    mount, calls = _gdrive(db, hit_cache=False)
    mount.resolve("/m/a.mkv")
    db.commit()
    calls.clear()

    header_calls = []
    mount._headers = lambda: (header_calls.append(1),
                              {"Authorization": f"Bearer tok-{len(header_calls)}"})[1]
    target = mount.resolve("/m/a.mkv")

    assert calls == [], "命中缓存时不该再走 Drive 目录解析"
    assert len(header_calls) == 1, "命中缓存时也必须现取一次凭据"
    assert target.headers["Authorization"] == "Bearer tok-1"


# ==================== 懒失效：上游 404 时自愈 ====================


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _req():
    from starlette.requests import Request

    return Request({
        "type": "http", "method": "GET", "path": "/videos/1/stream",
        "raw_path": b"/videos/1/stream", "query_string": b"", "root_path": "",
        "headers": [], "scheme": "http", "server": ("testserver", 80),
        "client": ("1.2.3.4", 5000),
    })


class _Target:
    def __init__(self, value="https://src/file"):
        self.kind = "url"
        self.value = value
        self.headers = {"Authorization": "Bearer t"}


def _item(path):
    return type("Item", (), {"file_path": path})()


def _patch_serve(monkeypatch, statuses):
    """按调用顺序返回状态码；记录每次尝试的 url"""
    seen = []
    box = list(statuses)

    async def _serve(url, request, headers=None, media_type="video/mp4",
                     cache_control=None):
        seen.append(url)
        from fastapi import HTTPException

        code = box.pop(0) if box else 200
        if code >= 400:
            raise HTTPException(status_code=code, detail=f"源站返回 {code}")
        return f"ok:{url}"

    monkeypatch.setattr("backend.emby_server.api.serve_remote_async", _serve)
    return seen


def _patch_resolve(monkeypatch, value="https://src/FRESH"):
    calls = []

    def _resolve(db, item):
        calls.append(item.file_path)
        return _Target(value)

    monkeypatch.setattr("backend.emby_server.api._play_target", _resolve)
    return calls


def test_stale_cache_404_triggers_reparse_and_retry(db, monkeypatch):
    """缓存里的 id 失效（文件被移动/删除）→ 清缓存、重解析、重试一次并成功"""
    from fastapi import HTTPException

    from backend.emby_server import api

    fic.store(db, 7, "/m/a.mkv", "STALE-FID")
    db.commit()
    seen = _patch_serve(monkeypatch, [404, 200])
    resolved = _patch_resolve(monkeypatch, "https://src/FRESH")

    out = _run(api._serve_remote_retry_on_stale(
        _Target("https://src/STALE"), _req(), db, _item("mount://7/m/a.mkv"), "video/mp4", None,
    ))
    assert out == "ok:https://src/FRESH"          # 重试拿到的是新地址
    assert seen == ["https://src/STALE", "https://src/FRESH"]
    assert resolved == ["mount://7/m/a.mkv"]       # 确实重新解析了一次
    db.commit()
    assert _rows(db) == []                        # 旧的那条已被清掉


def test_404_without_cache_row_does_not_retry(db, monkeypatch):
    """没有缓存行 = id 是现解析的，404 就是文件真没了 → 不做无意义的重试"""
    from fastapi import HTTPException

    from backend.emby_server import api

    seen = _patch_serve(monkeypatch, [404, 200])
    _patch_resolve(monkeypatch)

    with pytest.raises(HTTPException):
        _run(api._serve_remote_retry_on_stale(
            _Target("https://src/X"), _req(), db, _item("mount://7/m/a.mkv"), "video/mp4", None,
        ))
    assert seen == ["https://src/X"], "不该重试"


def test_404_on_local_file_does_not_retry(db, monkeypatch):
    """本机文件没有挂载缓存可言"""
    from fastapi import HTTPException

    from backend.emby_server import api

    seen = _patch_serve(monkeypatch, [404, 200])
    with pytest.raises(HTTPException):
        _run(api._serve_remote_retry_on_stale(
            _Target("https://src/X"), _req(), db, _item("/data/a.mkv"), "video/mp4", None,
        ))
    assert seen == ["https://src/X"]


def test_non_404_is_never_retried(db, monkeypatch):
    """502（源站不可达）与缓存无关，重试只会把一次故障拖成两次"""
    from fastapi import HTTPException

    from backend.emby_server import api

    fic.store(db, 7, "/m/a.mkv", "FID")
    db.commit()
    seen = _patch_serve(monkeypatch, [502, 200])
    with pytest.raises(HTTPException):
        _run(api._serve_remote_retry_on_stale(
            _Target("https://src/X"), _req(), db, _item("mount://7/m/a.mkv"), "video/mp4", None,
        ))
    assert seen == ["https://src/X"]
    db.commit()
    assert len(_rows(db)) == 1, "非 404 不该动缓存"


def test_success_never_touches_cache(db, monkeypatch):
    from backend.emby_server import api

    fic.store(db, 7, "/m/a.mkv", "FID")
    db.commit()
    seen = _patch_serve(monkeypatch, [200])
    _patch_resolve(monkeypatch)
    out = _run(api._serve_remote_retry_on_stale(
        _Target("https://src/X"), _req(), db, _item("mount://7/m/a.mkv"), "video/mp4", None,
    ))
    assert out == "ok:https://src/X"
    assert seen == ["https://src/X"]
    db.commit()
    assert len(_rows(db)) == 1


def test_reparse_writes_the_new_file_id_back(db, monkeypatch):
    """自愈要把新 id 落回缓存，否则每播一次都要重新解析一遍"""
    from backend.emby_server import api

    fic.store(db, 7, "/m/a.mkv", "STALE-FID")
    db.commit()
    _patch_serve(monkeypatch, [404, 200])

    def _resolve(db_, item):
        # 真实的 resolve 会把新 id 写回缓存，这里显式模拟那一步
        fic.store(db_, 7, "/m/a.mkv", "FRESH-FID")
        return _Target("https://src/FRESH")

    monkeypatch.setattr("backend.emby_server.api._play_target", _resolve)
    _run(api._serve_remote_retry_on_stale(
        _Target("https://src/STALE"), _req(), db, _item("mount://7/m/a.mkv"), "video/mp4", None,
    ))
    db.commit()
    assert fic.lookup(db, 7, "/m/a.mkv") == "FRESH-FID"