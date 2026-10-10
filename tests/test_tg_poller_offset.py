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


# ---------- poller offset 持久化 ----------

def test_poller_save_offset_persists(db):
    """_save_offset 必须真正写库：否则 offset 永不推进，同一批 update 被反复重放。"""
    poller._save_offset(db, 4242)
    db.rollback()  # 未提交的写入会在这里丢失（poller 随后直接 close 会话）
    store.invalidate()
    assert poller._get_offset(db) == 4242
