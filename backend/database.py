"""
统一数据库配置
整合用户端、管理后台和主项目数据到单一数据库
支持 PostgreSQL/MySQL + Redis 缓存
"""
import os
from sqlalchemy import create_engine, event, text, Column, Integer, String, Boolean, BigInteger, DateTime, Text, Numeric, ForeignKey, Index, JSON, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
import redis
from typing import Optional

def _env_int_or(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int((os.getenv(name) or "").strip() or default))
    except ValueError:
        return default


# ==================== 数据库配置 ====================
# 支持环境变量切换数据库类型
# v2.42.0 起**默认 PostgreSQL**：SQLite 只在单文件、写锁模型下工作，多进程
# 并发（扫描 / 播放上报 / 订单）容易撞 "database is locked"，且备份只能靠
# 文件级快照。老部署只要没设 DATABASE_TYPE，需要显式设 DATABASE_TYPE=sqlite
# 才能继续用 SQLite 路径（见下方 fallback 提示）。
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "postgresql")  # postgresql(默认), sqlite, mysql

# SQLite 默认库文件名（v2.30.0 品牌统一）。
SQLITE_DB_FILENAME = "aetrix_unified.db"
LEGACY_SQLITE_DB_FILENAME = "royalbot_unified.db"  # brand-scan: allow — 老部署的库文件名，只用于兼容


def default_sqlite_url(cwd: str = ".") -> str:
    """没有显式 ``DATABASE_URL`` 时的 SQLite 默认连接串

    改品牌**不该让任何人「换了个文件名就丢整站数据」**：只有新文件名不存在、
    老文件名还在时才继续沿用老文件名。两者都在（或都不在）时用新名——
    也就是说，一个正常升级上来的部署会一直用老库，直到有人真的把新名建出来。
    显式设了 ``DATABASE_URL`` 的部署完全不受这段逻辑影响。
    """
    base = os.path.abspath(cwd or ".")
    if not os.path.exists(os.path.join(base, SQLITE_DB_FILENAME)) and os.path.exists(
        os.path.join(base, LEGACY_SQLITE_DB_FILENAME)
    ):
        return f"sqlite:///./{LEGACY_SQLITE_DB_FILENAME}"
    return f"sqlite:///./{SQLITE_DB_FILENAME}"


if DATABASE_TYPE == "postgresql":
    DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://aetrix:password@localhost:5432/aetrix"
    # SQLAlchemy 2.x 的 postgresql:// 默认找 psycopg(v3) 驱动；仓库依赖是
    # psycopg2-binary，没装 psycopg 时显式指定 psycopg2，否则 import 期直接炸。
    # 装了 psycopg3 的环境不受影响（走更快的 v3）。
    if DATABASE_URL.startswith("postgresql://"):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql://"):]
    # 两个驱动都没装时**不能直接炸**：默认库是 PG，但本地开发 / 一次性脚本 /
    # 契约检查常常一个驱动都不装。降级到 SQLite 并明确告警——否则默认改 PG 之后，
    # 「不设环境变量直接跑个脚本」会从「能跑」变成「ModuleNotFoundError」。
    # 显式设了 DATABASE_TYPE=postgresql 的部署不会走到这里（那是有意的强制）。
    if os.getenv("DATABASE_TYPE", "").strip() == "":
        try:
            __import__("psycopg2")
        except ImportError:
            try:
                __import__("psycopg")
            except ImportError:
                import warnings as _warnings
                _warnings.warn(
                    "未安装 PostgreSQL 驱动（psycopg2-binary / psycopg[3]），"
                    "且未显式设置 DATABASE_TYPE，本次降级使用 SQLite。"
                    "生产部署请安装驱动或用 Docker Compose（镜像内已装）。",
                    RuntimeWarning, stacklevel=2,
                )
                DATABASE_TYPE = "sqlite"
                DATABASE_URL = os.getenv("DATABASE_URL") or default_sqlite_url()
elif DATABASE_TYPE == "mysql":
    DATABASE_URL = os.getenv("DATABASE_URL") or "mysql+pymysql://aetrix:password@localhost:3306/aetrix"
else:
    # SQLite 默认路径（相对工作目录，可通过 DATABASE_URL 覆盖）
    DATABASE_URL = os.getenv("DATABASE_URL") or default_sqlite_url()

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
# 原值 20+40=60 是**每进程**的上限；api / worker / EA 三个进程各自持有独立 engine，
# 峰值 180 > PG 默认 max_connections(100) → 高峰期随机 "too many clients already"。
# 改为可配 + 对多进程安全的默认值（3×(25+25)=150（需 PG max_connections≥200），留足运维连接余量）。
_POOL_SIZE = _env_int_or("DB_POOL_SIZE", 25, 1)
_MAX_OVERFLOW = _env_int_or("DB_MAX_OVERFLOW", 25, 0)
if DATABASE_TYPE == "postgresql":
    engine_config["pool_size"] = _POOL_SIZE
    engine_config["max_overflow"] = _MAX_OVERFLOW
