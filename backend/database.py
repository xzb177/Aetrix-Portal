"""
统一数据库配置
整合用户端、管理后台和主项目数据到单一数据库
支持 PostgreSQL/MySQL + Redis 缓存
"""
import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean, BigInteger, DateTime, Text, Numeric, ForeignKey, Index, JSON, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
import redis
from typing import Optional

# ==================== 数据库配置 ====================
# 支持环境变量切换数据库类型
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite")  # sqlite, postgresql, mysql

if DATABASE_TYPE == "postgresql":
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://royalbot:password@localhost:5432/royalbot"
    )
elif DATABASE_TYPE == "mysql":
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://royalbot:password@localhost:3306/royalbot"
    )
else:
    # SQLite 默认路径
    DATABASE_URL = "sqlite:////root/RoyalBot-Portal/backend/royalbot_unified.db"

# Redis 配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() == "true"

# ==================== 数据库引擎 ====================
engine_config = {
    "echo": os.getenv("DB_ECHO", "false").lower() == "true",
    "pool_pre_ping": True,
    "pool_recycle": 3600,
}

if DATABASE_TYPE == "sqlite":
    engine_config["connect_args"] = {"check_same_thread": False}
elif DATABASE_TYPE == "postgresql":
    engine_config["pool_size"] = 20
    engine_config["max_overflow"] = 40
elif DATABASE_TYPE == "mysql":
    engine_config["pool_size"] = 20
    engine_config["max_overflow"] = 40
    engine_config["pool_recycle"] = 7200

engine = create_engine(DATABASE_URL, **engine_config)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# ==================== Redis 连接 ====================
redis_client: Optional[redis.Redis] = None

if REDIS_ENABLED:
    try:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )
        # 测试连接
        redis_client.ping()
        print("✅ Redis 连接成功")
    except Exception as e:
        print(f"⚠️ Redis 连接失败: {e}，将使用内存缓存")
        redis_client = None


# ==================== 缓存管理 ====================
class CacheManager:
    """统一缓存管理器，支持 Redis 和内存缓存"""

    _memory_cache = {}

    @staticmethod
    def get(key: str) -> Optional[str]:
        """获取缓存"""
        if redis_client:
            try:
                value = redis_client.get(f"rb:{key}")
                return value
            except Exception:
                pass
        return CacheManager._memory_cache.get(key)

    @staticmethod
    def set(key: str, value: str, ttl: int = 300) -> bool:
        """设置缓存"""
        if redis_client:
            try:
                return redis_client.setex(f"rb:{key}", ttl, value)
            except Exception:
                pass
        CacheManager._memory_cache[key] = value
        return True

    @staticmethod
    def delete(key: str) -> bool:
        """删除缓存"""
        if redis_client:
            try:
                return redis_client.delete(f"rb:{key}") > 0
            except Exception:
                pass
        if key in CacheManager._memory_cache:
            del CacheManager._memory_cache[key]
        return True

    @staticmethod
    def delete_pattern(pattern: str) -> int:
        """批量删除缓存"""
        if redis_client:
            try:
                keys = redis_client.keys(f"rb:{pattern}")
                if keys:
                    return redis_client.delete(*keys)
            except Exception:
                pass
        # 内存缓存不支持模式匹配
        return 0

    @staticmethod
    def exists(key: str) -> bool:
        """检查缓存是否存在"""
        if redis_client:
            try:
                return redis_client.exists(f"rb:{key}") > 0
            except Exception:
                pass
        return key in CacheManager._memory_cache


cache = CacheManager()


# ==================== 导入所有模型 ====================
# 这里将导入所有统一的模型，稍后创建


# ==================== 数据库会话 ====================
def get_db() -> Session:
    """获取数据库会话（依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表"""
    from backend import models  # 导入所有模型
    Base.metadata.create_all(bind=engine)
    print(f"✅ 数据库初始化完成 ({DATABASE_TYPE})")


# ==================== 导出 ====================
__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "redis_client",
    "cache",
    "DATABASE_TYPE",
    "DATABASE_URL",
]
