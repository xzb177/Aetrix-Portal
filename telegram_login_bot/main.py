"""
RoyalBot Portal - Telegram 登录 Bot
专门处理网页登录功能的轻量级 Bot 服务
"""
import logging
import os
import sys
import asyncio
import json
import urllib.parse
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ==================== 配置 ====================

class Config:
    """Bot 配置类 - 从环境变量读取"""
    BOT_TOKEN = os.getenv("TELEGRAM_LOGIN_BOT_TOKEN", "")
    WEB_URL = os.getenv("WEB_URL", "https://login.laodaemby.xyz")
    ADMIN_BACKEND_URL = os.getenv("ADMIN_BACKEND_URL", "http://admin_backend:8080")

    # 允许的 Telegram 用户 ID（管理员，用于接收错误通知）
    ADMIN_IDS = []
    if os.getenv("ADMIN_IDS"):
        try:
            ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS").split(",")]
        except ValueError:
            pass

    @classmethod
    def validate(cls):
        """验证必需的配置"""
        if not cls.BOT_TOKEN:
            raise ValueError("TELEGRAM_LOGIN_BOT_TOKEN 环境变量未设置")


# ==================== 数据库接口 ====================

async def fetch_bot_config() -> dict:
    """
    从管理后台获取 Bot 配置
    支持动态更新 Bot Token 和 Web URL
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{Config.ADMIN_BACKEND_URL}/api/settings/public/telegram-login")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"从后台获取配置: telegram_login_enabled={data.get('telegram_login_enabled')}")
                return data
    except Exception as e:
        logger.warning(f"从后台获取配置失败: {e}")

    return {
        "telegram_login_enabled": True,
        "telegram_login_bot_username": "",
        "WEB_URL": Config.WEB_URL
    }


# ==================== 处理函数 ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    user = update.effective_user

    # 检查参数
    if not context.args:
        await update.message.reply_text(
            "👋 欢迎使用 RoyalBot Portal 登录 Bot！\n\n"
            "请从网页点击「Telegram 一键登录」按钮访问此 Bot。",
            parse_mode="HTML"
        )
        return

    action = context.args[0]

    # 处理登录请求
    if action == "web_login":
        await handle_web_login(update, context)
    elif action == "ping":
        await update.message.reply_text("✅ Bot 运行正常")
    else:
        await update.message.reply_text(
            f"❌ 未知命令: {action}\n\n"
            "请从网页点击「Telegram 一键登录」按钮访问此 Bot。",
            parse_mode="HTML"
        )


async def handle_web_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理网页登录请求"""
    user = update.effective_user

    try:
        # 获取最新配置
        config = await fetch_bot_config()
        web_url = config.get("WEB_URL", Config.WEB_URL)

        # 使用当前时间戳
        import time
        auth_date = int(time.time())

        # 构建用户数据
        user_data = {
            "id": user.id,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "username": user.username or "",
            "language_code": user.language_code or "",
            "auth_date": auth_date
        }

        # 将用户数据编码为 JSON 字符串
        user_json = json.dumps(user_data, ensure_ascii=False)

        # 构建登录 URL
        login_url = f"{web_url}/api/user/auth/telegram-login?id={user.id}&first_name={urllib.parse.quote(user.first_name or '')}"
        if user.username:
            login_url += f"&username={user.username}"
        if user.last_name:
            login_url += f"&last_name={urllib.parse.quote(user.last_name or '')}"
        login_url += f"&auth_date={auth_date}"

        # 计算 hash (简化版，实际验证在后端)
        import hmac
        import hashlib
        bot_token = Config.BOT_TOKEN
        secret_key = hashlib.sha256(bot_token.encode()).digest()
        data_check_string = f"auth_date={auth_date}\nfirst_name={urllib.parse.quote(user.first_name or '')}\nid={user.id}"
        if user.username:
            data_check_string += f"\nusername={user.username}"
        if user.last_name:
            data_check_string += f"\nlast_name={urllib.parse.quote(user.last_name or '')}"
        hash_value = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        login_url += f"&hash={hash_value}"

        logger.info(f"Web login request from user {user.id} ({user.username})")

        # 发送登录按钮
        keyboard = [[InlineKeyboardButton("🔐 点击登录网站", url=login_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"👋 你好，{user.first_name}！\n\n"
            "点击下方按钮完成登录：",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"处理登录请求失败: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ 登录失败，请稍后重试。\n"
            "如问题持续，请联系管理员。",
            parse_mode="HTML"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    await update.message.reply_text(
        "🔐 <b>RoyalBot Portal 登录 Bot</b>\n\n"
        "此 Bot 专门用于处理网页登录功能。\n\n"
        "<b>使用方法：</b>\n"
        "1. 访问 RoyalBot Portal 网页\n"
        "2. 点击「Telegram 一键登录」按钮\n"
        "3. 在打开的对话中点击「开始」\n"
        "4. 点击 Bot 返回的登录按钮完成登录\n\n"
        "<i>Powered by RoyalBot Portal</i>",
        parse_mode="HTML"
    )


# ==================== 错误处理 ====================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """处理所有错误"""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

    # 通知管理员
    if Config.ADMIN_IDS and update and hasattr(update, "effective_message"):
        from telegram import Bot
        bot = Bot(token=Config.BOT_TOKEN)
        error_msg = f"⚠️ Bot 错误:\n\n{context.error}"
        for admin_id in Config.ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=error_msg)
            except Exception:
                pass


# ==================== 主程序 ====================

def main():
    """启动 Bot"""
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        sys.exit(1)

    logger.info("🚀 RoyalBot Portal 登录 Bot 正在启动...")

    # 创建 Application
    application = Application.builder().token(Config.BOT_TOKEN).build()

    # 注册处理器
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # 注册错误处理器
    application.add_error_handler(error_handler)

    logger.info("✅ Bot 启动完成，开始轮询...")

    # 启动轮询
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True  # 启动时忽略积压的消息
    )


if __name__ == "__main__":
    main()