elif DATABASE_TYPE == "mysql":
    engine_config["pool_size"] = _POOL_SIZE
    engine_config["max_overflow"] = _MAX_OVERFLOW
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

_real_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class _SessionLocalProxy:
    """``SessionLocal`` 本体：一个永远在**调用时刻**解析目标的转发器。

    ## 为什么需要它

    仓库里 20+ 个模块写的是 ``from backend.database import SessionLocal``，
    那是 **import 期就把引用复制一份**到本模块（等价于值传递）。此后
    ``database.SessionLocal`` 换掉，它们手里的旧引用**不会跟着变**。

    正常运行时 ``SessionLocal`` 只在 ``database.py`` 赋值一次、无人改它，所以
    无害。但测试为隔离库会重设它，于是踩坑::

        import backend.database as dbmod
        from backend.emby_server import enrich_worker   # 此刻绑定旧 SessionLocal
        dbmod.SessionLocal = sessionmaker(...)          # 重建后 enrich_worker 不跟着变
        # enrich_worker.get_progress() 于是查旧库 → 读到空表 → assert 0 == 2

    是否踩中取决于测试文件的字母序，失败时隐时现，极难定位。

    ## 设计要点

    这个代理**对象本身永不更换**——所有模块 import 到的都是同一个实例。
    切换只发生在它内部指向的目标上，所以无论 import 顺序如何、各模块何时
    import，调用时看到的都是当前生效的那个。

    全仓库 ``SessionLocal`` 只被调用（``SessionLocal()``），没有任何属性访问，
    因此把它做成可调用对象是安全的。
    """

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, *args, **kwargs):
        return self._factory(*args, **kwargs)

    def __repr__(self):
        return f"<SessionLocal -> {self._factory!r}>"


# 全局唯一的代理实例。configure_session_local 只改它的目标，不换它。
SessionLocal = _SessionLocalProxy(_real_session_local)


def configure_session_local(factory=None) -> None:
    """切换 SessionLocal 代理指向的目标（**测试专用**）。

    请务必用这个函数，不要写 ``database.SessionLocal = ...``：
    直接赋值会把代理换成一个被冻结的真 factory，此后各模块 import 到的就不再是
    代理，转发能力随之失效——正是本类要解决的陷阱换个形式复发。

    ``factory=None`` 表示恢复默认（数据库模块的 engine）。

    传入代理自身会被忽略并回退到默认：调用方若想"保存再还原"，很容易把
    ``dbmod.SessionLocal``（代理本身）存下来再传回来，那会让代理指向自己、
    每次调用无限递归。这里挡掉这种误用。
    """
    if factory is None or isinstance(factory, _SessionLocalProxy):
        factory = _real_session_local
    SessionLocal._factory = factory


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
    """统一缓存管理器，支持 Redis 和内存缓存

    内存回退是有界的（借鉴 go-emby 的有界缓存思路）：条目上限
    ``_MEMORY_CACHE_MAX``，存 (value, expire_at)，读时校验过期、
    写满时先清过期条目再按 FIFO 淘汰最老的。Redis 故障时也不会
    无限增长吃掉内存。
    """

    _memory_cache: dict = {}
    _memory_cache_order: list = []  # FIFO 顺序，配合淘汰
    _MEMORY_CACHE_MAX = 2000

    @staticmethod
    def _memory_get(key: str) -> Optional[str]:
        entry = CacheManager._memory_cache.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        import time as _time
        if expire_at is not None and _time.time() > expire_at:
            CacheManager._memory_cache.pop(key, None)
            try:
                CacheManager._memory_cache_order.remove(key)
            except ValueError:
                pass
            return None
        return value

    @staticmethod
    def _memory_set(key: str, value: str, ttl: int = 300) -> None:
        import time as _time
        cache = CacheManager._memory_cache
        expire_at = _time.time() + ttl if ttl and ttl > 0 else None
        if key not in cache:
            # 写满：先清过期条目，不够再按 FIFO 淘汰最老
            while len(cache) >= CacheManager._MEMORY_CACHE_MAX:
                evicted = False
                now = _time.time()
                for k in list(cache.keys()):
                    _, exp = cache[k]
                    if exp is not None and now > exp:
                        cache.pop(k, None)
                        evicted = True
                        break
                if not evicted:
                    oldest = CacheManager._memory_cache_order.pop(0) if CacheManager._memory_cache_order else None
                    if oldest is not None:
                        cache.pop(oldest, None)
                    else:
                        break
            CacheManager._memory_cache_order.append(key)
        cache[key] = (value, expire_at)

    @staticmethod
    def get(key: str) -> Optional[str]:
        """获取缓存"""
        if redis_client:
            try:
                value = redis_client.get(f"rb:{key}")
                return value
            except Exception:
                pass
        return CacheManager._memory_get(key)

    @staticmethod
    def set(key: str, value: str, ttl: int = 300) -> bool:
        """设置缓存"""
        if redis_client:
            try:
                return redis_client.setex(f"rb:{key}", ttl, value)
            except Exception:
                pass
        CacheManager._memory_set(key, value, ttl)
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
            try:
                CacheManager._memory_cache_order.remove(key)
            except ValueError:
                pass
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
        return CacheManager._memory_get(key) is not None


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


