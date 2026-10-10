"""TG Bot / 注册门禁安全回归测试（be/core 审查）。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.integrations import store
from backend.tg_bot import handlers, login_token, poller


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


def _make_user(db, username="u1", tg_id=None):
    u = models.WebUser(username=username, telegram_id=tg_id, password_hash="x")
    db.add(u)
    db.commit()
    return u


# ---------- 绑定码暴力枚举 ----------

def test_bind_code_bruteforce_locked_out(db):
    victim = _make_user(db, username="victim")
    db.add(models.TgBindCode(user_id=victim.id, code="654321",
                             expires_at=datetime.now() + timedelta(minutes=10)))
    db.commit()
    attacker = 990001
    for guess in range(100000, 100000 + 20):
        handlers.verify_bind_code(db, attacker, attacker, str(guess))
    # 连续猜错后即使猜中也必须被拒绝
    handlers.verify_bind_code(db, attacker, attacker, "654321")
    db.refresh(victim)
    assert victim.telegram_id is None, "绑定码可被无限次枚举"


def test_bind_code_normal_flow_still_works(db):
    user = _make_user(db, username="normal")
    db.add(models.TgBindCode(user_id=user.id, code="123987",
                             expires_at=datetime.now() + timedelta(minutes=10)))
    db.commit()
    reply = handlers.verify_bind_code(db, 990002, 990002, "123987")
    assert reply and "绑定成功" in reply
    db.refresh(user)
    assert user.telegram_id == 990002


def test_bind_code_generated_with_csprng(db, monkeypatch):
    """绑定码不能用可预测的 random 模块生成。"""
    import random
    from backend import tg_bind

    monkeypatch.setattr(random, "randint", lambda a, b: 111111)
    monkeypatch.setattr(tg_bind, "get_bot_username", lambda db_: "")
    user = _make_user(db, username="gen")
    codes = {tg_bind.generate_bind_code(db, user)["code"] for _ in range(5)}
    assert codes != {"111111"}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
