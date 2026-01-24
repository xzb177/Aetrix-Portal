"""
邀请系统 API - 用户端
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List
import secrets
import string
import logging

from database import get_session
from database.models import InvitationCode, InvitationRecord, WebUser, SystemConfig
from schemas.invitation import (
    InvitationCodeResponse,
    InvitationStatsResponse,
    InvitationRecordResponse,
    CreateInvitationCode,
    ApplyInvitationCode
)
from api.auth import get_current_user
from schemas.auth import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["邀请"])


@router.get("/config")
async def get_invitation_config(
    db: Session = Depends(get_session)
):
    """
    获取邀请配置（公开接口，用于前端展示规则）

    返回邀请开关状态、邀请者奖励、被邀请者奖励等配置
    """
    return get_config(db)


def get_config(db: Session) -> dict:
    """获取邀请配置"""
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

    return result


@router.get("/my-code")
async def get_my_code(
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取我的邀请码

    如果没有邀请码，自动生成一个
    """
    try:
        config = get_config(db)

        if not config['invitation_enabled']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="邀请功能未启用"
            )

        # 查找已有邀请码
        code = db.query(InvitationCode).filter(
            InvitationCode.user_id == current_user.id
        ).first()

        if not code:
            # 自动生成邀请码
            code_str = generate_code()
            code = InvitationCode(
                code=code_str,
                user_id=current_user.id,
                use_count=0
            )
            db.add(code)
            db.commit()
            db.refresh(code)

        return {
            "code": 200,
            "message": "获取成功",
            "data": {
                "id": code.id,
                "code": code.code,
                "use_count": code.use_count,
                "created_at": code.created_at.isoformat() if code.created_at else None
            }
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"获取邀请码数据库错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取邀请码失败，请稍后重试"
        )
    except Exception as e:
        logger.error(f"获取邀请码未知错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取邀请码失败: {str(e)}"
        )


@router.post("/generate", response_model=InvitationCodeResponse)
async def generate_code(
    code_data: CreateInvitationCode,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    生成新邀请码
    """
    config = get_config(db)

    if not config['invitation_enabled']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="邀请功能未启用"
        )

    # 使用指定代码或生成新代码
    code_str = code_data.code if code_data.code else generate_code()

    # 检查代码是否已存在
    existing = db.query(InvitationCode).filter(
        InvitationCode.code == code_str
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码已存在"
        )

    # 删除旧邀请码（如果存在）
    old_code = db.query(InvitationCode).filter(
        InvitationCode.user_id == current_user.id
    ).first()
    if old_code:
        db.delete(old_code)

    # 创建新邀请码
    code = InvitationCode(
        code=code_str,
        user_id=current_user.id,
        use_count=0
    )
    db.add(code)
    db.commit()
    db.refresh(code)

    return InvitationCodeResponse(
        id=code.id,
        code=code.code,
        use_count=code.use_count,
        created_at=code.created_at
    )


@router.get("/records", response_model=List[InvitationRecordResponse])
async def get_invitation_records(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取我的邀请记录
    """
    config = get_config(db)

    if not config['invitation_enabled']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="邀请功能未启用"
        )

    records = db.query(InvitationRecord).filter(
        InvitationRecord.inviter_id == current_user.id
    ).order_by(
        InvitationRecord.created_at.desc()
    ).offset(skip).limit(limit).all()

    result = []
    for record in records:
        invitee = db.query(WebUser).filter(WebUser.id == record.invitee_id).first()
        result.append(InvitationRecordResponse(
            id=record.id,
            invitee_username=invitee.username if invitee else "未知用户",
            reward_points=record.reward_points,
            conversion_status=record.conversion_status or 'registered',
            first_payment_at=record.first_payment_at,
            first_subscription_at=record.first_subscription_at,
            created_at=record.created_at
        ))

    return result