def _dialect_col_spec(col_type: str, default: str) -> tuple[str, str]:
    """把迁移清单里的列类型/默认值转成当前方言合法的写法。

    清单里的 ``DATETIME`` / ``BOOLEAN ... DEFAULT 0`` 是 SQLite 口径：
    - PostgreSQL 没有 ``DATETIME`` 类型（叫 ``TIMESTAMP``）；
    - PG 不接受整数做布尔列的默认值（``DEFAULT 0`` 直接报错），必须写 ``TRUE``/``FALSE``。
    MySQL 两者都认，不用转。SQLite 保持原样。
    """
    dialect = engine.dialect.name
    if dialect == "postgresql":
        if col_type == "DATETIME":
            col_type = "TIMESTAMP"
        if col_type == "BOOLEAN":
            if default == "0":
                default = "FALSE"
            elif default == "1":
                default = "TRUE"
    return col_type, default


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
            # v2.44.0 注册渠道归因（admin/code/invitation/open）：老用户补列后为 NULL，
            # 按「未记录」显示——不硬猜成 open（见 backend/register_channel.py）
            ("register_channel", "VARCHAR(20)", "NULL"),
        ]),
        # v2.44.0 邀请码白名单（内测码 / 渠道码）：NULL / 空串都按「不限」处理，
        # 所以存量邀请码行为升级前后完全一致（见 backend/api/invitation.py）
        ("invitation_codes", [
            ("whitelist", "TEXT", "''"),
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
            # 诱饵码不建列：靠 HONEY- 前缀识别（见 backend/codes.is_honeypot），零表结构改动
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
            # v2.43.0 路径与存储后端分离：与 paths 逐条对应的后端列（local/rclone/115）。
            # 老库补列后为 ''，界面按「挂载类型 + 路径前缀」现推，行为与升级前一致。
            ("storage_backends", "TEXT", "''"),
            ("node_id", "INTEGER", "NULL"),
            ("realm_id", "INTEGER", "NULL"),
            # 本轮扫描起始时刻：与 updated_at 分开，避免被进度刷盘顶掉
            # （见 models.Library.scan_started_at 的说明）
            ("scan_started_at", "DATETIME", "NULL"),
            # v2.22.0 最近一次扫描结果：老库补列后为 NULL，等价于「尚未扫描」，
            # 不改变原有「只看 is_scanning / last_scan_at」的行为。
            ("scan_status", "VARCHAR(20)", "NULL"),
            ("scan_stats", "TEXT", "NULL"),
            ("scan_error", "VARCHAR(500)", "NULL"),
            # v2.27.0 扫描进行中的进度快照：老库补列后为 NULL（= 当前没有进度可看），
            # 不改动任何既有行为；只有真正开始扫描时才会被写入，结束即清空。
            ("scan_progress", "TEXT", "NULL"),
            # 媒体库封面由管理员直传，扫描/刮削不得覆盖；只保存图片目录下的相对路径。
            ("cover_path", "VARCHAR(500)", "NULL"),
            # 封面自动生成样式与文字（老库补列后为 NULL = 未启用，仍用直传的 cover_path）。
            # template: poster（海报拼贴）/ visual（主视觉）/ filmstrip（胶片带）
            ("cover_template", "VARCHAR(20)", "NULL"),
            # 标题/副标题支持 {library} {type} {year} 三个变量，只渲染纯文本
            ("cover_title", "VARCHAR(100)", "NULL"),
            ("cover_subtitle", "VARCHAR(100)", "NULL"),
            # v2.43.1 新片入库后自动重生成封面；老库补列后为 0（关闭），行为与升级前一致
            ("cover_auto_regen", "BOOLEAN", "0"),
            # v2.44.0 每库扫描开关；老库补列后分别为 1（增量）与 1（实时监听），
            # 即与升级前行为一致：本来就是有增量、有追新的
            ("incremental_scan", "BOOLEAN", "1"),
            ("fs_watch", "BOOLEAN", "1"),
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
            # v2.39.0 两阶段扫描：老库补列后 probe_status='pending'，但已有探测数据的
            # 条目会被后台 worker 按 needs_probe() 语义直接标 done，不会重复探测。
            ("probe_status", "VARCHAR(20)", "'pending'"),
            ("probe_priority", "INTEGER", "0"),
            ("probe_attempts", "INTEGER", "0"),
            ("probe_next_retry_at", "DATETIME", "NULL"),
            # v2.40.0 补全 worker 重试：老库补列后 enrich_attempts=0，
            # enrich_next_retry_at=NULL（可立即重试，由 worker 按退避调度）。
            ("enrich_attempts", "INTEGER", "0"),
            ("enrich_next_retry_at", "DATETIME", "NULL"),
            # v2.42.9 claim 租约：老库补列后为 NULL（历史 enriching 行没有抢单时刻，
            # janitor 用 date_modified 近似判定超时，不会误杀正在处理的条目）。
            ("enrich_claimed_at", "DATETIME", "NULL"),
            # v2.42.9 处方 4 调度优先级：repair 置顶 100 / 重试未匹配 50，0=默认。
            ("enrich_priority", "INTEGER", "0"),
            # 元数据来源标记：老库补列后为 NULL（历史数据未标记），
            # 由刮削时重新写入；查"刮没刮干净"不再依赖 last_scraped_at 反推。
            ("metadata_source", "VARCHAR(20)", "NULL"),
            # v2.48.0 软删除：老库补列后全为 NULL = 全部可见，行为与以前完全一致。
            # 回滚：MEDIA_SOFT_DELETE=0 启动时会把已隐藏的行清空（见 _resurrect_soft_deleted）。
            ("deleted_at", "DATETIME", "NULL"),
            # v2.49.0 文件名元数据：扫描时从文件名解析分辨率/发行来源（零 Drive 调用）。
            # video_codec / audio_codec 列已存在（探测器时代留下），复用即可。
            ("video_resolution", "VARCHAR(10)", "NULL"),
            ("media_source", "VARCHAR(30)", "NULL"),
            # 手动识别 P3：元数据锁定（Emby 式）。老库补列后默认 0 = 未锁定，
            # 行为与升级前完全一致；锁定只挡 enrich 自动抢单，不挡手动绑定/重刮。
            ("metadata_locked", "BOOLEAN", "0"),
            # v2.51.0 演员刮削：TMDB details 的 origin_country / spoken_languages
            # 落库，供 EA 详情页 Countries / Languages 用。
            # 老库补列后为空串 = 以前的 []，行为与升级前一致。
            ("countries", "TEXT", "''"),
            ("languages", "TEXT", "''"),
        ]),
        # 媒体流逐流细节：客户端「媒体信息」页要显示帧率/动态范围/位深/采样率等，
        # 缺了详情页只剩编码与码率几行（对比其它 Emby 服务端就很空）。
        ("emby_items", [
            ("drive_file_id", "VARCHAR(64)", "NULL"),
            # StrmAssistant #4 多版本合并：被合并条目的 merged_into_id 指向主记录
            ("merged_into_id", "INTEGER", "NULL"),
        ]),
        ("emby_media_streams", [
            ("frame_rate", "VARCHAR(20)", "NULL"),
            ("video_range", "VARCHAR(20)", "NULL"),
            ("profile", "VARCHAR(30)", "NULL"),
            ("level", "VARCHAR(30)", "NULL"),
            ("pixel_format", "VARCHAR(30)", "NULL"),
            ("aspect_ratio", "VARCHAR(20)", "NULL"),
            ("bit_depth", "INTEGER", "NULL"),
            ("sample_rate", "INTEGER", "NULL"),
            ("channel_layout", "VARCHAR(30)", "NULL"),
            ("sample_format", "VARCHAR(20)", "NULL"),
        ]),
    ]

    _newly_added_columns: list[tuple[str, str]] = []
    for table, columns in migrations:
        if table not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        with engine.begin() as conn:
            for col_name, col_type, default in columns:
                if col_name not in existing_cols:
                    col_type, default = _dialect_col_spec(col_type, default)
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type} DEFAULT {default}"
                    ))
                    print(f"  🔧 已迁移: {table}.{col_name} ({col_type})")
                    _newly_added_columns.append((table, col_name))

    _widen_code_column(existing_tables, inspector)
    _widen_bitrate_column(existing_tables, inspector)
    _widen_stream_title_columns(existing_tables, inspector)
    _backfill_orm_columns(existing_tables)
    # v2.49.0：本次刚补上 video_resolution 列的老库，用文件名解析回填已有条目
    # （纯字符串解析，零 Drive 调用；只跑一次，下次启动列已存在不会再触发）
    if ("emby_items", "video_resolution") in _newly_added_columns:
        _backfill_filename_meta()
    _ensure_probe_index(existing_tables)
    _ensure_enrich_index(existing_tables)
    _ensure_merged_into_id_index(existing_tables)
    _ensure_person_tmdb_id_index(existing_tables)
    _ensure_added_index(existing_tables)
    _ensure_deleted_index(existing_tables)
    _ensure_drive_file_id_index(existing_tables)
    _resurrect_soft_deleted(existing_tables)
    _ensure_default_realm()
    _hash_plain_emby_tokens(existing_tables)


