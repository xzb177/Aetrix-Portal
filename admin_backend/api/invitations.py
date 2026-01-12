"""
邀请管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from datetime import datetime

from admin_database_user import (
    get_user_db, InvitationCode, InvitationRecord,
    WebUser, SystemConfig
)
from admin_utils.auth import get_current_admin

router = APIRouter()


@router.get("/invitations/codes")
async def get_invitation_codes(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取邀请码列表 - 使用 JOIN 优化查询"""
    import logging
    from sqlalchemy import select
    logger = logging.getLogger(__name__)

    try:
        # 使用 LEFT JOIN 一次性获取关联的用户信息，避免 N+1 查询
        results = db.query(
            InvitationCode.id,
            InvitationCode.code,
            InvitationCode.user_id,
            InvitationCode.use_count,
            InvitationCode.created_at,
            WebUser.username
        ).outerjoin(
            WebUser, InvitationCode.user_id == WebUser.id
        ).order_by(
            InvitationCode.created_at.desc()
        ).offset(skip).limit(limit).all()

        logger.info(f"[邀请码] 查询到 {len(results)} 条记录")

        result = [
            {
                "id": row.id,
                "code": row.code,
                "user_id": row.user_id,
                "username": row.username or "未知用户",
                "use_count": row.use_count,
                "created_at": row.created_at
            }
            for row in results
        ]

        # 统一返回格式
        return {"code": 200, "message": "success", "data": result}

    except Exception as e:
        logger.error(f"[邀请码] 查询异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取邀请码失败: {str(e)}"
        )


@router.get("/invitations/records")
async def get_invitation_records(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取邀请记录列表 - 使用 JOIN 优化查询"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        # 使用 LEFT JOIN 一次性获取关联的用户和邀请码信息，避免 N+1 查询
        # 使用别名区分 inviter 和 invitee
        Inviter = WebUser.__table__.alias('inviter')
        Invitee = WebUser.__table__.alias('invitee')

        results = db.query(
            InvitationRecord.id,
            InvitationRecord.reward_points,
            InvitationRecord.created_at,
            Inviter.c.username.label('inviter_username'),
            Invitee.c.username.label('invitee_username'),
            InvitationCode.code
        ).outerjoin(
            Inviter, InvitationRecord.inviter_id == Inviter.c.id
        ).outerjoin(
            Invitee, InvitationRecord.invitee_id == Invitee.c.id
        ).outerjoin(
            InvitationCode, InvitationRecord.code_id == InvitationCode.id
        ).order_by(
            InvitationRecord.created_at.desc()
        ).offset(skip).limit(limit).all()

        result = [
            {
                "id": row.id,
                "inviter_username": row.inviter_username or "未知用户",
                "invitee_username": row.invitee_username or "未知用户",
                "code": row.code or "未知",
                "reward_points": row.reward_points,
                "created_at": row.created_at
            }
            for row in results
        ]

        return {"code": 200, "message": "success", "data": result}

    except Exception as e:
        logger.error(f"[邀请记录] 查询异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取邀请记录失败: {str(e)}"
        )


@router.get("/invitations/config")
async def get_invitation_config(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取邀请配置"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        configs = db.query(SystemConfig).filter(
            SystemConfig.key.in_([
                'invitation_enabled',
                'invitation_reward_points',
                'invitation_invitee_reward_points'
            ])
        ).all()

        result = {
            'invitation_enabled': True,
            'invitation_reward_points': 100,
            'invitation_invitee_reward_points': 50
        }

        for config in configs:
            if config.key == 'invitation_enabled':
                result['invitation_enabled'] = config.value.lower() == 'true' if config.value else True
            elif config.key == 'invitation_reward_points':
                result['invitation_reward_points'] = int(config.value) if config.value else 100
            elif config.key == 'invitation_invitee_reward_points':
                result['invitation_invitee_reward_points'] = int(config.value) if config.value else 50

        return {"code": 200, "message": "success", "data": result}

    except Exception as e:
        logger.error(f"[邀请配置] 查询异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取邀请配置失败: {str(e)}"
        )


@router.put("/invitations/config")
async def update_invitation_config(
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新邀请配置"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        config_keys = [
            'invitation_enabled',
            'invitation_reward_points',
            'invitation_invitee_reward_points'
        ]

        for key in config_keys:
            if key in data:
                config = db.query(SystemConfig).filter(
                    SystemConfig.key == key
                ).first()

                value = str(data[key])
                description = {
                    'invitation_enabled': '邀请系统开关',
                    'invitation_reward_points': '邀请者奖励积分',
                    'invitation_invitee_reward_points': '被邀请者奖励积分'
                }.get(key, '')

                if config:
                    config.value = value
                    config.updated_at = datetime.now()
                else:
                    config = SystemConfig(
                        key=key,
                        value=value,
                        description=description,
                        updated_at=datetime.now()
                    )
                    db.add(config)

        db.commit()

        return {"code": 200, "message": "配置更新成功", "data": None}

    except Exception as e:
        db.rollback()
        logger.error(f"[邀请配置] 更新异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新邀请配置失败: {str(e)}"
        )


@router.get("/invitations/stats")
async def get_invitation_stats(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取邀请统计"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        total_codes = db.query(InvitationCode).count()
        total_records = db.query(InvitationRecord).count()
        total_rewards = db.query(InvitationRecord).with_entities(
            func.sum(InvitationRecord.reward_points)
        ).scalar() or 0

        result = {
            "total_codes": total_codes,
            "total_invitations": total_records,
            "total_rewards": total_rewards
        }

        return {"code": 200, "message": "success", "data": result}

    except Exception as e:
        logger.error(f"[邀请统计] 查询异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取邀请统计失败: {str(e)}"
        )
