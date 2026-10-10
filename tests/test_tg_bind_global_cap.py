"""绑定码分布式枚举防护：多个 TG 账号各猜几次，全站累计猜错达到上限后待验证码作废。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.integrations import store
from backend.tg_bot import handlers


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


def _user(db, name):
    u = models.WebUser(username=name, password_hash="x")
    db.add(u)
    db.commit()
    return u


def test_distributed_bruteforce_invalidates_pending_code(db, monkeypatch):
    from backend import tg_bind

    victim = _user(db, "gvictim")
    db.add(models.TgBindCode(user_id=victim.id, code="654321",
                             expires_at=datetime.now() + timedelta(minutes=10)))
    db.commit()
    # 每个攻击账号只猜 2 次（远低于单账号限流），但账号很多
    guess = 100000
    for i in range(30):
        attacker = 7_100_000 + i
        for _ in range(2):
            handlers.verify_bind_code(db, attacker, attacker, str(guess))
            guess += 1
    handlers.verify_bind_code(db, 7_200_000, 7_200_000, "654321")
    db.refresh(victim)
    assert victim.telegram_id is None, "多 TG 账号分布式枚举仍可命中绑定码"

    # 受害者网页端验证时被明确告知失效，而不是静默失败
    monkeypatch.setattr(tg_bind.tg_integration, "token", lambda db_: "t")
    res = tg_bind.verify_bind(db, victim)
    assert res["success"] is False and res.get("code_expired") is True

    # 重新生成后可正常绑定
    monkeypatch.setattr(tg_bind, "get_bot_username", lambda db_: "")
    code = tg_bind.generate_bind_code(db, victim)["code"]
    db.commit()
    reply = handlers.verify_bind_code(db, 7_300_000, 7_300_000, code)
    assert reply and "绑定成功" in reply


def test_few_global_failures_do_not_invalidate(db):
    user = _user(db, "gok")
    db.add(models.TgBindCode(user_id=user.id, code="222333",
                             expires_at=datetime.now() + timedelta(minutes=10)))
    db.commit()
    for i in range(3):
        handlers.verify_bind_code(db, 7_400_000 + i, 7_400_000 + i, str(300000 + i))
    reply = handlers.verify_bind_code(db, 7_500_000, 7_500_000, "222333")
    assert reply and "绑定成功" in reply
