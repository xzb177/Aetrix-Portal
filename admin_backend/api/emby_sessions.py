"""
Emby 会话和转码管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from admin_database_user import get_user_db, EmbyServer
from admin_utils.auth import get_current_admin

router = APIRouter()


def get_emby_client(server_id: int, db: Session):
    """获取 Emby 客户端"""
    server = db.query(EmbyServer).filter(EmbyServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="服务器不存在"
        )
    if not server.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="服务器未激活"
        )
    from admin_utils.utils.emby_client import load_emby_server
    from admin_utils.utils.encryption import decrypt

    client = load_emby_server(server.url, decrypt(server.api_key))
    return client, server


@router.get("/sessions")
async def get_sessions(
    server_id: Optional[int] = None,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    获取在线用户会话列表
    如果指定 server_id，只返回该服务器的会话
    """
    if server_id:
        client, server = get_emby_client(server_id, db)
        sessions = client.get_sessions()
        return {
            "server_id": server_id,
            "server_name": server.name,
            "sessions": sessions
        }

    # 获取所有服务器的会话
    servers = db.query(EmbyServer).filter(EmbyServer.is_active == True).all()
    all_sessions = []
    for server in servers:
        try:
            from admin_utils.utils.emby_client import load_emby_server
            from admin_utils.utils.encryption import decrypt
            client = load_emby_server(server.url, decrypt(server.api_key))
            sessions = client.get_sessions()
            for session in sessions:
                session['server_id'] = server.id
                session['server_name'] = server.name
            all_sessions.extend(sessions)
        except Exception as e:
            # 跳过连接失败的服务器
            continue

    return {
        "total": len(all_sessions),
        "sessions": all_sessions
    }


@router.post("/sessions/{session_id}/kick")
async def delete_session(
    session_id: str,
    server_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    踢出用户（删除会话）
    """
    client, server = get_emby_client(server_id, db)

    success = client.delete_session(session_id)
    if success:
        return {"message": "用户已踢下线"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="操作失败"
        )


@router.get("/transcodings")
async def get_transcodings(
    server_id: Optional[int] = None,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    获取活跃的转码任务列表
    """
    if server_id:
        client, server = get_emby_client(server_id, db)
        transcodings = client.get_active_transcodings()
        return {
            "server_id": server_id,
            "server_name": server.name,
            "count": len(transcodings),
            "transcodings": transcodings
        }

    # 获取所有服务器的转码任务
    servers = db.query(EmbyServer).filter(EmbyServer.is_active == True).all()
    all_transcodings = []
    for server in servers:
        try:
            from admin_utils.utils.emby_client import load_emby_server
            from admin_utils.utils.encryption import decrypt
            client = load_emby_server(server.url, decrypt(server.api_key))
            transcodings = client.get_active_transcodings()
            for trans in transcodings:
                trans['server_id'] = server.id
                trans['server_name'] = server.name
            all_transcodings.extend(transcodings)
        except Exception:
            continue

    return {
        "total": len(all_transcodings),
        "transcodings": all_transcodings
    }


@router.get("/servers/{server_id}/libraries")
async def get_libraries(
    server_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    获取媒体库列表
    """
    client, server = get_emby_client(server_id, db)
    libraries = client.get_libraries()
    return {
        "server_id": server_id,
        "server_name": server.name,
        "libraries": libraries
    }


@router.post("/servers/{server_id}/libraries/refresh")
async def refresh_library(
    server_id: int,
    library_id: Optional[str] = None,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    刷新媒体库
    如果指定 library_id，只刷新该库，否则刷新所有库
    """
    client, server = get_emby_client(server_id, db)

    success = client.refresh_library(library_id)
    if success:
        return {
            "message": f"{'指定媒体库' if library_id else '所有媒体库'}刷新任务已提交",
            "server_id": server_id
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="刷新失败"
        )


@router.post("/servers/{server_id}/libraries/scan")
async def scan_library(
    server_id: int,
    library_id: Optional[str] = None,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    扫描媒体库（只添加新内容，不刷新元数据）
    """
    client, server = get_emby_client(server_id, db)

    success = client.scan_library(library_id)
    if success:
        return {
            "message": f"{'指定媒体库' if library_id else '所有媒体库'}扫描任务已提交",
            "server_id": server_id
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="扫描失败"
        )


@router.get("/servers/{server_id}/info")
async def get_server_info(
    server_id: int,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    获取服务器详细信息
    """
    client, server = get_emby_client(server_id, db)

    # 获取系统信息
    system_info = client.get_system_info()

    # 获取会话数
    sessions = client.get_sessions()

    # 获取转码数
    transcodings = client.get_active_transcodings()

    return {
        "server_id": server_id,
        "server_name": server.name,
        "system_info": system_info,
        "active_sessions": len(sessions),
        "active_transcodings": len(transcodings),
    }


@router.get("/servers/{server_id}/activity-log")
async def get_activity_log(
    server_id: int,
    start_index: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """
    获取服务器活动日志
    """
    client, server = get_emby_client(server_id, db)

    logs = client.get_activity_log(start_index, limit)

    return {
        "server_id": server_id,
        "server_name": server.name,
        "logs": logs
    }
