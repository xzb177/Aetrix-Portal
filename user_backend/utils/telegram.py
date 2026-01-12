"""
Telegram 通知工具
"""
import os
import httpx
from typing import Optional
from utils.config import settings


async def send_telegram_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """发送 Telegram 消息"""
    if not settings.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN 未配置")
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": False,
                },
                timeout=10.0
            )
            if response.status_code != 200:
                print(f"Telegram 消息发送失败: {response.text}")
            return response.status_code == 200
    except Exception as e:
        print(f"发送 Telegram 消息异常: {e}")
        return False


async def notify_admins(
    title: str,
    message: str,
    parse_mode: str = "HTML"
) -> int:
    """发送通知给所有配置的管理员"""
    if not settings.TELEGRAM_ADMIN_CHAT_IDS:
        print("TELEGRAM_ADMIN_CHAT_IDS 未配置")
        return 0

    chat_ids = [cid.strip() for cid in settings.TELEGRAM_ADMIN_CHAT_IDS.split(",") if cid.strip()]

    full_text = f"{title}\n\n{message}"
    success_count = 0

    for chat_id in chat_ids:
        if await send_telegram_message(chat_id, full_text, parse_mode):
            success_count += 1

    return success_count


async def notify_new_media_request(
    movie_name: str,
    username: str,
    year: Optional[str] = None,
    media_type: str = "movie",
    note: Optional[str] = None,
    request_id: int = 0,
):
    """通知管理员有新的求片请求"""
    # 类型映射
    type_map = {
        "movie": "电影",
        "series": "剧集",
        "anime": "动漫",
        "documentary": "纪录片",
        "other": "其他",
    }
    type_text = type_map.get(media_type, media_type)

    # 构建消息
    message = f"🔔 <b>新的求片请求</b>\n\n"
    message += f"📹 <b>影片名称</b>: {movie_name}\n"

    if year:
        message += f"📅 <b>年份</b>: {year}\n"

    message += f"🎬 <b>类型</b>: {type_text}\n"
    message += f"👤 <b>申请用户</b>: {username}\n"

    if note:
        message += f"📝 <b>备注</b>: {note}\n"

    # 管理后台链接（需要根据实际部署调整）
    admin_url = os.getenv("ADMIN_URL", "https://login.laodaemby.xyz")
    message += f"\n👉 <a href=\"{admin_url}/admin/media-requests\">前往处理</a>"

    await notify_admins("🎬 求片通知", message)
