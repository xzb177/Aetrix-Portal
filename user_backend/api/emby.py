"""
Emby 相关 API - 用户端
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import random
import string
import logging

from database import get_session
from database.models import EmbyServer, UserEmbyAccount, UserSubscription, PlanServerRelation, SubscriptionPlan
from schemas.emby import UserEmbyAccountResponse
from api.auth import get_current_user
from schemas.auth import UserResponse
from utils.emby_client import EmbyClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Emby"])


def create_emby_account(db: Session, user_id: int, subscription: UserSubscription):
    """
    为用户订阅创建 Emby 账号

    更新：现在会在 Emby 服务器上实际创建用户
    """
    # 获取订阅套餐关联的服务器
    relations = db.query(PlanServerRelation).filter(
        PlanServerRelation.plan_id == subscription.plan_id
    ).all()

    if not relations:
        logger.warning(f"套餐 {subscription.plan_id} 未关联服务器")
        return None

    # 构建权重列表
    servers = []
    for rel in relations:
        server = db.query(EmbyServer).filter(
            EmbyServer.id == rel.server_id,
            EmbyServer.is_active == True
        ).first()
        if server:
            # 检查是否超过最大用户数
            if server.max_users > 0 and server.current_users >= server.max_users:
                logger.warning(f"服务器 {server.name} 已达到最大用户数")
                continue
            for _ in range(rel.weight):
                servers.append(server)

    if not servers:
        logger.warning(f"套餐 {subscription.plan_id} 没有可用服务器")
        return None

    # 随机选择服务器
    selected_server = random.choice(servers)

    # 生成随机账号密码
    random_username = f"rb{user_id}{random.randint(1000, 9999)}"
    random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))

    # 计算过期时间（订阅到期后7天账号过期）
    from datetime import timedelta
    expires_at = subscription.end_date + timedelta(days=7)

    # ========== 关键修复：在 Emby 服务器上创建用户 ==========
    emby_client = EmbyClient(selected_server.url, selected_server.api_key)

    # 确保用户名唯一（优化版：一次性获取所有用户名，避免多次 API 调用）
    existing_usernames = emby_client.get_usernames_set(use_cache=True)
    counter = 0
    base_username = random_username
    while random_username in existing_usernames and counter < 10:
        counter += 1
        random_username = f"{base_username}_{counter}"

    # 在 Emby 服务器上创建用户
    create_result = emby_client.create_user(random_username, random_password)

    if not create_result['success']:
        logger.error(f"在 Emby 服务器 {selected_server.name} 上创建用户失败: {create_result['message']}")
        return None

    emby_user_id = create_result['user_id']
    logger.info(f"在 Emby 服务器 {selected_server.name} 上创建用户成功: {random_username} ({emby_user_id})")

    # 设置用户策略（权限）
    try:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == subscription.plan_id).first()
        if plan:
            import json
            features = json.loads(plan.features) if plan.features else {}
            max_sessions = features.get('max_sessions', 3)
            max_bitrate = features.get('max_bitrate', 150000000)
            enable_download = features.get('enable_download', False)

            emby_client.set_user_policy(
                user_id=emby_user_id,
                max_active_sessions=max_sessions,
                max_streaming_bitrate=max_bitrate,
                enable_content_downloading=enable_download
            )
            logger.info(f"已为用户 {random_username} 设置策略: max_sessions={max_sessions}, bitrate={max_bitrate}")
    except Exception as e:
        logger.warning(f"设置用户策略失败: {e}")
    # ========== 修复结束 ==========

    # 创建数据库记录
    emby_account = UserEmbyAccount(
        user_id=user_id,
        server_id=selected_server.id,
        subscription_id=subscription.id,
        emby_user_id=emby_user_id,  # 保存 Emby 服务器的用户 ID
        username=random_username,
        password=random_password,
        expires_at=expires_at
    )
    db.add(emby_account)

    # 更新服务器用户数
    selected_server.current_users += 1
    db.add(selected_server)

    db.commit()
    db.flush()

    logger.info(f"为用户 {user_id} 创建 Emby 账号: {selected_server.name} ({selected_server.url})")

    return {
        "id": emby_account.id,
        "server_id": selected_server.id,
        "server_name": selected_server.name,
        "server_url": selected_server.url,
        "username": random_username,
        "password": random_password,
        "expires_at": expires_at
    }


@router.get("/servers")
async def get_my_emby_accounts(
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取当前用户的 Emby 账号列表

    返回用户所有有效订阅对应的 Emby 服务器账号信息
    如果有订阅但没有账号，会自动创建
    """
    from datetime import datetime

    logger.info(f"[EMBY_DEBUG] 用户 {current_user.id} ({current_user.username}) 请求 Emby 账号")

    # 获取用户的有效订阅
    active_subscriptions = db.query(UserSubscription).filter(
        UserSubscription.user_id == current_user.id,
        UserSubscription.status == "active"
    ).all()

    logger.info(f"[EMBY_DEBUG] 用户 {current_user.id} 有 {len(active_subscriptions)} 个活跃订阅")

    if not active_subscriptions:
        return {
            "code": 200,
            "message": "获取成功",
            "data": []
        }

    # 获取这些订阅对应的 Emby 账号
    subscription_ids = [sub.id for sub in active_subscriptions]
    accounts = db.query(UserEmbyAccount).filter(
        UserEmbyAccount.subscription_id.in_(subscription_ids)
    ).all()

    logger.info(f"[EMBY_DEBUG] 用户 {current_user.id} 的订阅 {subscription_ids} 已有 {len(accounts)} 个账号")

    result = []

    # 检查每个订阅是否有对应的账号，没有则创建
    for subscription in active_subscriptions:
        # 查找该订阅的账号
        sub_accounts = [a for a in accounts if a.subscription_id == subscription.id]

        if not sub_accounts:
            # 没有账号，自动创建
            logger.info(f"[EMBY_DEBUG] 用户 {current_user.id} 的订阅 {subscription.id} (plan_id={subscription.plan_id}) 没有账号，开始创建")
            account_data = create_emby_account(db, current_user.id, subscription)
            if account_data:
                logger.info(f"[EMBY_DEBUG] 用户 {current_user.id} 账号创建成功: {account_data['username']}")
                is_expired = account_data["expires_at"] and account_data["expires_at"] < datetime.now()
                result.append(UserEmbyAccountResponse(
                    id=account_data["id"],
                    server_id=account_data["server_id"],
                    server_name=account_data["server_name"],
                    server_url=account_data["server_url"],
                    username=account_data["username"],
                    password=account_data["password"],
                    expires_at=account_data["expires_at"],
                    is_expired=is_expired
                ))
            else:
                logger.warning(f"[EMBY_DEBUG] 用户 {current_user.id} 账号创建失败")
        else:
            # 有账号，添加到结果
            for account in sub_accounts:
                server = db.query(EmbyServer).filter(EmbyServer.id == account.server_id).first()
                if server:
                    is_expired = account.expires_at and account.expires_at < datetime.now()
                    result.append(UserEmbyAccountResponse(
                        id=account.id,
                        server_id=server.id,
                        server_name=server.name,
                        server_url=server.url,
                        username=account.username,
                        password=account.password,
                        expires_at=account.expires_at,
                        is_expired=is_expired
                    ))

    logger.info(f"[EMBY_DEBUG] 用户 {current_user.id} 返回 {len(result)} 个账号")

    return {
        "code": 200,
        "message": "获取成功",
        "data": result
    }


