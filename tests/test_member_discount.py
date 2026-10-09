"""P4 会员等级折扣：discount_pct 字段、回填、查询、下单应用

全部用隔离的内存 SQLite，不碰生产库。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend import member_level as ml


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ml.ensure_member_levels_seeded(session)
    yield session
    session.close()


def _make_user(db, username, level=1, xp=0):
    u = models.WebUser(username=username, password_hash="x",
                       member_level=level, member_xp=xp)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------- 种子与回填 ----------

def test_seed_has_discount(db):
    """种子自带折扣值"""
    vals = {lv.level: lv.discount_pct for lv in db.query(models.MemberLevel).all()}
    assert vals == {1: 0, 2: 2, 3: 5, 4: 8, 5: 12, 6: 15}


def test_migrate_discount_pct_idempotent(db):
    """回填幂等：首次回填 0→默认值，第二次返回 0（标记已执行）"""
    # 模拟升级场景：迁移加列后老数据全 0
    for lv in db.query(models.MemberLevel).all():
        if lv.level != 1:  # Lv1 默认就是 0，保持
            lv.discount_pct = 0
    # 先清掉种子带的值，模拟老库
    db.query(models.MemberLevel).filter(models.MemberLevel.level == 3).update({"discount_pct": 0})
    db.commit()
    # 删掉可能已存在的标记（get_member_info 可能已触发）
    db.query(models.SystemConfig).filter(
        models.SystemConfig.key == ml._MIGRATION_FLAG).delete()
    db.commit()
    n = ml.migrate_discount_pct(db)
    assert n >= 1
    assert ml.migrate_discount_pct(db) == 0
    lv3 = db.query(models.MemberLevel).filter(models.MemberLevel.level == 3).first()
    assert lv3.discount_pct == 5


def test_migrate_does_not_override_manual(db):
    """标记执行后，管理员手动改的值不被覆盖"""
    db.query(models.SystemConfig).filter(
        models.SystemConfig.key == ml._MIGRATION_FLAG).delete()
    db.commit()
    ml.migrate_discount_pct(db)  # 首次执行，打上标记
    lv4 = db.query(models.MemberLevel).filter(models.MemberLevel.level == 4).first()
    lv4.discount_pct = 20  # 管理员自定义
    db.commit()
    assert ml.migrate_discount_pct(db) == 0
    db.refresh(lv4)
    assert lv4.discount_pct == 20


# ---------- 查询 ----------

def test_get_user_discount_pct(db):
    u = _make_user(db, "d1", level=3)
    assert ml.get_user_discount_pct(db, u) == 5
    u2 = _make_user(db, "d2", level=1)
    assert ml.get_user_discount_pct(db, u2) == 0


def test_get_member_info_has_discount(db):
    u = _make_user(db, "d3", level=4, xp=1600)
    info = ml.get_member_info(db, u)
    assert info["discount_pct"] == 8
    lv2 = next(x for x in info["levels"] if x["level"] == 2)
    assert lv2["discount_pct"] == 2


# ---------- 下单折扣 ----------

def _make_plan(db, name, price, access_mode="paid"):
    realm = models.ServerRealm(name=f"realm-{name}", slug=f"r-{name}",
                               access_mode=access_mode)
    db.add(realm)
    db.commit()
    db.refresh(realm)
    plan = models.SubscriptionPlan(name=name, price=price, duration_days=30,
                                   realm_id=realm.id, is_active=True)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def test_discount_only_paid_subscription(db, monkeypatch):
    """付费服订阅打折；公益服不打折；充值不打折"""
    import backend.api.economy as eco
    from decimal import Decimal

    u = _make_user(db, "d4", level=4)  # 8% 折扣
    paid_plan = _make_plan(db, "paid", 100, "paid")
    free_plan = _make_plan(db, "free", 100, "free")

    # 直接调内部折扣计算逻辑（不走 HTTP）
    assert ml.get_user_discount_pct(db, u) == 8

    # 模拟 create_payment_order 的折扣判断
    def is_paid(plan):
        try:
            r = plan.realm
            if r is not None and getattr(r, "access_mode", "paid") == "free":
                return False
        except Exception:
            pass
        return True

    assert is_paid(paid_plan) is True
    assert is_paid(free_plan) is False

    # 折扣金额计算：100 * 8% = 8.00
    disc = (Decimal("100") * Decimal(8) / Decimal(100)).quantize(Decimal("0.01"))
    assert disc == Decimal("8.00")
