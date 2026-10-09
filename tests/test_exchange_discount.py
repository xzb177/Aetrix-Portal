"""P3 兑换码折扣类型测试：discount 型核销发权益、下单抵扣口径。

全部用隔离的内存 SQLite，不碰生产库。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend import codes as code_lib
from backend.api import economy as E


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _user(db, name):
    u = models.WebUser(username=name, password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _code(db, pct, code="D85"):
    c = models.ExchangeCode(code=code, type="discount", discount_pct=pct,
                            max_uses=10, is_active=True,
                            expires_at=datetime.now() + timedelta(days=30))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _credit(db, user_id, code, pct=None, status="unused", expired=False):
    cr = E._grant_discount_credit(db, user_id, code)
    if pct is not None:
        cr.discount_pct = pct
    cr.status = status
    if expired:
        cr.expires_at = datetime.now() - timedelta(days=1)
    db.commit()
    db.refresh(cr)
    return cr


def test_grant(db):
    u = _user(db, "alice")
    c = _code(db, 85)
    credit = E._grant_discount_credit(db, u.id, c)
    db.commit()
    assert credit is not None
    assert credit.status == "unused"
    assert credit.discount_pct == 85
    assert credit.expires_at == c.expires_at


def test_math():
    assert E._exchange_discount_amount(Decimal("99.99"), 85) == (Decimal("15.00"), Decimal("84.99"))


def test_edge():
    assert E._exchange_discount_amount(Decimal("100"), 100) == (Decimal("1.00"), Decimal("99.00"))
    d, p = E._exchange_discount_amount(Decimal("0"), 85)
    assert d == Decimal("0") and p == Decimal("0")


def test_best_picks_lowest_pct(db):
    u = _user(db, "bob")
    c90 = _code(db, 90, code="D90")
    c85 = _code(db, 85, code="D85")
    _credit(db, u.id, c90)
    _credit(db, u.id, c85)
    best = E._best_discount_credit(db, u.id)
    assert best is not None
    assert best.discount_pct == 85


def test_best_skips_used_expired(db):
    u = _user(db, "carol")
    c1 = _code(db, 85, code="D851")
    c2 = _code(db, 90, code="D901")
    _credit(db, u.id, c1, status="used")
    _credit(db, u.id, c2, expired=True)
    assert E._best_discount_credit(db, u.id) is None


def test_redeem_twice_blocked(db):
    u = _user(db, "dave")
    c = _code(db, 85, code="D852")
    first = code_lib.record_redemption(db, code_lib.REDEMPTION_KIND_EXCHANGE, c.id, u.id)
    second = code_lib.record_redemption(db, code_lib.REDEMPTION_KIND_EXCHANGE, c.id, u.id)
    assert first is True
    assert second is False
