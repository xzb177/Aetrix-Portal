"""poller 在跑时，网页端绑定校验不得自己调 getUpdates（409 + 抢 update），改读库状态。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models, tg_bind
from backend.integrations import store
from backend.tg_bot import handlers, poller


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    store.invalidate()
    monkeypatch.setattr(tg_bind.tg_integration, "token", lambda db_: "t")

    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("poller 在跑时 verify_bind 调用了 getUpdates")

    monkeypatch.setattr(httpx, "Client", _Boom)
    yield session
    session.close()
    store.invalidate()


def _user(db, name):
    u = models.WebUser(username=name, password_hash="x")
    db.add(u)
    db.commit()
    return u


def test_verify_bind_reads_db_when_poller_active(db):
    poller._beat(db)
    user = _user(db, "pv1")
    db.add(models.TgBindCode(user_id=user.id, code="456789",
                             expires_at=datetime.now() + timedelta(minutes=10)))
    db.commit()
    res = tg_bind.verify_bind(db, user)
    assert res["success"] is False
    # poller 的绑定处理器消费了绑定码
    assert "绑定成功" in handlers.verify_bind_code(db, 8_100_001, 8_100_001, "456789")
    db.refresh(user)
    res = tg_bind.verify_bind(db, user)
    assert res == {"success": True, "telegram_id": 8_100_001}


def test_stale_heartbeat_not_active(db):
    store.write_values(db, {poller.HEARTBEAT_KEY: (datetime.now() - timedelta(hours=1)).isoformat()})
    db.commit()
    assert poller.is_active(db) is False
    poller._beat(db)
    assert poller.is_active(db) is True
