#!/usr/bin/env python3
"""订单关单与退款冒烟测试（v2.9.0）

要解决的问题：订单此前只能「标记已支付」，**不能关、也不能退**。线下多转了一笔、
用户点错套餐、支付回调把它搞重复了——后台一点办法都没有，只能去改数据库。
这一版把「关单」与「退款」做成一等公民，重点是**退款必须按账本精确冲正**：

1. **关单只针对未支付订单**：`pending → closed`，不碰权益、不打扰用户；
   已支付订单走退款，重复关单 / 对已支付订单关单都要被拒；
2. **退款按账本冲正**：充值退款扣回的是当时**实际发放**的积分（`PointsLog.ref_id =
   recharge:{order_id}`），不是按订单金额重算；同时撤回邀请人那笔返利
   （`rebate:{order_id}`）——只退买家不退返利，等于站点为一次退款付两遍钱；
3. **余额不够不硬扣**：默认拒绝并回报当前余额，管理员显式 `allow_negative=true`
   才允许扣成负数（客服先退钱后追账的场景）；
4. **订阅退款回滚天数**：按履约时记下的 `subscription_id` / `days_granted` 精确回滚；
   回滚后已过期则置 `cancelled`（真实撤销，与自然到期不是一回事），
   若用户还有别的来源的天数则保持生效中；
5. **退过的订单不能再被履约**：晚到/重放的支付回调与「补单」都不能把退过的订单再发一次货；
6. **留痕与可见性**：订单带 `refunded_at` / `refund_reason`，写审计，
   用户收到站内信、用户端订单列表能看到状态与原因；管理端有退款/关单记录列表；
7. **鉴权**：普通用户与未登录都碰不到这些接口。

用法：python scripts/smoke_test_refunds.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "e2e-test-secret-key-not-for-production"

WORK = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(WORK, 'refunds.db')}"

from datetime import datetime, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from backend import models, realms  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.security import hash_password  # noqa: E402

init_db()

from backend.main import app  # noqa: E402

client = TestClient(app)

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


# ==================== 播种 ====================

with SessionLocal() as db:
    realm = realms.active_realm(db)
    staff = models.WebUser(username="refund_staff", password_hash=hash_password("staffpass123"),
                           is_staff=True, is_active=True)
    buyer = models.WebUser(username="refund_buyer", password_hash=hash_password("buyerpass123"),
                           is_active=True, points=0)
    inviter = models.WebUser(username="refund_inviter", password_hash=hash_password("invpass123"),
                             is_active=True, points=0)
    db.add_all([staff, buyer, inviter])
    db.commit()

    # 邀请关系（返利 10%）：退款必须把邀请人那笔返利一起撤回
    code = models.InvitationCode(code="REFUNDCODE", user_id=inviter.id)
    db.add(code)
    db.commit()
    db.add(models.InvitationRecord(inviter_id=inviter.id, invitee_id=buyer.id, code_id=code.id))
    db.add(models.SystemConfig(key="invitation_enabled", value="true"))
    db.add(models.SystemConfig(key="invitation_rebate_percent", value="10"))

    # price 用于返利计算（订单金额 × 百分比），所以给个整数值让返利可断言：100 × 10% = 10
    pkg = models.RechargePackage(name="100 积分包", amount=100, price=100, bonus=0, is_active=True)
    plan = models.SubscriptionPlan(name="月卡", price=30, duration_days=30,
                                   realm_id=realm.id, is_active=True)
    db.add_all([pkg, plan])
    db.commit()

    realm_id, plan_id, pkg_id = realm.id, plan.id, pkg.id
    buyer_id, inviter_id = buyer.id, inviter.id


def make_recharge_order(order_id: str) -> None:
    with SessionLocal() as db:
        db.add(models.RechargeOrder(order_id=order_id, user_id=buyer_id, package_id=pkg_id,
                                    amount=100, price=100, payment_method="alipay",
                                    status="pending"))
        db.commit()


def make_subscription_order(order_id: str) -> None:
    with SessionLocal() as db:
        db.add(models.SubscriptionOrder(order_id=order_id, user_id=buyer_id, plan_id=plan_id,
                                        item_name="月卡", amount=30, payment_method="alipay",
                                        status="pending"))
        db.commit()


def points_of(user_id: int) -> int:
    with SessionLocal() as db:
        return int(db.query(models.WebUser.points).filter(
            models.WebUser.id == user_id).scalar() or 0)


def order_row(order_id: str):
    with SessionLocal() as db:
        row = db.query(models.RechargeOrder).filter(
            models.RechargeOrder.order_id == order_id).first()
        if row:
            return row
        return db.query(models.SubscriptionOrder).filter(
            models.SubscriptionOrder.order_id == order_id).first()


def station_titles(user_id: int) -> list[str]:
    with SessionLocal() as db:
        return [m.title for m in db.query(models.StationMessage).filter(
            models.StationMessage.to_user_id == user_id).order_by(models.StationMessage.id).all()]


def subscriptions_of(user_id: int) -> int:
    """该用户**生效中**的订阅条数（套餐被删 / 用户被删时不该变多）"""
    with SessionLocal() as db:
        return db.query(models.UserSubscription).filter(
            models.UserSubscription.user_id == user_id,
            models.UserSubscription.status == "active",
        ).count()


def ledger(user_id: int, type_: str) -> list:
    with SessionLocal() as db:
        return db.query(models.PointsLog).filter(
            models.PointsLog.user_id == user_id,
            models.PointsLog.type == type_).all()


r = client.post("/api/user/auth/login", json={"username": "refund_staff", "password": "staffpass123"})
check("管理员登录成功", r.status_code == 200, f"status={r.status_code}")
ADMIN_H = {"Authorization": f"Bearer {r.json()['access_token']}"}

r = client.post("/api/user/auth/login", json={"username": "refund_buyer", "password": "buyerpass123"})
check("普通用户登录成功", r.status_code == 200, f"status={r.status_code}")
USER_H = {"Authorization": f"Bearer {r.json()['access_token']}"}

# ==================== 1. 关单 ====================

print("\n--- 关单：未支付订单作废 ---")

make_recharge_order("RC-CLOSE-1")
r = client.post("/api/admin/economy/orders/RC-CLOSE-1/close", headers=ADMIN_H)
check("可关闭待支付订单", r.status_code == 200 and r.json()["status"] == "closed",
      f"status={r.status_code} {r.text[:120]}")
row = order_row("RC-CLOSE-1")
check("订单记为已关闭并带时间", row.status == "closed" and row.closed_at is not None)
check("关单不碰积分", points_of(buyer_id) == 0)
check("关单不打扰用户（他并没付钱）", "↩️ 订单已退款" not in station_titles(buyer_id))

r = client.post("/api/admin/economy/orders/RC-CLOSE-1/close", headers=ADMIN_H)
check("重复关单被拒", r.status_code == 400, f"status={r.status_code}")

r = client.post("/api/admin/economy/orders/RC-CLOSE-1/refund", headers=ADMIN_H, json={"reason": "x"})
check("已关闭订单不能退款", r.status_code == 400, f"status={r.status_code} {r.text[:80]}")

r = client.post("/api/admin/economy/orders/NOT-EXIST/close", headers=ADMIN_H)
check("不存在的订单返回 404", r.status_code == 404, f"status={r.status_code}")

# ==================== 2. 充值退款：按账本精确冲正 + 撤回返利 ====================

print("\n--- 充值退款：扣回实发积分 + 撤回邀请人返利 ---")

make_recharge_order("RC-REFUND-1")
r = client.post("/api/admin/economy/orders/RC-REFUND-1/mark-paid", headers=ADMIN_H)
check("补单发货成功", r.status_code == 200, f"status={r.status_code} {r.text[:100]}")
check("买家到账 100 积分", points_of(buyer_id) == 100, str(points_of(buyer_id)))
check("邀请人拿到 10% 返利（10 积分）", points_of(inviter_id) == 10, str(points_of(inviter_id)))
check("返利按订单金额算，不是按积分数量算",
      len(ledger(inviter_id, "rebate")) == 1 and int(ledger(inviter_id, "rebate")[0].amount) == 10,
      str([int(x.amount) for x in ledger(inviter_id, "rebate")]))

r = client.post("/api/admin/economy/orders/RC-REFUND-1/refund", headers=ADMIN_H,
                json={"reason": "线下重复付款"})
body = r.json() if r.status_code == 200 else {}
check("退款成功", r.status_code == 200, f"status={r.status_code} {r.text[:160]}")
check("按账本扣回 100 积分", body.get("revoked_points") == 100, str(body))
check("买家余额归零", points_of(buyer_id) == 0, str(points_of(buyer_id)))
check("邀请人返利被撤回", body.get("rebate_reversed") == 10 and points_of(inviter_id) == 0,
      f"{body.get('rebate_reversed')} / {points_of(inviter_id)}")

row = order_row("RC-REFUND-1")
check("订单记为已退款并留原因", row.status == "refunded"
      and row.refunded_at is not None and row.refund_reason == "线下重复付款",
      f"{row.status} / {row.refund_reason}")

check("积分账本有冲正流水", len(ledger(buyer_id, "refund")) == 1, str(ledger(buyer_id, "refund")))
check("返利撤回也进了账本", len(ledger(inviter_id, "refund")) == 1)
check("用户收到退款站内信", "↩️ 订单已退款" in station_titles(buyer_id), str(station_titles(buyer_id)))
with SessionLocal() as db:
    kinds = [m.message_type for m in db.query(models.StationMessage).filter(
        models.StationMessage.to_user_id == buyer_id,
        models.StationMessage.title == "↩️ 订单已退款").all()]
check("退款归到 economy 类（不复用 subscription.expired 语义）",
      kinds and all(k == "economy" for k in kinds), str(kinds))

r = client.post("/api/admin/economy/orders/RC-REFUND-1/refund", headers=ADMIN_H, json={"reason": "再来一次"})
check("重复退款被拒", r.status_code == 400, f"status={r.status_code}")

# 退过的订单不能因为回调/补单再发一次货
r = client.post("/api/admin/economy/orders/RC-REFUND-1/mark-paid", headers=ADMIN_H)
check("退过的订单不再被补单履约", points_of(buyer_id) == 0 and points_of(inviter_id) == 0,
      f"buyer={points_of(buyer_id)} inviter={points_of(inviter_id)}")

with SessionLocal() as db:
    from backend.api.economy import _fulfill_order
    order = db.query(models.RechargeOrder).filter(
        models.RechargeOrder.order_id == "RC-REFUND-1").first()
    # _fulfill_order 是同步函数（async 路由用 run_in_threadpool 调它），这里直接调
    _fulfill_order(db, recharge_order=order)
    db.commit()
check("回调重放也不会二次发货", points_of(buyer_id) == 0, str(points_of(buyer_id)))

# ==================== 3. 余额不足：默认不硬扣 ====================

print("\n--- 余额不足：默认拒绝，显式允许才扣成负数 ---")

make_recharge_order("RC-REFUND-2")
client.post("/api/admin/economy/orders/RC-REFUND-2/mark-paid", headers=ADMIN_H)
check("第二笔充值到账", points_of(buyer_id) == 100, str(points_of(buyer_id)))

# 把余额花掉（管理员调账，模拟用户已经用掉积分），让余额不足以冲正
r = client.post(f"/api/admin/economy/users/{buyer_id}/points", headers=ADMIN_H,
                json={"amount": -60, "reason": "测试：用户已消耗积分"})
check("管理员可调账（花掉 60 积分）", r.status_code == 200, f"status={r.status_code} {r.text[:100]}")
balance_after_spend = points_of(buyer_id)
check("余额 40 不足以冲正 100", balance_after_spend == 40, str(balance_after_spend))

r = client.post("/api/admin/economy/orders/RC-REFUND-2/refund", headers=ADMIN_H, json={"reason": "误购"})
check("余额不足时默认拒绝退款", r.status_code == 400, f"status={r.status_code} {r.text[:160]}")
check("拒绝时把当前余额告诉管理员", "积分" in r.text and str(balance_after_spend) in r.text, r.text[:160])
check("拒绝后订单未变", order_row("RC-REFUND-2").status == "paid", order_row("RC-REFUND-2").status)

r = client.post("/api/admin/economy/orders/RC-REFUND-2/refund", headers=ADMIN_H,
                json={"reason": "误购", "allow_negative": True})
check("允许负余额后退款成功", r.status_code == 200, f"status={r.status_code} {r.text[:160]}")
check("余额被扣成负数（先退款后追账）", points_of(buyer_id) == balance_after_spend - 100,
      str(points_of(buyer_id)))

# ==================== 4. 订阅退款：精确回滚天数 ====================

print("\n--- 订阅退款：按订单回滚天数 ---")

make_subscription_order("SO-REFUND-1")
r = client.post("/api/admin/economy/orders/SO-REFUND-1/mark-paid", headers=ADMIN_H)
check("订阅订单履约成功", r.status_code == 200, f"status={r.status_code} {r.text[:100]}")
row = order_row("SO-REFUND-1")
check("履约时记下了订阅与天数",
      row.subscription_id is not None and row.days_granted == 30,
      f"{row.subscription_id} / {row.days_granted}")

with SessionLocal() as db:
    sub = db.query(models.UserSubscription).filter(
        models.UserSubscription.id == row.subscription_id).first()
    end_before = sub.end_date

r = client.post("/api/admin/economy/orders/SO-REFUND-1/refund", headers=ADMIN_H,
                json={"reason": "用户申请退款"})
body = r.json() if r.status_code == 200 else {}
check("订阅退款成功", r.status_code == 200, f"status={r.status_code} {r.text[:160]}")
check("回滚了 30 天", body.get("revoked_days") == 30, str(body))

with SessionLocal() as db:
    sub = db.query(models.UserSubscription).filter(
        models.UserSubscription.id == row.subscription_id).first()
    check("到期时间精确回退 30 天",
          abs((end_before - sub.end_date).days) == 30,
          f"{end_before} → {sub.end_date}")
    check("回滚后已过期 → 状态置为 cancelled（真实撤销）", sub.status == "cancelled", sub.status)

check("退款后用户不再是会员", client.get("/api/user/auth/me", headers=USER_H).json()["is_vip"] is False)
check("用户收到订阅退款站内信", "↩️ 订单已退款" in station_titles(buyer_id))

# 用户还有别的来源的天数时：只回滚这一笔，不整单撤销
print("\n--- 订阅退款：用户还有别的天数时保持生效 ---")

with SessionLocal() as db:
    # 先手动给 60 天（比如卡码发的），再买 30 天
    db.add(models.UserSubscription(user_id=buyer_id, plan_id=plan_id, realm_id=realm_id,
                                   start_date=datetime.now(),
                                   end_date=datetime.now() + timedelta(days=60),
                                   status="active"))
    db.commit()

make_subscription_order("SO-REFUND-2")
client.post("/api/admin/economy/orders/SO-REFUND-2/mark-paid", headers=ADMIN_H)
with SessionLocal() as db:
    row2 = db.query(models.SubscriptionOrder).filter(
        models.SubscriptionOrder.order_id == "SO-REFUND-2").first()
    sub2 = db.query(models.UserSubscription).filter(
        models.UserSubscription.id == row2.subscription_id).first()
    end_before2 = sub2.end_date

r = client.post("/api/admin/economy/orders/SO-REFUND-2/refund", headers=ADMIN_H,
                json={"reason": "重复购买"})
check("有剩余天数时可退款", r.status_code == 200, f"status={r.status_code} {r.text[:120]}")
with SessionLocal() as db:
    sub2 = db.query(models.UserSubscription).filter(
        models.UserSubscription.id == row2.subscription_id).first()
    check("只回滚这一笔的 30 天", abs((end_before2 - sub2.end_date).days) == 30,
          f"{end_before2} → {sub2.end_date}")
    check("仍有剩余天数 → 保持生效中", sub2.status == "active", sub2.status)
check("用户仍是会员", client.get("/api/user/auth/me", headers=USER_H).json()["is_vip"] is True)

# 不退权益（只改状态）的选项
print("\n--- 退款可选不回滚权益（仅记账）---")

make_recharge_order("RC-REFUND-3")
client.post("/api/admin/economy/orders/RC-REFUND-3/mark-paid", headers=ADMIN_H)
balance_before = points_of(buyer_id)
r = client.post("/api/admin/economy/orders/RC-REFUND-3/refund", headers=ADMIN_H,
                json={"reason": "客服补偿", "revoke_entitlement": False})
check("可只退款不回滚权益（补偿场景）", r.status_code == 200 and r.json()["revoked_points"] == 0,
      f"status={r.status_code} {r.text[:120]}")
check("余额未变", points_of(buyer_id) == balance_before, str(points_of(buyer_id)))

# ==================== 5. 留痕 / 记录列表 / 用户端可见性 ====================

print("\n--- 留痕与可见性 ---")

r = client.get("/api/admin/economy/refunds", headers=ADMIN_H)
check("可读退款/关单记录", r.status_code == 200, f"status={r.status_code}")
records = r.json()["records"]
ids = {x["order_id"] for x in records}
check("记录里包含退款与关单两类", "RC-REFUND-1" in ids and "RC-CLOSE-1" in ids, str(sorted(ids)))
check("记录带原因与用户名",
      all(x.get("username") for x in records) and
      any(x["order_id"] == "RC-REFUND-1" and x["reason"] == "线下重复付款" for x in records),
      str(records[:2]))

with SessionLocal() as db:
    logs = db.query(models.AdminLog).filter(
        models.AdminLog.action.in_(("economy_refund_order", "economy_close_order"))).all()
    check("关单与退款都写了审计", len(logs) >= 4, f"count={len(logs)}")

r = client.get("/api/user/economy/payment/orders", headers=USER_H)
check("用户端订单列表可读", r.status_code == 200, f"status={r.status_code}")
refunded = [o for o in r.json()["orders"] if o["order_id"] == "RC-REFUND-1"]
check("用户端能看到退款状态与原因",
      bool(refunded) and refunded[0]["status"] == "refunded"
      and refunded[0]["refund_reason"] == "线下重复付款",
      str(refunded[:1]))

# ==================== 6. 鉴权 ====================

print("\n--- 鉴权 ---")

check("未登录不能关单",
      client.post("/api/admin/economy/orders/RC-CLOSE-1/close").status_code in (401, 403))
check("普通用户不能关单",
      client.post("/api/admin/economy/orders/RC-CLOSE-1/close", headers=USER_H).status_code in (401, 403))
check("普通用户不能退款",
      client.post("/api/admin/economy/orders/RC-REFUND-1/refund", headers=USER_H,
                  json={"reason": "x"}).status_code in (401, 403))
check("普通用户看不到退款记录",
      client.get("/api/admin/economy/refunds", headers=USER_H).status_code in (401, 403))

# ==================== 7. 支付回调：金额必须与订单对得上 ====================

# 验签只证明「这条通知来自网关」，不证明钱数对不对。
# 旧实现只看验签 + 订单号，回调报 0.01 元也照样发 100 积分。
# 这里用**独立的买家**，不动上面那些积分断言。

print("\n--- 支付回调：金额核对 ---")

from backend.api.economy import _yipay_sign  # noqa: E402

GATEWAY_KEY = "refund-notify-key"
with SessionLocal() as db:
    for key, value in (("payment_partner_key", GATEWAY_KEY), ("payment_partner_id", "1001")):
        row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if row:
            row.value = value
        else:
            db.add(models.SystemConfig(key=key, value=value))
    notify_buyer = models.WebUser(username="refund_notify_buyer",
                                  password_hash=hash_password("notifypass123"),
                                  is_active=True, points=0)
    db.add(notify_buyer)
    db.commit()
    notify_buyer_id = notify_buyer.id


def make_notify_order(order_id: str, price: str = "100.00") -> None:
    with SessionLocal() as db:
        db.add(models.RechargeOrder(order_id=order_id, user_id=notify_buyer_id, package_id=pkg_id,
                                    amount=100, price=Decimal(price), payment_method="alipay",
                                    status="pending"))
        db.commit()


def notify_call(order_id: str, money: str | None, key: str = GATEWAY_KEY):
    params = {
        "pid": "1001", "trade_no": "T-NOTIFY", "out_trade_no": order_id,
        "type": "alipay", "name": "积分充值", "trade_status": "TRADE_SUCCESS",
    }
    if money is not None:
        params["money"] = money
    params["sign"] = _yipay_sign(params, key)
    params["sign_type"] = "MD5"
    return client.get("/api/user/economy/payment/notify", params=params)


make_notify_order("RC-NOTIFY-LOW")
r = notify_call("RC-NOTIFY-LOW", "0.01")
check("少付钱的回调被拒（fail）", r.text.strip() == "fail", f"{r.status_code} {r.text[:60]}")
check("被拒后订单仍未支付", order_row("RC-NOTIFY-LOW").status == "pending",
      order_row("RC-NOTIFY-LOW").status)
check("被拒后不发货（积分没动）", points_of(notify_buyer_id) == 0, str(points_of(notify_buyer_id)))

make_notify_order("RC-NOTIFY-HIGH")
r = notify_call("RC-NOTIFY-HIGH", "100.01")
check("多付/报错金额也不放行（必须精确相等）", r.text.strip() == "fail", f"{r.text[:60]}")
check("依然未发货", points_of(notify_buyer_id) == 0, str(points_of(notify_buyer_id)))

make_notify_order("RC-NOTIFY-EXACT")
r = notify_call("RC-NOTIFY-EXACT", "100.00")
check("金额对得上就发货", r.text.strip() == "success", f"{r.text[:60]}")
check("订单已支付且积分到账", order_row("RC-NOTIFY-EXACT").status == "paid"
      and points_of(notify_buyer_id) == 100, f"{points_of(notify_buyer_id)}")

# 网关没带 money 的旧口径：只记日志，不能把正常付款卡死
make_notify_order("RC-NOTIFY-NOMONEY")
r = notify_call("RC-NOTIFY-NOMONEY", None)
check("回调未带金额时仍按订单发货（兼容旧网关）",
      r.text.strip() == "success" and points_of(notify_buyer_id) == 200,
      f"{r.text[:60]} / {points_of(notify_buyer_id)}")

make_notify_order("RC-NOTIFY-BADSIGN")
r = notify_call("RC-NOTIFY-BADSIGN", "100.00", key="wrong-key")
check("错密钥的回调仍被拦（验签之前）", r.text.strip() == "fail" and points_of(notify_buyer_id) == 200,
      str(points_of(notify_buyer_id)))


# ==================== 7. 履约缺料：套餐/用户被删时必须 fail（不能静默 success）====================

print("\n--- 履约缺料：下单后套餐被删 ---")

# 旧实现：`_fulfill_order` 里 `if user and plan:` 不成立就什么都不做，
# 但订单已经被 `_claim_order` 原子标成 paid、优惠券还会被 consume——
# 用户付了钱、订单显示已支付、权益一点没到，还没有任何报错。
# 现在抛 FulfillmentError → 回调回滚并返回 fail（网关会重试 / 转人工）。

from datetime import datetime as _dt  # noqa: E402

from backend import coupons as coupons_mod  # noqa: E402


def make_coupon_usage(order_id: str, user_id: int) -> int:
    """造一条「已预订」的优惠券额度（真实链路由 coupons.reserve 产生）"""
    with SessionLocal() as db:
        coupon = models.CouponCode(code=f"COUP-{order_id}", kind="subscription",
                                   discount_type="fixed", value=5, max_uses=10,
                                   use_count=1, is_active=True)
        db.add(coupon)
        db.flush()
        usage = models.CouponUsage(coupon_id=coupon.id, user_id=user_id, order_id=order_id,
                                   kind="subscription", status=coupons_mod.RESERVED,
                                   list_price=Decimal("30.00"), discount_amount=Decimal("5.00"),
                                   paid_amount=Decimal("25.00"))
        db.add(usage)
        db.commit()
        return usage.id


def make_doomed_subscription_order(order_id: str, *, user_id: int, plan_id_) -> int:
    usage_id = make_coupon_usage(order_id, user_id)
    with SessionLocal() as db:
        db.add(models.SubscriptionOrder(
            order_id=order_id, user_id=user_id, plan_id=plan_id_, item_name="限时套餐",
            amount=Decimal("25.00"), payment_method="alipay", status="pending",
            coupon_usage_id=usage_id,
        ))
        db.commit()
    return usage_id


# 7.1 套餐在下单之后被删掉
with SessionLocal() as db:
    doomed_plan = models.SubscriptionPlan(name="即将下架的套餐", price=30, duration_days=30,
                                         is_active=True, realm_id=realm_id)
    db.add(doomed_plan)
    db.commit()
    doomed_plan_id = doomed_plan.id

doomed_order = "SO-NOTIFY-NOPLAN"
make_doomed_subscription_order(doomed_order, user_id=notify_buyer_id, plan_id_=doomed_plan_id)
before_subs = subscriptions_of(notify_buyer_id)

with SessionLocal() as db:
    db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == doomed_plan_id).delete(synchronize_session=False)
    db.commit()

r = notify_call(doomed_order, "25.00")
check("套餐被删后回调返回 fail（不再静默 success）", r.text.strip() == "fail",
      f"{r.status_code} {r.text[:80]}")
check("缺料时订单保持未支付（没有被标成 paid）",
      order_row(doomed_order).status == "pending", str(order_row(doomed_order).status))
check("缺料时不给用户发订阅", subscriptions_of(notify_buyer_id) == before_subs,
      f"{before_subs} -> {subscriptions_of(notify_buyer_id)}")
with SessionLocal() as db:
    usage = db.query(models.CouponUsage).filter(
        models.CouponUsage.order_id == doomed_order).first()
check("缺料时优惠券额度没有被 consume（还留在 reserved）",
      usage is not None and usage.status == coupons_mod.RESERVED,
      f"status={getattr(usage, 'status', None)}")

# 7.2 用户在下单之后被删（订阅订单指向一个不存在的用户）
orphan_order = "SO-NOTIFY-NOUSER"
with SessionLocal() as db:
    ghost = models.WebUser(username="refund_ghost", password_hash="x", is_active=True)
    db.add(ghost)
    db.commit()
    ghost_id = ghost.id
    db.add(models.SubscriptionOrder(
        order_id=orphan_order, user_id=ghost_id, plan_id=plan_id, item_name="月卡",
        amount=Decimal("30.00"), payment_method="alipay", status="pending",
    ))
    db.commit()
    db.query(models.WebUser).filter(models.WebUser.id == ghost_id).delete(
        synchronize_session=False)
    db.commit()

r = notify_call(orphan_order, "30.00")
check("用户被删后回调返回 fail", r.text.strip() == "fail", f"{r.status_code} {r.text[:80]}")
check("用户被删时订单保持未支付", order_row(orphan_order).status == "pending",
      str(order_row(orphan_order).status))

# 7.3 同一笔缺料订单：人工补单（后台）也要给出可读的 400，而不是 500
r = client.post(f"/api/admin/economy/orders/{doomed_order}/mark-paid", headers=ADMIN_H,
                json={})
check("人工补单遇到缺料返回 400 + 说明（不是 500）",
      r.status_code == 400 and "履约失败" in r.text, f"{r.status_code} {r.text[:120]}")
check("补单失败后订单仍未支付", order_row(doomed_order).status == "pending",
      str(order_row(doomed_order).status))

# 7.4 修好之后（套餐重建 + 补单）履约应当恢复正常：这一条保证上面的改动没有把正常路径挡掉
with SessionLocal() as db:
    fixed_plan = models.SubscriptionPlan(name="恢复的套餐", price=25, duration_days=30,
                                         is_active=True, realm_id=realm_id)
    db.add(fixed_plan)
    db.commit()
    db.query(models.SubscriptionOrder).filter(
        models.SubscriptionOrder.order_id == doomed_order
    ).update({"plan_id": fixed_plan.id}, synchronize_session=False)
    db.commit()

r = notify_call(doomed_order, "25.00")
check("缺料修好后回调恢复正常（success）", r.text.strip() == "success",
      f"{r.status_code} {r.text[:80]}")
check("修好后订单支付并发出订阅",
      order_row(doomed_order).status == "paid"
      and subscriptions_of(notify_buyer_id) == before_subs + 1,
      f"{order_row(doomed_order).status} / {subscriptions_of(notify_buyer_id)}")

print("\n" + "=" * 60)
if failures:
    print(f"❌ {len(failures)}/{checks} 项失败：")
    for name in failures:
        print(f"   - {name}")
    sys.exit(1)
print(f"✅ 订单退款/关单冒烟测试全部通过（{checks} 项）")
