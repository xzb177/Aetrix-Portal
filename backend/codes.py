"""卡码体系：注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码

借鉴 twilight-kotomi 的 RegCode 模型：一份数据结构靠 ``code_type`` 区分用途，
``days`` 表示授予或叠加的会员天数，``is_decoy`` 为蜜罐码，``target_username`` 为指名码。

本项目与参考实现的差异：会员口径以 ``UserSubscription(end_date)`` 为**单一事实来源**
（v2.5.1 起 is_vip / 付费墙 / 后台订阅总览都按它现算），因此卡码的「天数」最终落到订阅上：
无生效订阅则新建一条，有则在其到期时间上叠加。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models

# 卡码类型（对齐参考项目 type 1/2/3）
CODE_TYPE_REGISTER = 1  # 注册码：为尚无会员的账号开通会员
CODE_TYPE_RENEW = 2  # 续期码：在原有到期时间上叠加
CODE_TYPE_WHITELIST = 3  # 白名单码：置为长期有效
CODE_TYPE_NAMES = {
    CODE_TYPE_REGISTER: "注册码",
    CODE_TYPE_RENEW: "续期码",
    CODE_TYPE_WHITELIST: "白名单码",
}
CODE_TYPE_PREFIX = {CODE_TYPE_REGISTER: "REG", CODE_TYPE_RENEW: "REN", CODE_TYPE_WHITELIST: "VIP"}

PERMANENT_DAYS = 36500  # 永久近似（100 年）
DEFAULT_DAYS = 30
MAX_RANDOM_LEN = 40

# 易抄写字符集（去掉 0/1/I/O 等易混淆字符），与参考项目 base32-* 一致
_SAFE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_HEX_ALPHABET = "0123456789ABCDEF"
_URLSAFE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

RANDOM_ALGORITHMS = {
    "base32-16": (_SAFE_ALPHABET, 16),
    "base32-20": (_SAFE_ALPHABET, 20),
    "base32-24": (_SAFE_ALPHABET, 24),
    "base32-32": (_SAFE_ALPHABET, 32),
    "hex20": (_HEX_ALPHABET, 20),
    "hex32": (_HEX_ALPHABET, 32),
    "digits-12": ("0123456789", 12),
    "digits-16": ("0123456789", 16),
    "urlsafe-24": (_URLSAFE_ALPHABET, 24),
    "urlsafe-32": (_URLSAFE_ALPHABET, 32),
}
DEFAULT_ALGORITHM = "base32-20"
DEFAULT_FORMAT = "{type}-{random}"


def normalize_days(days: Optional[int]) -> int:
    """天数规范化：0（未填）按 30 天；负数统一为 -1（永久）"""
    if days is None:
        return DEFAULT_DAYS
    days = int(days)
    if days == 0:
        return DEFAULT_DAYS
    return -1 if days < 0 else days


def format_days(days: Optional[int]) -> str:
    """给前端展示的天数文案"""
    days = normalize_days(days)
    return "永久" if days < 0 else f"{days} 天"


def random_part(algorithm: str = DEFAULT_ALGORITHM) -> str:
    alphabet, length = RANDOM_ALGORITHMS.get(algorithm, RANDOM_ALGORITHMS[DEFAULT_ALGORITHM])
    return "".join(secrets.choice(alphabet) for _ in range(length))


def render_code(
    *,
    code_type: int,
    days: int,
    index: int = 1,
    template: str = DEFAULT_FORMAT,
    algorithm: str = DEFAULT_ALGORITHM,
) -> str:
    """按模板生成卡码

    支持占位符 ``{random}`` / ``{type}`` / ``{days}`` / ``{index}``；
    模板不含 ``{random}`` 时自动追加 ``-{random}``，避免批量生成出重复码。
    """
    template = (template or DEFAULT_FORMAT).strip() or DEFAULT_FORMAT
    code = (
        template.replace("{type}", CODE_TYPE_PREFIX.get(code_type, "REG"))
        .replace("{days}", "PERM" if days < 0 else str(days))
        .replace("{index}", str(index))
    )
    if "{random}" in template:
        code = code.replace("{random}", random_part(algorithm))
    else:
        code = f"{code}-{random_part(algorithm)}"
    return code[:64].upper()


# ==================== 会员天数授予 ====================


def _resolve_plan(db: Session):
    """卡码授予天数所用套餐

    优先配置 ``code_default_plan_id``，其次任何启用中的套餐，
    最后回落到一个隐藏的「卡码开通」套餐（is_active=False，不在商店出现）。
    """
    config = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "code_default_plan_id"
    ).first()
    if config and str(config.value or "").strip().isdigit():
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == int(str(config.value).strip())
        ).first()
        if plan:
            return plan

    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.is_active == True)  # noqa: E712
        .order_by(models.SubscriptionPlan.sort_order)
        .first()
    )
    if plan:
        return plan

    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.name == "卡码开通"
    ).first()
    if not plan:
        plan = models.SubscriptionPlan(
            name="卡码开通", description="卡码开通/续期自动创建（不在商店展示）",
            price=0, duration_days=DEFAULT_DAYS, is_active=False, sort_order=999,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
    return plan


def grant_membership_days(db: Session, user: models.WebUser, days: int) -> models.UserSubscription:
    """按天数开通或延长会员，返回生效中的订阅

    `with_for_update()` 在 PostgreSQL 下锁住该订阅行，避免同一用户并发叠加天数时
    两边读到同一到期时间、后提交的覆盖前者（丢天数）；SQLite 忽略该子句。
    """
    total = PERMANENT_DAYS if days < 0 else max(int(days), 1)
    now = datetime.now()
    sub = (
        db.query(models.UserSubscription)
        .filter(
            models.UserSubscription.user_id == user.id,
            models.UserSubscription.status == "active",
            models.UserSubscription.end_date > now,
        )
        .order_by(models.UserSubscription.end_date.desc())
        .with_for_update()
        .first()
    )
    if sub:
        # 已有生效订阅：叠加（续期语义），而非覆盖
        sub.end_date = sub.end_date + timedelta(days=total)
        sub.status = "active"
    else:
        plan = _resolve_plan(db)
        sub = models.UserSubscription(
            user_id=user.id, plan_id=plan.id, start_date=now,
            end_date=now + timedelta(days=total), status="active",
        )
        db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def has_active_membership(db: Session, user: models.WebUser) -> bool:
    now = datetime.now()
    return (
        db.query(models.UserSubscription)
        .filter(
            models.UserSubscription.user_id == user.id,
            models.UserSubscription.status == "active",
            models.UserSubscription.end_date > now,
        )
        .first()
        is not None
    )


# ==================== 卡码识别与核销 ====================


def find_reg_code(db: Session, raw: str) -> Optional[models.RegistrationCode]:
    if not raw:
        return None
    return (
        db.query(models.RegistrationCode)
        .filter(func.upper(models.RegistrationCode.code) == raw.strip().upper())
        .first()
    )


def consume(db: Session, code: models.RegistrationCode, user_id: int) -> None:
    """记录一次卡码消耗（使用次数、使用者审计、用满自动停用）"""
    code.use_count = (code.use_count or 0) + 1
    used = [i for i in str(code.used_by or "").split(",") if i.strip()]
    used.append(str(user_id))
    code.used_by = ",".join(dict.fromkeys(used))[:500]
    if code.max_uses and code.use_count >= code.max_uses:
        code.is_active = False
    db.commit()


def grant_days_for(code: models.RegistrationCode) -> int:
    """该卡码应授予的天数：白名单码一律长期有效，其余取 days"""
    if code.code_type == CODE_TYPE_WHITELIST:
        return -1
    return normalize_days(code.days)


def reg_code_error(code: models.RegistrationCode) -> Optional[str]:
    """卡码自身可用性检查（不论使用者）"""
    if not code.is_active:
        return "卡码已停用"
    if code.expires_at and code.expires_at < datetime.now():
        return "卡码已过期"
    if code.max_uses and code.use_count >= code.max_uses:
        return "卡码已用尽"
    return None


def preview_code(db: Session, raw: str, username: Optional[str] = None) -> dict:
    """统一识别卡码 / 邀请码 / 兑换码，供前端「使用卡码」入口预览

    对齐参考项目的 previewCode：一个入口自动识别来源，前端无需分类调用。
    """
    raw = (raw or "").strip()
    if not raw:
        return {"valid": False, "kind": "unknown", "message": "请输入卡码"}

    code = find_reg_code(db, raw)
    if code:
        error = reg_code_error(code)
        named_ok = True
        if code.target_username:
            named_ok = bool(username) and code.target_username.strip().lower() == username.strip().lower()
        return {
            "valid": error is None and named_ok,
            "kind": "code",
            "code_type": code.code_type,
            "type_name": CODE_TYPE_NAMES.get(code.code_type, "卡码"),
            "days": normalize_days(code.days),
            "days_text": format_days(code.days),
            "is_named": bool(code.target_username),
            "target_username": code.target_username,
            "remaining_uses": max((code.max_uses or 0) - (code.use_count or 0), 0),
            "message": error or ("该卡码限指定账号使用" if not named_ok else "卡码有效"),
        }

    invitation = db.query(models.InvitationCode).filter(
        func.upper(models.InvitationCode.code) == raw.upper()
    ).first()
    if invitation:
        return {
            "valid": False, "kind": "invite", "days": 0, "days_text": "-",
            "message": "这是邀请码，请在注册页填写",
        }

    exchange = db.query(models.ExchangeCode).filter(
        func.upper(models.ExchangeCode.code) == raw.upper()
    ).first()
    if exchange:
        return {
            "valid": False, "kind": "exchange", "days": exchange.duration_days or 0,
            "days_text": format_days(exchange.duration_days) if exchange.type == "subscription" else "-",
            "message": "这是兑换码，请在「钱包 → 兑换码」中核销",
        }

    return {"valid": False, "kind": "unknown", "message": "卡码不存在"}


def redeem_code(db: Session, user: models.WebUser, raw: str) -> dict:
    """核销卡码：注册码 / 续期码 / 白名单码

    - 注册码：仅用于尚无生效会员的账号（已有会员请用续期码，与参考实现口径一致）
    - 续期码：在当前到期时间上叠加天数
    - 白名单码：置为长期有效
    - 诱饵码：不暴露身份，统一返回「卡码无效」，同时封禁账号并落安全日志
    - 指名码：非空 target_username 仅限该用户使用
    """
    from backend.authlog import record_event

    raw = (raw or "").strip()
    if not raw:
        return {"success": False, "message": "请输入卡码"}

    code = find_reg_code(db, raw)
    if not code:
        preview = preview_code(db, raw)
        return {"success": False, "message": preview.get("message") or "卡码无效"}

    error = reg_code_error(code)
    if error:
        return {"success": False, "message": error}

    if code.is_decoy:
        # 蜜罐：诱饵码只应出现在盗版/破解渠道，使用即视为违规
        user.is_active = False
        record_event(
            db, username=user.username, user_id=user.id, success=False,
            reason="decoy_code", detail=f"使用了诱饵码 {code.code}，账号已自动封禁",
        )
        db.commit()
        return {"success": False, "message": "卡码无效"}

    if code.target_username and code.target_username.strip().lower() != (user.username or "").lower():
        return {"success": False, "message": "该卡码限指定账号使用"}

    days = grant_days_for(code)
    if code.code_type == CODE_TYPE_REGISTER and has_active_membership(db, user):
        return {"success": False, "message": "账号已有生效中的会员，请使用续期码"}

    sub = grant_membership_days(db, user, days)
    consume(db, code, user.id)

    type_name = CODE_TYPE_NAMES.get(code.code_type, "卡码")
    return {
        "success": True,
        "message": f"{type_name}核销成功，会员到期时间 {sub.end_date.strftime('%Y-%m-%d %H:%M')}",
        "code_type": code.code_type,
        "days": days,
        "end_date": sub.end_date.isoformat(),
    }