def _backfill_filename_meta() -> None:
    """v2.49.0：老库补上 video_resolution 列后，用文件名解析回填已有条目。

    纯字符串解析，零 Drive 调用。只处理 file_path 非空且 video_resolution
    为空的行；已有探测数据的字段（非空的 video_codec / 非零的 width 等）
    不覆盖——文件名解析只是回退，不如 ffprobe 精确。
    分批提交；幂等（跑过一次后触发条件不再成立）。
    """
    from backend.emby_server import models as emby_models
    from backend.emby_server.filename_meta import parse_filename, resolution_to_wh

    MI = emby_models.MediaItem
    session = Session(bind=engine)
    try:
        # 先一次性拿 ID（避免“解析不到的行保持 NULL 被反复选中”的死循环）
        all_ids = [
            row[0] for row in session.query(MI.id).filter(
                MI.video_resolution.is_(None), MI.file_path.isnot(None)
            ).all()
        ]
        BATCH = 1000
        total = 0
        for i in range(0, len(all_ids), BATCH):
            chunk = all_ids[i:i + BATCH]
            rows = (
                session.query(
                    MI.id, MI.file_path, MI.video_codec, MI.audio_codec,
                    MI.media_source, MI.width, MI.height,
                )
                .filter(MI.id.in_(chunk))
                .all()
            )
            mappings = []
            for (row_id, file_path, vcodec, acodec, msource, width, height) in rows:
                name = (file_path or "").rsplit("/", 1)[-1]
                meta = parse_filename(name)
                m = {"id": row_id, "video_resolution": meta.get("resolution")}
                if not vcodec and meta.get("video_codec"):
                    m["video_codec"] = meta["video_codec"]
                if not acodec and meta.get("audio_codec"):
                    m["audio_codec"] = meta["audio_codec"]
                if not msource and meta.get("source"):
                    m["media_source"] = meta["source"]
                w, h = resolution_to_wh(meta.get("resolution"))
                if not width and w:
                    m["width"] = w
                if not height and h:
                    m["height"] = h
                mappings.append(m)
            session.bulk_update_mappings(MI, mappings)
            session.commit()
            total += len(mappings)
        if total:
            print(f"  🔧 已回填: emby_items 文件名元数据 {total} 条")
    finally:
        session.close()


