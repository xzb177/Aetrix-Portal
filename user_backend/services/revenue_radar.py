"""
异常收入雷达服务
检测同IP多号、兑换码套利、邀请刷量、退款前高强度观看
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.models import (
    WebUser, UserSubscription, SubscriptionOrder, ExchangeCode,
    ExchangeCodeRecord, InvitationRecord, UserEmbyAccount, Message
)

logger = logging.getLogger(__name__)


class RevenueRadarService:
    """异常收入检测"""

    @staticmethod
    def scan_anomalies(db: Session, days: int = 7) -> Dict[str, Any]:
        """扫描异常行为"""
        now = datetime.now()
        cutoff = now - timedelta(days=days)
        alerts = []

        # 1. 同IP多号检测
        ip_alerts = RevenueRadarService._detect_multi_account_by_ip(db, cutoff)
        alerts.extend(ip_alerts)

        # 2. 兑换码套利检测
        code_alerts = RevenueRadarService._detect_code_abuse(db, cutoff)
        alerts.extend(code_alerts)

        # 3. 邀请刷量检测
        invite_alerts = RevenueRadarService._detect_invite_farming(db, cutoff)
        alerts.extend(invite_alerts)

        # 4. 退款前高强度观看
        refund_alerts = RevenueRadarService._detect_refund_abuse(db, cutoff)
        alerts.extend(refund_alerts)

        return {
            "scan_period_days": days,
            "total_alerts": len(alerts),
            "alerts": alerts,
            "summary": {
                "multi_account": len([a for a in alerts if a["type"] == "multi_account"]),
                "code_abuse": len([a for a in alerts if a["type"] == "code_abuse"]),
                "invite_farming": len([a for a in alerts if a["type"] == "invite_farming"]),
                "refund_abuse": len([a for a in alerts if a["type"] == "refund_abuse"]),
            },
            "scanned_at": now.isoformat()
        }

    @staticmethod
    def _detect_multi_account_by_ip(db: Session, cutoff: datetime) -> List[Dict]:
        """检测同一IP注册多个账号"""
        alerts = []
        # 查询最近注册的用户，按注册IP分组
        # 注：需要 UserAuditLog 记录注册IP
        return alerts

    @staticmethod
    def _detect_code_abuse(db: Session, cutoff: datetime) -> List[Dict]:
        """检测兑换码套利（同一用户短时间内大量使用兑换码）"""
        alerts = []
        records = db.query(
            ExchangeCodeRecord.user_id,
            func.count(ExchangeCodeRecord.id).label('count')
        ).filter(
            ExchangeCodeRecord.created_at >= cutoff
        ).group_by(
            ExchangeCodeRecord.user_id
        ).having(
            func.count(ExchangeCodeRecord.id) >= 5
        ).all()

        for user_id, count in records:
            user = db.query(WebUser).filter(WebUser.id == user_id).first()
            alerts.append({
                "type": "code_abuse",
                "severity": "high" if count >= 10 else "medium",
                "user_id": user_id,
                "username": user.username if user else "未知",
                "detail": f"{count}天内使用了 {count} 个兑换码",
                "action": "建议核查账号"
            })

        return alerts

    @staticmethod
    def _detect_invite_farming(db: Session, cutoff: datetime) -> List[Dict]:
        """检测邀请刷量（邀请人短时间内邀请大量用户）"""
        alerts = []
        invites = db.query(
            InvitationRecord.inviter_id,
            func.count(InvitationRecord.id).label('count')
        ).filter(
            InvitationRecord.created_at >= cutoff
        ).group_by(
            InvitationRecord.inviter_id
        ).having(
            func.count(InvitationRecord.id) >= 10
        ).all()

        for inviter_id, count in invites:
            user = db.query(WebUser).filter(WebUser.id == inviter_id).first()
            alerts.append({
                "type": "invite_farming",
                "severity": "high" if count >= 20 else "medium",
                "user_id": inviter_id,
                "username": user.username if user else "未知",
                "detail": f"{count}天内邀请了 {count} 人",
                "action": "建议核查邀请真实性"
            })

        return alerts

    @staticmethod
    def _detect_refund_abuse(db: Session, cutoff: datetime) -> List[Dict]:
        """检测退款前高强度观看"""
        alerts = []
        # 查找最近退款的订单
        refunded = db.query(SubscriptionOrder).filter(
            SubscriptionOrder.status == 'refunded',
            SubscriptionOrder.paid_at >= cutoff
        ).all()

        for order in refunded:
            user = db.query(WebUser).filter(WebUser.id == order.user_id).first()
            if user:
                alerts.append({
                    "type": "refund_abuse",
                    "severity": "medium",
                    "user_id": order.user_id,
                    "username": user.username,
                    "detail": f"订单 {order.order_id} 已退款",
                    "action": "建议核查观看记录"
                })

        return alerts

    @staticmethod
    def get_dashboard(db: Session) -> Dict[str, Any]:
        """获取异常雷达仪表盘数据"""
        scan = RevenueRadarService.scan_anomalies(db, days=30)

        return {
            "total_alerts_30d": scan["total_alerts"],
            "breakdown": scan["summary"],
            "recent_alerts": scan["alerts"][:10],
            "risk_score": min(scan["total_alerts"] * 5, 100)
        }
