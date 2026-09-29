"""直链 302 的服务账号（JWT）支持测试。

全部用 mock / 临时文件 / 本地生成的 RSA 密钥，不碰真实 rclone、
不碰真实 Google API、不写任何真实密码或 token。
"""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.emby_server import direct_url
from backend.emby_server.direct_url import (
    _sa_access_token,
    _sa_jwt_assertion,
    _token_from_conf,
    get_access_token,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """token 缓存是进程级的，每个测试前清空，避免相互污染。"""
    direct_url._token_cache.clear()
    yield
    direct_url._token_cache.clear()


# ---------------- 测试辅助 ----------------

class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """替代 httpx.AsyncClient 的最小 fake，支持 async 上下文协议。"""

    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return self._handler(url, kwargs)


def _patch_async_client(monkeypatch, handler):
    monkeypatch.setattr(
        direct_url.httpx, "AsyncClient", lambda **kwargs: _FakeClient(handler)
    )


def _make_sa_json(tmp_path, token_uri="https://oauth2.googleapis.com/token"):
    """生成一份格式正确的服务账号 JSON（本地生成 RSA 私钥，真签名）。"""
    pytest.importorskip("jose")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    sa = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "keyid123",
        "private_key": pem,
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": token_uri,
    }
    p = tmp_path / "sa.json"
    p.write_text(json.dumps(sa), encoding="utf-8")
    return str(p), sa


def _write_sa_conf(tmp_path, sa_path, remote="MP", extra=""):
    """rclone.conf：服务账号型 remote。"""
    conf = (
        f"[{remote}]\n"
        f"type = drive\n"
        f"scope = drive\n"
        f"service_account_file = {sa_path}\n"
        f"team_drive = 0ABCDEF\n"
        f"{extra}"
    )
    p = tmp_path / "rclone.conf"
    p.write_text(conf, encoding="utf-8")
    return str(p)


def _future_expiry():
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


# ---------------- _sa_jwt_assertion ----------------

def test_sa_jwt_assertion_structure(tmp_path):
    """JWT 三段式、header 是 RS256、claims 字段齐全。"""
    pytest.importorskip("jose")
    from jose import jwt as _jwt

    sa_path, sa = _make_sa_json(tmp_path)
    assertion = _sa_jwt_assertion(sa, "MP")
    assert assertion is not None
    parts = assertion.split(".")
    assert len(parts) == 3, "JWT 必须是 header.payload.signature 三段"
    header = json.loads(__import__("base64").urlsafe_b64decode(parts[0] + "=="))
    assert header["alg"] == "RS256"
    # 用公钥验签：能解开且 claims 正确
    claims = _jwt.get_unverified_claims(assertion)
    assert claims["iss"] == sa["client_email"]
    assert claims["scope"] == "https://www.googleapis.com/auth/drive"
    assert claims["aud"] == sa["token_uri"]
    assert claims["exp"] - claims["iat"] == 3600


