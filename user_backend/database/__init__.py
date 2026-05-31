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
    from . import models_new  # 创新功能模型
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

        # 1. 检查 web_users 表并添加缺失的字段
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

        # 2. 修改 recharge_orders 表的 package_id 为可空（SQLite 不支持直接修改，需要重建表）
        cursor.execute('PRAGMA table_info(recharge_orders)')
        recharge_columns = cursor.fetchall()
        recharge_col_names = [col[1] for col in recharge_columns]

        # 检查 package_id 是否允许 NULL
        package_id_nullable = None
        for col in recharge_columns:
            if col[1] == 'package_id':
                package_id_nullable = col[3]  # 0 = NOT NULL, 1 = NULL
                break

        # 如果 package_id 存在且为 NOT NULL，需要重建表
        if package_id_nullable == 0:
            print('[DB Migration] 重建 recharge_orders 表，使 package_id 可空...')
            try:
                # 1. 创建新表
                cursor.execute('''
                    CREATE TABLE recharge_orders_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        order_id VARCHAR(64) UNIQUE NOT NULL,
                        user_id INTEGER NOT NULL,
                        package_id INTEGER NULL,
                        amount INTEGER NOT NULL,
                        price DECIMAL(10, 2) NOT NULL,
                        payment_method VARCHAR(50),
                        status VARCHAR(20) DEFAULT 'pending',
                        payment_url VARCHAR(500),
                        paid_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 2. 复制数据
                cursor.execute('''
                    INSERT INTO recharge_orders_new
                    SELECT * FROM recharge_orders
                ''')

                # 3. 删除旧表
                cursor.execute('DROP TABLE recharge_orders')

                # 4. 重命名新表
                cursor.execute('ALTER TABLE recharge_orders_new RENAME TO recharge_orders')

                # 5. 重建索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_recharge_user ON recharge_orders(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_recharge_status ON recharge_orders(status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_recharge_order_id ON recharge_orders(order_id)')

                print('[DB Migration] recharge_orders 表重建完成')
            except Exception as e:
                print(f'[DB Migration] 重建 recharge_orders 表失败: {e}')

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
