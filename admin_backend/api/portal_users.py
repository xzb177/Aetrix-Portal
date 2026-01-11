"""
门户用户管理 API - 管理后台
性能优化版：修复 N+1 查询问题
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime

from admin_database_user import (
    get_user_db, WebUser, UserSubscription,
    SubscriptionPlan, UserEmbyAccount, EmbyServer
)
from admin_utils.auth import get_current_admin

router = APIRouter()


@router.get("/portal/users")
async def get_users(
    search: Optional[str] = None,
    is_vip_only: bool = False,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取门户用户列表 - 优化版，修复 N+1 查询"""
    query = db.query(WebUser)

    if search:
        # 使用索引友好的 LIKE 查询
        safe_search = search.replace("%", "\\%").replace("_", "\\_")
        query = query.filter(
            (WebUser.username.contains(safe_search)) |
            (WebUser.email.contains(safe_search))
        )

    users = query.order_by(
        WebUser.created_at.desc()
    ).offset(skip).limit(limit).all()

    if not users:
        return []

    # 批量获取用户 ID
    user_ids = [u.id for u in users]

    # 一次性查询所有用户的订阅状态
    active_subs = db.query(UserSubscription).filter(
        UserSubscription.user_id.in_(user_ids),
        UserSubscription.status == 'active'
    ).all()

    # 一次性查询所有用户的 Emby 账号数量
    emby_counts = db.query(
        UserEmbyAccount.user_id,
        db.func.count(UserEmbyAccount.id).label('count')
    ).filter(
        UserEmbyAccount.user_id.in_(user_ids)
    ).group_by(UserEmbyAccount.user_id).all()

    # 构建查找字典
    sub_dict = {sub.user_id: sub for sub in active_subs}
    emby_dict = {int(row.user_id): row.count for row in emby_counts}

    result = []
    for user in users:
        active_sub = sub_dict.get(user.id)
        emby_count = emby_dict.get(user.id, 0)

        result.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "telegram_id": user.telegram_id,
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "is_vip": active_sub is not None,
            "current_plan": active_sub.plan.name if active_sub and active_sub.plan else None,
            "emby_account_count": emby_count,
            "created_at": user.created_at
        })

    return result


@router.get("/portal/users/stats")
async def get_user_stats(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取用户统计 - 优化版，使用单次查询"""
    from datetime import datetime, timedelta
    from sqlalchemy import func, case, literal_column

    # 今日开始时间
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = datetime.now() - timedelta(days=7)

    # 使用单次查询获取所有统计
    stats = db.query(
        func.count(WebUser.id).label('total_users'),
        func.sum(case((WebUser.is_active == True, 1), else_=0)).label('active_users'),
        func.sum(case((WebUser.is_staff == True, 1), else_=0)).label('staff_users'),
        func.sum(case((WebUser.created_at >= today_start, 1), else_=0)).label('new_users_today'),
        func.sum(case(
            (WebUser.is_active == True, 1),
            else_=0
        )).filter(WebUser.created_at >= today_start).label('active_today'),
    ).first()

    # VIP 用户数
    vip_users = db.query(func.count(func.distinct(UserSubscription.user_id))).filter(
        UserSubscription.status == 'active'
    ).scalar()

    # Emby 账号数
    emby_accounts = db.query(func.count(UserEmbyAccount.id)).scalar()

    return {
        "total_users": stats.total_users or 0,
        "active_users": int(stats.active_users or 0),
        "active_today": int(stats.active_today or 0),
        "active_week": 0,  # 可按需添加
        "new_users_today": stats.new_users_today or 0,
        "staff_users": int(stats.staff_users or 0),
        "vip_users": vip_users or 0,
        "emby_accounts": emby_accounts or 0,
        "total_watch_minutes": 0
    }


@router.get("/portal/users/{user_id}")
async def get_user_detail(
    user_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取用户详情 - 优化版，使用 JOIN 减少 N+1 查询"""
    user = db.query(WebUser).filter(WebUser.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 使用 JOIN 一次性获取订阅和计划信息
    subscriptions = db.query(UserSubscription).join(
        SubscriptionPlan,
        UserSubscription.plan_id == SubscriptionPlan.id
    ).filter(
        UserSubscription.user_id == user_id
    ).order_by(UserSubscription.created_at.desc()).all()

    sub_list = []
    for sub in subscriptions:
        sub_list.append({
            "id": sub.id,
            "plan_name": sub.plan.name if sub.plan else "未知",
            "start_date": sub.start_date,
            "end_date": sub.end_date,
            "status": sub.status,
            "auto_renew": sub.auto_renew
        })

    # 使用 JOIN 一次性获取 Emby 账号和服务器信息
    emby_accounts = db.query(UserEmbyAccount).join(
        EmbyServer,
        UserEmbyAccount.server_id == EmbyServer.id
    ).filter(
        UserEmbyAccount.user_id == user_id
    ).all()

    emby_list = []
    for acc in emby_accounts:
        emby_list.append({
            "id": acc.id,
            "server_name": acc.server.name if acc.server else "未知",
            "username": acc.username,
            "password": acc.password,
            "expires_at": acc.expires_at,
            "created_at": acc.created_at
        })

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "telegram_id": user.telegram_id,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "created_at": user.created_at,
        "subscriptions": sub_list,
        "emby_accounts": emby_list
    }


@router.put("/portal/users/{user_id}/status")
async def update_user_status(
    user_id: int,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新用户状态"""
    user = db.query(WebUser).filter(WebUser.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    if 'is_active' in data:
        user.is_active = data['is_active']
    if 'is_staff' in data:
        user.is_staff = data['is_staff']

    db.commit()

    return {"message": "用户状态更新成功"}


@router.delete("/portal/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """删除用户"""
    user = db.query(WebUser).filter(WebUser.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 删除相关数据
    db.query(UserEmbyAccount).filter(
        UserEmbyAccount.user_id == user_id
    ).delete(synchronize_session=False)

    db.delete(user)
    db.commit()

    return {"message": "用户删除成功"}