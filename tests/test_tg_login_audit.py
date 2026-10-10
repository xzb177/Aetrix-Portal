"""/tg-login 一键免密登录必须和密码登录一样：写登录日志 + 走 share_guard 跨城市判定。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend import models
from backend.api import emby_portal
from backend.integrations import store


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    store.invalidate()
    yield session
    session.close()
    store.invalidate()


def _request():
    return Request({"type": "http", "method": "POST", "path": "/tg-login",
                    "headers": [(b"user-agent", b"pytest")], "client": ("1.2.3.4", 1234)})


def _setup(db, monkeypatch, verdict=None):
    u = models.WebUser(username="tgl", password_hash="x", telegram_id=555, is_active=True)
    db.add(u)
    db.commit()
    from backend.tg_bot import login_token
    monkeypatch.setattr(login_token, "consume_login_token",
                        lambda t: {"user_id": u.id, "telegram_id": 555})
    seen = []

    def fake_note(db_, user, ip, **k):
        seen.append((user.id, ip))
        return verdict

    monkeypatch.setattr(emby_portal.share_guard, "note_activity", fake_note)
    monkeypatch.setattr(emby_portal, "_issue_auth_response", lambda user, db_, **k: {"ok": True})
    return u, seen


def test_tg_login_writes_log_and_runs_share_guard(db, monkeypatch):
    u, seen = _setup(db, monkeypatch)
    res = emby_portal.tg_login(_request(), emby_portal.TgLoginRequest(token="t"), db)
    assert res == {"ok": True}
    logs = db.query(models.LoginLog).filter(models.LoginLog.user_id == u.id).all()
    assert any(l.success and l.reason == "tg_login" for l in logs)
    assert seen and seen[0][0] == u.id


def test_tg_login_blocked_by_share_guard(db, monkeypatch):
    _setup(db, monkeypatch, verdict={"blocked": True})
    with pytest.raises(HTTPException) as ei:
        emby_portal.tg_login(_request(), emby_portal.TgLoginRequest(token="t"), db)
    assert ei.value.status_code == 403
