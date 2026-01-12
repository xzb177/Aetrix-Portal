"""
订阅 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import get_session
from database.models import (
    WebUser, SubscriptionPlan, UserSubscription, SubscriptionOrder,
    EmbyServer, PlanServerRelation, UserEmbyAccount
)
from schemas.subscription import (
    SubscriptionPlanResponse,
    UserSubscriptionResponse,
    CreateSubscriptionOrder,
    OrderResponse
)
from api.auth import get_current_user
from typing import List
import uuid
import json
import random

router = APIRouter()


def select_server_by_weight(db: Session, plan_id: int) -> EmbyServer:
    """
    按权重选择服务器（负载均衡）

    优先选择用户数未满的服务器，按权重随机分配
    """
    # 获取套餐关联的服务器
    relations = db.query(PlanServerRelation).filter(
        PlanServerRelation.plan_id == plan_id
    ).all()

    if not relations:
        return None

    # 构建服务器候选池（按权重）
    candidates = []
    for relation in relations:
        server = db.query(EmbyServer).filter(
            EmbyServer.id == relation.server_id,
            EmbyServer.is_active == True
        ).first()

        if not server:
            continue

        # 检查用户数是否已满
        if server.max_users > 0 and server.current_users >= server.max_users:
            continue

        # 按权重添加到候选池
        for _ in range(relation.weight):
            candidates.append(server)

    if not candidates:
        return None

    # 随机选择一个服务器
    return random.choice(candidates)


def create_emby_account(db: Session, user_id: int, server_id: int, subscription_id: int):
    """
    在 Emby 服务器上创建账号

    Args:
        db: 数据库会话
        user_id: 用户 ID
        server_id: 服务器 ID
        subscription_id: 订阅 ID
    """
    from utils.emby_client import load_emby_server

    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    subscription = db.query(UserSubscription).filter(
        UserSubscription.id == subscription_id
    ).first()
    user = db.query(WebUser).filter(WebUser.id == user_id).first()

    if not server or not subscription or not user:
        return None

    # 初始化 Emby 客户端
    client = load_emby_server(server.url, server.api_key)

    # 生成用户名和密码
    username = client.generate_username(user_id)
    password = client.generate_password(12)

    # 在 Emby 创建用户
    result = client.create_user(username, password)

    if result['success']:
        # 保存账号信息
        account = UserEmbyAccount(
            user_id=user_id,
            server_id=server_id,
            subscription_id=subscription_id,
            emby_user_id=result['user_id'],
            username=username,
            password=password,
            expires_at=subscription.end_date
        )
        db.add(account)

        # 更新服务器用户数
        server.current_users += 1

        db.commit()
        return account

    return None


@router.get("/plans", response_model=List[SubscriptionPlanResponse])
async def get_plans(db: Session = Depends(get_session)):
    """获取订阅套餐列表"""
    plans = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True
    ).order_by(SubscriptionPlan.sort_order).all()

    result = []
    for plan in plans:
        features = []
        if plan.features:
            try:
                features = json.loads(plan.features)
            except:
                features = plan.features.split(',')

        result.append(SubscriptionPlanResponse(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            price=float(plan.price),
            duration_days=plan.duration_days,
            features=features if isinstance(features, list) else [features],
            is_popular=plan.is_popular,
        ))

    return result


@router.get("/my")
async def get_my_subscription(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """获取当前用户的订阅"""
    subscription = db.query(UserSubscription).filter(
        UserSubscription.user_id == current_user.id,
        UserSubscription.status == 'active'
    ).order_by(UserSubscription.created_at.desc()).first()

    # 如果没有活跃订阅，返回空对象而不是 404
    if not subscription:
        return {
            "data": None,
            "has_subscription": False
        }

    # 计算剩余天数
    days_remaining = (subscription.end_date - datetime.now()).days

    features = []
    if subscription.plan.features:
        try:
            features = json.loads(subscription.plan.features)
        except:
            features = subscription.plan.features.split(',')

    return {
        "data": {
            "id": subscription.id,
            "plan": {
                "id": subscription.plan.id,
                "name": subscription.plan.name,
                "description": subscription.plan.description,
                "price": float(subscription.plan.price),
                "duration_days": subscription.plan.duration_days,
                "features": features if isinstance(features, list) else [features],
                "is_popular": subscription.plan.is_popular,
            },
            "start_date": subscription.start_date,
            "end_date": subscription.end_date,
            "status": subscription.status,
            "days_remaining": max(0, days_remaining),
        },
        "has_subscription": True
    }


@router.post("/order", response_model=OrderResponse)
async def create_subscription_order(
    data: CreateSubscriptionOrder,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """创建订阅订单"""
    # 获取套餐
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == data.plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    # 生成订单号
    order_id = f"SUB{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

    # 创建订单
    order = SubscriptionOrder(
        order_id=order_id,
        user_id=current_user.id,
        plan_id=plan.id,
        item_name=plan.name,
        amount=plan.price,
        payment_method=data.payment_method,
        status="pending",
        payment_url=f"https://pay.example.com/pay/{order_id}",  # 实际支付链接
    )
    db.add(order)
    db.commit()

    # TODO: 调用支付接口创建支付订单

    return OrderResponse(
        order_id=order_id,
        item_name=order.item_name,
        amount=float(order.amount),
        payment_method=order.payment_method,
        status=order.status,
        payment_url=order.payment_url,
        created_at=order.created_at,
    )


@router.get("/order/{order_id}", response_model=OrderResponse)
async def get_order_status(
    order_id: str,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """查询订单状态"""
    order = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.order_id == order_id,
        SubscriptionOrder.user_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    return OrderResponse(
        order_id=order.order_id,
        item_name=order.item_name,
        amount=float(order.amount),
        payment_method=order.payment_method,
        status=order.status,
        payment_url=order.payment_url,
        created_at=order.created_at,
        paid_at=order.paid_at,
    )


@router.post("/callback/{order_id}")
async def payment_callback(
    order_id: str,
    db: Session = Depends(get_session)
):
    """
    支付回调接口

    当支付成功后，支付平台会调用此接口
    """
    # 查找订单
    order = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.order_id == order_id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # 检查订单状态
    if order.status == "paid":
        return {"message": "Order already processed"}

    # 更新订单状态
    order.status = "paid"
    order.paid_at = datetime.now()

    # 获取套餐信息
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == order.plan_id
    ).first()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    # 计算订阅时间
    start_date = datetime.now()
    end_date = start_date + timedelta(days=plan.duration_days)

    # 创建订阅
    subscription = UserSubscription(
        user_id=order.user_id,
        plan_id=plan.id,
        start_date=start_date,
        end_date=end_date,
        status="active"
    )
    db.add(subscription)
    db.flush()

    # 选择服务器并创建 Emby 账号
    server = select_server_by_weight(db, plan.id)
    if server:
        create_emby_account(db, order.user_id, server.id, subscription.id)
    else:
        # 如果没有可用服务器，仍然创建订阅，但不创建 Emby 账号
        pass

    db.commit()

    return {"message": "Payment processed successfully"}
