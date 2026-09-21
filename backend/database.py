"""
统一数据库配置
整合用户端、管理后台和主项目数据到单一数据库
支持 PostgreSQL/MySQL + Redis 缓存
"""
import os
from sqlalchemy import create_engine, event, Column, Integer, String, Boolean, BigInteger, DateTime, Text, Numeric, ForeignKey, Index, JSON, Float
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
    # SQLite 默认路径（相对工作目录，可通过 DATABASE_URL 覆盖）
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./royalbot_unified.db")

# Redis 配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"

# ==================== 数据库引擎 ====================
engine_config = {
    "echo": os.getenv("DB_ECHO", "false").lower() == "true",
    "pool_pre_ping": True,
    "pool_recycle": 3600,
}

if DATABASE_TYPE == "sqlite":
    # busy timeout：等待写锁而不是立刻报 "database is locked"（媒体扫描/播放上报并发场景）
    engine_config["connect_args"] = {"check_same_thread": False, "timeout": 30}
elif DATABASE_TYPE == "postgresql":
    engine_config["pool_size"] = 20
    engine_config["max_overflow"] = 40
elif DATABASE_TYPE == "mysql":
    engine_config["pool_size"] = 20
    engine_config["max_overflow"] = 40
    engine_config["pool_recycle"] = 7200

engine = create_engine(DATABASE_URL, **engine_config)

if DATABASE_TYPE == "sqlite":
    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        # WAL 模式：读写不互斥，显著降低高并发下的写锁冲突；
        # busy_timeout：写锁被占时等待而不是立刻报 "database is locked"
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

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


def _auto_migrate():
    """轻量自动迁移：为已有表补充新增列（SQLite/MySQL/PG 通用）

    create_all 只建新表不改旧表，这里用 ALTER TABLE ADD COLUMN 补齐 v2.3.0 新增字段。
    幂等：列已存在时跳过。
    """
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    migrations = {
        "web_users": [
            ("points", "INTEGER", "0"),
        ],
        # v2.6.15 通知历史记录真实投递结果：邮件/TG 发送失败必须留下原因，
        # 而不是像以前那样一律写成 status="sent"
        "notification_history": [
            ("error_message", "TEXT", "NULL"),
        ],
        # v2.5.6 卡码体系：注册码 → 注册/续期/白名单/诱饵/指名
        "registration_codes": [
            ("code_type", "INTEGER", "1"),
            ("days", "INTEGER", "30"),
            ("is_decoy", "BOOLEAN", "0"),
            ("target_username", "VARCHAR(50)", "NULL"),
            ("source", "VARCHAR(20)", "'admin'"),
        ],
        # v2.6.4 媒体库刮削策略、虚拟媒体库与搜索增强；v2.6.5 增加 115 账号绑定
        # v2.6.6 增加存储挂载绑定（storage_mounts）：媒体库的内容来源
        "emby_libraries": [
            ("scrape_policy", "VARCHAR(20)", "'missing_only'"),
            ("is_virtual", "BOOLEAN", "0"),
            ("platform", "VARCHAR(30)", "NULL"),
            ("account_115_id", "INTEGER", "NULL"),
            ("mount_ids", "TEXT", "''"),
            # v2.6.20 多节点：指定由哪台 EA 负责这个库（NULL = 所有节点可见、由面板扫描）
            ("node_id", "INTEGER", "NULL"),
            # v2.6.20 多服运营：这个库属于哪个服（见 backend/realms.py）
            ("realm_id", "INTEGER", "NULL"),
        ],
        # v2.6.20 多节点：EA 用 node_key 认领自己那条服务器记录
        "remote_servers": [
            ("node_key", "VARCHAR(60)", "NULL"),
            ("realm_id", "INTEGER", "NULL"),
        ],
        # v2.6.20 多服运营：订阅、套餐、卡码、求片、挂载都归属到某个服
        "subscription_plans": [
            ("realm_id", "INTEGER", "NULL"),
        ],
        "user_subscriptions": [
            ("realm_id", "INTEGER", "NULL"),
        ],
        "registration_codes": [
            ("realm_id", "INTEGER", "NULL"),
        ],
        "movie_requests": [
            ("realm_id", "INTEGER", "NULL"),
        ],
        "storage_mounts": [
            ("realm_id", "INTEGER", "NULL"),
        ],
        # v2.6.19 求片可以转交外部服务（MoviePilot 订阅 / qBittorrent 加种）：
        # 把「交给谁、成没成、为什么没成」落库，否则面板只能显示一句模糊的失败
        "movie_requests": [
            ("push_target", "VARCHAR(20)", "NULL"),
            ("push_status", "VARCHAR(20)", "NULL"),
            ("push_message", "VARCHAR(300)", "NULL"),
            ("pushed_at", "DATETIME", "NULL"),
        ],
        "emby_items": [
            ("imdb_id", "VARCHAR(20)", "NULL"),
            ("aliases", "TEXT", "''"),
            ("platforms", "TEXT", "''"),
            ("last_probed_at", "DATETIME", "NULL"),
            ("last_scraped_at", "DATETIME", "NULL"),
            ("repair_requested_at", "DATETIME", "NULL"),
        ],
    }

    for table, columns in migrations.items():
        if table not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        with engine.begin() as conn:
            for col_name, col_type, default in columns:
                if col_name not in existing_cols:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type} DEFAULT {default}"
                    ))
                    print(f"  🔧 已迁移: {table}.{col_name} ({col_type})")

    _widen_code_column(existing_tables, inspector)
    _ensure_default_realm()