@router.get("/account/{account_id}")
async def get_emby_account(
    account_id: int,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取指定 Emby 账号的详细信息
    """
    account = db.query(UserEmbyAccount).filter(
        UserEmbyAccount.id == account_id,
        UserEmbyAccount.user_id == current_user.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账号不存在"
        )

    server = db.query(EmbyServer).filter(EmbyServer.id == account.server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    from datetime import datetime
    is_expired = account.expires_at and account.expires_at < datetime.now()

    return {
        "code": 200,
        "message": "获取成功",
        "data": UserEmbyAccountResponse(
            id=account.id,
            server_id=server.id,
            server_name=server.name,
            server_url=server.url,
            username=account.username,
            password=account.password,
            expires_at=account.expires_at,
            is_expired=is_expired
        )
    }


@router.get("/available-servers")
async def get_available_servers(
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取当前用户可用的 Emby 服务器列表

    根据用户的订阅套餐，返回可用的服务器列表
    """
    # 获取用户的有效订阅
    active_subscriptions = db.query(UserSubscription).filter(
        UserSubscription.user_id == current_user.id,
        UserSubscription.status == "active"
    ).all()

    if not active_subscriptions:
        return {
            "code": 200,
            "message": "获取成功",
            "data": {"servers": []}
        }

    # 获取订阅套餐关联的服务器
    plan_ids = [sub.plan_id for sub in active_subscriptions]
    relations = db.query(PlanServerRelation).filter(
        PlanServerRelation.plan_id.in_(plan_ids)
    ).all()

    server_ids = list(set([r.server_id for r in relations]))
    servers = db.query(EmbyServer).filter(
        EmbyServer.id.in_(server_ids),
        EmbyServer.is_active == True
    ).all()

    return {
        "code": 200,
        "message": "获取成功",
        "data": {
            "servers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "url": s.url,
                    "current_users": s.current_users,
                    "max_users": s.max_users
                }
                for s in servers
            ]
        }
    }
