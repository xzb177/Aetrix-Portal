"""Emby 认证失败必须返回 401 空 body（对齐官方 Emby）。

2026-09-26 线上实测：官方 iOS 客户端登录失败时，我们曾返回
401 + {"error": "InvalidUsernameOrPassword"} JSON，客户端尝试按
认证成功结构解析该 body，弹出"数据解析错误"；真 Emby 返回 401 空
body，客户端正常提示用户名或密码不正确。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from starlette.requests import Request

from backend.database import SessionLocal, init_db
from backend.emby_server import api as emby_api

init_db()


def _req():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/emby/Users/AuthenticateByName",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
        "client": ("127.0.0.1", 54321),
    }
    return Request(scope)


def test_auth_fail_unknown_user_401_empty_body():
    db = SessionLocal()
    try:
        resp = emby_api.authenticate_by_name(
            _req(), {"Username": "不存在的用户xyz", "Pw": "wrong"}, db)
        assert resp.status_code == 401
        assert resp.body == b"", f"body 必须为空，实际为 {resp.body!r}"
    finally:
        db.close()


def test_auth_fail_empty_password_401_empty_body():
    db = SessionLocal()
    try:
        resp = emby_api.authenticate_by_name(
            _req(), {"Username": "anyone", "Pw": ""}, db)
        assert resp.status_code == 401
        assert resp.body == b"", f"body 必须为空，实际为 {resp.body!r}"
    finally:
        db.close()
