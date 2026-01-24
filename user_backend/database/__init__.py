"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base
import os

# 数据库配置
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'sqlite:///royalbot.db'  # 默认使用 SQLite
)

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化数据库表"""
    from . import models
    import sqlite3

    # badges: 暂时禁用，数据库表结构需要迁移
    # from .badges import Badge, UserBadge
    Base.metadata.create_all(bind=engine)
    # 同时创建徽章表
    # Badge.metadata.create_all(bind=engine)
    # UserBadge.metadata.create_all(bind=engine)

    # 执行数据库迁移，添加缺失的字段
    _run_migrations()


def _run_migrations():
    """运行数据库迁移，添加缺失的字段"""
    import sqlite3
    import os

    # 从 DATABASE_URL 中提取数据库文件路径
    db_path = os.getenv('DATABASE_URL', 'sqlite:///royalbot.db').replace('sqlite:///', '')
    if not db_path.startswith('/'):
        db_path = f'/app/{db_path}'

    # 如果数据库文件不存在，跳过迁移
    if not os.path.exists(db_path):
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 检查 web_users 表并添加缺失的字段
        cursor.execute('PRAGMA table_info(web_users)')
        columns = [col[1] for col in cursor.fetchall()]

        # 需要添加的字段
        migrations = [
            ('points', 'INTEGER DEFAULT 0'),
            ('balance', 'INTEGER DEFAULT 0'),
            ('completed_requests_count', 'INTEGER DEFAULT 0'),
            ('total_requests_count', 'INTEGER DEFAULT 0'),
        ]

        for column_name, column_def in migrations:
            if column_name not in columns:
                try:
                    cursor.execute(f'ALTER TABLE web_users ADD COLUMN {column_name} {column_def}')
                    print(f'[DB Migration] 添加字段: web_users.{column_name}')
                except sqlite3.OperationalError as e:
                    if 'duplicate column' not in str(e).lower():
                        print(f'[DB Migration] 警告: {e}')

        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[DB Migration] 迁移失败: {e}')


def get_session() -> Session:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db():
    """获取数据库会话（依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
