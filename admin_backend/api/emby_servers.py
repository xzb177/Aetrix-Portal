"""
Emby 服务器管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from admin_database_user import get_user_db, EmbyServer, PlanServerRelation, SubscriptionPlan, UserEmbyAccount, WebUser
from admin_utils.auth import get_current_admin

router = APIRouter()


@router.get("/servers")
async def get_servers(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取 Emby 服务器列表 - 使用子查询优化"""
    from sqlalchemy import func

    # 使用子查询一次性获取每个服务器的套餐数量
    plan_count_subquery = (
        db.query(
            PlanServerRelation.server_id,
            func.count(PlanServerRelation.id).label('plan_count')
        )
        .group_by(PlanServerRelation.server_id)
        .subquery()
    )

    servers = db.query(
        EmbyServer.id,
        EmbyServer.name,
        EmbyServer.url,
        EmbyServer.is_active,
        EmbyServer.max_users,
        EmbyServer.current_users,
        EmbyServer.created_at,
        EmbyServer.updated_at,
        plan_count_subquery.c.plan_count
    ).outerjoin(
        plan_count_subquery, EmbyServer.id == plan_count_subquery.c.server_id
    ).order_by(
        EmbyServer.created_at.desc()
    ).all()

    result = [
        {
            "id": server.id,
            "name": server.name,
            "url": server.url,
            "is_active": server.is_active,
            "max_users": server.max_users,
            "current_users": server.current_users,
            "plan_count": server.plan_count or 0,
            "created_at": server.created_at,
            "updated_at": server.updated_at
        }
        for server in servers
    ]

    return result


