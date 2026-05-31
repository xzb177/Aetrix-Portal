"""
流失预测服务
分析用户活跃度，预测流失风险，自动执行挽留动作
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.models import (
    WebUser, UserSubscription, UserEmbyAccount, EmbyServer,
    Message, UserAuditLog
)

logger = logging.getLogger(__name__)


class ChurnPredictionService:
    """流失预测与挽留"""

    # 风险阈值
    RISK_THRESHOLDS = {
        "low": 20,
        "medium": 50,
        "high": 75,
        "critical": 90,
    }

    @staticmethod
    def analyze_user(user_id: int, db: Session) -> Dict[str, Any]:
        """分析单个用户的流失风险"""
        user = db.query(WebUser).filter(WebUser.id == user_id).first()
        if not user:
            return {"error": "用户不存在"}

        now = datetime.now()
        risk_factors = []
        score = 0

        # 因子1：最近登录时间
        last_login = user.updated_at or user.created_at
        if last_login:
            days_inactive = (now - last_login).days
            if days_inactive >= 14:
                risk_factors.append(f"inactive_{days_inactive}days")
                score += min(days_inactive * 3, 40)
            elif days_inactive >= 7:
                risk_factors.append(f"inactive_{days_inactive}days")
                score += days_inactive * 2

        # 因子2：订阅即将过期
        subscription = db.query(UserSubscription).filter(
            UserSubscription.user_id == user_id,
            UserSubscription.status == 'active'
        ).first()

        if subscription:
            days_to_expiry = (subscription.end_date - now).days if subscription.end_date else 999
            if days_to_expiry <= 3:
                risk_factors.append(f"expiring_in_{days_to_expiry}d")
                score += 25
            elif days_to_expiry <= 7:
                risk_factors.append(f"expiring_in_{days_to_expiry}d")
                score += 10
        else:
            risk_factors.append("no_active_subscription")
            score += 30

        # 因子3：无 Emby 账号
        emby_accounts = db.query(UserEmbyAccount).filter(
            UserEmbyAccount.user_id == user_id,
            UserEmbyAccount.is_active == True
        ).count()

        if emby_accounts == 0:
            risk_factors.append("no_emby_account")
            score += 20

        # 因子4：无最近活动记录
        recent_activity = db.query(UserAuditLog).filter(
            UserAuditLog.user_id == user_id,
            UserAuditLog.created_at >= now - timedelta(days=7)
        ).count()

        if recent_activity == 0:
            risk_factors.append("no_recent_activity")
            score += 15

        # 确定风险等级
        if score >= 70:
            level = "critical"
        elif score >= 50:
            level = "high"
        elif score >= 30:
            level = "medium"
        else:
            level = "low"

        return {
            "user_id": user_id,
            "username": user.username,
            "risk_score": min(score, 100),
            "risk_level": level,
            "factors": risk_factors,
            "evaluated_at": now.isoformat()
        }

    @staticmethod
    def run_churn_scan(db: Session, auto_action: bool = False) -> Dict[str, Any]:
        """
        扫描所有活跃用户，评估流失风险

        Args:
            auto_action: 是否自动执行挽留动作
        """
        now = datetime.now()
        results = {"scanned": 0, "at_risk": 0, "actions_taken": 0}

        # 扫描有活跃订阅的用户
        active_user_ids = db.query(UserSubscription.user_id).filter(
            UserSubscription.status == 'active'
        ).distinct().all()

        for (user_id,) in active_user_ids:
            results["scanned"] += 1
            assessment = ChurnPredictionService.evaluate_user(user_id, db)

            if assessment["risk_level"] in ["high", "critical"]:
                results["at_risk"] += 1

                if auto_action and assessment["risk_level"] == "critical":
                    # 自动挽留：送1天高级体验
                    action_taken = ChurnPredictionService._auto_retain(user_id, db, assessment)
                    if action_taken:
                        results["actions_taken"] += 1

        return results

    @staticmethod
    def evaluate_user(user_id: int, db: Session) -> Dict[str, Any]:
        """评估单个用户（别名）"""
        return ChurnPredictionService.check_and_retain(user_id, db)

    @staticmethod
    def check_and_retain(user_id: int, db: Session) -> Dict[str, Any]:
        """检查用户流失风险并返回评估结果"""
        return ChurnPredictionService._evaluate(user_id, db)

    @staticmethod
    def _evaluate(user_id: int, db: Session) -> Dict[str, Any]:
        """内部评估方法"""
        user = db.query(WebUser).filter(WebUser.id == user_id).first()
        if not user:
            return {"user_id": user_id, "risk_level": "unknown", "risk_score": 0, "factors": []}

        now = datetime.now()
        risk_factors = []
        score = 0

        # 最近登录
        last_login = user.updated_at or user.created_at
        if last_login:
            days_inactive = (now - last_login).days
            if days_inactive >= 14:
                risk_factors.append(f"inactive_{days_inactive}days")
                score += min(days_inactive * 3, 40)
            elif days_inactive >= 7:
                score += days_inactive * 2

        # 订阅状态
        subscription = db.query(UserSubscription).filter(
            UserSubscription.user_id == user_id,
            UserSubscription.status == 'active'
        ).first()

        if subscription and subscription.end_date:
            days_to_expiry = (subscription.end_date - now).days
            if days_to_expiry <= 3:
                risk_factors.append(f"expiring_in_{days_to_expiry}d")
                score += 25
        elif not subscription:
            risk_factors.append("no_active_subscription")
            score += 30

        # 确定等级
        if score >= 70:
            level = "critical"
        elif score >= 50:
            level = "high"
        elif score >= 30:
            level = "medium"
        else:
            level = "low"

        return {
            "user_id": user_id,
            "username": user.username,
            "risk_score": min(score, 100),
            "risk_level": level,
            "factors": risk_factors,
            "evaluated_at": now.isoformat()
        }

    @staticmethod
    def _auto_retain(user_id: int, db: Session, assessment: Dict) -> bool:
        """自动挽留动作"""
        try:
            # 检查是否已经挽留过
            existing = db.query(Message).filter(
                Message.user_id == user_id,
                Message.title.like("%流失挽留%")
            ).first()

            if existing:
                return False

            # 发送挽留消息 + 送体验
            msg = Message(
                user_id=user_id,
                title="🎁 流失挽留：送你 1 天高级体验",
                content="我们注意到你最近不太活跃，特送你 1 天高级体验。"
                        "续费可享专属优惠，详情联系管理员。",
                message_type="system"
            )
            db.add(msg)
            db.commit()

            logger.info(f"流失挽留已执行: user={user_id}, risk={assessment['risk_level']}")
            return True

        except Exception as e:
            logger.error(f"流失挽留执行失败: {e}")
            return False
