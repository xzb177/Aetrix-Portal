# -*- coding: utf-8 -*-
"""红包业务逻辑（公益服模块3-娱乐板块）

规则：
- 发红包：从发送者积分扣除 total_amount + 手续费，创建红包（24小时过期）
- 抢红包：随机金额（剩余金额随机分配，保证每人至少1分）
- 防重复：同一用户不能重复领取同一红包
- 红包过期后剩余积分退回发送者（领取时检查）

金额分配：随机红包算法，最后一个领取者拿剩余全部。

P0 统一货币体系：
- 手续费：默认 5%，可通过 SystemConfig redpacket_fee_pct 配置（0=不收）
- 频率限制：7天窗口，可通过 SystemConfig 配置（0=不限）
  - redpacket_send_limit_7d：7天内最多发送次数（默认20）
  - redpacket_recv_limit_7d：7天内最多领取次数（默认10，管理员发出的不计）
- 账本类型：redpacket（发出/抢到/退回）、redpacket_fee（手续费扣除）
"""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.api import economy

logger = logging.getLogger(__name__)

# 红包有效期（小时）
PACKET_TTL_HOURS = 24


def _get_int_config(db: Session, key: str, default: int) -> int:
    """读 SystemConfig 整数配置（读不到或非法则用默认值）"""
    cfg = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == key).first()
    try:
        return int(cfg.value) if cfg and cfg.value else default
    except (ValueError, TypeError):
        return default


def send_packet(
    db: Session,
    sender: models.WebUser,
    total_amount: int,
    total_count: int,
) -> models.RedPacket:
    """发红包

    校验：金额>0，个数>0，金额>=个数（每人至少1分），余额充足（含手续费）
    频率：7天内发送次数上限（redpacket_send_limit_7d，0=不限）
    手续费：按 redpacket_fee_pct 比例额外扣除，记 redpacket_fee 账本
    """
    if total_amount <= 0:
        raise ValueError("红包金额必须大于0")
    if total_count <= 0:
        raise ValueError("红包个数必须大于0")
    if total_amount < total_count:
        raise ValueError("红包金额不能小于个数（每人至少1分）")
    if total_count > 100:
        raise ValueError("红包个数不能超过100")

    # 发送频率检查
    send_limit = _get_int_config(db, "redpacket_send_limit_7d", 20)
    if send_limit > 0:
        week_ago = datetime.now() - timedelta(days=7)
        sent = db.query(models.RedPacket).filter(
            models.RedPacket.sender_id == sender.id,
            models.RedPacket.created_at >= week_ago,
        ).count()
        if sent >= send_limit:
            raise ValueError(f"7天内最多发送 {send_limit} 次红包")

    # 手续费（向上取整）
    fee_pct = _get_int_config(db, "redpacket_fee_pct", 5)
    fee = math.ceil(total_amount * fee_pct / 100) if fee_pct > 0 else 0
    need = total_amount + fee

    balance = int(sender.points or 0)
    if balance < need:
        if fee > 0:
            raise ValueError(
                f"积分不足，需要 {need} 分（含手续费 {fee} 分），当前 {balance} 分")
        raise ValueError(f"积分不足，需要 {need} 分，当前 {balance} 分")

    # 扣分：红包本体 + 手续费（分开记账）
    economy._add_points(db, sender, -total_amount, "redpacket", f"发出红包 {total_amount} 分")
    if fee > 0:
        economy._add_points(
            db, sender, -fee, "redpacket_fee", f"红包手续费 {fee} 分（{fee_pct}%）")

    packet = models.RedPacket(
        sender_id=sender.id,
        total_amount=total_amount,
        total_count=total_count,
        remaining_amount=total_amount,
        remaining_count=total_count,
        expires_at=datetime.now() + timedelta(hours=PACKET_TTL_HOURS),
    )
    db.add(packet)
    db.commit()
    db.refresh(packet)
    logger.info("红包发出: sender=%s amount=%s count=%s fee=%s",
                sender.id, total_amount, total_count, fee)
    return packet