@router.post("/servers")
async def create_server(
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """添加 Emby 服务器"""
    server = EmbyServer(
        name=data.get('name'),
        url=data.get('url'),
        api_key=data.get('api_key'),
        max_users=data.get('max_users', 0),
        is_active=True,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    db.add(server)
    db.commit()
    db.refresh(server)

    return {
        "id": server.id,
        "name": server.name,
        "message": "服务器添加成功"
    }


@router.put("/servers/{server_id}")
async def update_server(
    server_id: int,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新 Emby 服务器"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    if 'name' in data:
        server.name = data['name']
    if 'url' in data:
        server.url = data['url']
    if 'api_key' in data:
        server.api_key = data['api_key']
    if 'is_active' in data:
        server.is_active = data['is_active']
    if 'max_users' in data:
        server.max_users = data['max_users']

    server.updated_at = datetime.now()
    db.commit()

    return {"message": "服务器更新成功"}


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """删除 Emby 服务器"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    # 检查是否有关联的账号
    account_count = db.query(UserEmbyAccount).filter(
        UserEmbyAccount.server_id == server_id
    ).count()

    if account_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"服务器还有 {account_count} 个关联账号，无法删除"
        )

    # 删除套餐关联
    db.query(PlanServerRelation).filter(
        PlanServerRelation.server_id == server_id
    ).delete()

    db.delete(server)
    db.commit()

    return {"message": "服务器删除成功"}


@router.post("/servers/{server_id}/sync")
async def sync_server_users(
    server_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """同步服务器用户数"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    # 使用 Emby 客户端获取实际用户数
    from admin_utils.utils.emby_client import load_emby_server

    client = load_emby_server(server.url, server.api_key)
    test_result = client.test_connection()

    if not test_result['success']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法连接到服务器: {test_result['message']}"
        )

    # 获取用户数
    user_count = client.get_users_count()
    server.current_users = user_count
    server.updated_at = datetime.now()
    db.commit()

    return {
        "message": "同步成功",
        "current_users": user_count
    }


@router.post("/servers/test")
async def test_server(
    data: dict,
    admin = Depends(get_current_admin)
):
    """测试服务器连接"""
    from admin_utils.utils.emby_client import load_emby_server

    client = load_emby_server(data.get('url'), data.get('api_key'))
    result = client.test_connection()

    return result


@router.get("/servers/{server_id}/users")
async def get_server_users(
    server_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取服务器用户列表 - 使用 JOIN 优化查询"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    # 从 Emby 获取用户
    from admin_utils.utils.emby_client import load_emby_server

    client = load_emby_server(server.url, server.api_key)
    users = client.get_users()

    # 使用 JOIN 一次性获取本地账号信息和用户名
    local_accounts = db.query(
        UserEmbyAccount.emby_user_id,
        UserEmbyAccount.user_id,
        WebUser.username.label('linked_username')
    ).outerjoin(
        WebUser, UserEmbyAccount.user_id == WebUser.id
    ).filter(
        UserEmbyAccount.server_id == server_id
    ).all()

    local_map = {acc.emby_user_id: acc for acc in local_accounts}

    result = []
    for user in users:
        local_acc = local_map.get(user['id'])
        result.append({
            "emby_user_id": user['id'],
            "username": user['name'],
            "has_password": user['has_password'],
            "last_login": user['last_login'],
            "linked_user_id": local_acc.user_id if local_acc else None,
            "linked_username": local_acc.linked_username if local_acc else None
        })

    return result


@router.get("/plans/{plan_id}/servers")
async def get_plan_servers(
    plan_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取套餐关联的服务器 - 使用 JOIN 优化查询"""
    results = db.query(
        PlanServerRelation.id,
        PlanServerRelation.server_id,
        PlanServerRelation.weight,
        EmbyServer.name.label('server_name'),
        EmbyServer.is_active
    ).outerjoin(
        EmbyServer, PlanServerRelation.server_id == EmbyServer.id
    ).filter(
        PlanServerRelation.plan_id == plan_id
    ).all()

    result = [
        {
            "id": row.id,
            "server_id": row.server_id,
            "server_name": row.server_name,
            "weight": row.weight,
            "is_active": row.is_active
        }
        for row in results
        if row.server_name  # 过滤掉没有服务器记录的关联
    ]

    return result


@router.post("/plans/{plan_id}/servers")
async def add_server_to_plan(
    plan_id: int,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """添加服务器到套餐"""
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="套餐不存在"
        )

    # 检查是否已关联
    existing = db.query(PlanServerRelation).filter(
        PlanServerRelation.plan_id == plan_id,
        PlanServerRelation.server_id == data.get('server_id')
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="服务器已关联到此套餐"
        )

    relation = PlanServerRelation(
        plan_id=plan_id,
        server_id=data.get('server_id'),
        weight=data.get('weight', 1),
        created_at=datetime.now()
    )
    db.add(relation)
    db.commit()

    return {"message": "服务器关联成功"}


@router.put("/plans/servers/{relation_id}")
async def update_plan_server(
    relation_id: int,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新服务器权重"""
    relation = db.query(PlanServerRelation).filter(
        PlanServerRelation.id == relation_id
    ).first()

    if not relation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="关联不存在"
        )

    if 'weight' in data:
        relation.weight = data['weight']

    db.commit()

    return {"message": "权重更新成功"}


@router.delete("/plans/servers/{relation_id}")
async def remove_server_from_plan(
    relation_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """移除套餐服务器关联"""
    relation = db.query(PlanServerRelation).filter(
        PlanServerRelation.id == relation_id
    ).first()

    if not relation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="关联不存在"
        )

    db.delete(relation)
    db.commit()

    return {"message": "关联移除成功"}


@router.get("/servers/{server_id}/users/{emby_user_id}/policy")
async def get_user_policy(
    server_id: int,
    emby_user_id: str,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取 Emby 用户策略"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    from admin_utils.utils.emby_client import load_emby_server
    client = load_emby_server(server.url, server.api_key)
    policy = client.get_user_policy(emby_user_id)

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在或获取策略失败"
        )

    return policy


@router.post("/servers/{server_id}/users/{emby_user_id}/policy")
async def update_user_policy(
    server_id: int,
    emby_user_id: str,
    data: dict,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """更新 Emby 用户策略"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    from admin_utils.utils.emby_client import load_emby_server
    client = load_emby_server(server.url, server.api_key)

    # 获取可选参数
    max_active_sessions = data.get('max_active_sessions', 3)
    enable_video_playback = data.get('enable_video_playback', True)
    enable_audio_playback = data.get('enable_audio_playback', True)
    enable_content_deletion = data.get('enable_content_deletion', False)
    enable_content_downloading = data.get('enable_content_downloading', False)
    enable_sync_transcoding = data.get('enable_sync_transcoding', True)
    enable_media_conversion = data.get('enable_media_conversion', True)
    max_streaming_bitrate = data.get('max_streaming_bitrate', 150000000)
    blocked_tags = data.get('blocked_tags')
    enabled_folders = data.get('enabled_folders')

    success = client.set_user_policy(
        user_id=emby_user_id,
        max_active_sessions=max_active_sessions,
        enable_video_playback=enable_video_playback,
        enable_audio_playback=enable_audio_playback,
        enable_content_deletion=enable_content_deletion,
        enable_content_downloading=enable_content_downloading,
        enable_sync_transcoding=enable_sync_transcoding,
        enable_media_conversion=enable_media_conversion,
        max_streaming_bitrate=max_streaming_bitrate,
        blocked_tags=blocked_tags,
        enabled_folders=enabled_folders
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="设置用户策略失败"
        )

    return {"message": "用户策略更新成功"}


@router.post("/servers/{server_id}/users/{emby_user_id}/policy/reset")
async def reset_user_policy(
    server_id: int,
    emby_user_id: str,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """重置用户策略为默认值"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )

    from admin_utils.utils.emby_client import load_emby_server
    client = load_emby_server(server.url, server.api_key)

    # 重置为默认值
    success = client.set_user_policy(
        user_id=emby_user_id,
        max_active_sessions=3,
        enable_video_playback=True,
        enable_audio_playback=True,
        enable_content_deletion=False,
        enable_content_downloading=False,
        enable_sync_transcoding=True,
        enable_media_conversion=True,
        max_streaming_bitrate=150000000,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="重置用户策略失败"
        )

    return {"message": "用户策略已重置为默认值"}