@router.get("/stats")
async def get_invitation_stats(
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取邀请统计
    """
    try:
        config = get_config(db)

        if not config['invitation_enabled']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="邀请功能未启用"
            )

        # 获取邀请码
        code = db.query(InvitationCode).filter(
            InvitationCode.user_id == current_user.id
        ).first()

        # 如果没有邀请码，自动生成
        if not code:
            code_str = generate_code()
            code = InvitationCode(
                code=code_str,
                user_id=current_user.id,
                use_count=0
            )
            db.add(code)
            db.commit()
            db.refresh(code)

        # 统计邀请记录
        records = db.query(InvitationRecord).filter(
            InvitationRecord.inviter_id == current_user.id
        ).all()

        total_rewards = sum(r.reward_points for r in records)

        return {
            "code": 200,
            "message": "获取成功",
            "data": {
                "total_invitations": len(records),
                "total_rewards": total_rewards,
                "my_code": code.code,
                "use_count": code.use_count or 0
            }
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"获取邀请统计数据库错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取邀请统计失败，请稍后重试"
        )
    except Exception as e:
        logger.error(f"获取邀请统计未知错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取邀请统计失败: {str(e)}"
        )


@router.post("/apply")
async def apply_invitation(
    data: ApplyInvitationCode,
    db: Session = Depends(get_session)
):
    """
    使用邀请码

    注意：此接口应在注册时调用，需要验证会话中的用户状态
    """
    config = get_config(db)

    if not config['invitation_enabled']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="邀请功能未启用"
        )

    # 查找邀请码
    code = db.query(InvitationCode).filter(
        InvitationCode.code == data.code
    ).first()

    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="邀请码不存在"
        )

    # TODO: 这里需要在注册流程中集成
    # 1. 验证当前用户是否正在注册
    # 2. 创建邀请记录
    # 3. 给邀请者和被邀请者发放奖励

    return {
        "message": "邀请码验证成功，注册完成后将自动发放奖励",
        "inviter_id": code.user_id,
        "code": code.code
    }


def generate_code(length: int = 8) -> str:
    """
    生成邀请码

    Args:
        length: 邀请码长度

    Returns:
        邀请码
    """
    alphabet = string.ascii_uppercase + string.digits
    # 排除容易混淆的字符
    alphabet = alphabet.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def process_invitation_reward(db: Session, invitee_id: int, code_str: str):
    """
    处理邀请奖励（在注册成功后调用）

    Args:
        db: 数据库会话
        invitee_id: 被邀请者用户 ID
        code_str: 邀请码字符串
    """
    config = get_config(db)

    code = db.query(InvitationCode).filter(InvitationCode.code == code_str).first()
    if not code:
        return

    # 检查是否已经处理过
    existing = db.query(InvitationRecord).filter(
        InvitationRecord.invitee_id == invitee_id
    ).first()

    if existing:
        return

    # 创建邀请记录
    inviter_reward = config['invitation_reward_points']
    invitee_reward = config['invitation_invitee_reward_points']

    record = InvitationRecord(
        inviter_id=code.user_id,
        invitee_id=invitee_id,
        code=code_str,
        reward_points=inviter_reward + invitee_reward
    )
    db.add(record)

    # 增加邀请码使用次数
    code.use_count += 1

    db.commit()

    # TODO: 这里可以集成 MP 积分系统
    # 给邀请者和被邀请者发放积分


def update_conversion_status(db: Session, user_id: int, status: str):
    """
    更新邀请转化状态

    在用户首次支付或订阅成功时调用

    Args:
        db: 数据库会话
        user_id: 用户 ID
        status: 转化状态 (paid/subscribed)
    """
    from datetime import datetime

    record = db.query(InvitationRecord).filter(
        InvitationRecord.invitee_id == user_id
    ).first()

    if not record:
        return

    updated = False
    now = datetime.now()

    if status == 'paid' and record.conversion_status == 'registered':
        record.conversion_status = 'paid'
        record.first_payment_at = now
        updated = True

    if status == 'subscribed':
        # 订阅是更高的状态，无论当前状态如何都更新
        if record.conversion_status != 'subscribed':
            record.conversion_status = 'subscribed'
            record.first_subscription_at = now
            # 如果还没有首次支付时间，同时设置
            if not record.first_payment_at:
                record.first_payment_at = now
            updated = True

    if updated:
        db.commit()
        logger.info(f"更新邀请转化状态: user_id={user_id}, status={status}, record_id={record.id}")


def get_conversion_stats(db: Session, inviter_id: int) -> dict:
    """
    获取邀请转化统计

    Args:
        db: 数据库会话
        inviter_id: 邀请者 ID

    Returns:
        转化统计数据
    """
    records = db.query(InvitationRecord).filter(
        InvitationRecord.inviter_id == inviter_id
    ).all()

    return {
        'total': len(records),
        'registered': sum(1 for r in records if r.conversion_status == 'registered'),
        'paid': sum(1 for r in records if r.conversion_status == 'paid'),
        'subscribed': sum(1 for r in records if r.conversion_status == 'subscribed'),
        'conversion_rate': round(
            sum(1 for r in records if r.conversion_status in ['paid', 'subscribed']) / len(records) * 100, 1
        ) if records else 0
    }
