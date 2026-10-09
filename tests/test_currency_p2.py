import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import models
from backend.models import Base
from backend.api.economy import _get_float_config, _add_points

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()

def make_user(db, username="u1", points=0):
    u = models.WebUser(username=username, password_hash="test", points=points)
    db.add(u); db.commit(); db.refresh(u)
    return u

def test_recharge_ratio_default(db):
    """_get_float_config 缺失 key 时返回默认值"""
    assert _get_float_config(db, "recharge_ratio", 1.2) == 1.2

def test_recharge_ratio_from_config(db):
    """_get_float_config 读到配置值"""
    db.add(models.SystemConfig(key="recharge_ratio", value="1.5"))
    db.commit()
    assert _get_float_config(db, "recharge_ratio", 1.2) == 1.5

def test_recharge_ratio_invalid_fallback(db):
    """非法配置值时回退默认值"""
    db.add(models.SystemConfig(key="recharge_ratio", value="abc"))
    db.commit()
    assert _get_float_config(db, "recharge_ratio", 1.2) == 1.2

def test_points_calculation(db):
    """100 元按 1.2 比例 = 120 积分（向下取整）"""
    assert int(Decimal("100") * Decimal("1.2")) == 120
    assert int(Decimal("99.99") * Decimal("1.2")) == 119

def test_subscription_buy_deducts_points(db):
    """积分购买订阅扣积分并写台账"""
    user = make_user(db, points=1000)
    _add_points(db, user, -500, "subscription_buy", "积分购买订阅 - 测试套餐", "subscription_points:TEST123")
    db.commit()
    db.refresh(user)
    assert user.points == 500
    log = db.query(models.PointsLog).filter(models.PointsLog.user_id == user.id, models.PointsLog.type == "subscription_buy").first()
    assert log is not None
    assert log.amount == -500
    assert log.balance_after == 500

def test_plan_points_price_nullable(db):
    """套餐积分价可为空"""
    p1 = models.SubscriptionPlan(name="无积分价", price=Decimal("10"), duration_days=30)
    p2 = models.SubscriptionPlan(name="有积分价", price=Decimal("10"), duration_days=30, points_price=Decimal("500"))
    db.add_all([p1, p2]); db.commit(); db.refresh(p1); db.refresh(p2)
    assert p1.points_price is None
    assert int(p2.points_price) == 500

