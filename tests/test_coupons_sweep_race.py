"""sweep_stale_reservations 与支付回调的并发竞态回归测试（TOCTOU）

时序：
  1. sweep 扫到订单仍是 pending、核销记录仍是 RESERVED；
  2. 支付回调把同一订单置为 paid、核销记录置为 CONSUMED 并提交；
  3. 旧实现拿「扫描时的旧值」无条件把订单写回 closed，release() 又把刚消费的额度退回去，
     订单 / 支付 / 额度三处对账不一致。

修复后第 3 步的条件 UPDATE 必须拿到 0 行，refresh 后按 paid 收尾。
"""

import decimal
import sys
from datetime import datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, ".")

from backend import coupons, models  # noqa: E402

# 状态常量在 coupons / models 里都可能定义，按可用来源取
RESERVED = getattr(coupons, "RESERVED", None) or getattr(models, "RESERVED", None)
CONSUMED = getattr(coupons, "CONSUMED", None) or getattr(models, "CONSUMED", None)

ORDER_ID = "RACE-ORDER-0001"


def _placeholder(col):
    """按列类型给非空且无默认值的列造一个占位值"""
    try:
        py = col.type.python_type
    except (AttributeError, NotImplementedError):  # pragma: no cover
        py = str
    if py is int:
        return 1
    if py is float:
        return 1.0
    if py is bool:
        return False
    if py is decimal.Decimal:
        return decimal.Decimal("1.00")
    if py is datetime:
        return datetime.now()
    return f"t_{col.name}"


def _make(model, **overrides):
    """按表定义补齐非空字段，避免测试与 models.py 的字段演进强耦合"""
    kwargs = {}
    for col in model.__table__.columns:
        if col.name in overrides or col.primary_key:
            continue
        if col.nullable or col.default is not None or col.server_default is not None:
            continue
        kwargs[col.name] = _placeholder(col)
    kwargs.update(overrides)
    return model(**kwargs)


def test_sweep_keeps_order_paid_after_concurrent_payment(tmp_path):
    # 文件库：engine.begin() 的另一个连接才能看到已提交的数据（:memory: 做不到）
    engine = create_engine(f"sqlite:///{tmp_path / 'coupons_sweep_race.db'}")
    # 只建用到的表，SQLite 默认不校验外键，未建的表不影响
    for model in (models.WebUser, models.RechargePackage, models.CouponCode,
                  models.CouponUsage, models.RechargeOrder):
        model.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)

    stale_at = datetime.now() - timedelta(hours=72)

    # ---- 造数：用户 + 充值套餐 + 优惠券 + pending 订单 + RESERVED 核销记录 ----
    setup = Session()
    try:
        user = _make(models.WebUser)
        package = _make(models.RechargePackage)
        coupon = _make(models.CouponCode, use_count=1)
        setup.add_all([user, package, coupon])
        setup.commit()

        user_id, package_id, coupon_id = user.id, package.id, coupon.id
        order = _make(models.RechargeOrder, order_id=ORDER_ID, user_id=user_id,
                      package_id=package_id, amount=1000,
                      price=decimal.Decimal("9.90"), status="pending")
        usage_kwargs = {"order_id": ORDER_ID, "status": RESERVED, "created_at": stale_at}
        # 核销记录指向优惠券的外键字段名各版本可能不同，存在才显式指过去
        for fk_name in ("coupon_id", "coupon_code_id", "code_id"):
            if fk_name in models.CouponUsage.__table__.columns:
                usage_kwargs[fk_name] = coupon_id
        setup.add_all([order, _make(models.CouponUsage, **usage_kwargs)])
        setup.commit()
    finally:
        setup.close()

    reader = Session()
    # 先把 pending 的订单读进 session 缓存：sweep 后面再查同一行会直接复用这份旧值
    cached = reader.query(models.RechargeOrder).filter_by(order_id=ORDER_ID).first()
    assert cached is not None and cached.status == "pending"

    # ---- 关键：sweep 写回订单之前，用另一个连接模拟支付回调并提交 ----
    fired = {"done": False}

    def pay_just_before_sweep_writes(conn, cursor, statement, parameters, context, executemany):
        if fired["done"]:
            return
        head = statement.lstrip().upper()
        if not head.startswith("UPDATE") or "recharge_orders" not in statement:
            return
        fired["done"] = True
        with engine.begin() as other:
            other.execute(models.RechargeOrder.__table__.update().where(
                models.RechargeOrder.__table__.c.order_id == ORDER_ID
            ).values(status="paid"))
            other.execute(models.CouponUsage.__table__.update().where(
                models.CouponUsage.__table__.c.order_id == ORDER_ID
            ).values(status=CONSUMED))

    event.listen(engine, "before_cursor_execute", pay_just_before_sweep_writes)
    try:
        summary = coupons.sweep_stale_reservations(reader, hours=48)
        reader.commit()  # 后台线程在 sweep 之后提交
    finally:
        event.remove(engine, "before_cursor_execute", pay_just_before_sweep_writes)
        reader.close()

    assert fired["done"], "sweep 没走到写回订单的分支，竞态没被复现"
    assert summary["scanned"] == 1

    # ---- 断言：订单仍是 paid、核销记录仍是 CONSUMED、额度没有被退回 ----
    check = Session()
    try:
        assert check.query(models.RechargeOrder).filter_by(
            order_id=ORDER_ID).one().status == "paid"
        assert check.query(models.CouponUsage).filter_by(
            order_id=ORDER_ID).one().status == CONSUMED
        assert check.query(models.CouponCode).filter_by(id=coupon_id).one().use_count == 1
    finally:
        check.close()
