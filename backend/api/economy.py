"""
用户经济系统 API：每日签到 / 兑换码 / 支付下单 / 订单查询

端点（前缀 /api/user/economy）：
- GET  /checkin/status        查询今日签到状态、连签、奖励规则
- POST /checkin               每日签到（发积分，连续签到加成）
- GET  /points/log            积分流水（台账）
- GET  /exchange/config       公开的积分/订阅兑换奖励规则
- POST /exchange/redeem       兑换码核销（积分 / 订阅）
- GET  /payment/packages      充值套餐列表（公开）
- GET  /payment/plans         订阅套餐列表（公开）
- GET  /payment/methods       可用支付方式（按网关能力推导）
- GET  /payment/coupon/config 优惠券开关（关闭时用户端不显示优惠码输入框）
- POST /payment/coupon/quote  优惠码试算（能不能用、省多少、实付多少）
- POST /payment/order         创建支付订单（充值积分 / 购买订阅），返回支付跳转 URL
- GET  /payment/orders        我的订单列表
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend import coupons, models, realms
from backend.database import get_db
from backend.api.user import get_current_user
from backend.ratelimit import check_rate_limit, client_ip
from backend.security import resolve_jwt_user_id
from backend.notifications import notify_admin_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user/economy", tags=["用户端-经济系统"])

bearer_scheme_deps = None  # reserved


# ==================== 配置中心工具 ====================

def _get_config(db: Session, key: str, default: str) -> str:
    config = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return config.value if config and config.value is not None else default


def _get_int_config(db: Session, key: str, default: int) -> int:
    try:
        return int(_get_config(db, key, str(default)))
    except (TypeError, ValueError):
        return default


def _get_bool_config(db: Session, key: str, default: bool) -> bool:
    return _get_config(db, key, "true" if default else "false").strip().lower() == "true"


# ==================== 签到 ====================

def _today_start() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _add_points(
    db: Session, user: models.WebUser, amount: int,
    type_: str, description: str, ref_id: str | None = None,
) -> int:
    """加积分并写台账（amount 可为负）

    用 SQL 级自增（`points = coalesce(points,0) + amount`）而不是 Python 读改写：
    后者在并发下会丢更新（两个请求各自读到同一旧余额，后提交的覆盖前者）。
    返回写入后的真实余额。
    """
    db.query(models.WebUser).filter(models.WebUser.id == user.id).update(
        {models.WebUser.points: func.coalesce(models.WebUser.points, 0) + amount},
        synchronize_session="fetch",
    )
    balance = int(
        db.query(models.WebUser.points).filter(models.WebUser.id == user.id).scalar() or 0
    )
    db.add(models.PointsLog(
        user_id=user.id,
        amount=amount,
        balance_after=balance,
        type=type_,
        description=description,
        ref_id=ref_id,
    ))
    return balance


def _checkin_rules(db: Session) -> dict:
    """签到奖励规则（管理端 SystemConfig 可调）"""
    return {
        "enabled": _get_bool_config(db, "checkin_enabled", True),
        "base_points": _get_int_config(db, "checkin_base_points", 5),
        "streak_bonus": _get_int_config(db, "checkin_streak_bonus", 2),
        "streak_max_bonus": _get_int_config(db, "checkin_streak_max_bonus", 10),
    }


class CheckinStatusResponse(BaseModel):
    enabled: bool
    checked_today: bool
    streak: int
    base_points: int
    streak_bonus: int
    streak_max_bonus: int
    points: int


@router.get("/checkin/status", response_model=CheckinStatusResponse)
def checkin_status(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = _today_start()
    checked = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == current_user.id,
        models.CheckinRecord.checkin_date >= today,
    ).first() is not None

    # 连签数：今日已签按当日记录，未签则按昨天回溯
    anchor = today
    if not checked:
        anchor = today - timedelta(days=1)
    last = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == current_user.id,
        models.CheckinRecord.checkin_date <= anchor,
    ).order_by(models.CheckinRecord.checkin_date.desc()).first()
    streak = last.streak if last else 0

    rules = _checkin_rules(db)
    return CheckinStatusResponse(
        enabled=rules["enabled"],
        checked_today=checked,
        streak=streak,
        base_points=rules["base_points"],
        streak_bonus=rules["streak_bonus"],
        streak_max_bonus=rules["streak_max_bonus"],
        points=current_user.points or 0,
    )


@router.post("/checkin")
async def do_checkin(
    request: Request,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """每日签到：基础积分 + 连签加成（封顶）"""
    allowed, _ = check_rate_limit(f"checkin:{current_user.id}", 5, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")

    rules = _checkin_rules(db)
    if not rules["enabled"]:
        raise HTTPException(status_code=403, detail="签到功能未开启")

    today = _today_start()
    exists = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == current_user.id,
        models.CheckinRecord.checkin_date >= today,
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="今天已经签到过啦")

    # 连签：昨天有记录则 +1，否则重置为 1
    yesterday_record = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == current_user.id,
        models.CheckinRecord.checkin_date >= today - timedelta(days=1),
        models.CheckinRecord.checkin_date < today,
    ).order_by(models.CheckinRecord.checkin_date.desc()).first()
    streak = (yesterday_record.streak + 1) if yesterday_record else 1

    bonus = min(rules["streak_bonus"] * (streak - 1), rules["streak_max_bonus"])
    reward = rules["base_points"] + bonus

    record = models.CheckinRecord(
        user_id=current_user.id,
        checkin_date=today,
        points_awarded=reward,
        streak=streak,
    )
    db.add(record)
    try:
        # 唯一索引 (user_id, checkin_date) 是并发防重的最后一道门：
        # 先 flush 让冲突在此处暴露，避免「先发积分、后落库失败」或直接 500
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="今天已经签到过啦")
    except OperationalError:
        # 数据库写锁竞争：没发奖也没落库，让客户端重试
        db.rollback()
        raise HTTPException(status_code=409, detail="签到请求冲突，请稍后重试")
    balance = _add_points(
        db, current_user, reward, "checkin",
        f"每日签到（连续 {streak} 天）", f"checkin:{today.strftime('%Y%m%d')}",
    )
    db.commit()

    await notify_admin_event(
        event_type="economy.checkin",
        user_id=current_user.id,
        title=f"📅 签到成功 +{reward} 积分",
        content=(f"已连续签到 {streak} 天，当前余额 {balance} 积分。"
                 f"\n明日再来看看，连签奖励更高！"),
    )
    return {
        "success": True,
        "points_awarded": reward,
        "streak": streak,
        "balance": balance,
        "message": f"签到成功，+{reward} 积分（连续 {streak} 天）",
    }


# ==================== 积分流水 ====================

@router.get("/points/log")
def points_log(
    limit: int = 50,
    offset: int = 0,
    type_filter: Optional[str] = None,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.PointsLog).filter(
        models.PointsLog.user_id == current_user.id
    )
    if type_filter:
        query = query.filter(models.PointsLog.type == type_filter)

    total = query.count()
    logs = query.order_by(models.PointsLog.created_at.desc()).offset(offset).limit(min(limit, 200)).all()
    return {
        "total": total,
        "balance": current_user.points or 0,
        "logs": [
            {
                "id": l.id,
                "amount": l.amount,
                "balance_after": l.balance_after,
                "type": l.type,
                "description": l.description,
                "ref_id": l.ref_id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


# ==================== 兑换码 ====================

def _grant_subscription(db: Session, user: models.WebUser, plan: models.SubscriptionPlan,
                        days: int, source: str, ref_id: str,
                        realm_id: int | None = None) -> models.UserSubscription:
    """发放订阅：**同一个服**已有有效订阅则顺延，否则新建

    订阅是一个服一个的：甲服的兑换码只能顺延甲服的会员，不能给乙服的会员加天数。

    `with_for_update()` 在 PostgreSQL 下是真正的行锁，避免同一用户并发发放
    （同时核销两张码 / 码与支付回调撞车）时两边都读到同一到期时间、互相覆盖；
    SQLite 会忽略它，但 SQLite 写入本身是库级串行的。
    """
    now = datetime.now()
    target_realm = realm_id if realm_id is not None else plan.realm_id
    query = db.query(models.UserSubscription).filter(
        models.UserSubscription.user_id == user.id,
        models.UserSubscription.status == "active",
        models.UserSubscription.end_date > now,
    )
    if target_realm is not None:
        query = query.filter(models.UserSubscription.realm_id == target_realm)
    active = query.order_by(models.UserSubscription.end_date.desc()).with_for_update().first()

    if active:
        active.end_date = active.end_date + timedelta(days=days)
        active.updated_at = now
        subscription = active
    else:
        subscription = models.UserSubscription(
            user_id=user.id,
            plan_id=plan.id,
            realm_id=target_realm if target_realm is not None else realms.active_realm_id(db),
            start_date=now,
            end_date=now + timedelta(days=days),
            status="active",
        )
        db.add(subscription)
        db.flush()
    return subscription


@router.get("/exchange/config")
async def exchange_config(db: Session = Depends(get_db)):
    return {
        "enabled": _get_bool_config(db, "exchange_enabled", True),
        "invitee_note": "被邀请注册的奖励自动发放",
    }


class RedeemRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)


@router.post("/exchange/redeem")
async def redeem_exchange_code(
    request: Request,
    req: RedeemRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """兑换码核销：points 型发积分；subscription 型发订阅"""
    allowed, _ = check_rate_limit(f"redeem:{current_user.id}", 10, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")

    if not _get_bool_config(db, "exchange_enabled", True):
        raise HTTPException(status_code=403, detail="兑换功能未开启")

    code_str = req.code.strip().upper()
    code = db.query(models.ExchangeCode).filter(
        models.ExchangeCode.code == code_str
    ).first()

    now = datetime.now()
    if code is None or not code.is_active or (code.expires_at and code.expires_at < now):
        raise HTTPException(status_code=400, detail="兑换码无效或已过期")

    # 先原子占位再去发奖：只有仍可用的兑换码才会被 +1，并发下第二个请求 rowcount=0，
    # 因此不会出现「同一张单次码被同时核销两次、发两份奖励」。
    try:
        claimed = (
            db.query(models.ExchangeCode)
            .filter(
                models.ExchangeCode.id == code.id,
                models.ExchangeCode.is_active.is_(True),
                or_(
                    models.ExchangeCode.expires_at.is_(None),
                    models.ExchangeCode.expires_at > now,
                ),
                or_(
                    models.ExchangeCode.max_uses.is_(None),
                    models.ExchangeCode.use_count < models.ExchangeCode.max_uses,
                ),
            )
            .update(
                {models.ExchangeCode.use_count: func.coalesce(models.ExchangeCode.use_count, 0) + 1},
                synchronize_session=False,
            )
        )
    except OperationalError:
        # SQLite 下读写事务升级失败（并发写入）：没发奖也没占位，让客户端重试
        db.rollback()
        raise HTTPException(status_code=409, detail="兑换码正在核销中，请稍后重试")
    if not claimed:
        db.rollback()
        raise HTTPException(status_code=400, detail="兑换码已用尽或已过期")

    # 占位成功后才读回详情：use_count 是 SQL 级自增，身份映射里的旧实例要 refresh，
    # 否则下面判断「用满停用」会拿到过期的 0
    db.refresh(code)

    result: dict = {"success": True}
    if code.type == "points":
        balance = _add_points(
            db, current_user, code.points_value, "exchange",
            f"兑换码 {code_str}", f"exchange:{code_str}",
        )
        result.update(reward_type="points", points=code.points_value, balance=balance,
                      message=f"兑换成功，+{code.points_value} 积分")
    elif code.type == "subscription":
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == code.plan_id
        ).first() if code.plan_id else None
        if not plan:
            # 已原子占位但无法履约：回滚，别白白吃掉一次使用次数
            db.rollback()
            raise HTTPException(status_code=400, detail="兑换码关联套餐不存在")
        subscription = _grant_subscription(
            db, current_user, plan, code.duration_days, "exchange", code_str,
            # 兑换码按它自己所属的服发会员（未标注时回退到套餐的服）
            realm_id=getattr(code, "realm_id", None) or plan.realm_id,
        )
        result.update(reward_type="subscription", plan_name=plan.name,
                      days=code.duration_days,
                      end_date=subscription.end_date.isoformat(),
                      message=f"兑换成功，「{plan.name}」× {code.duration_days} 天")
    else:
        db.rollback()
        raise HTTPException(status_code=400, detail="兑换码类型不支持")

    # 核销审计（use_count 已在上面原子 +1，这里只补使用者并处理用满停用）
    used = [i for i in str(code.used_by or "").split(",") if i.strip()]
    if str(current_user.id) not in used:
        used.append(str(current_user.id))
    code.used_by = ",".join(used)[:500]
    if code.max_uses and (code.use_count or 0) >= code.max_uses:
        code.is_active = False
    db.commit()

    await notify_admin_event(
        event_type="economy.redeem",
        user_id=current_user.id,
        title="🎁 兑换成功",
        content=result["message"],
    )
    return result


# ==================== 支付下单（易支付兼容网关） ====================

class PaymentMethod(BaseModel):
    id: str
    name: str
    enabled: bool


@router.get("/payment/methods", response_model=list[PaymentMethod])
async def payment_methods(db: Session = Depends(get_db)):
    methods = [
        PaymentMethod(id="alipay", name="支付宝", enabled=True),
        PaymentMethod(id="wxpay", name="微信支付", enabled=True),
    ]
    if _get_config(db, "payment_qqpay_enabled", "false").lower() == "true":
        methods.append(PaymentMethod(id="qqpay", name="QQ 钱包", enabled=True))
    return methods


@router.get("/payment/packages")
def payment_packages(db: Session = Depends(get_db)):
    """充值套餐（积分）"""
    if not _get_bool_config(db, "recharge_enabled", True):
        return {"enabled": False, "packages": []}
    packages = db.query(models.RechargePackage).filter(
        models.RechargePackage.is_active == True  # noqa: E712
    ).order_by(models.RechargePackage.sort_order).all()
    return {
        "enabled": True,
        "packages": [
            {
                "id": p.id, "name": p.name, "amount": p.amount,
                "bonus": p.bonus, "price": float(p.price),
                "is_popular": p.is_popular,
                "total_points": p.amount + p.bonus,
            }
            for p in packages
        ],
    }


@router.get("/payment/plans")
def payment_plans(realm_id: Optional[int] = None, db: Session = Depends(get_db)):
    """订阅套餐（购买订阅）

    套餐是一个服一个的：默认只展示**当前服**的可购套餐（``realm_id=0`` 看全部服）。
    用户买哪一份，会员就开在哪个服。

    同时下发该服的**接入方式**：公益服（``is_free``）不需要卖会员，用户端的钱包页
    据此把「开通会员」换成「公益服 · 免费开放」的说明，不再推付费引导。
    """
    if not _get_bool_config(db, "subscription_purchase_enabled", True):
        return {"enabled": False, "plans": []}
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope(db.query(models.SubscriptionPlan),
                         models.SubscriptionPlan.realm_id, scope_id)
    plans = query.filter(
        models.SubscriptionPlan.is_active == True  # noqa: E712
    ).order_by(models.SubscriptionPlan.sort_order).all()
    free = realms.is_free_realm(db, scope_id) if scope_id else False
    return {
        "enabled": True,
        "realm_id": scope_id,
        "access_mode": "free" if free else "paid",
        "is_free": free,
        "access_note": realms.access_note_of(db, scope_id) if scope_id else "",
        "plans": [
            {
                "id": p.id, "name": p.name, "description": p.description,
                "price": float(p.price), "duration_days": p.duration_days,
                "features": p.features, "is_popular": p.is_popular,
                "realm_id": p.realm_id,
                "realm_name": (p.realm.name if p.realm else ""),
            }
            for p in plans
        ],
    }


@router.get("/payment/coupon/config")
async def coupon_config(db: Session = Depends(get_db)):
    """优惠券开关：关闭时用户端不展示优惠码输入框，避免填了才报错"""
    return {"enabled": coupons.enabled(db)}


class CouponQuoteRequest(BaseModel):
    code: str = Field(..., description="用户填写的优惠码")
    kind: str = Field(..., description="recharge / subscription")
    item_id: int = Field(..., description="充值套餐ID 或 套餐ID")


@router.post("/payment/coupon/quote")
async def coupon_quote(
    req: CouponQuoteRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """优惠码试算（下单前预览）

    用 POST 而不是 GET：优惠码不该进访问日志/浏览器历史（与卡码预检同一考虑）。
    下单时走的是同一套 `coupons.quote`，不会出现「预览 8 折、实付全价」。
    """
    allowed, _ = check_rate_limit(f"coupon-quote:{current_user.id}", 30, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")
    return coupons.quote(db, user=current_user, code=req.code,
                         kind=req.kind, item_id=req.item_id)


class CreateOrderRequest(BaseModel):
    kind: str = Field(..., description="recharge=充值积分 / subscription=购买订阅")
    item_id: int = Field(..., description="充值套餐ID 或 套餐ID")
    payment_method: str = Field(default="alipay")
    coupon_code: str = Field(default="", description="优惠码（可空）；下单时占额度，付款转已用，关单/退款自动还回")


def _yipay_sign(params: dict, key: str) -> str:
    """易支付 MD5 签名：按 key ASCII 升序拼接 a=b&...&<key>"""
    filtered = {k: v for k, v in params.items()
                if v not in (None, "") and k != "sign" and k != "sign_type"}
    qs = urlencode(sorted(filtered.items()))
    return hashlib.md5(f"{qs}{key}".encode("utf-8")).hexdigest()


@router.post("/payment/order")
def create_payment_order(
    request: Request,
    req: CreateOrderRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建支付订单，返回易支付跳转 URL（epay 标准提交）"""
    allowed, _ = check_rate_limit(f"order:{current_user.id}", 10, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="下单过于频繁，请稍后再试")

    gateway = _get_config(db, "payment_gateway_url", "").strip().rstrip("/")
    pid = _get_config(db, "payment_partner_id", "").strip()
    key = _get_config(db, "payment_partner_key", "").strip()
    if not gateway or not pid or not key:
        raise HTTPException(status_code=503, detail="支付通道未配置，请联系管理员")

    site_url = _get_config(db, "site_url", "").strip().rstrip("/")
    notify_url = f"{site_url}/api/user/economy/payment/notify"
    return_url = f"{site_url}/wallet?paid=1"

    order_id = f"RB{int(time.time() * 1000)}{uuid.uuid4().hex[:6].upper()}"

    if req.kind == "recharge":
        if not _get_bool_config(db, "recharge_enabled", True):
            raise HTTPException(status_code=403, detail="充值功能未开启")
        package = db.query(models.RechargePackage).filter(
            models.RechargePackage.id == req.item_id,
            models.RechargePackage.is_active == True,  # noqa: E712
        ).first()
        if not package:
            raise HTTPException(status_code=404, detail="充值套餐不存在")
        item_name = f"积分充值 - {package.name}"
        amount = package.price
        order = models.RechargeOrder(
            order_id=order_id, user_id=current_user.id,
            package_id=package.id, amount=package.amount + package.bonus,
            price=amount, payment_method=req.payment_method, status="pending",
        )
    elif req.kind == "subscription":
        if not _get_bool_config(db, "subscription_purchase_enabled", True):
            raise HTTPException(status_code=403, detail="订阅购买未开启")
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == req.item_id,
            models.SubscriptionPlan.is_active == True,  # noqa: E712
        ).first()
        if not plan:
            raise HTTPException(status_code=404, detail="套餐不存在")
        item_name = f"订阅购买 - {plan.name}"
        amount = plan.price
        order = models.SubscriptionOrder(
            order_id=order_id, user_id=current_user.id,
            plan_id=plan.id, item_name=plan.name,
            amount=amount, payment_method=req.payment_method, status="pending",
        )
    else:
        raise HTTPException(status_code=400, detail="kind 必须是 recharge 或 subscription")

    # 优惠券：预览与下单共用 coupons.quote（同一套口径），下单即占额度
    list_price = Decimal(str(amount))
    discount_amount = Decimal("0.00")
    paid_amount = list_price
    preview = None
    coupon_code = (req.coupon_code or "").strip()
    if coupon_code:
        preview = coupons.quote(db, user=current_user, code=coupon_code,
                                kind=req.kind, item_id=req.item_id)
        discount_amount = Decimal(str(preview["discount_amount"]))
        paid_amount = Decimal(str(preview["paid_amount"]))
        coupon_code = preview["code"]

    # 订单上快照「原价 / 优惠 / 实付」，并让订单金额一律等于**实付**：
    # 对账、邀请返利比例、退款都以用户真付的钱为准，不能按原价算。
    order.list_price = list_price
    order.discount_amount = discount_amount
    if req.kind == "recharge":
        order.price = paid_amount
    else:
        order.amount = paid_amount

    db.add(order)
    if preview is not None:
        coupon = db.query(models.CouponCode).filter(
            models.CouponCode.id == preview["coupon_id"]).first()
        if coupon is None:
            raise HTTPException(status_code=400, detail="优惠码不存在")
        # 占额度（条件 UPDATE，并发也超不了总限）；失败则整笔下单回滚
        usage = coupons.reserve(db, coupon=coupon, user=current_user, order_id=order_id,
                                kind=req.kind, list_price=list_price,
                                discount=discount_amount, paid=paid_amount)
        order.coupon_usage_id = usage.id
    db.commit()

    params = {
        "pid": pid,
        "type": req.payment_method,
        "out_trade_no": order_id,
        "notify_url": notify_url,
        "return_url": return_url,
        "name": item_name,
        "money": f"{float(paid_amount):.2f}",
    }
    params["sign"] = _yipay_sign(params, key)
    params["sign_type"] = "MD5"
    pay_url = f"{gateway}/submit.php?{urlencode(params)}"

    order.payment_url = pay_url
    db.commit()

    logger.info("创建支付订单: user=%s order=%s kind=%s amount=%s discount=%s",
                current_user.id, order_id, req.kind, paid_amount, discount_amount)
    return {
        "success": True,
        "order_id": order_id,
        "amount": float(paid_amount),
        "list_price": float(list_price),
        "discount_amount": float(discount_amount),
        "coupon_code": coupon_code,
        "pay_url": pay_url,
        "message": "订单已创建，正在跳转支付",
    }


