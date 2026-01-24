"""
徽章系统 API
彩蛋功能：身份签名卡 + 徽章系统
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from database import get_db
from database.models import WebUser, UserEmbyAccount, MovieRequest, BalanceTransaction, EmbyServer, Badge, UserBadge, INITIAL_BADGES
from api.auth import get_current_user
from utils.config import settings


class Response(BaseModel):
    """统一响应格式"""
    data: Any
    message: Optional[str] = None

router = APIRouter()

# Feature Flag
BADGES_ENABLED = getattr(settings, 'FEATURE_EASTER_EGG', True)


def get_badge_progress(user: WebUser, badge: Badge, db: Session) -> dict:
    """计算用户徽章进度"""
    # 检查是否已解锁
    user_badge = db.query(UserBadge).filter(
        UserBadge.user_id == user.id,
        UserBadge.badge_id == badge.id
    ).first()

    unlocked = False
    progress = 0
    max_progress = badge.requirement_value

    if badge.requirement_type == 'first_bind':
        # 首次绑定 Emby
        has_account = db.query(UserEmbyAccount).filter(
            UserEmbyAccount.user_id == user.id
        ).first()
        progress = 1 if has_account else 0
        unlocked = progress >= max_progress

    elif badge.requirement_type == 'request_count':
        # 求片次数
        count = db.query(MovieRequest).filter(
            MovieRequest.user_id == user.id
        ).count()
        progress = count
        unlocked = progress >= max_progress

    elif badge.requirement_type == 'recharge_amount':
        # 充值金额（分）
        total = db.query(BalanceTransaction).filter(
            BalanceTransaction.user_id == user.id,
            BalanceTransaction.type == 'recharge'
        ).all()
        progress = sum(t.amount for t in total)
        unlocked = progress >= max_progress

    return {
        'unlocked': unlocked,
        'progress': progress,
        'max_progress': max_progress,
        'unlocked_at': user_badge.unlocked_at.isoformat() if user_badge and user_badge.unlocked_at else None
    }


def check_and_unlock_badge(user_id: int, badge_code: str, db: Session) -> Optional[UserBadge]:
    """检查并解锁徽章"""
    badge = db.query(Badge).filter(
        Badge.code == badge_code,
        Badge.is_active == True
    ).first()

    if not badge:
        return None

    user = db.query(WebUser).filter(WebUser.id == user_id).first()
    if not user:
        return None

    # 检查是否已解锁
    existing = db.query(UserBadge).filter(
        UserBadge.user_id == user_id,
        UserBadge.badge_id == badge.id
    ).first()

    progress_data = get_badge_progress(user, badge, db)

    if progress_data['unlocked']:
        if existing:
            # 更新进度
            existing.progress = progress_data['progress']
            existing.updated_at = datetime.now()
            db.commit()
            return existing
        else:
            # 解锁徽章
            new_badge = UserBadge(
                user_id=user_id,
                badge_id=badge.id,
                progress=progress_data['progress'],
                unlocked_at=datetime.now()
            )
            db.add(new_badge)
            db.commit()
            db.refresh(new_badge)
            return new_badge

    # 更新进度
    if existing:
        existing.progress = progress_data['progress']
        existing.updated_at = datetime.now()
        db.commit()

    return None


@router.get("/badges")
async def get_user_badges(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户徽章列表"""
    if not BADGES_ENABLED:
        return Response(data={'badges': [], 'total': 0, 'unlocked': 0})

    # 获取所有启用的徽章
    badges = db.query(Badge).filter(
        Badge.is_active == True
    ).order_by(Badge.sort_order).all()

    result = []
    unlocked_count = 0

    for badge in badges:
        progress_data = get_badge_progress(current_user, badge, db)

        badge_data = {
            'id': badge.id,
            'code': badge.code,
            'name': badge.name,
            'name_en': badge.name_en,
            'description': badge.description,
            'icon': badge.icon,
            'color': badge.color,
            'rarity': badge.rarity,
            'category': badge.category,
            'unlocked': progress_data['unlocked'],
            'progress': progress_data['progress'],
            'max_progress': progress_data['max_progress'],
            'unlocked_at': progress_data['unlocked_at']
        }

        if badge_data['unlocked']:
            unlocked_count += 1

        result.append(badge_data)

    return Response(data={
        'badges': result,
        'total': len(result),
        'unlocked': unlocked_count
    })


@router.get("/badges/identity-card")
async def get_identity_card(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取身份卡数据"""
    if not BADGES_ENABLED:
        raise HTTPException(status_code=404, detail="Feature not enabled")

    # 获取用户徽章
    badges = db.query(Badge).filter(
        Badge.is_active == True
    ).order_by(Badge.sort_order).all()

    unlocked_badges = []
    for badge in badges:
        progress_data = get_badge_progress(current_user, badge, db)
        if progress_data['unlocked']:
            unlocked_badges.append({
                'code': badge.code,
                'name': badge.name,
                'icon': badge.icon,
                'color': badge.color,
                'rarity': badge.rarity,
                'unlocked_at': progress_data['unlocked_at']
            })

    # 计算等级（基于解锁徽章数）
    level = len(unlocked_badges) + 1

    # 获取 Emby 绑定信息
    emby_accounts = db.query(UserEmbyAccount).filter(
        UserEmbyAccount.user_id == current_user.id,
        UserEmbyAccount.is_active == True
    ).all()

    server_names = []
    for acc in emby_accounts:
        if acc.server:
            server_names.append(acc.server.name)

    return Response(data={
        'username': current_user.username,
        'user_id': current_user.id,
        'joined_at': current_user.created_at.isoformat(),
        'level': level,
        'badges': unlocked_badges,
        'total_requests': current_user.total_requests_count,
        'completed_requests': current_user.completed_requests_count,
        'emby_servers': server_names,
        'is_vip': False  # TODO: 从订阅状态判断
    })


@router.post("/badges/check")
async def check_badges(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动触发徽章检查（测试用）"""
    if not BADGES_ENABLED:
        return Response(data={'newly_unlocked': []})

    newly_unlocked = []

    for badge_def in INITIAL_BADGES:
        result = check_and_unlock_badge(current_user.id, badge_def['code'], db)
        if result and result.unlocked_at:
            # 检查是否刚刚解锁（5秒内）
            if (datetime.now() - result.unlocked_at).total_seconds() < 5:
                badge = db.query(Badge).filter(Badge.id == result.badge_id).first()
                newly_unlocked.append({
                    'code': badge.code,
                    'name': badge.name,
                    'icon': badge.icon
                })

    return Response(data={'newly_unlocked': newly_unlocked})


@router.get("/badges/initialize")
async def initialize_badges(
    db: Session = Depends(get_db),
    current_user: WebUser = Depends(get_current_user)
):
    """初始化徽章数据（仅管理员）"""
    if not current_user.is_staff:
        raise HTTPException(status_code=403, detail="Forbidden")

    for badge_def in INITIAL_BADGES:
        existing = db.query(Badge).filter(Badge.code == badge_def['code']).first()
        if not existing:
            badge = Badge(**badge_def)
            db.add(badge)

    db.commit()
    return Response(data={'message': 'Badges initialized'})
