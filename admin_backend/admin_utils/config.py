"""
后台管理系统配置
"""
import os
import secrets
from typing import List
from pydantic_settings import BaseSettings


def generate_secret_key() -> str:
    """生成或获取密钥"""
    # 使用容器内路径，通过持久化卷保存
    key_file = "/app/data/.secret_key"
    if os.path.exists(key_file):
        with open(key_file, "r") as f:
            return f.read().strip()
    # 生成新密钥
    key = secrets.token_urlsafe(64)
    try:
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        with open(key_file, "w") as f:
            f.write(key)
        os.chmod(key_file, 0o600)
    except (OSError, PermissionError):
        # 如果无法写入文件，直接返回生成的密钥
        pass
    return key


class Settings(BaseSettings):
    """配置类"""

    # 服务配置
    HOST: str = os.getenv("ADMIN_HOST", "127.0.0.1")  # 默认只监听本地
    PORT: int = int(os.getenv("ADMIN_PORT", "8080"))
    DEBUG: bool = os.getenv("ADMIN_DEBUG", "false").lower() == "true"

    # 数据库配置（独立数据库）
    DATABASE_URL: str = os.getenv(
        "DB_URL",
        "sqlite:////app/data/admin.db"
    )
    DB_ECHO: bool = os.getenv("DB_ECHO", "false").lower() == "true"

    # Redis 配置
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_ENABLED: bool = os.getenv("REDIS_ENABLED", "true").lower() == "true"
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "300"))  # 默认缓存5分钟

    # JWT 配置 - 使用强密钥
    SECRET_KEY: str = os.getenv("ADMIN_SECRET_KEY", "") or generate_secret_key()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ADMIN_TOKEN_EXPIRE", "60"))  # 默认60分钟
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # 刷新令牌7天有效

    # 密码策略
    MIN_PASSWORD_LENGTH: int = 12
    REQUIRE_PASSWORD_COMPLEXITY: bool = True
    PASSWORD_HISTORY_COUNT: int = 5  # 记录最近5个密码

    # 前端 URL（CORS）
    FRONTEND_URLS: List[str] = os.getenv(
        "ADMIN_FRONTEND_URLS",
        "http://localhost:5173,http://localhost:3000,https://login.laodaemby.xyz"
    ).split(",")

    # 默认管理员密码（必须通过环境变量设置）
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "")

    # 强制首次登录修改密码
    FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN: bool = True

    # 会话安全
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30
    SESSION_TIMEOUT_MINUTES: int = 60

    # 路径配置（支持环境变量覆盖）
    USER_BACKEND_DIR: str = os.getenv("USER_BACKEND_DIR", "/opt/royalbot/user_backend")
    ROYALBOT_DB_PATH: str = os.getenv("ROYALBOT_DB_PATH", "/opt/royalbot/data/royalbot.db")
    PUSHED_ITEMS_DIR: str = os.getenv("PUSHED_ITEMS_DIR", "/opt/royalbot/data")
    # 主项目 SQLite 数据库路径（Telegram Bot 用户数据）
    MAIN_DB_PATH: str = os.getenv("MAIN_DB_PATH", "/app/data/royalbot.db")

    # 安全设置
    ENABLE_RATE_LIMIT: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    ENABLE_CSRF_PROTECTION: bool = True

    # Cookie 认证配置
    ENABLE_COOKIE_AUTH: bool = os.getenv("ENABLE_COOKIE_AUTH", "true").lower() == "true"
    COOKIE_DOMAIN: str | None = os.getenv("COOKIE_DOMAIN")  # 如: ".laodaemby.xyz"

    # Emby 配置
    EMBY_URL: str = os.getenv("EMBY_URL", "")
    EMBY_API_KEY: str = os.getenv("EMBY_API_KEY", "")

    # 线路管理功能开关（默认启用）
    FEATURE_ROUTE_ADMIN: bool = os.getenv("FEATURE_ROUTE_ADMIN", "true").lower() == "true"

    # 推送配置
    TELEGRAM_BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    NOTIFICATION_CHATS: List[str] = os.getenv("EMBY_NOTIFY_CHATS", "").split(",") if os.getenv("EMBY_NOTIFY_CHATS") else []

    # 分页配置
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # 允许的排序列白名单
    ALLOWED_SORT_COLUMNS: set = {
        "id", "username", "created_at", "updated_at",
        "tg_id", "email", "status", "role", "expiry_date"
    }

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # 忽略额外的环境变量


settings = Settings()
