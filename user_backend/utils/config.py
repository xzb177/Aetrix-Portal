"""
用户端后端配置
"""
import secrets
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # 应用信息
    APP_NAME: str = "RoyalBot User Portal"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # 数据库
    DATABASE_URL: str = "sqlite:///royalbot.db"

    # JWT 配置 - 必须从环境变量设置，否则使用随机密钥（每次重启失效）
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    # Access Token 有效期（4小时 - 安全性平衡）
    # 生产环境建议使用 15-30 分钟 + Refresh Token 机制
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 4  # 4 小时
    # Refresh Token 有效期（7天 - 用于长期保持登录）
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS - 从环境变量读取，避免硬编码
    FRONTEND_URLS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]
    # 额外的 CORS 源（从环境变量读取，逗号分隔）
    ADDITIONAL_CORS_ORIGINS: str = ""

    # Telegram 配置
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""
    # 管理员通知聊天 ID（逗号分隔）
    TELEGRAM_ADMIN_CHAT_IDS: str = ""

    # 易支付配置
    YIPAY_GATEWAY_URL: str = ""  # 易支付网关地址，如 https://pay.example.com/submit.php
    YIPAY_PARTNER_ID: str = ""  # 商户ID (pid)
    YIPAY_KEY: str = ""  # 商户密钥
    # 订阅支付回调地址 - 从环境变量读取
    YIPAY_NOTIFY_URL: str = ""  # 异步回调地址
    YIPAY_RETURN_URL: str = ""  # 同步跳转地址
    # 充值支付回调地址
    YIPAY_RECHARGE_NOTIFY_URL: str = ""  # 充值异步回调地址
    YIPAY_RECHARGE_RETURN_URL: str = ""  # 充值同步跳转地址

    # 外部 API 地址
    EXTERNAL_API_URL: str = ""  # 外部 API 地址，用于回调等

    # 安全配置（支持从数据库读取）
    CRON_SECRET: str = ""  # 定时任务 API 鉴权密钥
    CRYPTO_KEY: str = ""  # 加密密钥（Fernet 格式）

    # 彩蛋功能开关
    FEATURE_EASTER_EGG: bool = True  # 身份签名卡 + 徽章系统开关

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # 忽略额外的环境变量


def get_settings() -> Settings:
    """获取配置实例，确保 SECRET_KEY 已设置"""
    settings = Settings()

    # 如果没有设置 SECRET_KEY，生成一个随机密钥（仅在开发环境）
    # 生产环境必须通过环境变量设置
    if not settings.SECRET_KEY:
        if settings.DEBUG:
            # 开发环境：生成随机密钥
            settings.SECRET_KEY = secrets.token_urlsafe(32)
            print("⚠️  WARNING: Using auto-generated SECRET_KEY for development")
            print(f"   Generated key: {settings.SECRET_KEY[:16]}...")
        else:
            raise ValueError(
                "SECRET_KEY must be set in environment variables for production! "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

    # 处理额外的 CORS 源（过滤空字符串）
    if settings.ADDITIONAL_CORS_ORIGINS:
        additional_origins = [origin.strip() for origin in settings.ADDITIONAL_CORS_ORIGINS.split(",") if origin.strip()]
        settings.FRONTEND_URLS.extend(additional_origins)

    # 过滤空字符串
    settings.FRONTEND_URLS = [u for u in settings.FRONTEND_URLS if u.strip()]

    return settings


# 配置缓存（从数据库读取的配置）
_config_cache: dict = {}


def get_config_value(key: str, default: str = "") -> str:
    """
    获取配置值（支持从数据库读取）

    优先级：
    1. 环境变量
    2. 数据库配置（system_configs 表）
    3. 默认值

    Args:
        key: 配置键
        default: 默认值

    Returns:
        配置值
    """
    import os

    # 1. 先检查环境变量
    env_key = key.upper()
    env_value = os.getenv(env_key)
    if env_value is not None:
        return env_value

    # 2. 检查缓存
    if key in _config_cache:
        return _config_cache[key]

    # 3. 从数据库读取（延迟导入避免循环依赖）
    try:
        from database import SessionLocal
        from database.models import SystemConfig

        db = SessionLocal()
        try:
            config = db.query(SystemConfig).filter(
                SystemConfig.key == key
            ).first()
            if config and config.value:
                _config_cache[key] = config.value
                return config.value
        finally:
            db.close()
    except Exception:
        pass  # 数据库可能还未初始化

    # 4. 返回默认值
    return default


def reload_config_cache():
    """重新加载配置缓存（从数据库）"""
    global _config_cache
    _config_cache.clear()

    try:
        from database import SessionLocal
        from database.models import SystemConfig

        db = SessionLocal()
        try:
            configs = db.query(SystemConfig).all()
            for config in configs:
                _config_cache[config.key] = config.value
        finally:
            db.close()
    except Exception:
        pass


def get_cron_secret() -> str:
    """获取 CRON_SECRET"""
    return get_config_value("cron_secret", os.getenv("CRON_SECRET", "cron_default_secret_change_me"))


def get_crypto_key() -> str:
    """获取 CRYPTO_KEY"""
    key = get_config_value("crypto_key", os.getenv("CRYPTO_KEY", ""))
    return key


settings = get_settings()
