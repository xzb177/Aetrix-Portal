"""
订阅套餐管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
import json

from admin_database_user import (
    get_user_db, SubscriptionPlan, UserSubscription,
    SubscriptionOrder, WebUser, PlanServerRelation
)
from admin_utils.auth import get_current_admin

router = APIRouter()


@router.get("/subscriptions/plans")
async def get_plans(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取订阅套餐列表"""
    plans = db.query(SubscriptionPlan).order_by(
        SubscriptionPlan.sort_order
    ).all()

    result = []
    for plan in plans:
        features = []
        if plan.features:
            try:
                features = json.loads(plan.features)
            except:
                features = plan.features.split(',')

        # 获取关联的服务器数量
        server_count = db.query(PlanServerRelation).filter(
            PlanServerRelation.plan_id == plan.id
        ).count()

        result.append({
            "id": plan.id,
            "name": plan.name,
            "description": plan.description,
            "price": float(plan.price),
            "duration_days": plan.duration_days,
            "features": features if isinstance(features, list) else [features],
            "is_active": plan.is_active,
            "is_popular": plan.is_popular,
            "sort_order": plan.sort_order,
            "server_count": server_count,
            "created_at": plan.created_at
        })

    return result


@router.post("/subscriptions/plans")
async def create_plan(
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """创建订阅套餐"""
    features = data.get('features', [])
    if isinstance(features, list):
        features = json.dumps(features)
    else:
        features = str(features)

    plan = SubscriptionPlan(
        name=data.get('name'),
        description=data.get('description'),
        price=data.get('price'),
        duration_days=data.get('duration_days'),
        features=features,
        is_active=data.get('is_active', True),
        is_popular=data.get('is_popular', False),
        sort_order=data.get('sort_order', 0),
        created_at=datetime.now()
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    return {
        "id": plan.id,
        "message": "套餐创建成功"
    }


@router.put("/subscriptions/plans/{plan_id}")
async def update_plan(
    plan_id: int,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新订阅套餐"""
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == plan_id
    ).first()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="套餐不存在"
        )

    if 'name' in data:
        plan.name = data['name']
    if 'description' in data:
        plan.description = data['description']
    if 'price' in data:
        plan.price = data['price']
    if 'duration_days' in data:
        plan.duration_days = data['duration_days']
    if 'features' in data:
        features = data['features']
        if isinstance(features, list):
            plan.features = json.dumps(features)
        else:
            plan.features = str(features)
    if 'is_active' in data:
        plan.is_active = data['is_active']
    if 'is_popular' in data:
        plan.is_popular = data['is_popular']
    if 'sort_order' in data:
        plan.sort_order = data['sort_order']

    db.commit()

    return {"message": "套餐更新成功"}


@router.delete("/subscriptions/plans/{plan_id}")
async def delete_plan(
    plan_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """删除订阅套餐"""
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == plan_id
    ).first()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="套餐不存在"
        )

    # 检查是否有订阅
    sub_count = db.query(UserSubscription).filter(
        UserSubscription.plan_id == plan_id
    ).count()

    if sub_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"套餐还有 {sub_count} 个订阅，无法删除"
        )

    # 删除服务器关联
    db.query(PlanServerRelation).filter(
        PlanServerRelation.plan_id == plan_id
    ).delete()

    db.delete(plan)
    db.commit()

    return {"message": "套餐删除成功"}


@router.get("/subscriptions/orders")
async def get_orders(
    status_filter: str = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取订阅订单列表 - 使用 JOIN 优化查询"""
    query = db.query(
        SubscriptionOrder.id,
        SubscriptionOrder.order_id,
        SubscriptionOrder.user_id,
        SubscriptionOrder.amount,
        SubscriptionOrder.payment_method,
        SubscriptionOrder.status,
        SubscriptionOrder.paid_at,
        SubscriptionOrder.created_at,
        WebUser.username,
        SubscriptionPlan.name.label('plan_name')
    ).outerjoin(
        WebUser, SubscriptionOrder.user_id == WebUser.id
    ).outerjoin(
        SubscriptionPlan, SubscriptionOrder.plan_id == SubscriptionPlan.id
    )

    if status_filter:
        query = query.filter(SubscriptionOrder.status == status_filter)

    results = query.order_by(
        SubscriptionOrder.created_at.desc()
    ).offset(skip).limit(limit).all()

    result = [
        {
            "id": row.id,
            "order_id": row.order_id,
            "user_id": row.user_id,
            "username": row.username or "未知用户",
            "plan_name": row.plan_name or "未知套餐",
            "amount": float(row.amount),
            "payment_method": row.payment_method,
            "status": row.status,
            "paid_at": row.paid_at,
            "created_at": row.created_at
        }
        for row in results
    ]

    return result


@router.get("/subscriptions/list")
async def get_subscriptions(
    status_filter: str = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取用户订阅列表 - 使用 JOIN 优化查询"""
    query = db.query(
        UserSubscription.id,
        UserSubscription.user_id,
        UserSubscription.start_date,
        UserSubscription.end_date,
        UserSubscription.status,
        UserSubscription.auto_renew,
        UserSubscription.created_at,
        WebUser.username,
        SubscriptionPlan.name.label('plan_name')
    ).outerjoin(
        WebUser, UserSubscription.user_id == WebUser.id
    ).outerjoin(
        SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id
    )

    if status_filter:
        query = query.filter(UserSubscription.status == status_filter)

    results = query.order_by(
        UserSubscription.created_at.desc()
    ).offset(skip).limit(limit).all()

    result = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "username": row.username or "未知用户",
            "plan_name": row.plan_name or "未知套餐",
            "start_date": row.start_date,
            "end_date": row.end_date,
            "status": row.status,
            "auto_renew": row.auto_renew,
            "created_at": row.created_at
        }
        for row in results
    ]

    return result
