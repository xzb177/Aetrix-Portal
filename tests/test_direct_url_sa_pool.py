"""直链 302 的服务账号轮换池测试。

全部用 mock / 临时目录，不碰真实 rclone、不碰真实 Google API、
不写任何真实私钥。不起真实后台线程（prewarm/healthcheck 除专项测试外均关闭）。
"""
import asyncio
import json
import os
import time

import pytest

from backend.emby_server import direct_url
from backend.emby_server.direct_url import (
    SARateLimited,
    ServiceAccountPool,
    get_sa_pool,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_pool_singleton():
    """单例是进程级的，每个测试前复位，避免相互污染。"""
    direct_url._sa_pool = None
    yield
    direct_url._sa_pool = None


# ---------------- 测试辅助 ----------------

def _sa_file(tmp_path, name, subdir=None):
    """写一份结构有效的 SA JSON（私钥为假值——扫描只校验存在性）。"""
    d = tmp_path / subdir if subdir else tmp_path
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({
        "type": "service_account",
        "private_key": "fake-key-for-scan",
        "client_email": f"{name}@test.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }), encoding="utf-8")
    return str(p)


def _make_pool(tmp_path, cooldown_sec=300.0, **kwargs):
    kwargs.setdefault("prewarm", False)
    kwargs.setdefault("healthcheck_interval", 0)
    return ServiceAccountPool(sa_dir=str(tmp_path), cooldown_sec=cooldown_sec, **kwargs)


def _fake_fetcher(monkeypatch, behavior):
    """behavior: {path: ("token", str) | ("rate_limit",) | ("fail",)}。

    未指定的 path 默认返回 TOKEN_<basename>。返回 calls 列表。
    """
    calls = []

    async def fake(sa_file, remote):
        calls.append(sa_file)
        kind = behavior.get(sa_file, ("token", f"TOKEN_{os.path.basename(sa_file)}"))
        if kind[0] == "rate_limit":
            raise SARateLimited("429")
        if kind[0] == "fail":
            return None
        return (kind[1], time.time() + 3600)

    monkeypatch.setattr(direct_url, "_sa_access_token", fake)
    return calls


# ---------------- 扫描 ----------------

def test_pool_scans_recursively_and_skips_invalid(tmp_path):
    _sa_file(tmp_path, "a.json")
    _sa_file(tmp_path, "b.json", subdir="nested")
    # 无效文件：类型不对 / JSON 损坏 / 非 json 后缀
    (tmp_path / "c.json").write_text(json.dumps({"type": "authorized_user"}))
    (tmp_path / "d.json").write_text("{broken")
    (tmp_path / "e.txt").write_text("hello")
    pool = _make_pool(tmp_path)
    assert pool.account_count == 2
    emails = sorted(a["email"] for a in pool._accounts)
    assert emails == ["a.json@test.iam.gserviceaccount.com",
                      "b.json@test.iam.gserviceaccount.com"]


def test_pool_empty_and_missing_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _make_pool(empty).account_count == 0
    assert _make_pool(tmp_path / "no-such-dir").account_count == 0


# ---------------- 轮换 ----------------

def test_pool_round_robin_order(monkeypatch, tmp_path):
    a = _sa_file(tmp_path, "a.json")
    b = _sa_file(tmp_path, "b.json")
    c = _sa_file(tmp_path, "c.json")
    _fake_fetcher(monkeypatch, {})
    pool = _make_pool(tmp_path)
    got = [run(pool.get_token())[0] for _ in range(4)]
    assert got == ["TOKEN_a.json", "TOKEN_b.json", "TOKEN_c.json", "TOKEN_a.json"]


def test_pool_token_cached_across_rotation(monkeypatch, tmp_path):
    """转一圈回来用缓存：4 次 get_token 只应实际生成 2 次。"""
    _sa_file(tmp_path, "a.json")
    _sa_file(tmp_path, "b.json")
    calls = _fake_fetcher(monkeypatch, {})
    pool = _make_pool(tmp_path)
    got = [run(pool.get_token())[0] for _ in range(4)]
    assert got == ["TOKEN_a.json", "TOKEN_b.json", "TOKEN_a.json", "TOKEN_b.json"]
    assert len(calls) == 2, f"缓存未命中，实际生成了 {len(calls)} 次"


def test_pool_expired_token_regenerates(monkeypatch, tmp_path):
    a = _sa_file(tmp_path, "a.json")
    n = {"i": 0}

    async def fake(sa_file, remote):
        n["i"] += 1
        return (f"TOKEN_{n['i']}", time.time() + 3600)

    monkeypatch.setattr(direct_url, "_sa_access_token", fake)
    pool = _make_pool(tmp_path)
    assert run(pool.get_token())[0] == "TOKEN_1"
    # 手动过期
    with pool._lock:
        pool._tokens[a]["expiry"] = time.time() - 10
    assert run(pool.get_token())[0] == "TOKEN_2"
    assert n["i"] == 2


# ---------------- 限流故障转移 ----------------

def test_pool_rate_limit_skips_cooling_sa(monkeypatch, tmp_path):
    a = _sa_file(tmp_path, "a.json")
    _sa_file(tmp_path, "b.json")
    _sa_file(tmp_path, "c.json")
    _fake_fetcher(monkeypatch, {a: ("rate_limit",)})
    pool = _make_pool(tmp_path)
    # 第一次：A 被限流冷却，返回 B
    assert run(pool.get_token())[0] == "TOKEN_b.json"
    # 之后：A 在冷却中被跳过，只在 B/C 之间轮换
    got = [run(pool.get_token())[0] for _ in range(4)]
    assert got == ["TOKEN_c.json", "TOKEN_b.json", "TOKEN_c.json", "TOKEN_b.json"]
    assert "TOKEN_a.json" not in got


def test_pool_all_cooling_returns_none(monkeypatch, tmp_path):
    a = _sa_file(tmp_path, "a.json")
    b = _sa_file(tmp_path, "b.json")
    _fake_fetcher(monkeypatch, {a: ("rate_limit",), b: ("rate_limit",)})
    pool = _make_pool(tmp_path)
    assert run(pool.get_token()) is None
    with pool._lock:
        assert len(pool._cooldown_until) == 2


def test_pool_cooldown_expires(monkeypatch, tmp_path):
    a = _sa_file(tmp_path, "a.json")
    state = {"limited": True}

    async def fake(sa_file, remote):
        if state["limited"]:
            raise SARateLimited("429")
        return ("TOKEN_OK", time.time() + 3600)

    monkeypatch.setattr(direct_url, "_sa_access_token", fake)
    pool = _make_pool(tmp_path, cooldown_sec=0.05)
    assert run(pool.get_token()) is None  # 被限流
    time.sleep(0.12)  # 冷却过期
    state["limited"] = False
    assert run(pool.get_token())[0] == "TOKEN_OK"


def test_pool_non_rate_limit_failure_tries_next(monkeypatch, tmp_path):
    """400 类账号级失败不冷却，换下一个账号继续。"""
    a = _sa_file(tmp_path, "a.json")
    _sa_file(tmp_path, "b.json")
    _fake_fetcher(monkeypatch, {a: ("fail",)})
    pool = _make_pool(tmp_path)
    assert run(pool.get_token())[0] == "TOKEN_b.json"
    with pool._lock:
        assert not pool._cooldown_until, "非限流失败不应进入冷却"


def test_pool_empty_returns_none(monkeypatch, tmp_path):
    pool = _make_pool(tmp_path)  # 空目录
    assert run(pool.get_token()) is None


# ---------------- 预热与单例 ----------------

def test_pool_prewarm_populates_cache(monkeypatch, tmp_path):
    _sa_file(tmp_path, "a.json")
    _sa_file(tmp_path, "b.json")
    calls = _fake_fetcher(monkeypatch, {})
    pool = ServiceAccountPool(sa_dir=str(tmp_path), prewarm=True, healthcheck_interval=0)
    deadline = time.time() + 5
    while time.time() < deadline:
        with pool._lock:
            if len(pool._tokens) == 2:
                break
        time.sleep(0.05)
    with pool._lock:
        assert len(pool._tokens) == 2
    # 预热后 get_token 直接命中缓存，不再请求
    before = len(calls)
    run(pool.get_token())
    run(pool.get_token())
    assert len(calls) == before


def test_get_sa_pool_singleton(monkeypatch):
    created = []
    orig = direct_url.ServiceAccountPool

    def fake_cls(*args, **kwargs):
        created.append(1)
        return orig(*args, **kwargs)

    monkeypatch.setattr(direct_url, "ServiceAccountPool", fake_cls)
    p1 = get_sa_pool()
    p2 = get_sa_pool()
    assert p1 is p2
    assert len(created) == 1
