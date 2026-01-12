"""
WebSocket 实时通知服务
支持用户订阅不同频道的实时通知
"""
import json
import asyncio
from typing import Dict, Set, Optional, Any
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # 存储所有活跃连接 {user_id: {websocket}}
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # 存储用户订阅的频道 {user_id: set of channels}
        self.user_channels: Dict[int, Set[str]] = {}
        # 频道订阅者 {channel: set of user_ids}
        self.channel_subscribers: Dict[str, Set[int]] = {}
        # Redis 发布订阅
        self.redis_pubsub = None

    async def connect(self, websocket: WebSocket, user_id: int):
        """接受新连接"""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(f"用户 {user_id} WebSocket 连接成功")

    def disconnect(self, websocket: WebSocket, user_id: int):
        """断开连接"""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                # 清理用户频道订阅
                if user_id in self.user_channels:
                    for channel in self.user_channels[user_id]:
                        if channel in self.channel_subscribers:
                            self.channel_subscribers[channel].discard(user_id)
                    del self.user_channels[user_id]
        logger.info(f"用户 {user_id} WebSocket 断开连接")

    async def subscribe(self, user_id: int, channels: list):
        """订阅频道"""
        if user_id not in self.user_channels:
            self.user_channels[user_id] = set()
        for channel in channels:
            self.user_channels[user_id].add(channel)
            if channel not in self.channel_subscribers:
                self.channel_subscribers[channel] = set()
            self.channel_subscribers[channel].add(user_id)
        logger.info(f"用户 {user_id} 订阅频道: {channels}")

    async def unsubscribe(self, user_id: int, channels: list):
        """取消订阅频道"""
        if user_id in self.user_channels:
            for channel in channels:
                self.user_channels[user_id].discard(channel)
                if channel in self.channel_subscribers:
                    self.channel_subscribers[channel].discard(user_id)
        logger.info(f"用户 {user_id} 取消订阅频道: {channels}")

    async def send_personal(self, message: dict, user_id: int):
        """发送个人消息"""
        if user_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"发送消息给用户 {user_id} 失败: {e}")
                    disconnected.add(connection)
            # 清理断开的连接
            for conn in disconnected:
                self.active_connections[user_id].discard(conn)

    async def broadcast_to_channel(self, channel: str, message: dict):
        """向频道广播消息"""
        if channel in self.channel_subscribers:
            for user_id in self.channel_subscribers[channel]:
                await self.send_personal(message, user_id)

    async def broadcast_to_all(self, message: dict):
        """广播给所有连接"""
        for user_id in list(self.active_connections.keys()):
            await self.send_personal(message, user_id)

    def get_online_count(self) -> int:
        """获取在线用户数"""
        return len(self.active_connections)

    def get_online_users(self) -> list:
        """获取在线用户ID列表"""
        return list(self.active_connections.keys())


# 全局连接管理器实例
manager = ConnectionManager()


# ==================== 通知消息类型 ====================

class NotificationType:
    """通知类型常量"""
    # 系统通知
    SYSTEM_ANNOUNCEMENT = "system.announcement"
    SYSTEM_MAINTENANCE = "system.maintenance"

    # 订阅相关
    SUBSCRIPTION_PURCHASED = "subscription.purchased"
    SUBSCRIPTION_EXPIRED = "subscription.expired"
    SUBSCRIPTION_RENEWED = "subscription.renewed"

    # 工单相关
    TICKET_CREATED = "ticket.created"
    TICKET_REPLIED = "ticket.replied"
    TICKET_RESOLVED = "ticket.resolved"

    # Emby 相关
    EMBY_ACCOUNT_CREATED = "emby.account_created"
    EMBY_ACCOUNT_EXPIRED = "emby.account_expired"
    EMBY_SESSION_STARTED = "emby.session_started"

    # 支付相关
    PAYMENT_SUCCESS = "payment.success"
    PAYMENT_FAILED = "payment.failed"

    # 邀请相关
    INVITATION_NEW_USER = "invitation.new_user"
    INVITATION_REWARD = "invitation.reward"


async def send_notification(
    notification_type: str,
    user_id: int,
    title: str,
    message: str,
    data: Optional[dict] = None
):
    """发送通知给指定用户"""
    notification = {
        "type": notification_type,
        "title": title,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now().isoformat(),
    }
    await manager.send_personal(notification, user_id)


async def broadcast_notification(
    notification_type: str,
    channel: str,
    title: str,
    message: str,
    data: Optional[dict] = None
):
    """广播通知到频道"""
    notification = {
        "type": notification_type,
        "title": title,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now().isoformat(),
    }
    await manager.broadcast_to_channel(channel, notification)


# ==================== FastAPI WebSocket 路由 ====================

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

websocket_router = APIRouter(tags=["WebSocket"])


class SubscribeRequest(BaseModel):
    """订阅请求模型"""
    channels: list
    action: str = "subscribe"  # subscribe 或 unsubscribe


@websocket_router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket 连接端点"""
    await manager.connect(websocket, user_id)

    try:
        # 发送连接成功消息
        await websocket.send_json({
            "type": "connection.connected",
            "message": "WebSocket 连接成功",
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
        })

        while True:
            # 接收客户端消息
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "subscribe":
                # 订阅频道
                channels = data.get("channels", [])
                await manager.subscribe(user_id, channels)
                await websocket.send_json({
                    "type": "subscription.success",
                    "channels": channels,
                    "message": f"已订阅: {', '.join(channels)}",
                })

            elif action == "unsubscribe":
                # 取消订阅
                channels = data.get("channels", [])
                await manager.unsubscribe(user_id, channels)
                await websocket.send_json({
                    "type": "unsubscription.success",
                    "channels": channels,
                    "message": f"已取消订阅: {', '.join(channels)}",
                })

            elif action == "ping":
                # 心跳检测
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat(),
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        manager.disconnect(websocket, user_id)


# ==================== REST API 用于发送通知 ====================

notification_router = APIRouter(prefix="/api/notifications", tags=["通知"])


class SendNotificationRequest(BaseModel):
    """发送通知请求"""
    user_id: int
    title: str
    message: str
    notification_type: str
    data: Optional[dict] = None


class BroadcastRequest(BaseModel):
    """广播通知请求"""
    channel: str
    title: str
    message: str
    notification_type: str
    data: Optional[dict] = None


@notification_router.post("/send")
async def send_notification_endpoint(request: SendNotificationRequest):
    """发送通知给指定用户（API）"""
    await send_notification(
        notification_type=request.notification_type,
        user_id=request.user_id,
        title=request.title,
        message=request.message,
        data=request.data,
    )
    return {"success": True, "message": "通知已发送"}


@notification_router.post("/broadcast")
async def broadcast_notification_endpoint(request: BroadcastRequest):
    """广播通知到频道（API）"""
    await broadcast_notification(
        notification_type=request.notification_type,
        channel=request.channel,
        title=request.title,
        message=request.message,
        data=request.data,
    )
    return {"success": True, "message": "广播已发送"}


@notification_router.get("/online-users")
async def get_online_users():
    """获取在线用户列表（API）"""
    return {
        "count": manager.get_online_count(),
        "users": manager.get_online_users(),
    }


# 导出
__all__ = [
    "manager",
    "websocket_router",
    "notification_router",
    "send_notification",
    "broadcast_notification",
    "NotificationType",
]
