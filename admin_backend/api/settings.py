"""
系统配置管理 API
支持在后台可视化配置系统参数
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from admin_database_user import get_user_db, SystemConfig
from admin_utils.auth import get_current_admin


router = APIRouter(tags=["系统配置"])


# ==================== 请求/响应模型 ====================

class ConfigItem(BaseModel):
    """配置项"""
    key: str = Field(..., description="配置键")
    value: str = Field(..., description="配置值")
    description: Optional[str] = Field(None, description="描述")


class ConfigUpdate(BaseModel):
    """更新配置"""
    key: str
    value: str


class ConfigCategory(BaseModel):
    """配置分类"""
    name: str
    description: str
    items: List[Dict[str, Any]]


# ==================== 配置定义 ====================

# 配置项定义（包含默认值和描述）
CONFIG_DEFINITIONS = {
    # MoviePilot 配置
    "moviepilot_url": {
        "category": "MoviePilot",
        "description": "MoviePilot 服务地址",
        "default": "http://localhost:3000",
        "type": "url",
        "label": "服务地址"
    },
    "moviepilot_api_token": {
        "category": "MoviePilot",
        "description": "MoviePilot API Token",
        "default": "moviepilot",
        "type": "password",
        "label": "API Token"
    },
    "tmdb_api_key": {
        "category": "MoviePilot",
        "description": "TMDB API Key（用于搜索影视信息、获取海报等）。向 https://www.themoviedb.org/settings/api 申请",
        "default": "",
        "type": "password",
        "label": "TMDB API Key"
    },
    "tmdb_base_url": {
        "category": "MoviePilot",
        "description": "TMDB API 基础地址（留空使用默认值）",
        "default": "https://api.themoviedb.org/3",
        "type": "url",
        "label": "TMDB API 地址"
    },
    "tmdb_image_base_url": {
        "category": "MoviePilot",
        "description": "TMDB 图片服务地址（留空使用默认值）",
        "default": "https://image.tmdb.org/t/p",
        "type": "url",
        "label": "TMDB 图片地址"
    },
    "tmdb_language": {
        "category": "MoviePilot",
        "description": "TMDB 搜索语言（如：zh-CN, en-US, ja-JP）",
        "default": "zh-CN",
        "type": "text",
        "label": "TMDB 语言"
    },

    # Telegram 通知配置
    "telegram_bot_token": {
        "category": "Telegram通知",
        "description": "⚠️ 注意：此 Token 仅用于系统通知推送，不用于登录功能。向 @BotFather 发送 /newbot 创建机器人后获取",
        "default": "",
        "type": "password",
        "label": "通知 Bot Token"
    },
    "telegram_notify_chats": {
        "category": "Telegram通知",
        "description": "接收系统通知的 Chat ID，多个用逗号分隔。向 @userinfobot 发送消息可获取你的 Chat ID",
        "default": "",
        "type": "text",
        "label": "通知 Chat IDs"
    },

    # Telegram 登录配置
    "telegram_login_bot_token": {
        "category": "Telegram登录",
        "description": "✅ 必填。向 @BotFather 发送 /newbot 获取 Token（格式：123456:ABC-DEF...）。此 Token 用于验证用户登录数据的真实性",
        "default": "",
        "type": "password",
        "label": "登录 Bot Token"
    },
    "telegram_login_bot_username": {
        "category": "Telegram登录",
        "description": "✅ 必填。Bot 用户名（不含 @ 符号），如：my_service_bot。创建 Bot 时由 @BotFather 指定，或调用 https://api.telegram.org/bot<TOKEN>/getMe 获取",
        "default": "",
        "type": "text",
        "label": "Bot 用户名"
    },
    "telegram_login_enabled": {
        "category": "Telegram登录",
        "description": "开启后用户可使用 Telegram 一键登录。需先填写 Bot Token 和用户名才可开启",
        "default": "true",
        "type": "boolean",
        "label": "启用 Telegram 登录"
    },
    "telegram_login_callback_url": {
        "category": "Telegram登录",
        "description": "登录成功后的回调地址。留空则自动使用当前域名（推荐）",
        "default": "",
        "type": "url",
        "label": "回调地址（可选）"
    },
    "telegram_login_welcome_message": {
        "category": "Telegram登录",
        "description": "用户首次通过 Telegram 登录后显示的欢迎消息",
        "default": "欢迎登录！",
        "type": "text",
        "label": "欢迎消息"
    },

    # 求片配置
    "request_limit_per_user": {
        "category": "求片配置",
        "description": "每个用户可提交的求片数量限制（0表示不限制）",
        "default": "5",
        "type": "number",
        "label": "求片数量限制"
    },
    "request_limit_vip_bonus": {
        "category": "求片配置",
        "description": "VIP 用户额外获得的求片次数",
        "default": "5",
        "type": "number",
        "label": "VIP 额外次数"
    },
    "request_limit_period": {
        "category": "求片配置",
        "description": "求片限制周期：total=总计有效求片，monthly=当月求片，weekly=当周求片",
        "default": "total",
        "type": "text",
        "label": "限制周期"
    },

    # 推送策略配置
    "high_quality_push_hour": {
        "category": "推送策略",
        "description": "高质量推送时间（小时，0-23）",
        "default": "20",
        "type": "number",
        "label": "推送时间"
    },
    "high_quality_rating_threshold": {
        "category": "推送策略",
        "description": "最低评分阈值",
        "default": "6.0",
        "type": "number",
        "label": "评分阈值"
    },
    "high_quality_bitrate_threshold": {
        "category": "推送策略",
        "description": "最低码率阈值（bps）",
        "default": "20000000",
        "type": "number",
        "label": "码率阈值"
    },
    "high_quality_min_width": {
        "category": "推送策略",
        "description": "最小视频宽度",
        "default": "1920",
        "type": "number",
        "label": "最小宽度"
    },
    "check_interval_minutes": {
        "category": "推送策略",
        "description": "检查新内容间隔（分钟）",
        "default": "30",
        "type": "number",
        "label": "检查间隔"
    },

    # 安全配置
    "cron_secret": {
        "category": "安全配置",
        "description": "定时任务 API 鉴权密钥（用于手动触发定时任务）",
        "default": "",
        "type": "password",
        "label": "定时任务密钥"
    },
    "crypto_key": {
        "category": "安全配置",
        "description": "加密密钥（用于加密 Emby API Key 等敏感数据，Fernet 格式）",
        "default": "",
        "type": "password",
        "label": "加密密钥"
    },
    "max_concurrent_sessions": {
        "category": "安全配置",
        "description": "Emby 用户最大同时活跃会话数（防账号共享）",
        "default": "3",
        "type": "number",
        "label": "最大并发会话"
    },
    "max_streaming_bitrate": {
        "category": "安全配置",
        "description": "Emby 最大流媒体码率（bps，默认 150Mbps）",
        "default": "150000000",
        "type": "number",
        "label": "最大码率"
    },
    "enable_content_downloading": {
        "category": "安全配置",
        "description": "是否允许用户下载 Emby 内容",
        "default": "false",
        "type": "boolean",
        "label": "允许下载"
    },
    "subscription_expire_warning_days": {
        "category": "安全配置",
        "description": "订阅过期前提醒天数（逗号分隔，如：3,1）",
        "default": "3,1",
        "type": "text",
        "label": "过期提醒天数"
    },
    "order_timeout_minutes": {
        "category": "安全配置",
        "description": "未支付订单超时时间（分钟）",
        "default": "30",
        "type": "number",
        "label": "订单超时时间"
    },
}


# ==================== 辅助函数 ====================

def get_config_value(db: Session, key: str, default: str = "") -> str:
    """获取配置值，优先从数据库读取"""
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if config:
        return config.value or default
    # 回退到环境变量
    import os
    env_key = key.upper()
    return os.getenv(env_key, CONFIG_DEFINITIONS.get(key, {}).get("default", default))


def set_config_value(db: Session, key: str, value: str, description: str = None) -> SystemConfig:
    """设置配置值"""
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    from datetime import datetime
    if config:
        config.value = value
        config.updated_at = datetime.now()
        if description:
            config.description = description
    else:
        config = SystemConfig(
            key=key,
            value=value,
            description=description or CONFIG_DEFINITIONS.get(key, {}).get("description", ""),
            updated_at=datetime.now()
        )
        db.add(config)
    db.commit()
    db.refresh(config)
    return config


def get_all_configs(db: Session) -> Dict[str, str]:
    """获取所有配置（字典形式）"""
    configs = {}
    for config in db.query(SystemConfig).all():
        configs[config.key] = config.value
    return configs


# ==================== API 端点 ====================

@router.get("/")
async def get_settings(
    category: Optional[str] = None,
    admin = Depends(get_current_admin)
):
    """获取配置列表"""
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        result = []

        if category:
            # 获取指定分类的配置
            for key, defn in CONFIG_DEFINITIONS.items():
                if defn["category"] == category:
                    value = get_config_value(db, key, defn["default"])
                    result.append({
                        "key": key,
                        "value": value,
                        "label": defn["label"],
                        "description": defn["description"],
                        "type": defn["type"],
                        "category": defn["category"]
                    })
        else:
            # 获取所有配置，按分类分组
            for key, defn in CONFIG_DEFINITIONS.items():
                value = get_config_value(db, key, defn["default"])
                result.append({
                    "key": key,
                    "value": value,
                    "label": defn["label"],
                    "description": defn["description"],
                    "type": defn["type"],
                    "category": defn["category"]
                })

        return {"items": result}
    finally:
        db.close()


@router.get("/categories")
async def get_categories(admin = Depends(get_current_admin)):
    """获取配置分类"""
    categories = {}
    for key, defn in CONFIG_DEFINITIONS.items():
        cat = defn["category"]
        if cat not in categories:
            categories[cat] = {
                "name": cat,
                "description": f"{cat} 相关配置",
                "count": 0
            }
        categories[cat]["count"] += 1

    return {"categories": list(categories.values())}


@router.post("/update")
async def update_setting(
    data: ConfigUpdate,
    admin = Depends(get_current_admin)
):
    """更新单个配置项"""
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        defn = CONFIG_DEFINITIONS.get(data.key)
        if not defn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"配置项 {data.key} 不存在"
            )

        config = set_config_value(db, data.key, data.value, defn.get("description"))

        return {
            "message": "配置已更新",
            "config": {
                "key": config.key,
                "value": config.value,
                "description": config.description
            }
        }
    finally:
        db.close()


@router.post("/batch-update")
async def batch_update_settings(
    items: List[ConfigUpdate],
    admin = Depends(get_current_admin)
):
    """批量更新配置"""
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        updated = []
        for item in items:
            defn = CONFIG_DEFINITIONS.get(item.key)
            if defn:
                config = set_config_value(db, item.key, item.value, defn.get("description"))
                updated.append({
                    "key": config.key,
                    "value": config.value
                })

        return {
            "message": f"已更新 {len(updated)} 项配置",
            "updated": updated
        }
    finally:
        db.close()


@router.post("/reset")
async def reset_setting(
    key: str,
    admin = Depends(get_current_admin)
):
    """重置配置为默认值"""
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        defn = CONFIG_DEFINITIONS.get(key)
        if not defn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"配置项 {key} 不存在"
            )

        # 删除数据库中的配置，将回退到默认值
        db.query(SystemConfig).filter(SystemConfig.key == key).delete()
        db.commit()

        return {
            "message": "配置已重置",
            "key": key,
            "default_value": defn["default"]
        }
    finally:
        db.close()


@router.get("/export")
async def export_settings(admin = Depends(get_current_admin)):
    """导出配置（用于备份）"""
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        configs = db.query(SystemConfig).all()
        return {
            "settings": [
                {
                    "key": c.key,
                    "value": c.value,
                    "description": c.description
                }
                for c in configs
            ]
        }
    finally:
        db.close()


@router.post("/import")
async def import_settings(
    items: List[Dict[str, str]],
    admin = Depends(get_current_admin)
):
    """导入配置"""
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        imported = []
        for item in items:
            key = item.get("key")
            value = item.get("value", "")
            description = item.get("description")

            defn = CONFIG_DEFINITIONS.get(key)
            if defn:
                config = set_config_value(db, key, value, description)
                imported.append(key)

        return {
            "message": f"已导入 {len(imported)} 项配置",
            "imported": imported
        }
    finally:
        db.close()


@router.post("/generate-secret")
async def generate_secret_key(
    key_type: str = "cron",  # cron 或 crypto
    admin = Depends(get_current_admin)
):
    """
    生成密钥

    Args:
        key_type: 密钥类型（cron=定时任务密钥, crypto=加密密钥）
    """
    import secrets
    from datetime import datetime

    if key_type == "crypto":
        # 生成 Fernet 加密密钥
        from cryptography.fernet import Fernet
        generated_key = Fernet.generate_key().decode()
        config_key = "crypto_key"
        description = "加密密钥（Fernet 格式）"
    else:
        # 生成随机密钥
        generated_key = secrets.token_urlsafe(32)
        config_key = "cron_secret"
        description = "定时任务 API 鉴权密钥"

    # 保存到数据库
    from admin_database_user import get_user_db as get_db
    db = next(get_db())
    try:
        config = set_config_value(db, config_key, generated_key, description)

        return {
            "message": f"已生成 {key_type} 密钥",
            "key": config_key,
            "value": generated_key,
            "description": description,
            "created_at": config.updated_at.isoformat() if config.updated_at else datetime.now().isoformat()
        }
    finally:
        db.close()


@router.post("/reload-cache")
async def reload_config_cache(
    admin = Depends(get_current_admin)
):
    """
    重新加载配置缓存

    使管理后台修改的配置立即生效，无需重启服务
    """
    try:
        # 这里需要通知 user_backend 重新加载配置
        # 可以通过 Redis 发布订阅，或者重启服务
        # 简单起见，返回提示需要重启

        return {
            "message": "配置缓存重载提示",
            "note": "配置已保存到数据库，需要重启 user_backend 服务才能生效",
            "restart_command": "docker compose restart user_backend"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"重载配置失败: {str(e)}"
        )


@router.get("/public/telegram-login")
async def get_public_telegram_login_config():
    """
    获取公开的 Telegram 登录配置（无需鉴权）
    用于前端获取登录相关配置
    """
    from admin_database_user import get_user_db as get_db
    import os

    db = next(get_db())
    try:
        # 获取 Telegram 登录相关配置
        bot_username = get_config_value(db, "telegram_login_bot_username", "")
        bot_token = get_config_value(db, "telegram_login_bot_token", "")

        # 如果数据库中没有，尝试从环境变量获取
        if not bot_username:
            bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "")
        if not bot_token:
            bot_token = os.getenv("TELEGRAM_LOGIN_BOT_TOKEN", "")

        # 从 Bot Token 中提取 Bot ID（格式：123456:ABC-DEF...）
        bot_id = ""
        if bot_token and ":" in bot_token:
            bot_id = bot_token.split(":", 1)[0]

        # 获取启用状态
        enabled_str = get_config_value(db, "telegram_login_enabled", "true")
        enabled = enabled_str.lower() in ("true", "1", "yes")

        return {
            "telegram_login_enabled": enabled,
            "telegram_login_bot_username": bot_username,
            "telegram_login_bot_id": bot_id
        }
    finally:
        db.close()


@router.get("/public/tmdb")
async def get_public_tmdb_config():
    """
    获取公开的 TMDB 配置（无需鉴权）
    用于 user_backend 获取 TMDB API 配置
    """
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        # 获取 TMDB 相关配置
        api_key = get_config_value(db, "tmdb_api_key", "")
        base_url = get_config_value(db, "tmdb_base_url", "https://api.themoviedb.org/3")
        image_base_url = get_config_value(db, "tmdb_image_base_url", "https://image.tmdb.org/t/p")
        language = get_config_value(db, "tmdb_language", "zh-CN")

        return {
            "tmdb_api_key": api_key,
            "tmdb_base_url": base_url,
            "tmdb_image_base_url": image_base_url,
            "tmdb_language": language
        }
    finally:
        db.close()


@router.get("/public/request-limit")
async def get_public_request_limit_config():
    """
    获取公开的求片限制配置（无需鉴权）
    用于 user_backend 获取求片限制配置
    """
    from admin_database_user import get_user_db as get_db

    db = next(get_db())
    try:
        # 获取求片限制相关配置
        limit_per_user = get_config_value(db, "request_limit_per_user", "5")
        vip_bonus = get_config_value(db, "request_limit_vip_bonus", "5")
        limit_period = get_config_value(db, "request_limit_period", "total")

        return {
            "request_limit_per_user": int(limit_per_user),
            "request_limit_vip_bonus": int(vip_bonus),
            "request_limit_period": limit_period
        }
    finally:
        db.close()
