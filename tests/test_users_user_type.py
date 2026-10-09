"""用户管理 user_type 筛选回归测试（v2.55 公益服并入用户管理）

全部用隔离的内存 SQLite，不碰生产库。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.api.admin import list_users


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user(db, username, is_welfare=False, welfare_expires_at=None):
    u = models.WebUser(username=username, email=f"{username}@t.com", password_hash="x",
                       is_welfare=is_welfare, welfare_expires_at=welfare_expires_at)
    db.add(u)
    db.commit()
    return u


def _sub(db, user_id, days_left=30):
    plan = models.SubscriptionPlan(name="test-plan", price=9.99, duration_days=30)
    db.add(plan)
    db.commit()
    s = models.UserSubscription(user_id=user_id, plan_id=plan.id, status="active",
                                end_date=datetime.now() + timedelta(days=days_left))
    db.add(s)
    db.commit()
    return s


@pytest.fixture()
def seeded(db):
    # 公益用户（含过期）
    w1 = _user(db, "welfare_ok", is_welfare=True,
               welfare_expires_at=datetime.now() + timedelta(days=10))
    w2 = _user(db, "welfare_expired", is_welfare=True,
               welfare_expires_at=datetime.now() - timedelta(days=5))
    # 付费用户
    p1 = _user(db, "paid_user")
    _sub(db, p1.id, days_left=30)
    # 既是公益又有订阅：类型按公益算
    both = _user(db, "welfare_paid", is_welfare=True,
                 welfare_expires_at=datetime.now() + timedelta(days=10))
    _sub(db, both.id, days_left=30)
    # 普通用户
    n1 = _user(db, "normal_user")
    return db


def _names(res):
    return sorted(u["username"] for u in res["users"])


def test_filter_welfare(seeded):
    res = list_users(user_type="welfare", db=seeded, current_admin=None)
    assert _names(res) == ["welfare_expired", "welfare_ok", "welfare_paid"]


def test_filter_paid(seeded):
    res = list_users(user_type="paid", db=seeded, current_admin=None)
    assert _names(res) == ["paid_user"]


def test_filter_normal(seeded):
    res = list_users(user_type="normal", db=seeded, current_admin=None)
    assert _names(res) == ["normal_user"]


def test_filter_all_default(seeded):
    res = list_users(db=seeded, current_admin=None)
    assert res["total"] == 5


def test_filter_invalid_falls_back_to_all(seeded):
    res = list_users(user_type="bogus", db=seeded, current_admin=None)
    assert res["total"] == 5


def test_row_fields(seeded):
    res = list_users(user_type="welfare", db=seeded, current_admin=None)
    by_name = {u["username"]: u for u in res["users"]}
    w = by_name["welfare_ok"]
    assert w["is_welfare"] is True
    assert w["user_type"] == "welfare"
    assert w["welfare_expires_at"] is not None
    # 过期公益用户类型仍是 welfare
    assert by_name["welfare_expired"]["user_type"] == "welfare"
    # 既有公益又有订阅：公益优先
    assert by_name["welfare_paid"]["user_type"] == "welfare"

    res2 = list_users(db=seeded, current_admin=None)
    by_name2 = {u["username"]: u for u in res2["users"]}
    assert by_name2["paid_user"]["user_type"] == "paid"
    assert by_name2["normal_user"]["user_type"] == "normal"
    assert by_name2["normal_user"]["is_welfare"] is False
    assert by_name2["normal_user"]["welfare_expires_at"] is None
