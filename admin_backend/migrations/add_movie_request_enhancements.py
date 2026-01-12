"""
求片功能增强数据库迁移
添加同求表、日志表，扩展求片表字段
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, ForeignKey, Index, JSON, DateTime
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
import os

USER_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://royalbot:royalbot_change_me@postgres:5432/royalbot"
)

engine = create_engine(USER_DB_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()


def upgrade():
    """执行迁移"""

    # 1. 为 movie_requests 表添加新列
    with engine.connect() as conn:
        # 检查列是否已存在
        inspector = engine.dialect.get_inspector(engine)
        existing_columns = [col['name'] for col in inspector.get_columns('movie_requests')]

        # 添加新列
        new_columns = {
            'status_remark': 'ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS status_remark TEXT',
            'download_id': 'ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS download_id VARCHAR(255)',
            'poster_url': 'ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS poster_url VARCHAR(500)',
            'tmdb_id': 'ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS tmdb_id VARCHAR(50)',
            'seek_count': 'ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS seek_count INTEGER DEFAULT 1',
            'completed_at': 'ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP',
        }

        for col_name, sql in new_columns.items():
            if col_name not in existing_columns:
                conn.execute(sql)
                print(f"✅ 添加列: {col_name}")

        # 添加索引
        new_indexes = [
            'CREATE INDEX IF NOT EXISTS idx_req_created ON movie_requests(created_at)',
        ]

        for sql in new_indexes:
            try:
                conn.execute(sql)
                print(f"✅ 创建索引成功")
            except Exception as e:
                print(f"⚠️  索引可能已存在: {e}")

        conn.commit()

    # 2. 创建同求表
    conn = engine.connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movie_request_subscribers (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES movie_requests(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notified BOOLEAN DEFAULT FALSE,
            UNIQUE(request_id, user_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sub_req ON movie_request_subscribers(request_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sub_user ON movie_request_subscribers(user_id)")
    conn.commit()
    print("✅ 创建表: movie_request_subscribers")

    # 3. 创建日志表
    conn = engine.connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movie_request_logs (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES movie_requests(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES web_users(id) ON DELETE SET NULL,
            log_type VARCHAR(20) NOT NULL,
            content TEXT,
            extra_data JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_req ON movie_request_logs(request_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_type ON movie_request_logs(log_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_created ON movie_request_logs(created_at)")
    conn.commit()
    print("✅ 创建表: movie_request_logs")

    print("\n🎉 迁移完成！")


def downgrade():
    """回滚迁移"""
    conn = engine.connect()

    # 删除新增的表
    conn.execute("DROP TABLE IF EXISTS movie_request_logs CASCADE")
    conn.execute("DROP TABLE IF EXISTS movie_request_subscribers CASCADE")

    # 删除新增的列
    conn.execute("ALTER TABLE movie_requests DROP COLUMN IF EXISTS status_remark")
    conn.execute("ALTER TABLE movie_requests DROP COLUMN IF EXISTS download_id")
    conn.execute("ALTER TABLE movie_requests DROP COLUMN IF EXISTS poster_url")
    conn.execute("ALTER TABLE movie_requests DROP COLUMN IF EXISTS tmdb_id")
    conn.execute("ALTER TABLE movie_requests DROP COLUMN IF EXISTS seek_count")
    conn.execute("ALTER TABLE movie_requests DROP COLUMN IF EXISTS completed_at")

    conn.commit()
    print("⏪ 回滚完成")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        downgrade()
    else:
        upgrade()