def claim_packet(db: Session, user: models.WebUser, packet_id: int) -> dict:
    """抢红包

    校验：红包存在、未过期、还有剩余、未领过
    频率：7天内领取次数上限（redpacket_recv_limit_7d，0=不限；管理员发出的不计）
    金额：随机 1 ~ (剩余金额-剩余个数+1)，最后一个拿全部剩余
    """
    packet = db.query(models.RedPacket).filter(
        models.RedPacket.id == packet_id).first()
    if packet is None:
        raise ValueError("红包不存在")

    # 领取频率检查（管理员发出的红包不计入）
    recv_limit = _get_int_config(db, "redpacket_recv_limit_7d", 10)
    if recv_limit > 0:
        week_ago = datetime.now() - timedelta(days=7)
        claimed = db.query(models.RedPacketClaim).join(
            models.RedPacket,
            models.RedPacketClaim.packet_id == models.RedPacket.id,
        ).join(
            models.WebUser,
            models.RedPacket.sender_id == models.WebUser.id,
        ).filter(
            models.RedPacketClaim.user_id == user.id,
            models.RedPacketClaim.created_at >= week_ago,
            models.WebUser.is_staff == False,  # noqa: E712
        ).count()
        if claimed >= recv_limit:
            raise ValueError(f"7天内最多领取 {recv_limit} 次红包")

    now = datetime.now()
    if packet.expires_at and packet.expires_at < now:
        raise ValueError("红包已过期")
    if packet.remaining_count <= 0:
        raise ValueError("红包已被抢完")

    # 防重复领取
    dup = db.query(models.RedPacketClaim).filter(
        models.RedPacketClaim.packet_id == packet_id,
        models.RedPacketClaim.user_id == user.id,
    ).first()
    if dup:
        raise ValueError("你已经领过这个红包了")

    # 随机金额
    if packet.remaining_count == 1:
        amount = packet.remaining_amount
    else:
        max_amount = packet.remaining_amount - packet.remaining_count + 1
        amount = random.randint(1, max_amount)

    # 更新红包
    packet.remaining_amount -= amount
    packet.remaining_count -= 1

    # 给领取者加分
    economy._add_points(db, user, amount, "redpacket", f"抢到红包 {amount} 分")

    # 写领取记录
    db.add(models.RedPacketClaim(
        packet_id=packet.id, user_id=user.id, amount=amount))
    db.commit()

    logger.info("红包领取: packet=%s user=%s amount=%s", packet_id, user.id, amount)
    return {
        "packet_id": packet.id,
        "amount": amount,
        "remaining_count": packet.remaining_count,
    }


def get_packet(db: Session, packet_id: int, user: models.WebUser | None = None) -> dict:
    """红包详情"""
    packet = db.query(models.RedPacket).filter(
        models.RedPacket.id == packet_id).first()
    if packet is None:
        raise ValueError("红包不存在")

    claims = db.query(models.RedPacketClaim).filter(
        models.RedPacketClaim.packet_id == packet_id
    ).order_by(models.RedPacketClaim.id).all()

    user_ids = {c.user_id for c in claims} | {packet.sender_id}
    users = {u.id: u.username for u in db.query(models.WebUser).filter(
        models.WebUser.id.in_(user_ids)).all()} if user_ids else {}

    claimed_by_me = False
    if user is not None:
        claimed_by_me = any(c.user_id == user.id for c in claims)

    return {
        "id": packet.id,
        "sender_id": packet.sender_id,
        "sender_name": users.get(packet.sender_id, "未知"),
        "total_amount": packet.total_amount,
        "total_count": packet.total_count,
        "remaining_amount": packet.remaining_amount,
        "remaining_count": packet.remaining_count,
        "expires_at": packet.expires_at.isoformat() if packet.expires_at else None,
        "created_at": packet.created_at.isoformat() if packet.created_at else None,
        "claimed_by_me": claimed_by_me,
        "claims": [
            {
                "user_id": c.user_id,
                "username": users.get(c.user_id, "未知"),
                "amount": c.amount,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in claims
        ],
    }


def refund_expired(db: Session) -> int:
    """过期红包退款（供定时任务调用）：剩余积分退回发送者"""
    now = datetime.now()
    expired = db.query(models.RedPacket).filter(
        models.RedPacket.expires_at < now,
        models.RedPacket.remaining_count > 0,
        models.RedPacket.remaining_amount > 0,
    ).all()

    count = 0
    for packet in expired:
        sender = db.query(models.WebUser).filter(
            models.WebUser.id == packet.sender_id).first()
        if sender is None:
            continue
        refund = packet.remaining_amount
        economy._add_points(
            db, sender, refund, "redpacket", f"红包过期退回 {refund} 分")
        packet.remaining_amount = 0
        packet.remaining_count = 0
        count += 1

    if count:
        db.commit()
        logger.info("过期红包退款: %s 个", count)
    return count
