"""Google Drive 令牌层：服务账号（JWT）取票测试。

全部用 mock / 临时文件 / 本地生成的 RSA 密钥，不碰真实 rclone、
不碰真实 Google API、不写任何真实密码或 token。

（直链 302 与 rclone.conf 取票已删除，剩余用例只覆盖原生挂载在用的令牌层。）
"""
import asyncio
import json
import time

import pytest

from backend.emby_server import direct_url
from backend.emby_server.direct_url import (
    _sa_access_token,
    _sa_jwt_assertion,
)


def run(coro):
    return asyncio.run(coro)


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
