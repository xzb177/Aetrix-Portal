"""
推送管理 API
"""
import os
import httpx
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from admin_database import get_db, AdminUser
from admin_utils.models_loader import AdminLog
from schemas.push import PushHistoryItem, PushConfig, PushConfigUpdate, NewReleaseItem
from schemas.common import Response
from admin_utils.auth import require_permission
from admin_utils.config import settings

router = APIRouter()

# 推送记录文件路径（使用配置中的路径）
PUSHED_ITEMS_FILE = os.path.join(settings.PUSHED_ITEMS_DIR, "pushed_emby_items.txt")


async def send_telegram_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """发送 Telegram 消息"""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10.0
            )
            return response.status_code == 200
    except Exception as e:
        print(f"发送 Telegram 消息失败: {e}")
        return False


def get_pushed_items() -> set:
    """获取已推送的媒体 ID 集合"""
    if not os.path.exists(PUSHED_ITEMS_FILE):
        return set()
    with open(PUSHED_ITEMS_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())


def add_pushed_item(item_id: str):
    """添加已推送的媒体 ID"""
    os.makedirs(os.path.dirname(PUSHED_ITEMS_FILE), exist_ok=True)
    with open(PUSHED_ITEMS_FILE, "a") as f:
        f.write(f"{item_id}\n")


@router.get("/config", response_model=Response[PushConfig])
async def get_push_config(
    current_admin = Depends(require_permission("push.view"))
):
    """获取推送配置"""
    return Response(data=PushConfig(
        high_quality_push_hour=int(os.getenv("HIGH_QUALITY_PUSH_HOUR", "20")),
        high_quality_rating_threshold=float(os.getenv("HIGH_QUALITY_RATING_THRESHOLD", "6.0")),
        high_quality_bitrate_threshold=int(os.getenv("HIGH_QUALITY_BITRATE_THRESHOLD", "20000000")),
        high_quality_min_width=int(os.getenv("HIGH_QUALITY_MIN_WIDTH", "1920")),
        check_interval_minutes=int(os.getenv("CHECK_NEW_RELEASES_INTERVAL", "1800")) // 60,
        notification_chats=",".join(settings.NOTIFICATION_CHATS),
    ))


@router.post("/config", response_model=Response[dict])
async def update_push_config(
    data: PushConfigUpdate,
    request: Request,
    current_admin = Depends(require_permission("push.config")),
    db: Session = Depends(get_db)
):
    """更新推送配置"""
    update_data = data.model_dump(exclude_unset=True)

    # 更新环境变量（实际需要重启服务生效）
    for key, value in update_data.items():
        env_key = key.upper()
        os.environ[env_key] = str(value)

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="update_push_config",
        resource="config",
        details=update_data,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "推送配置已更新（部分配置需要重启服务生效）"})


@router.get("/history", response_model=Response[list])
async def get_push_history(
    limit: int = Query(20, ge=1, le=100),
    current_admin = Depends(require_permission("push.view"))
):
    """获取推送历史"""
    pushed_items = get_pushed_items()

    # 从 Emby 获取详细信息
    items_data = []
    if settings.EMBY_URL and settings.EMBY_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                for item_id in list(pushed_items)[-limit:]:
                    try:
                        response = await client.get(
                            f"{settings.EMBY_URL}/Users/{settings.EMBY_API_KEY}/Items/{item_id}",
                            headers={"X-Emby-Token": settings.EMBY_API_KEY},
                            timeout=5.0
                        )
                        if response.status_code == 200:
                            item = response.json()
                            poster_url = None
                            if item.get("ImageTags"):
                                poster_url = f"{settings.EMBY_URL}/Items/{item_id}/Images/Primary"

                            items_data.append({
                                "item_id": item_id,
                                "item_name": item.get("Name", ""),
                                "poster_url": poster_url,
                                "pushed_at": None,  # 推送时间未记录
                            })
                    except Exception:
                        continue
        except Exception:
            pass

    return Response(data=items_data)


@router.post("/send", response_model=Response[dict])
async def send_manual_push(
    item_id: str = Query(..., description="Emby 媒体 ID"),
    message: Optional[str] = Query(None, description="自定义消息"),
    current_admin = Depends(require_permission("push.send")),
    db: Session = Depends(get_db)
):
    """手动推送影片到群组"""
    if not settings.EMBY_URL or not settings.EMBY_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Emby 配置不完整",
        )

    # 获取媒体信息
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.EMBY_URL}/Users/{settings.EMBY_API_KEY}/Items/{item_id}",
                headers={"X-Emby-Token": settings.EMBY_API_KEY},
                timeout=10.0
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="媒体不存在",
                )
            item = response.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取媒体信息失败",
        )

    # 构建推送消息
    name = item.get("Name", "")
    year = item.get("ProductionYear", "")
    overview = item.get("Overview", "")[:200] if item.get("Overview") else ""
    rating = item.get("CommunityRating", 0)

    if message:
        text = message
    else:
        text = f"🎬 新片推荐\n\n<b>{name}</b> ({year})\n"
        if rating:
            text += f"⭐ 评分: {rating}\n"
        if overview:
            text += f"\n{overview}...\n"
        text += f"\n👉 /view_{item_id}"

    # 发送到所有配置的群组
    success_count = 0
    for chat_id in settings.NOTIFICATION_CHATS:
        if await send_telegram_message(chat_id.strip(), text):
            success_count += 1

    # 记录推送
    add_pushed_item(item_id)

    return Response(data={
        "message": f"推送完成，成功发送到 {success_count}/{len(settings.NOTIFICATION_CHATS)} 个群组",
        "item_name": name,
    })


@router.post("/test", response_model=Response[dict])
async def test_push(
    current_admin = Depends(require_permission("push.send"))
):
    """测试推送"""
    test_message = "🔔 后台管理系统测试推送\n\n这是一条来自 RoyalBot Emby 后台管理系统的测试消息。"

    success_count = 0
    for chat_id in settings.NOTIFICATION_CHATS:
        if await send_telegram_message(chat_id.strip(), test_message):
            success_count += 1

    return Response(data={
        "message": f"测试推送完成，成功发送到 {success_count}/{len(settings.NOTIFICATION_CHATS)} 个群组",
    })
