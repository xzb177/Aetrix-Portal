#!/usr/bin/env python3
"""
迁移脚本：添加充值余额字段

执行方式：docker exec -it royalbot_user_backend python3 scripts/migrate_add_balance.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database import DATABASE_URL

def migrate():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        # 检查字段是否已存在
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='web_users' AND column_name='balance'
        """))
        if result.fetchone():
            print("✅ 字段 balance 已存在，跳过")
            return

        print("📝 添加 balance 字段...")
        conn.execute(text("""
            ALTER TABLE web_users ADD COLUMN balance INTEGER NOT NULL DEFAULT 0
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS balance_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES web_users(id),
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                transaction_type VARCHAR(50) NOT NULL,
                source_type VARCHAR(50),
                source_id INTEGER,
                description VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_bt_user ON balance_transactions(user_id)
        """))
        conn.commit()
        print("✅ 迁移完成")

if __name__ == "__main__":
    migrate()
