"""公益服 TG 绑定门禁测试

全部用隔离的内存 SQLite，不碰生产库。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend import tg_bind


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_user(db, username, **kw):
    u = models.WebUser(username=username, password_hash="x", **kw)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _set_config(db, key, value):
    cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if cfg:
        cfg.value = str(value)
    else:
        db.add(models.SystemConfig(key=key, value=str(value)))
    db.commit()


def test_switch_off_bypass(db):
    _set_config(db, "welfare_require_tg_bind", "0")
    user = _make_user(db, "alice")
    assert tg_bind.require_tg_bound(user, db) is user


def test_bound_user_pass(db):
    _set_config(db, "welfare_require_tg_bind", "1")
    user = _make_user(db, "bob", telegram_id=12345)
    assert tg_bind.require_tg_bound(user, db) is user


def test_unbound_no_grace_403(db):
    _set_config(db, "welfare_require_tg_bind", "1")
    _set_config(db, "tg_bind_launch_at", (datetime.utcnow() - timedelta(days=30)).isoformat())
    user = _make_user(db, "carol")
    user.created_at = datetime.utcnow() - timedelta(days=60)
    db.commit()
    db.refresh(user)
    with pytest.raises(HTTPException) as exc:
        tg_bind.require_tg_bound(user, db)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "TG_NOT_BOUND"


def test_old_user_in_grace_pass(db):
    _set_config(db, "welfare_require_tg_bind", "1")
    _set_config(db, "tg_bind_launch_at", (datetime.utcnow() - timedelta(days=1)).isoformat())
    user = _make_user(db, "dave")
    user.created_at = datetime.utcnow() - timedelta(days=60)
    db.commit()
    db.refresh(user)
    assert tg_bind.require_tg_bound(user, db) is user


def test_new_user_no_grace(db):
    _set_config(db, "welfare_require_tg_bind", "1")
    _set_config(db, "tg_bind_launch_at", (datetime.utcnow() - timedelta(days=30)).isoformat())
    user = _make_user(db, "erin")
    user.created_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    db.refresh(user)
    with pytest.raises(HTTPException) as exc:
        tg_bind.require_tg_bound(user, db)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "TG_NOT_BOUND"


def test_generate_code(db):
    user = _make_user(db, "frank")
    code1 = tg_bind.generate_bind_code(db, user)
    assert len(code1["code"]) == 6 and code1["code"].isdigit()
    code2 = tg_bind.generate_bind_code(db, user)
    assert len(code2["code"]) == 6 and code2["code"].isdigit()
    assert code2["code"] != code1["code"]
    old = db.query(models.TgBindCode).filter(models.TgBindCode.code == code1["code"]).first()
    assert old is not None
    assert old.used_at is not None


def test_unbind(db):
    user = _make_user(db, "grace", telegram_id=999)
    tg_bind.unbind(db, user)
    assert user.telegram_id is None
    db.commit()
    db.refresh(user)
    assert user.telegram_id is None


def test_get_bind_status(db):
    _set_config(db, "welfare_require_tg_bind", "1")
    user = _make_user(db, "heidi")
    status = tg_bind.get_bind_status(db, user)
    assert status["bound"] is False
    assert status["required"] is True
    user.telegram_id = 12345
    db.commit()
    db.refresh(user)
    status = tg_bind.get_bind_status(db, user)
    assert status["bound"] is True