def _hash_plain_emby_tokens(existing_tables: set) -> None:
    """P1 安全修复：emby_api_tokens.token 改存 SHA256 哈希。

    存量明文 token（40 位 token_hex(20) 或其他遗留格式）一次性哈希化。
    幂等：只处理长度 != 64 的行，已哈希的（64 位 hex）跳过，跑两次不坏。
    注意这是单向的：回滚代码版本不会恢复明文，旧客户端会话需重新登录。
    """
    import hashlib

    if "emby_api_tokens" not in existing_tables:
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, token FROM emby_api_tokens WHERE LENGTH(token) != 64")
        ).fetchall()
        for rid, tok in rows:
            hashed = hashlib.sha256(tok.encode("utf-8")).hexdigest()
            conn.execute(
                text("UPDATE emby_api_tokens SET token = :h WHERE id = :i"),
                {"h": hashed, "i": rid},
            )
        if rows:
            print(f"  🔧 已迁移: emby_api_tokens.token 哈希化 {len(rows)} 条")


def _ensure_probe_index(existing_tables: set) -> None:
    """两阶段扫描（v2.39.0）：给老库补探测队列表索引（幂等）

    create_all 只在建新表时建索引；升级上来的库 emby_items 表已存在，
    这里按 inspector 显式补上 ``idx_item_probe``，worker 取待探测条目时走索引。
    """
    from sqlalchemy import inspect, text

    if "emby_items" not in existing_tables:
        return
    inspector = inspect(engine)
    names = {ix["name"] for ix in inspector.get_indexes("emby_items")}
    if "idx_item_probe" in names:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX idx_item_probe "
            "ON emby_items (probe_status, probe_priority, id)"
        ))
        print("  🔧 已迁移: emby_items.idx_item_probe（探测队列索引）")