def test_sa_jwt_assertion_bad_key_returns_none():
    """私钥损坏时返回 None，不抛异常。"""
    sa = {
        "client_email": "a@b.c",
        "private_key": "NOT-A-REAL-KEY",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    assert _sa_jwt_assertion(sa, "MP") is None


# ---------------- _sa_access_token ----------------

def test_sa_access_token_success(monkeypatch, tmp_path):
    """正常流程：读 JSON -> JWT -> POST token_uri -> 拿到 token。"""
    sa_path, sa = _make_sa_json(tmp_path)
    calls = []

    def handler(url, kwargs):
        calls.append((url, kwargs))
        assert url == sa["token_uri"]
        data = kwargs["data"]
        assert data["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
        assert data["assertion"].count(".") == 2, "assertion 必须是 JWT"
        return _FakeResp(200, {"access_token": "SA_TOKEN_1", "expires_in": 3600})

    _patch_async_client(monkeypatch, handler)
    before = time.time()
    result = run(_sa_access_token(sa_path, "MP"))
    assert result is not None
    token, expiry = result
    assert token == "SA_TOKEN_1"
    assert before + 3500 < expiry <= before + 3700
    assert len(calls) == 1


def test_sa_access_token_missing_file_returns_none():
    assert run(_sa_access_token("/tmp/does-not-exist-sa.json", "MP")) is None


def test_sa_access_token_bad_json_returns_none(tmp_path):
    p = tmp_path / "sa.json"
    p.write_text("{not json", encoding="utf-8")
    assert run(_sa_access_token(str(p), "MP")) is None


def test_sa_access_token_wrong_type_returns_none(tmp_path):
    p = tmp_path / "sa.json"
    p.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    assert run(_sa_access_token(str(p), "MP")) is None


def test_sa_access_token_missing_fields_returns_none(tmp_path):
    p = tmp_path / "sa.json"
    p.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    assert run(_sa_access_token(str(p), "MP")) is None


def test_sa_access_token_http_error_returns_none(monkeypatch, tmp_path):
    sa_path, _ = _make_sa_json(tmp_path)
    _patch_async_client(monkeypatch, lambda url, kwargs: _FakeResp(400))
    assert run(_sa_access_token(sa_path, "MP")) is None


@pytest.mark.parametrize("status", [429, 403])
def test_sa_access_token_rate_limited_raises(monkeypatch, tmp_path, status):
    """429/403 抛 SARateLimited，调用方（轮换池）据此做冷却故障转移。"""
    from backend.emby_server.direct_url import SARateLimited

    sa_path, _ = _make_sa_json(tmp_path)
    _patch_async_client(monkeypatch, lambda url, kwargs: _FakeResp(status))
    with pytest.raises(SARateLimited):
        run(_sa_access_token(sa_path, "MP"))


def test_sa_access_token_network_error_returns_none(monkeypatch, tmp_path):
    sa_path, _ = _make_sa_json(tmp_path)

    def handler(url, kwargs):
        raise ConnectionError("boom")

    _patch_async_client(monkeypatch, handler)
    assert run(_sa_access_token(sa_path, "MP")) is None


def test_sa_access_token_no_access_token_in_response(monkeypatch, tmp_path):
    sa_path, _ = _make_sa_json(tmp_path)
    _patch_async_client(monkeypatch, lambda url, kwargs: _FakeResp(200, {}))
    assert run(_sa_access_token(sa_path, "MP")) is None


# ---------------- _token_from_conf ----------------

def test_token_from_conf_sa_only(monkeypatch, tmp_path):
    """只有 service_account_file、没有 OAuth token：返回 SA 路径。"""
    sa_path, _ = _make_sa_json(tmp_path)
    monkeypatch.setenv("RCLONE_CONF_PATH", _write_sa_conf(tmp_path, sa_path))
    info = _token_from_conf("MP")
    assert info is not None
    assert info["service_account_file"] == sa_path
    assert info["access_token"] == ""


def test_token_from_conf_neither_returns_none(monkeypatch, tmp_path):
    """既没有 token 也没有 service_account_file：返回 None。"""
    p = tmp_path / "rclone.conf"
    p.write_text("[MP]\ntype = drive\nscope = drive\n", encoding="utf-8")
    monkeypatch.setenv("RCLONE_CONF_PATH", str(p))
    assert _token_from_conf("MP") is None


def test_token_from_conf_oauth_and_sa(monkeypatch, tmp_path):
    """两者都有：都返回，优先级由 get_access_token 决定。"""
    sa_path, _ = _make_sa_json(tmp_path)
    token = {"access_token": "OAUTH1", "refresh_token": "r",
             "expiry": _future_expiry()}
    conf = (
        "[MP]\n"
        "type = drive\n"
        f"service_account_file = {sa_path}\n"
        f"token = {json.dumps(token)}\n"
    )
    p = tmp_path / "rclone.conf"
    p.write_text(conf, encoding="utf-8")
    monkeypatch.setenv("RCLONE_CONF_PATH", str(p))
    info = _token_from_conf("MP")
    assert info["access_token"] == "OAUTH1"
    assert info["service_account_file"] == sa_path


# ---------------- get_access_token（端到端） ----------------

def _pool_for_sa(monkeypatch, tmp_path, sa_path=None):
    """给 get_access_token 造一个只含 tmp 目录 SA 的轮换池（不预热、不起后台线程）。"""
    from backend.emby_server.direct_url import ServiceAccountPool

    if sa_path is None:
        sa_path, _ = _make_sa_json(tmp_path)
    pool = ServiceAccountPool(
        sa_dir=str(tmp_path), prewarm=False, healthcheck_interval=0
    )
    monkeypatch.setattr(direct_url, "get_sa_pool", lambda: pool)
    return pool


def test_get_access_token_sa_uses_pool(monkeypatch, tmp_path):
    """SA 型 remote：get_access_token 走轮换池拿 token。"""
    sa_path, _ = _make_sa_json(tmp_path)
    monkeypatch.setenv("RCLONE_CONF_PATH", _write_sa_conf(tmp_path, sa_path))
    _pool_for_sa(monkeypatch, tmp_path, sa_path)
    calls = []

    def handler(url, kwargs):
        calls.append(url)
        return _FakeResp(200, {"access_token": "SA_POOL_TOKEN", "expires_in": 3600})

    _patch_async_client(monkeypatch, handler)
    assert run(get_access_token("MP:")) == "SA_POOL_TOKEN"
    assert len(calls) == 1


def test_get_access_token_oauth_preferred_over_sa(monkeypatch, tmp_path):
    """两者都有且 OAuth token 有效：用 OAuth，不碰轮换池。"""
    sa_path, _ = _make_sa_json(tmp_path)
    token = {"access_token": "OAUTH_VALID", "refresh_token": "r",
             "expiry": _future_expiry()}
    conf = (
        "[MP]\n"
        "type = drive\n"
        f"service_account_file = {sa_path}\n"
        f"token = {json.dumps(token)}\n"
    )
    p = tmp_path / "rclone.conf"
    p.write_text(conf, encoding="utf-8")
    monkeypatch.setenv("RCLONE_CONF_PATH", str(p))

    def _boom_pool():
        raise AssertionError("OAuth 有效时不应使用轮换池")

    monkeypatch.setattr(direct_url, "get_sa_pool", _boom_pool)

    def handler(url, kwargs):
        raise AssertionError("OAuth 有效时不应发起任何 token 请求")

    _patch_async_client(monkeypatch, handler)
    assert run(get_access_token("MP:")) == "OAUTH_VALID"


def test_get_access_token_sa_pool_empty_returns_none(monkeypatch, tmp_path):
    """池子里没有可用 SA：返回 None（调用方回退到代理）。"""
    sa_path, _ = _make_sa_json(tmp_path)
    monkeypatch.setenv("RCLONE_CONF_PATH", _write_sa_conf(tmp_path, sa_path))
    # 池目录是空的
    empty = tmp_path / "empty"
    empty.mkdir()
    from backend.emby_server.direct_url import ServiceAccountPool

    pool = ServiceAccountPool(sa_dir=str(empty), prewarm=False, healthcheck_interval=0)
    monkeypatch.setattr(direct_url, "get_sa_pool", lambda: pool)
    assert run(get_access_token("MP:")) is None
