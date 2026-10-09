import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.models import Base
from backend import vitality


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _has(obj, key):
    if isinstance(obj, dict):
        return key in obj
    return hasattr(obj, key)
def test_defaults(db):
    cfg = vitality.get_vitality_config(db)
    assert cfg["enabled"] is True
    assert cfg["max"] == 14 and cfg["daily_cost"] == 1
    assert cfg["limit_threshold"] == 3 and cfg["point_cost"] == 10

def test_add_vitality_clamp(db):
    u = models.WebUser(username="u1", password_hash="x", is_welfare=True, vitality=14)
    db.add(u); db.commit()
    assert vitality._add_vitality(db, u.id, 5, "test") == 14
    assert vitality._add_vitality(db, u.id, -20, "test") == 0
    logs = db.query(models.VitalityLog).filter_by(user_id=u.id).all()
    assert len(logs) == 2 and logs[1].balance_after == 0

def test_daily_deduct(db):
    for i, v in [(1, 10), (2, 1), (3, 0)]:
        db.add(models.WebUser(username=f"u{i}", password_hash="x", is_welfare=True, vitality=v))
    db.add(models.WebUser(username="u4", password_hash="x", is_welfare=False, vitality=10))
    db.commit()
    r = vitality.daily_deduct(db)
    assert r["deducted"] == 2 and r["suspended"] == 1
    assert db.query(models.WebUser).filter_by(username="u1").one().vitality == 9
    assert db.query(models.WebUser).filter_by(username="u2").one().vitality == 0
    assert db.query(models.WebUser).filter_by(username="u4").one().vitality == 10

def test_ensure_can_play(db):
    low = models.WebUser(username="low", password_hash="x", is_welfare=True, vitality=2)
    ok = models.WebUser(username="ok", password_hash="x", is_welfare=True, vitality=3)
    plain = models.WebUser(username="plain", password_hash="x", is_welfare=False, vitality=0)
    staff = models.WebUser(username="staff", password_hash="x", is_welfare=True, vitality=0, is_staff=True)
    for u in (low, ok, plain, staff):
        db.add(u)
    db.commit()
    with pytest.raises(HTTPException) as e:
        vitality.ensure_can_play(db, low)
    assert e.value.status_code == 403
    vitality.ensure_can_play(db, ok)
    vitality.ensure_can_play(db, plain)
    vitality.ensure_can_play(db, staff)
    db.add(models.SystemConfig(key="vitality_enabled", value="false")); db.commit()
    from backend.integrations import store as _store
    _store.invalidate("vitality_enabled")
    vitality.ensure_can_play(db, low)
