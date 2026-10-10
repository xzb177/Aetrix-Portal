"""积分双花回归：余额「先读后扣」在并发下会把余额扣成负数。

用 SQLAlchemy 的 before_cursor_execute 钩子模拟并发：在被测代码第一次扣
web_users.points 的那条 UPDATE 执行**之前**，同一连接上先把余额清零（相当于另一个
请求刚刚花光并提交）。旧实现已经在 Python 里判过「余额够」，会照扣成负数；
修复后扣减条件放进 UPDATE 的 WHERE，应当拒绝并保持余额不为负。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.api import economy


@pytest.fixture()
def env():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield engine, session
    session.close()


def _drain_before_first_points_update(engine, user_id: int, to: int = 0):
    """第一次扣积分的 UPDATE 之前把该用户余额改成 to（默认清零，模拟并发请求已花光）"""
    state = {"fired": False}

    @event.listens_for(engine, "before_cursor_execute")
    def _hook(conn, cursor, statement, parameters, context, executemany):
        if state["fired"]:
            return
        s = statement.lstrip().upper()
        if s.startswith("UPDATE WEB_USERS") and "POINTS" in s:
            state["fired"] = True
            cursor.execute("UPDATE web_users SET points = ? WHERE id = ?", (to, user_id))

    return state


def _user(db, name, points):
    u = models.WebUser(username=name, password_hash="x", points=points, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _cfg(db, key, value):
    db.add(models.SystemConfig(key=key, value=str(value)))
    db.commit()


def _balance(db, uid):
    db.expire_all()
    return db.query(models.WebUser.points).filter(models.WebUser.id == uid).scalar()


# ---------- 公共原语 ----------

def test_spend_points_rejects_insufficient(env):
    _, db = env
    u = _user(db, "u1", 10)
    with pytest.raises(economy.InsufficientPoints):
        economy._spend_points(db, u, 11, "t", "t")
    assert _balance(db, u.id) == 10
    assert economy._spend_points(db, u, 10, "t", "t") == 0


# ---------- 积分购买订阅 ----------

def test_points_subscription_purchase_no_double_spend(env):
    engine, db = env
    for k, v in (("payment_gateway_url", "https://pay.example"),
                 ("payment_partner_id", "1"), ("payment_partner_key", "k")):
        _cfg(db, k, v)
    plan = models.SubscriptionPlan(name="月卡", price=10, points_price=100,
                                   duration_days=30, is_active=True)
    db.add(plan)
    db.commit()
    u = _user(db, "buyer", 100)

    _drain_before_first_points_update(engine, u.id)
    req = economy.CreateOrderRequest(kind="subscription", item_id=plan.id,
                                     payment_method="alipay", pay_with_points=True)
    with pytest.raises(HTTPException) as ei:
        economy.create_payment_order(None, req, current_user=u, db=db)
    assert ei.value.status_code == 400
    assert _balance(db, u.id) >= 0
    assert db.query(models.UserSubscription).count() == 0


# ---------- 积分转账 ----------

def test_transfer_no_double_spend(env):
    engine, db = env
    sender = _user(db, "alice", 100)
    bob = _user(db, "bob", 0)
    _cfg(db, "points_transfer_fee_pct", 0)

    _drain_before_first_points_update(engine, sender.id)
    with pytest.raises(ValueError):
        economy.transfer_points_core(db, sender, "bob", 100)
    assert _balance(db, sender.id) >= 0
    assert _balance(db, bob.id) == 0


def test_transfer_fee_shortfall_rolls_back_principal(env):
    """本金扣完后手续费不够（并发花掉）：整笔回滚，不能只扣本金"""
    engine, db = env
    sender = _user(db, "alice", 105)  # 100 + 5% 手续费 = 105，预检通过
    _user(db, "bob", 0)
    _drain_before_first_points_update(engine, sender.id, to=104)  # 并发花掉 1 分
    with pytest.raises(ValueError):
        economy.transfer_points_core(db, sender, "bob", 100)
    # 模拟的「并发扣分」与被测事务在同一连接上，会随回滚一起撤销；关键是整笔不生效
    assert _balance(db, sender.id) >= 0
    assert db.query(models.PointsLog).count() == 0
    assert _balance(db, db.query(models.WebUser.id).filter_by(username="bob").scalar()) == 0


# ---------- 发红包 ----------

def test_send_redpacket_no_double_spend(env):
    from backend import welfare_redpacket as rp

    engine, db = env
    _cfg(db, "redpacket_fee_pct", 0)
    sender = _user(db, "carol", 100)
    _drain_before_first_points_update(engine, sender.id)
    with pytest.raises(ValueError):
        rp.send_packet(db, sender, 100, 5)
    assert _balance(db, sender.id) >= 0
    assert db.query(models.RedPacket).count() == 0