def _ensure_enrich_index(existing_tables: set) -> None:
    """给老库补补全队列的复合索引（幂等，v2.48.0）

    与 :func:`_ensure_probe_index` 同理。探测队列早就有 ``idx_item_probe``，
    补全队列当初只给了 ``enrich_status`` 单列索引——而 ``_claim_batch`` 的抢单是
    ``WHERE enrich_status='pending' AND enrich_next_retry_at<=now`` 再按
    ``enrich_priority`` 排序，单列索引帮不上忙，积压一涨就是排序全表。

    **可回滚**：``DROP INDEX idx_item_enrich`` 即可，无数据影响。
    """
    from sqlalchemy import inspect, text

    if "emby_items" not in existing_tables:
        return
    inspector = inspect(engine)
    names = {ix["name"] for ix in inspector.get_indexes("emby_items")}
    if "idx_item_enrich" in names:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX idx_item_enrich "
            "ON emby_items (enrich_status, enrich_next_retry_at, enrich_priority)"
        ))
        print("  🔧 已迁移: emby_items.idx_item_enrich（补全队列复合索引）")


def _ensure_added_index(existing_tables: set) -> None:
    """给老库补追新日历的入库时间索引（幂等）

    与 :func:`_ensure_probe_index` 同理：``create_all`` 只在建新表时建索引，
    升级上来的库 ``emby_items`` 表已存在，这里按 inspector 显式补上
    ``idx_item_added``，否则用户打开追新日历就是一次全表扫。
    """
    from sqlalchemy import inspect, text

    if "emby_items" not in existing_tables:
        return
    inspector = inspect(engine)
    names = {ix["name"] for ix in inspector.get_indexes("emby_items")}
    if "idx_item_added" in names:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX idx_item_added "
            "ON emby_items (date_added, item_type)"
        ))
        print("  🔧 已迁移: emby_items.idx_item_added（追新日历索引）")


def _ensure_deleted_index(existing_tables: set) -> None:
    """给老库补软删除可见性索引（幂等，v2.48.0）

    可见性过滤（``deleted_at IS NULL``）是全局拼上去的，与几乎所有查询的
    ``library_id = ?`` 绑在一起。把 deleted_at 跟在 library_id 后面，已下架的行
    在索引里就被跳过，不必回表再过滤。

    **可回滚**：``DROP INDEX idx_item_lib_deleted`` 即可，无数据影响。
    """
    from sqlalchemy import inspect, text

    if "emby_items" not in existing_tables:
        return
    inspector = inspect(engine)
    names = {ix["name"] for ix in inspector.get_indexes("emby_items")}
    if "idx_item_lib_deleted" in names:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX idx_item_lib_deleted "
            "ON emby_items (library_id, deleted_at)"
        ))
        print("  🔧 已迁移: emby_items.idx_item_lib_deleted（软删除可见性索引）")



def _ensure_merged_into_id_index(existing_tables: set) -> None:
    """给老库补多版本合并查询索引（幂等）

    ``merged_into_id`` 列在模型里有 ``index=True``，但老库是 ALTER 加的列，
    create_all 不会给已存在的表补索引。这里显式补上，供多版本合并/
    拆分查询 ``WHERE merged_into_id = ?`` 走索引。
    """
    from sqlalchemy import inspect, text

    if "emby_items" not in existing_tables:
        return
    inspector = inspect(engine)
    names = {ix["name"] for ix in inspector.get_indexes("emby_items")}
    if "idx_item_merged_into_id" in names:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX idx_item_merged_into_id "
            "ON emby_items (merged_into_id)"
        ))
        print("  已迁移: emby_items.idx_item_merged_into_id（多版本合并索引）")


def _ensure_person_tmdb_id_index(existing_tables: set) -> None:
    """给老库补演员 TMDB ID 索引（幂等，防御式）

    emby_people 表较新，老库可能没有 tmdb_id 列：先检查列存在才建索引，
    列不存在时静默跳过（不报错、不阻塞启动）。
    """
    from sqlalchemy import inspect, text

    if "emby_people" not in existing_tables:
        return
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("emby_people")}
    if "tmdb_id" not in cols:
        return
    names = {ix["name"] for ix in inspector.get_indexes("emby_people")}
    if "idx_person_tmdb_id" in names:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX idx_person_tmdb_id "
            "ON emby_people (tmdb_id)"
        ))
        print("  已迁移: emby_people.idx_person_tmdb_id（演员 TMDB 索引）")


def _ensure_drive_file_id_index(existing_tables: set) -> None:
    """v2.52.0: 给老库补 drive_file_id 索引（幂等）

    改名/移动检测按 drive_file_id 批量查条目，没有索引就是全表扫。
    """
    from sqlalchemy import inspect, text

    if "emby_items" not in existing_tables:
        return
    inspector = inspect(engine)
    names = {ix["name"] for ix in inspector.get_indexes("emby_items")}
    if "idx_item_drive_file_id" in names:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX idx_item_drive_file_id "
            "ON emby_items (drive_file_id)"
        ))
        print("  已迁移: emby_items.idx_item_drive_file_id")