@router.get("/payment/orders")
def my_orders(
    kind: Optional[str] = None,
    limit: int = 30,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的订单列表（充值 + 订阅合并）

    带优惠快照：原价 / 优惠金额 / 实付 / 用的哪个码。用户端要能自己对账
    （“我明明用了券，为什么订单显示全价”）。
    """
    orders: list[dict] = []

    if kind in (None, "recharge"):
        for o in db.query(models.RechargeOrder).filter(
            models.RechargeOrder.user_id == current_user.id
        ).order_by(models.RechargeOrder.created_at.desc()).limit(limit).all():
            orders.append({
                "order_id": o.order_id, "kind": "recharge",
                "item_name": f"积分充值（+{o.amount} 积分）",
                "amount": float(o.price), "status": o.status,
                "list_price": float(o.list_price or 0),
                "discount_amount": float(o.discount_amount or 0),
                "coupon_code": "",
                "coupon_usage_id": o.coupon_usage_id,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                # 退款留痕：用户端要能看到“为什么退了/退了多少”，否则只会来问客服
                "refunded_at": o.refunded_at.isoformat() if o.refunded_at else None,
                "refund_reason": o.refund_reason or "",
            })

    if kind in (None, "subscription"):
        for o in db.query(models.SubscriptionOrder).filter(
            models.SubscriptionOrder.user_id == current_user.id
        ).order_by(models.SubscriptionOrder.created_at.desc()).limit(limit).all():
            orders.append({
                "order_id": o.order_id, "kind": "subscription",
                "item_name": f"订阅 - {o.item_name}",
                "amount": float(o.amount), "status": o.status,
                "list_price": float(o.list_price or 0),
                "discount_amount": float(o.discount_amount or 0),
                "coupon_code": "",
                "coupon_usage_id": o.coupon_usage_id,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                "refunded_at": o.refunded_at.isoformat() if o.refunded_at else None,
                "refund_reason": o.refund_reason or "",
            })

    # 优惠码回填（一次查完，不给每条订单配一个查询）
    usage_ids = {o["coupon_usage_id"] for o in orders if o.get("coupon_usage_id")}
    if usage_ids:
        rows = db.query(models.CouponUsage.id, models.CouponCode.code).join(
            models.CouponCode, models.CouponCode.id == models.CouponUsage.coupon_id
        ).filter(models.CouponUsage.id.in_(usage_ids)).all()
        code_map = {uid: code for uid, code in rows}
        for o in orders:
            o["coupon_code"] = code_map.get(o["coupon_usage_id"], "")
    for o in orders:
        o.pop("coupon_usage_id", None)

    orders.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return {"orders": orders[:limit]}


# ==================== 支付回调 ====================

def _verify_yipay_notify(params: dict, key: str) -> bool:
    """易支付回调验签（MD5）

    比较用 ``hmac.compare_digest``：签名是回调方给的字符串，逐字节短路比较
    会把「对了几位」变成可测量的时间差（v2.30.0）。
    """
    sign = str(params.get("sign") or "")
    expected = _yipay_sign(params, key)
    return hmac.compare_digest(sign.lower(), expected.lower())


def _order_paid_amount(recharge_order=None, subscription_order=None) -> Optional[Decimal]:
    """订单**应付金额**（实付口径）

    下单时把订单金额统一写成实付（原价 / 优惠 / 实付三个快照见 ``create_payment_order``），
    所以这里读的就是用户真正该付的钱。
    """
    order = recharge_order if recharge_order is not None else subscription_order
    if order is None:
        return None
    raw = order.price if recharge_order is not None else order.amount
    if raw is None:
        return None
    try:
        return Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _notify_amount(value) -> Optional[Decimal]:
    """回调里报的金额（解析不了返回 None，不是 0）"""
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _amount_mismatch(recharge_order, subscription_order, raw: dict) -> Optional[str]:
    """回调金额与订单是否对不上（对不上时返回给人看的说明）

    验签只证明「这条通知来自网关」；它不证明**钱数对不对**。网关配错价、订单号被复用、
    上游按别的金额收款时，旧实现照样发货（积分 / 会员都按订单发货），而钱只收了一部分。

    所以回调里报了金额就逐笔核对：对不上 **不发货**（返回 fail，让网关重试并让运维看见）。
    回调没带金额时只能记一行日志按原逻辑发货——不能因为「读不到 money」把正常付款卡死。
    """
    expected = _order_paid_amount(recharge_order, subscription_order)
    reported = _notify_amount(raw.get("money"))
    if expected is None:
        return None
    if reported is None:
        logger.warning("支付回调未带金额，无法核对（按订单实付 %s 发货）: order=%s",
                       expected, raw.get("out_trade_no"))
        return None
    if reported != expected:
        return f"金额不符：订单应付 {expected}，回调报 {reported}"
    return None


def _claim_order(db: Session, model, order) -> bool:
    """把订单从「未支付」原子地推进到 ``paid``：并发回调 / 人工补单只有一个能拿到那一行

    旧实现的判定与发货之间是读-改-写（``if status not in (paid, refunded, closed)``）：
    网关重试回调和管理员补单撞在一起时，两个事务都读到 ``pending`` → 双倍积分 / 双份订阅。
    SQLite 的单写锁能部分兜住，跳机器部署的 PostgreSQL 下就是实打实的资损。

    现在先做条件 ``UPDATE ... WHERE status NOT IN (...)``：

    - 拿到 1 行 → 由本请求发货（并发第二个请求会在行锁上等到提交，然后拿到 0 行）；
    - 拿到 0 行 → 已被别人履约（或已退款/关单），跳过发货，幂等成立。

    更新与发货在同一事务里，失败会一起回滚；``paid_at`` 不再由调用方另行赋值。
    """
    if order is None or order.status in ("paid", "refunded", "closed"):
        return False
    claimed = (
        db.query(model)
        .filter(model.id == order.id, model.status.notin_(("paid", "refunded", "closed")))
        .update({"status": "paid", "paid_at": datetime.now()}, synchronize_session=False)
    )
    if not claimed:
        return False
    # 让当前事务里的 ORM 对象与刚写入的行保持一致（后续代码与提交都用它）
    order.status = "paid"
    order.paid_at = datetime.now()
    return True


class FulfillmentError(RuntimeError):
    """履约缺料：订单该发的东西已经不存在了（套餐被删 / 用户被删等）

    这类情况**必须**让调用方回滚并把回调判成失败（网关会重试，或者转人工补单），
    不能静默返回 success——「钱收了、订单标了 paid、用户什么都没拿到」是最坏的结果，
    而且优惠券还会被照常 ``consume`` 掉。
    """


async def _fulfill_order(db: Session, recharge_order=None, subscription_order=None) -> list:
    """订单履约：充值发积分 / 订阅发放，幂等（重复回调不重复发货）

    **返回待发送的通知列表，不要在这里就发出去。**

    履约事务（积分 / 订阅 / 订单状态）还没 ``commit`` 时，通知服务会另开一个 session 写站内信，
    在 SQLite 上这属于「读事务升级为写事务」，会被直接判为 ``database is locked``（不会等锁），
    结果是「充值成功」这类站内信被静默丢弃（只留一行日志），而钱已经收了。
    所以通知由调用方在 ``db.commit()`` 之后统一发：见 ``send_fulfill_notifications``。
    """
    # 已退款 / 已关闭的订单绝不再履约：支付回调可能晚到或重放（网关重试、管理员已经
    # 关单后又收到回调），只判 `!= "paid"` 会把退过的订单又发一遍货。
    pending: list = []
    if recharge_order and _claim_order(db, models.RechargeOrder, recharge_order):
        user = db.query(models.WebUser).filter(
            models.WebUser.id == recharge_order.user_id
        ).first()
        if user is None:
            # 用户被删了：订单不能就这么标成 paid 又什么都不发（见 FulfillmentError）
            raise FulfillmentError(
                f"充值履约缺料：订单 {recharge_order.order_id} 的用户 "
                f"#{recharge_order.user_id} 已不存在"
            )
        if user:
            _add_points(
                db, user, recharge_order.amount, "recharge",
                f"充值到账（订单 {recharge_order.order_id}）",
                f"recharge:{recharge_order.order_id}",
            )
            # 邀请返利：被邀请人充值 → 邀请人得返利积分
            try:
                from backend.api.invitation import apply_rebate
                apply_rebate(db, user, float(recharge_order.price or 0),
                             recharge_order.order_id)
            except Exception:  # noqa: BLE001 — 返利失败不阻塞充值履约
                logger.exception("充值返利计算失败: %s", recharge_order.order_id)
            pending.append(dict(
                event_type="economy.recharge_success",
                user_id=user.id,
                title=f"💰 充值成功 +{recharge_order.amount} 积分",
                content=f"订单 {recharge_order.order_id} 已到账，当前余额 {user.points} 积分。",
            ))
        # 优惠券预订 → 已消费（额度仍占用）；关单/退款时才释放
        # （订单状态与 paid_at 已由 _claim_order 原子写入，见该函数的说明）
        coupons.consume(db, recharge_order.coupon_usage_id)

    if subscription_order and _claim_order(db, models.SubscriptionOrder, subscription_order):
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == subscription_order.plan_id
        ).first()
        user = db.query(models.WebUser).filter(
            models.WebUser.id == subscription_order.user_id
        ).first()
        if user is None or plan is None:
            # 下单之后、支付回调之前套餐被删（或用户被删）：订单会被标成 paid 但用户
            # 什么都拿不到，优惠券还会被 consume 掉——旧实现就是在这里静静地什么都不做，
            # 然后回调返回 success。现在抛出去：调用方回滚 + 返回 fail，转人工处理。
            raise FulfillmentError(
                f"订阅履约缺料：订单 {subscription_order.order_id}"
                f"（套餐 {'已删除' if plan is None else '正常'}、"
                f"用户 {'已删除' if user is None else '正常'}）"
            )
        if user and plan:
            subscription = _grant_subscription(
                db, user, plan,
                plan.duration_days, "purchase", subscription_order.order_id,
                realm_id=plan.realm_id,
            )
            # 记下「这条订单开出的是哪份订阅、多少天」：退款按这笔精确回滚，
            # 不靠猜用户当前那笔生效中的订阅（可能来自卡码/兑换码/别的订单）。
            subscription_order.subscription_id = subscription.id
            subscription_order.days_granted = plan.duration_days
            pending.append(dict(
                event_type="economy.subscription_success",
                user_id=user.id,
                title="🎉 订阅购买成功",
                content=(f"「{plan.name}」已开通，"
                         f"到期时间 {subscription.end_date.strftime('%Y-%m-%d')}。"),
                related_id=subscription.id,
            ))
        coupons.consume(db, subscription_order.coupon_usage_id)

    return pending


async def send_fulfill_notifications(pending: list) -> None:
    """履约事务提交之后发送站内信（失败只记日志，不影响已到账的订单）"""
    for item in pending or []:
        try:
            await notify_admin_event(**item)
        except Exception as exc:  # noqa: BLE001 — 通知失败不能影响支付结果
            logger.warning("履约通知发送失败（用户 %s）: %s", item.get("user_id"), exc)


@router.api_route("/payment/notify", methods=["GET", "POST"], response_class=PlainTextResponse)
async def payment_notify(request: Request, db: Session = Depends(get_db)):
    """易支付异步回调：验签 → 履约 → 返回 success"""
    raw = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            raw.update({k: v for k, v in form.items() if isinstance(v, str)})
        except Exception:  # noqa: BLE001
            pass

    out_trade_no = raw.get("out_trade_no", "")
    trade_status = raw.get("trade_status", "")
    logger.info("支付回调: order=%s status=%s", out_trade_no, trade_status)

    key = _get_config(db, "payment_partner_key", "").strip()
    if not key:
        return "fail"
    if not _verify_yipay_notify(raw, key):
        logger.warning("支付回调验签失败: order=%s", out_trade_no)
        return "fail"
    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return "success"  # 非成功状态直接确认，避免重复通知

    recharge_order = db.query(models.RechargeOrder).filter(
        models.RechargeOrder.order_id == out_trade_no
    ).first()
    subscription_order = db.query(models.SubscriptionOrder).filter(
        models.SubscriptionOrder.order_id == out_trade_no
    ).first()

    if not recharge_order and not subscription_order:
        logger.warning("支付回调订单不存在: %s", out_trade_no)
        return "fail"

    mismatch = _amount_mismatch(recharge_order, subscription_order, raw)
    if mismatch:
        logger.error("支付回调被拒（%s）: order=%s", mismatch, out_trade_no)
        return "fail"

    try:
        pending = await _fulfill_order(db, recharge_order=recharge_order,
                                 subscription_order=subscription_order)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("订单履约失败: %s", out_trade_no)
        return "fail"

    # 先提交再发通知：见 _fulfill_order 的说明（履约中另开会话写站内信会撞 SQLite 写锁）
    await send_fulfill_notifications(pending)
    return "success"


@router.api_route("/payment/return", methods=["GET"], response_class=JSONResponse)
async def payment_return(request: Request, db: Session = Depends(get_db)):
    """同步跳转：返回前端跳转地址（前端钱包页轮询订单状态）"""
    order_id = request.query_params.get("out_trade_no", "")
    return {"success": True, "order_id": order_id, "redirect": f"/wallet?order={order_id}"}
