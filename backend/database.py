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
        # WAL 下 synchronous=NORMAL 是安全的：事务提交不再等 fsync 落盘，
        # 只在 checkpoint 时同步。默认的 FULL 会让每次提交（播放进度上报、
        # token 更新这类高频写）都付一次 fsync。
        cursor.execute("PRAGMA synchronous=NORMAL")
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

    create_all 只建新表不改旧表，这里用 ALTER TABLE ADD COLUMN 补齐新增字段。
    幂等：列已存在时跳过。

    **必须用列表，不能用 {表名: 列} 的字典**：同一张表在不同版本各自加过列
    （``registration_codes`` 有 v2.5.6 与 v2.6.20 两批），字典字面量里后一个键会
    静默覆盖前一个，历史列就永远补不上——升级上来的库会在查询时报
    ``no such column``（全站 500）。列表则按出现顺序逐条追加，重复表名不会互相吞掉。
    """
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    migrations: list[tuple[str, list[tuple[str, str, str]]]] = [
        ("web_users", [
            ("points", "INTEGER", "0"),
            # v2.26.0 管理员角色（super / operator / viewer）：老库补列后为 NULL，
            # 按 super 处理 → 升级前后权限完全一致（见 backend/admin_roles.py）
            ("admin_role", "VARCHAR(20)", "NULL"),
        ]),
        # v2.6.15 通知历史记录真实投递结果：邮件/TG 发送失败必须留下原因，
        # 而不是像以前那样一律写成 status="sent"
        ("notification_history", [
            ("error_message", "TEXT", "NULL"),
        ]),
        # v2.5.6 卡码体系：注册码 → 注册/续期/白名单/诱饵/指名
        # v2.6.20 多服运营：卡码归属到某个服（见 backend/realms.py）
        ("registration_codes", [
            ("code_type", "INTEGER", "1"),
            ("days", "INTEGER", "30"),
            ("is_decoy", "BOOLEAN", "0"),
            ("target_username", "VARCHAR(50)", "NULL"),
            ("source", "VARCHAR(20)", "'admin'"),
            ("realm_id", "INTEGER", "NULL"),
        ]),
        # v2.6.4 媒体库刮削策略、虚拟媒体库与搜索增强；v2.6.5 增加 115 账号绑定
        # v2.6.6 增加存储挂载绑定（storage_mounts）：媒体库的内容来源
        # v2.6.20 多节点：node_id 指定由哪台 EA 负责这个库（NULL = 所有节点可见）
        ("emby_libraries", [
            ("scrape_policy", "VARCHAR(20)", "'missing_only'"),
            ("is_virtual", "BOOLEAN", "0"),
            ("platform", "VARCHAR(30)", "NULL"),
            ("account_115_id", "INTEGER", "NULL"),
            ("mount_ids", "TEXT", "''"),
            ("node_id", "INTEGER", "NULL"),
            ("realm_id", "INTEGER", "NULL"),
            # v2.22.0 最近一次扫描结果：老库补列后为 NULL，等价于「尚未扫描」，
            # 不改变原有「只看 is_scanning / last_scan_at」的行为。
            ("scan_status", "VARCHAR(20)", "NULL"),
            ("scan_stats", "TEXT", "NULL"),
            ("scan_error", "VARCHAR(500)", "NULL"),
        ]),
        # v2.6.20 多节点：EA 用 node_key 认领自己那条服务器记录；服务器归属到某个服
        ("remote_servers", [
            ("node_key", "VARCHAR(60)", "NULL"),
            ("realm_id", "INTEGER", "NULL"),
        ]),
        # v2.7.0 公益服：一个服可以免费开放（access_mode=free，不需要订阅就能看），
        # 并带上自己的规则文案与下载策略。老库补列时默认 paid/允许下载 → 行为不变。
        ("server_realms", [
            ("access_mode", "VARCHAR(10)", "'paid'"),
            ("access_note", "VARCHAR(500)", "''"),
            ("allow_download", "BOOLEAN", "NULL"),
        ]),
        # v2.6.20 多服运营：订阅、套餐、卡码、求片、挂载都归属到某个服
        ("subscription_plans", [
            ("realm_id", "INTEGER", "NULL"),
        ]),
        ("user_subscriptions", [
            ("realm_id", "INTEGER", "NULL"),
        ]),
        ("storage_mounts", [
            ("realm_id", "INTEGER", "NULL"),
        ]),
        # v2.6.19 求片可以转交外部服务（MoviePilot 订阅 / qBittorrent 加种）：
        # 把「交给谁、成没成、为什么没成」落库，否则面板只能显示一句模糊的失败
        # v2.6.20 多服运营：求片也归属到某个服
        ("movie_requests", [
            ("realm_id", "INTEGER", "NULL"),
            ("push_target", "VARCHAR(20)", "NULL"),
            ("push_status", "VARCHAR(20)", "NULL"),
            ("push_message", "VARCHAR(300)", "NULL"),
            ("pushed_at", "DATETIME", "NULL"),
        ]),
        # v2.10.0 优惠券：订单上快照「原价 / 优惠金额 / 核销记录」。
        # 退款与对账要能解释「当时到底按多少钱算的」——套餐改价之后不能按现价重算。
        # （新表 coupon_codes / coupon_usages 由 create_all 建，不在此列）
        ("recharge_orders", [
            ("list_price", "NUMERIC(10, 2)", "0"),
            ("discount_amount", "NUMERIC(10, 2)", "0"),
            ("coupon_usage_id", "INTEGER", "NULL"),
        ]),
        ("subscription_orders", [
            ("list_price", "NUMERIC(10, 2)", "0"),
            ("discount_amount", "NUMERIC(10, 2)", "0"),
            ("coupon_usage_id", "INTEGER", "NULL"),
        ]),
        ("emby_items", [
            ("imdb_id", "VARCHAR(20)", "NULL"),
            ("aliases", "TEXT", "''"),
            ("platforms", "TEXT", "''"),
            ("last_probed_at", "DATETIME", "NULL"),
            ("last_scraped_at", "DATETIME", "NULL"),
            ("repair_requested_at", "DATETIME", "NULL"),
        ]),
    ]

    for table, columns in migrations:
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
    _backfill_orm_columns(existing_tables)
    _ensure_default_realm()


def _backfill_orm_columns(existing_tables: set) -> None:
    """兜底：ORM 声明了、库里却没有的列，在这里补上（幂等）

    上面的清单靠人维护，漏一条就会让某个页面在**升级过的库**上莫名其妙 500
    （历史上真发生过：``movie_requests.realm_id`` 被同名键覆盖，管理后台首页直接 500）。
    这里以 ``Base.metadata`` 为准做一次对账，只补列、不删列、不改类型：
    新库不受影响，老库不会再出现「模型有这个字段、库里没有」的错位。
    """
    from sqlalchemy import text, inspect

    # 每次重新 inspect：上面的清单已经改过表结构，缓存的列信息会过时
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        missing = [c for c in table.columns if c.name not in existing_cols and not c.primary_key]
        if not missing:
            continue
        with engine.begin() as conn:
            for col in missing:
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {_column_ddl(col)}"))
                print(f"  🔧 已迁移: {table.name}.{col.name}（按模型补齐）")


def _column_ddl(col) -> str:
    """把 ORM 列编译成 ALTER TABLE 片段：类型 + 字面量默认值（没有就留空 = 可空）"""
    ddl = f"{col.name} {col.type.compile(engine.dialect)}"
    arg = getattr(getattr(col, "default", None), "arg", None)
    if arg is None or callable(arg):
        return ddl
    if isinstance(arg, bool):
        literal = "1" if arg else "0"
    elif isinstance(arg, (int, float)):
        literal = str(arg)
    elif isinstance(arg, str):
        literal = "'" + arg.replace("'", "''") + "'"
    else:
        return ddl
    return f"{ddl} DEFAULT {literal}"


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
