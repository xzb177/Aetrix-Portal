"""
阶梯邀请服务
管理阶梯邀请奖励：邀请 1 人/3 人/5 人 有不同奖励
"""
import logging
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.models import WebUser, InvitationRecord, Message
from database.models_new import TieredInviteReward, UserInviteProgress

logger = logging.getLogger(__name__)


# 默认阶梯配置
DEFAULT_TIERS = [
    {
        "tier": 1,
        "required_invites": 1,
        "reward_type": "badge",
        "reward_value": {"badge_id": "inviter_bronze", "name": "青铜邀请官"},
        "description": "邀请 1 人，获得青铜邀请官徽章"
    },
    {
        "tier": 2,
        "required_invites": 3,
        "reward_type": "subscription_days",
        "reward_value": {"days": 3},
        "description": "邀请满 3 人，送 3 天订阅时长"
    },
    {
        "tier": 3,
        "required_invites": 5,
        "reward_type": "subscription_days",
        "reward_value": {"days": 7, "badge_id": "inviter_gold", "badge_name": "黄金邀请官"},
        "description": "邀请满 5 人，送 7 天订阅 + 黄金邀请官徽章"
    },
]


class TieredInviteService:
    """阶梯邀请管理"""

    @staticmethod
    def check_and_reward(user_id: int, db: Session) -> List[Dict]:
        """检查用户邀请进度，发放未领取的奖励（带幂等锁）"""
        import redis as _redis
        import os as _os
        rewards_earned = []

        # 幂等锁：防止并发重复发放
        lock_key = f"invite_reward_lock:{user_id}"
        try:
            r = _redis.from_url(
                _os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True, socket_timeout=3
            )
            if not r.set(lock_key, "1", nx=True, ex=10):
                return []  # 另一个请求正在处理
        except Exception:
            pass  # Redis 不可用时降级

        # 获取或创建进度记录
        progress = db.query(UserInviteProgress).filter(
            UserInviteProgress.user_id == user_id
        ).first()

        if not progress:
            progress = UserInviteProgress(user_id=user_id, total_invites=0, completed_tiers=[])
            db.add(progress)

        # 统计有效邀请数
        invite_count = db.query(InvitationRecord).filter(
            InvitationRecord.inviter_id == user_id
        ).count()

        progress.total_invites = invite_count
        completed = progress.completed_tiers or []

        # 检查每个阶梯
        tiers = db.query(TieredInviteReward).filter(
            TieredInviteReward.is_active == True
        ).order_by(TieredInviteReward.tier).all()

        if not tiers:
            # 使用默认配置
            tiers_data = DEFAULT_TIERS
        else:
            tiers_data = [{"tier": t.tier, "required_invites": t.required_invites,
                           "reward_type": t.reward_type, "reward_value": t.reward_value,
                           "description": t.description} for t in tiers]

        for tier_config in tiers_data:
            tier_num = tier_config["tier"]
            required = tier_config["required_invites"]

            if tier_num in completed:
                continue  # 已完成

            if invite_count >= required:
                # 达标，发放奖励
                reward_result = TieredInviteService._grant_reward(
                    user_id, tier_config, db
                )
                completed.append(tier_num)
                rewards_earned.append({
                    "tier": tier_num,
                    "description": tier_config["description"],
                    "reward": reward_result
                })

        progress.completed_tiers = completed
        progress.last_invite_at = datetime.now()
        db.commit()

        return rewards_earned

    @staticmethod
    def _grant_reward(user_id: int, tier_config: Dict, db: Session) -> Dict:
        """发放阶梯奖励"""
        reward_type = tier_config["reward_type"]
        reward_value = tier_config["reward_value"]

        if reward_type == "subscription_days":
            # 延长订阅
            from database.models import UserSubscription
            sub = db.query(UserSubscription).filter(
                UserSubscription.user_id == user_id,
                UserSubscription.status == 'active'
            ).first()

            if sub and sub.end_date:
                from datetime import timedelta
                sub.end_date += timedelta(days=reward_value.get("days", 1))
                db.commit()
                return {"type": "subscription_days", "days": reward_value["days"]}

        elif reward_type == "badge":
            # 发放徽章（发消息通知）
            msg = Message(
                user_id=user_id,
                title=f"🏆 恭喜获得 {reward_value.get('name', '邀请徽章')}",
                content=tier_config["description"],
                message_type="system"
            )
            db.add(msg)
            db.commit()
            return {"type": "badge", "badge_id": reward_value.get("badge_id")}

        return {"type": "none"}

    @staticmethod
    def get_progress(user_id: int, db: Session) -> Dict[str, Any]:
        """获取用户邀请进度"""
        progress = db.query(UserInviteProgress).filter(
            UserInviteProgress.user_id == user_id
        ).first()

        invite_count = db.query(InvitationRecord).filter(
            InvitationRecord.inviter_id == user_id
        ).count()

        completed = progress.completed_tiers if progress else []

        tiers = []
        for tc in DEFAULT_TIERS:
            tiers.append({
                "tier": tc["tier"],
                "required": tc["required_invites"],
                "description": tc["description"],
                "completed": tc["tier"] in completed,
                "progress": min(invite_count, tc["required_invites"])
            })

        return {
            "total_invites": invite_count,
            "completed_tiers": completed,
            "tiers": tiers
        }
