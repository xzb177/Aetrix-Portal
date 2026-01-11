"""
用户管理 API
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_, desc

from admin_database import get_main_db, UserBinding
from admin_utils.models_loader import AdminLog, Permission
from schemas.user import UserListItem, UserDetail, UserUpdate, UserStats, UserSearchRequest
from schemas.common import Response, PaginatedResponse, PageParams
from admin_utils.auth import get_current_admin, require_permission

router = APIRouter()


def sanitize_like_query(value: str) -> str:
    """转义 LIKE 查询中的特殊字符，防止 SQL 注入"""
    if not value:
        return ""
    # 转义 LIKE 特殊字符: % _ \
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


@router.get("", response_model=Response[PaginatedResponse[UserListItem]])
async def get_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    is_vip: Optional[bool] = None,
    has_emby: Optional[bool] = None,
    sort_by: str = "tg_id",
    sort_order: str = "desc",
    current_admin = Depends(require_permission("users.view")),
    db: Session = Depends(get_main_db)
):
    """获取用户列表（支持搜索和筛选）"""
    try:
        # 构建查询
        query = db.query(UserBinding)

        # 关键词搜索（使用转义防止 SQL 注入）
        if keyword:
            safe_keyword = sanitize_like_query(keyword.strip())
            query = query.filter(
                or_(
                    UserBinding.tg_id.like(f"%{safe_keyword}%"),
                    UserBinding.emby_account.like(f"%{safe_keyword}%"),
                )
            )

        # VIP 筛选
        if is_vip is not None:
            query = query.filter(UserBinding.is_vip == is_vip)

        # Emby 绑定筛选
        if has_emby is not None:
            if has_emby:
                query = query.filter(UserBinding.emby_account != None, UserBinding.emby_account != "")
            else:
                query = query.filter(or_(UserBinding.emby_account == None, UserBinding.emby_account == ""))

        # 排序（使用白名单验证列名）
        ALLOWED_SORT_COLUMNS = {
            "id", "tg_id", "emby_account", "is_vip",
            "points", "bank_points", "attack", "total_watch_minutes",
            "total_checkin_days", "last_checkin_date", "created_at"
        }
        sort_column_name = sort_by if sort_by in ALLOWED_SORT_COLUMNS else "tg_id"
        sort_column = getattr(UserBinding, sort_column_name, UserBinding.tg_id)

        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(sort_column)

        # 分页
        total = query.count()
        offset = (page - 1) * page_size
        users = query.offset(offset).limit(page_size).all()

        # 转换为响应格式
        items = [
            UserListItem(
                tg_id=u.tg_id,
                username=None,  # 需要从 Telegram API 获取
                emby_account=u.emby_account,
                is_vip=u.is_vip if u.is_vip is not None else False,
                points=u.points or 0,
                bank_points=u.bank_points or 0,
                attack=u.attack or 0,
                total_watch_minutes=u.total_watch_minutes or 0,
                total_checkin_days=u.total_checkin_days or 0,
                last_checkin_date=u.last_checkin_date,
                watch_streak=u.watch_streak or 0,
            )
            for u in users
        ]

        return Response(data=PaginatedResponse.create(items, total, page, page_size))
    except Exception as e:
        # 如果 bindings 表不存在或为空，返回空结果
        from admin_utils.logging_config import logger, ErrorCode
        logger.warning(f"Error querying users: {e}")
        # 返回空结果而不是错误
        return Response(data=PaginatedResponse.create(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
        ))


@router.get("/{user_id}", response_model=Response[UserDetail])
async def get_user_detail(
    user_id: int,
    current_admin = Depends(require_permission("users.view")),
    db: Session = Depends(get_main_db)
):
    """获取用户详情"""
    user = db.query(UserBinding).filter(UserBinding.tg_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    return Response(data=UserDetail(
        tg_id=user.tg_id,
        username=None,
        emby_account=user.emby_account,
        is_vip=user.is_vip if user.is_vip is not None else False,
        points=user.points or 0,
        bank_points=user.bank_points or 0,
        accumulated_interest=user.accumulated_interest or 0,
        total_earned=user.total_earned or 0,
        total_spent=user.total_spent or 0,
        attack=user.attack or 0,
        weapon=user.weapon,
        breakthrough_level=user.breakthrough_level or 0,
        consecutive_checkin=user.consecutive_checkin or 0,
        total_checkin_days=user.total_checkin_days or 0,
        last_checkin_date=user.last_checkin_date,
        daily_watch_minutes=user.daily_watch_minutes or 0,
        total_watch_minutes=user.total_watch_minutes or 0,
        watch_streak=user.watch_streak or 0,
        total_watch_checkin_days=user.total_watch_checkin_days or 0,
        max_watch_streak=user.max_watch_streak or 0,
        watch_checkin_today=user.watch_checkin_today if user.watch_checkin_today is not None else False,
        early_bird_wins=user.early_bird_wins or 0,
        achievements=user.achievements or "",
    ))


@router.put("/{user_id}", response_model=Response[dict])
async def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    current_admin = Depends(require_permission("users.edit")),
    db: Session = Depends(get_main_db)
):
    """更新用户信息"""
    user = db.query(UserBinding).filter(UserBinding.tg_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 更新字段
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="update_user",
        resource="user",
        resource_id=str(user_id),
        details=update_data,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "用户信息更新成功"})


@router.post("/{user_id}/vip", response_model=Response[dict])
async def toggle_vip(
    user_id: int,
    request: Request,
    current_admin = Depends(require_permission("users.vip")),
    db: Session = Depends(get_main_db)
):
    """切换用户 VIP 状态"""
    user = db.query(UserBinding).filter(UserBinding.tg_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    user.is_vip = not user.is_vip

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="toggle_vip",
        resource="user",
        resource_id=str(user_id),
        details={"is_vip": user.is_vip},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    status_text = "开通" if user.is_vip else "取消"
    return Response(data={"message": f"VIP {status_text}成功", "is_vip": user.is_vip})


@router.get("/stats/overview", response_model=Response[UserStats])
async def get_user_stats(
    current_admin = Depends(require_permission("stats.view")),
    db: Session = Depends(get_main_db)
):
    """获取用户统计数据"""
    # 总用户数
    total_users = db.query(func.count(UserBinding.tg_id)).scalar()

    # VIP 用户数
    vip_users = db.query(func.count(UserBinding.tg_id)).filter(UserBinding.is_vip == True).scalar()

    # 今日新用户（使用首次签到作为注册日期近似值）
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    new_users_today = db.query(func.count(UserBinding.tg_id)).filter(
        UserBinding.last_checkin >= today_start,
        UserBinding.total_checkin_days <= 1
    ).scalar()

    # 周活跃用户（7天内有登录）
    week_ago = datetime.now() - timedelta(days=7)
    active_users_week = db.query(func.count(UserBinding.tg_id)).filter(
        UserBinding.last_active_time >= week_ago
    ).scalar()

    # 总观影分钟数
    total_watch_minutes = db.query(func.sum(UserBinding.total_watch_minutes)).scalar() or 0

    # 总签到天数
    total_checkin_days = db.query(func.sum(UserBinding.total_checkin_days)).scalar() or 0

    return Response(data=UserStats(
        total_users=total_users or 0,
        vip_users=vip_users or 0,
        new_users_today=new_users_today or 0,
        active_users_week=active_users_week or 0,
        total_watch_minutes=total_watch_minutes,
        total_checkin_days=total_checkin_days,
    ))


@router.delete("/{user_id}", response_model=Response[dict])
async def delete_user(
    user_id: int,
    request: Request,
    current_admin = Depends(require_permission("users.delete")),
    db: Session = Depends(get_main_db)
):
    """删除用户（谨慎操作）"""
    user = db.query(UserBinding).filter(UserBinding.tg_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 记录操作日志（删除前）
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="delete_user",
        resource="user",
        resource_id=str(user_id),
        details={
            "emby_account": user.emby_account,
            "is_vip": user.is_vip,
            "points": user.points,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)

    db.delete(user)
    db.commit()

    return Response(data={"message": "用户删除成功"})
