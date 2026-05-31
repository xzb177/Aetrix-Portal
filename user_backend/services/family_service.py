"""
家庭席位服务
管理家庭组、子账号、权限
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from database.models import WebUser
from database.models_new import FamilySeat, FamilyMember

logger = logging.getLogger(__name__)

# 套餐配置
PLAN_CONFIG = {
    "standard": {"max_members": 3, "name": "标准家庭"},
    "premium": {"max_members": 5, "name": "高级家庭"},
    "elite": {"max_members": 8, "name": "旗舰家庭"},
}


class FamilyService:
    """家庭席位管理"""

    @staticmethod
    def create_family(owner_id: int, plan_type: str = "standard", db: Session = None) -> Dict[str, Any]:
        """创建家庭组"""
        config = PLAN_CONFIG.get(plan_type, PLAN_CONFIG["standard"])

        # 检查是否已有家庭
        existing = db.query(FamilySeat).filter(FamilySeat.owner_id == owner_id).first()
        if existing:
            return {"success": False, "message": "你已经创建了家庭组"}

        family = FamilySeat(
            owner_id=owner_id,
            plan_type=plan_type,
            max_members=config["max_members"],
            is_active=True
        )
        db.add(family)
        db.commit()
        db.refresh(family)

        return {
            "success": True,
            "family_id": family.id,
            "plan_type": plan_type,
            "max_members": config["max_members"],
            "message": f"家庭组创建成功（{config['name']}，最多 {config['max_members']} 人）"
        }

    @staticmethod
    def add_member(owner_id: int, invite_username: str, nickname: str = "", db: Session = None) -> Dict[str, Any]:
        """添加家庭成员"""
        family = db.query(FamilySeat).filter(
            FamilySeat.owner_id == owner_id,
            FamilySeat.is_active == True
        ).first()

        if not family:
            return {"success": False, "message": "你还没有创建家庭组"}

        # 检查人数限制
        current_count = db.query(FamilyMember).filter(
            FamilyMember.family_id == family.id,
            FamilyMember.is_active == True
        ).count()

        if current_count >= family.max_members:
            return {"success": False, "message": f"家庭组已满（{family.max_members} 人）"}

        # 查找被邀请用户
        invite_user = db.query(WebUser).filter(WebUser.username == invite_username).first()
        if not invite_user:
            return {"success": False, "message": f"用户 {invite_username} 不存在"}

        if invite_user.id == owner_id:
            return {"success": False, "message": "不能邀请自己"}

        # 检查是否已在家庭中
        existing = db.query(FamilyMember).filter(
            FamilyMember.family_id == family.id,
            FamilyMember.user_id == invite_user.id,
            FamilyMember.is_active == True
        ).first()

        if existing:
            return {"success": False, "message": f"{invite_username} 已在你的家庭组中"}

        # 添加成员
        member = FamilyMember(
            family_id=family.id,
            user_id=invite_user.id,
            nickname=nickname or invite_username,
            role="member",
            is_active=True
        )
        db.add(member)
        db.commit()

        return {
            "success": True,
            "message": f"已邀请 {invite_username} 加入家庭组",
            "member_id": member.id
        }

    @staticmethod
    def remove_member(owner_id: int, member_id: int, db: Session = None) -> Dict[str, Any]:
        """移除家庭成员"""
        family = db.query(FamilySeat).filter(FamilySeat.owner_id == owner_id).first()
        if not family:
            return {"success": False, "message": "家庭组不存在"}

        member = db.query(FamilyMember).filter(
            FamilyMember.id == member_id,
            FamilyMember.family_id == family.id
        ).first()

        if not member:
            return {"success": False, "message": "成员不存在"}

        member.is_active = False
        db.commit()

        return {"success": True, "message": "成员已移除"}

    @staticmethod
    def get_family_info(owner_id: int, db: Session = None) -> Dict[str, Any]:
        """获取家庭组信息"""
        family = db.query(FamilySeat).filter(FamilySeat.owner_id == owner_id).first()
        if not family:
            return {"has_family": False}

        members = db.query(FamilyMember).filter(
            FamilyMember.family_id == family.id,
            FamilyMember.is_active == True
        ).all()

        member_list = []
        for m in members:
            user = db.query(WebUser).filter(WebUser.id == m.user_id).first()
            member_list.append({
                "id": m.id,
                "username": user.username if user else "未知",
                "nickname": m.nickname,
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None
            })

        return {
            "has_family": True,
            "family_id": family.id,
            "plan_type": family.plan_type,
            "plan_name": PLAN_CONFIG.get(family.plan_type, {}).get("name", "未知"),
            "max_members": family.max_members,
            "current_members": len(member_list),
            "members": member_list,
            "created_at": family.created_at.isoformat() if family.created_at else None
        }