def _resurrect_soft_deleted(existing_tables: set) -> None:
    """回滚软删除：``MEDIA_SOFT_DELETE=0`` 时把已隐藏的条目放回来（幂等）

    关掉开关意味着清理阶段回到硬删，也就是「条目会真的消失」。如果不把已隐藏的行
    放回来，它们就会变成既不显示、也永远删不掉的僵尸行——所以开关关掉的**那一刻**
    就必须恢复成软删除上线前的可见状态，之后的删除才是真的删除。
    """
    from sqlalchemy import text

    from backend.emby_server.soft_delete import soft_delete_enabled

    if soft_delete_enabled() or "emby_items" not in existing_tables:
        return
    with engine.begin() as conn:
        restored = conn.execute(
            text("UPDATE emby_items SET deleted_at = NULL WHERE deleted_at IS NOT NULL")
        ).rowcount
    if restored:
        print(f"  🔧 软删除已关闭：{restored} 条隐藏条目已恢复可见")


def _all_metadata():
    """所有 ORM 元数据（不止本模块的 Base）

    ``backend.emby_server.models`` 自建了一个 Base（两种部署形态要能分开建表），
    它不在 ``Base.metadata`` 里。以前这份对账只看 ``Base.metadata``，于是
    **emby_* 的表从来没被兼底过**：每次给 ``emby_libraries`` 加新列，都必须同步手写一条
    ``_MISSING_COLUMNS``；漏了就直接报 “table emby_libraries has no column named …”
    （建表走的是 emby 的 Base，而那条 ALTER 只对已经存在的表生效）。
    改成两边都以 ORM 为准，忘了写也能自愈。
    """
    from backend.emby_server import models as emby_models

    return (Base.metadata, emby_models.Base.metadata)


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
    seen_tables: set = set()
    for meta in _all_metadata():
        for table in meta.sorted_tables:
            if table.name not in existing_tables or table.name in seen_tables:
                continue
            seen_tables.add(table.name)
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            missing = [c for c in table.columns
                       if c.name not in existing_cols and not c.primary_key]
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
        # PG 不接受整数做布尔默认值（DEFAULT 1 直接报错），必须写 TRUE/FALSE；
        # SQLite/MySQL 用 1/0 也认。
        if engine.dialect.name == "postgresql":
            literal = "TRUE" if arg else "FALSE"
        else:
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


def _widen_bitrate_column(existing_tables: set, inspector) -> None:
    """emby_items.bitrate 曾是 32 位 integer，遇到超大码率时探测 worker 整轮崩

    部分高码率原盘（4K/8K remux）报出的 bitrate 会超过 2**31-1，落库时抛
    ``NumericValueOutOfRange``，把 ``_probe_one`` 整轮打成异常、探测全停。
    这里加宽为 BIGINT（先钳位历史值再改类型），语句幂等，已是 BIGINT 直接跳过。
    SQLite 整数本身是 64 位，无需处理。
    """
    from sqlalchemy import text

    if "emby_items" not in existing_tables:
        return
    dialect = engine.dialect.name
    if dialect not in ("postgresql", "mysql"):
        return
    for col in inspector.get_columns("emby_items"):
        if col["name"] != "bitrate":
            continue
        if col["type"] is not None and "bigint" in str(col["type"]).lower():
            return
        with engine.begin() as conn:
            # 历史值理论上都写进来了（越界的当场就失败了），钳位仅作兜底
            conn.execute(text(
                "UPDATE emby_items SET bitrate = 2147483647 "
                "WHERE bitrate IS NOT NULL AND bitrate > 2147483647"
            ))
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE emby_items ALTER COLUMN bitrate TYPE BIGINT"))
            else:
                conn.execute(text("ALTER TABLE emby_items MODIFY COLUMN bitrate BIGINT"))
        print("  🔧 已迁移: emby_items.bitrate → BIGINT（修 32 位码率溢出）")


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


def _widen_stream_title_columns(existing_tables: set, inspector) -> None:
    """emby_media_streams.display_title/title 从 VARCHAR(200) 扩到 500

    生产日志：ffprobe 的 tags.title（流描述句，长度不受控）与外挂字幕文件名
    偶发超 200 字，PG 报 ``StringDataRightTruncation``，单条 INSERT 失败把
    整个写事务（同批扫描/探测/补全）全部带崩。模型已改为 String(500)，
    老库在这里幂等加宽；SQLite 不校验 VARCHAR 长度，无需处理。
    """
    from sqlalchemy import text

    if "emby_media_streams" not in existing_tables:
        return
    dialect = engine.dialect.name
    if dialect not in ("postgresql", "mysql"):
        return
    for col in inspector.get_columns("emby_media_streams"):
        if col["name"] not in ("display_title", "title"):
            continue
        length = getattr(col.get("type"), "length", None)
        if length is None or length >= 500:
            continue
        with engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text(
                    f"ALTER TABLE emby_media_streams ALTER COLUMN {col['name']} "
                    "TYPE VARCHAR(500)"
                ))
            else:
                conn.execute(text(
                    f"ALTER TABLE emby_media_streams MODIFY COLUMN {col['name']} "
                    "VARCHAR(500)"
                ))
        print(f"  🔧 已迁移: emby_media_streams.{col['name']} 宽度 → 500"
              "（修 StringDataRightTruncation）")


