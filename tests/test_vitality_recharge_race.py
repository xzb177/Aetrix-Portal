"""积分续活力：剩余空间检查在事务外 → 并发续费超付（活力被上限截断，积分照扣）。"""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.models import Base
from backend.api import economy


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _call(db, user, points, monkeypatch, between=None):
    monkeypatch.setattr(economy, "check_rate_limit", lambda *a, **k: (True, 0))

    async def fake_threadpool(fn, *a, **k):
        if between:
            between()
        return fn(*a, **k)

    monkeypatch.setattr(economy, "run_in_threadpool", fake_threadpool)
    payload = economy.VitalityRechargeRequest(points=points)
    return asyncio.run(economy.recharge_vitality(None, payload, current_user=user, db=db))


def test_recharge_caps_to_headroom_inside_txn(db, monkeypatch):
    u = models.WebUser(username="v1", password_hash="x", is_welfare=True, vitality=10, points=1000)
    db.add(u); db.commit()

    def concurrent_fill():
        # 另一笔续费在本请求「算空间」之后、扣分之前提交：活力已被续到 13
        db.query(models.WebUser).filter_by(id=u.id).update({"vitality": 13})
        db.commit()

    # 请求续 4 点（max=14，外层看到空间 4），实际只剩 1 点空间
    res = _call(db, u, 40, monkeypatch, between=concurrent_fill)
    assert res["vitality_gained"] == 1
    assert res["points_spent"] == 10
    db.expire_all()
    row = db.get(models.WebUser, u.id)
    assert row.vitality == 14
    assert row.points == 990


def test_recharge_full_inside_txn_spends_nothing(db, monkeypatch):
    u = models.WebUser(username="v2", password_hash="x", is_welfare=True, vitality=12, points=1000)
    db.add(u); db.commit()

    def concurrent_fill():
        db.query(models.WebUser).filter_by(id=u.id).update({"vitality": 14})
        db.commit()

    with pytest.raises(HTTPException) as ei:
        _call(db, u, 20, monkeypatch, between=concurrent_fill)
    assert ei.value.status_code == 400
    db.expire_all()
    assert db.get(models.WebUser, u.id).points == 1000


def test_recharge_insufficient_points_atomic(db, monkeypatch):
    u = models.WebUser(username="v3", password_hash="x", is_welfare=True, vitality=0, points=5)
    db.add(u); db.commit()
    with pytest.raises(HTTPException) as ei:
        _call(db, u, 10, monkeypatch)
    assert ei.value.status_code == 400
    db.expire_all()
    row = db.get(models.WebUser, u.id)
    assert row.points == 5 and (row.vitality or 0) == 0
