# -*- coding: utf-8 -*-
"""红包业务逻辑（公益服模块3-娱乐板块）

手动编写（OpenRouter 免费模型 429 限流，按 backend/points.py 模式手写）。

规则：
- 发红包：从发送者积分扣除 total_amount，创建红包（24小时过期）
- 抢红包：随机金额（剩余金额随机分配，保证每人至少1分）
- 防重复：同一用户不能重复领取同一红包
- 红包过期后剩余积分退回发送者（领取时检查）

金额分配：随机红包算法，最后一个领取者拿剩余全部。
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.api import economy

logger = logging.getLogger(__name__)

# 红包有效期（小时）
PACKET_TTL_HOURS = 24


def send_packet(
    db: Session,
    sender: models.WebUser,
    total_amount: int,
    total_count: int,
) -> models.RedPacket:
    """发红包

    校验：金额>0，个数>0，金额>=个数（每人至少1分），余额充足
    """
    if total_amount <= 0:
        raise ValueError("红包金额必须大于0")
    if total_count <= 0:
        raise ValueError("红包个数必须大于0")
    if total_amount < total_count:
        raise ValueError("红包金额不能小于个数（每人至少1分）")
    if total_count > 100:
        raise ValueError("红包个数不能超过100")

    balance = int(sender.points or 0)
    if balance < total_amount:
        raise ValueError(f"积分不足，需要 {total_amount} 分，当前 {balance} 分")

    # 扣分
    economy._add_points(db, sender, -total_amount, "redpacket", f"发出红包 {total_amount} 分")

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
    logger.info("红包发出: sender=%s amount=%s count=%s", sender.id, total_amount, total_count)
    return packet


def claim_packet(db: Session, user: models.WebUser, packet_id: int) -> dict:
    """抢红包

    校验：红包存在、未过期、还有剩余、未领过
    金额：随机 1 ~ (剩余金额-剩余个数+1)，最后一个拿全部剩余
    """
    packet = db.query(models.RedPacket).filter(
        models.RedPacket.id == packet_id).first()
    if packet is None:
        raise ValueError("红包不存在")

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