_PG_LOCK_KEY = 72772620260929


def _sqlite_lock_path() -> str:
    """迁移锁文件：与 SQLite 库同目录（锁必须和数据在同一个文件系统上）。"""
    try:
        url = engine.url
    except Exception:  # noqa: BLE001 — engine 未就绪时退到 cwd
        return ".aetrix-migrate.lock"
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        return ".aetrix-migrate.lock"
    import os.path
    return os.path.join(os.path.dirname(os.path.abspath(url.database)) or ".",
                        ".aetrix-migrate.lock")


def _acquire_migrate_lock():
    """跨进程互斥地跑 schema 初始化/迁移。

    为什么必须有：init_db() 会被 api、worker、EA 三个进程**同时**调用，而建表/加列/
    建索引在 PG 与 SQLite 上都没有 IF NOT EXISTS。三个进程同时判定"表不存在"→ 全部
    执行 → 后到的抛 DuplicateTable / duplicate column name。而 main.py 与 worker.py
    都是 fail-closed 的 raise / return 1，restart: unless-stopped 下变成崩溃重启循环。

    切换到 PG（空库、首次建全表）时三条路径几乎必然同时进来，所以这是**切换的前置
    条件**，不是可选优化。

    两种方言各用各的原生手段：
    - PostgreSQL：pg_advisory_lock（会话级、跨进程、不占表）；
    - SQLite：fcntl.flock 文件锁。**不用数据库事务做锁**——试过 BEGIN IMMEDIATE 与
      "占一行不提交"，两种都会因为 create_all 走 engine 的其它连接、而 busy_timeout
      对该场景不生效而报 "database is locked"。flock 是操作系统级阻塞，语义明确。

    拿不到锁时**仍然继续**（fail-open）——加锁只是把"几乎必错"降为"几乎不错"，
    不能让一次锁故障把服务彻底挡住；原有"重复执行后自愈"的能力保留。
    """
    import contextlib

    @contextlib.contextmanager
    def _locked():
        if DATABASE_TYPE == "postgresql":
            conn = engine.connect()
            try:
                conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _PG_LOCK_KEY})
                try:
                    yield
                finally:
                    try:
                        conn.execute(text("SELECT pg_advisory_unlock(:k)"),
                                     {"k": _PG_LOCK_KEY})
                    except Exception:  # noqa: BLE001 — 解锁失败不影响已完成的迁移
                        pass
            finally:
                conn.close()
            return

        import fcntl
        import os
        path = _sqlite_lock_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fh = open(path, "w")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # 阻塞直到拿到
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

    return _locked()


def _ensure_admin_roles() -> None:
    """S1：空角色管理员的一次性迁移 + 「没有超管」时的防锁死自愈（见 backend/admin_roles.py）

    失败只记日志不阻断启动：失败的后果是空角色管理员按只读处理（fail closed），
    可以随时用 ``python scripts/create_admin.py <用户名>`` 把站长显式写成 super。
    """
    import logging

    from backend import admin_roles

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        result = admin_roles.ensure_legacy_admin_roles(db)
        if result.get("migrated"):
            log.warning("S1 迁移：空角色管理员 id=%s 已写为 super（最早的管理员）", result["migrated"])
        if result.get("left_viewer"):
            log.warning(
                "S1 迁移：空角色管理员 id=%s 现在按只读（viewer）处理，"
                "需要更高权限请由超级管理员在「管理员」页显式授予角色", result["left_viewer"])
        if result.get("healed"):
            log.warning("库里没有启用中的超级管理员：已把最早的管理员 id=%s 提为 super", result["healed"])
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("管理员角色迁移失败（空角色管理员将按只读处理）")
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表并执行轻量自动迁移。

    迁移失败必须让调用方感知：继续启动会把“模型已升级、数据库仍是旧结构”的
    半可用服务暴露出去，首个业务请求才 500，且可能在不完整 schema 上继续写数据。
    部署探针 / lifespan 会据此 fail-closed；一次性 CLI 也能拿到真实异常。
    """
    from backend import models  # 导入所有模型
    from backend.emby_server import models as emby_models  # 自建 Emby 服务器模型
    with _acquire_migrate_lock():
        Base.metadata.create_all(bind=engine)
        _auto_migrate()
        _ensure_admin_roles()
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