def _ensure_default_realm() -> None:
    """把「服」这套新结构补齐到可用状态（幂等，可反复执行）

    升级上来的单服部署不应该因为多了「多服运营」而行为变化，所以：

    1. 没有任何服时，建一个默认服（``slug='main'``）——它就是以前那套部署；
    2. 把所有 ``realm_id`` 为空的旧数据（套餐/订阅/卡码/求片/媒体库/挂载/服务器）
       回填到默认服；
    3. 默认服写进 ``SystemConfig['active_realm_id']``（面板顶部的「当前服」）。

    只在表已存在时执行；全新库由 create_all 建表，随后首次业务写入时自然落到默认服。
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "server_realms" not in tables:
        return

    realm_tables = {
        "subscription_plans": "realm_id",
        "user_subscriptions": "realm_id",
        "registration_codes": "realm_id",
        "movie_requests": "realm_id",
        "remote_servers": "realm_id",
        "emby_libraries": "realm_id",
        "storage_mounts": "realm_id",
    }
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, name FROM server_realms ORDER BY id LIMIT 1")).first()
        if row is None:
            conn.execute(text(
                "INSERT INTO server_realms (name, slug, url, description, is_active, sort_order, created_at) "
                "VALUES (:name, :slug, '', :desc, :active, 0, :now)"
            ), {
                "name": "默认服", "slug": "main",
                "desc": "升级自动创建：原有数据全部归到这个服，可改名或直接拆成多个服",
                "active": True, "now": datetime.now(),
            })
            row = conn.execute(text("SELECT id FROM server_realms ORDER BY id LIMIT 1")).first()
            print(f"  🏠 已创建默认服 server_realms.id={row[0]}（原有数据将归入该服）")
        default_id = row[0]
        for table, column in realm_tables.items():
            if table not in tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                continue
            result = conn.execute(text(
                f"UPDATE {table} SET {column} = :rid WHERE {column} IS NULL"
            ), {"rid": default_id})
            if result.rowcount:
                print(f"  🔧 已回填: {table}.{column} → 服 #{default_id}（{result.rowcount} 行）")
        active = conn.execute(text(
            "SELECT value FROM system_configs WHERE key = 'active_realm_id'"
        )).first()
        if active is None:
            conn.execute(text(
                "INSERT INTO system_configs (key, value, description, updated_at) "
                "VALUES ('active_realm_id', :value, :desc, :now)"
            ), {"value": str(default_id), "desc": "面板当前操作的服（多服运营）", "now": datetime.now()})
            print(f"  🔧 已设置当前服: active_realm_id={default_id}")


def _widen_code_column(existing_tables: set, inspector) -> None:
    """卡码格式支持占位符后可能超过 20 字符，PG/MySQL 需要显式扩宽列宽

    SQLite 不校验 VARCHAR 长度，无需处理。语句幂等，已扩宽时直接跳过。
    """
    from sqlalchemy import text

    if "registration_codes" not in existing_tables:
        return
    dialect = engine.dialect.name
    if dialect not in ("postgresql", "mysql"):
        return
    for col in inspector.get_columns("registration_codes"):
        if col["name"] == "code" and (col.get("type") is None or getattr(col["type"], "length", 64) < 64):
            with engine.begin() as conn:
                if dialect == "postgresql":
                    conn.execute(text("ALTER TABLE registration_codes ALTER COLUMN code TYPE VARCHAR(64)"))
                else:
                    conn.execute(text("ALTER TABLE registration_codes MODIFY COLUMN code VARCHAR(64) NOT NULL"))
            print("  🔧 已迁移: registration_codes.code 宽度 → 64")


def init_db():
    """初始化数据库，创建所有表并执行轻量自动迁移"""
    from backend import models  # 导入所有模型
    from backend.emby_server import models as emby_models  # 自建 Emby 服务器模型
    Base.metadata.create_all(bind=engine)
    try:
        _auto_migrate()
    except Exception as e:  # noqa: BLE001 — 迁移失败不阻塞启动，新库不受影响
        print(f"⚠️ 自动迁移失败（可忽略，若为全新数据库）: {e}")
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
