"""
数据库连接和会话管理
管理后台使用独立数据库，主项目数据通过只读连接访问
"""
import sys
import os
import importlib.util

# 添加当前项目路径优先（避免与主项目模块冲突）
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 添加主项目路径（用于访问主项目数据）
sys.path.insert(1, "/root/royalbot")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from admin_utils.config import settings
from admin_utils.models_loader import AdminUser, AdminRole, Permission, AdminLog

# ==================== 管理后台独立数据库 ====================
# 管理员相关表：admin_users, admin_roles, admin_logs
# 性能优化：连接池配置
admin_engine = create_engine(
    settings.DATABASE_URL,  # PostgreSQL: postgresql://royalbot:xxx@postgres:5432/royalbot
    echo=settings.DB_ECHO,
    pool_pre_ping=True,  # 连接前检查可用性
    pool_recycle=3600,  # 1小时后回收连接
    pool_size=10,  # 基础连接池大小
    max_overflow=20,  # 最大额外连接数
    pool_timeout=30,  # 获取连接超时时间
    pool_use_lifo=True,  # 后进先出，减少空闲连接
    connect_args={
        "connect_timeout": 10,
        "options": "-c statement_timeout=30000",  # 30秒查询超时
    } if "postgresql" in settings.DATABASE_URL else {},
)
AdminSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=admin_engine)

# ==================== 主项目数据库（只读）====================
# 用于访问用户数据（web_users 等）
# 现在使用 PostgreSQL（与用户端共享数据库）
main_engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=5,
    max_overflow=10,
    connect_args={
        "connect_timeout": 10,
        "options": "-c statement_timeout=30000",
    } if "postgresql" in settings.DATABASE_URL else {},
)
MainSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=main_engine)

# ==================== SQLite 数据库（兼容旧 Telegram Bot）====================
# 保留 SQLite 用于访问旧的 bindings 表（如果需要）
sqlite_db_path = os.path.expanduser(settings.MAIN_DB_PATH)
sqlite_engine = create_engine(
    f"sqlite:///{sqlite_db_path}",
    connect_args={"check_same_thread": False},
    echo=settings.DB_ECHO,
)
SqliteSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)

# 导入本地模型（从主项目）
import admin_models
UserBinding = admin_models.UserBinding
MovieBookmark = admin_models.MovieBookmark
ThemeActivity = admin_models.ThemeActivity
ThemeActivityProgress = admin_models.ThemeActivityProgress

# 导出所有模型
__all__ = [
    "AdminUser",
    "AdminRole",
    "AdminLog",
    "Permission",
    "UserBinding",
    "MovieBookmark",
    "ThemeActivity",
    "ThemeActivityProgress",
    "AdminSessionLocal",
    "MainSessionLocal",
    "admin_engine",
    "main_engine",
    "init_db",
    "get_admin_db",
    "get_main_db",
]


def init_db():
    """初始化管理后台数据库（创建管理员表等）"""
    # 只在管理后台数据库中创建管理员相关的表
    AdminUser.metadata.create_all(bind=admin_engine)
    AdminRole.metadata.create_all(bind=admin_engine)
    AdminLog.metadata.create_all(bind=admin_engine)

    # 创建默认管理员（如果不存在）
    db = AdminSessionLocal()
    try:
        # 检查是否有管理员
        admin_count = db.query(AdminUser).count()
        if admin_count == 0:
            # 安全检查：必须设置管理员密码
            if not settings.DEFAULT_ADMIN_PASSWORD:
                raise RuntimeError(
                    "⚠️ 安全警告：创建管理员需要设置 DEFAULT_ADMIN_PASSWORD 环境变量！\n"
                    "请在 .env 文件中添加: DEFAULT_ADMIN_PASSWORD=你的强密码"
                )

            # 检查密码强度（使用新的密码策略）
            pwd = settings.DEFAULT_ADMIN_PASSWORD
            if len(pwd) < settings.MIN_PASSWORD_LENGTH:
                raise RuntimeError(
                    f"⚠️ 安全警告：管理员密码长度至少需要 {settings.MIN_PASSWORD_LENGTH} 位！"
                )

            if settings.REQUIRE_PASSWORD_COMPLEXITY:
                import re
                errors = []
                if not re.search(r'[A-Z]', pwd):
                    errors.append("大写字母")
                if not re.search(r'[a-z]', pwd):
                    errors.append("小写字母")
                if not re.search(r'\d', pwd):
                    errors.append("数字")
                if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>?]', pwd):
                    errors.append("特殊字符")

                if errors:
                    raise RuntimeError(
                        f"⚠️ 密码复杂度不足，必须包含: {', '.join(errors)}\n"
                        f"当前密码不符合安全要求（长度≥{settings.MIN_PASSWORD_LENGTH}，"
                        f"需包含大小写字母、数字和特殊字符）"
                    )

            # 创建默认超级管理员
            from admin_utils.auth import get_password_hash
            super_admin = AdminUser(
                username="admin",
                password_hash=get_password_hash(pwd),
                role="super_admin",
                is_active=True,
            )
            db.add(super_admin)
            db.commit()
            print("✅ 默认管理员已创建 (用户名: admin)")
            print("⚠️  首次登录后请立即修改密码！")
        else:
            print("✅ 管理员表已存在，跳过创建")
    except Exception as e:
        db.rollback()
        print(f"❌ 创建默认管理员失败: {e}")
        raise
    finally:
        db.close()


def get_admin_db() -> Session:
    """获取管理后台数据库会话（用于管理员表操作）"""
    db = AdminSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_main_db() -> Session:
    """获取主项目数据库会话（用于读取 Telegram 用户等数据）"""
    db = MainSessionLocal()
    try:
        yield db
    finally:
        db.close()


# 兼容旧的 get_db 函数（默认使用管理后台数据库）
def get_db():
    """获取管理后台数据库会话（兼容旧代码）"""
    yield from get_admin_db()
