#!/usr/bin/env python3
"""
RoyalBot Portal 数据库迁移脚本
从 SQLite 迁移到 PostgreSQL

用法:
    python migrate-to-postgres.py [--source SOURCE_DB] [--target TARGET_URL]

示例:
    python migrate-to-postgres.py \\
        --source /root/RoyalBot-Portal/user_backend/royalbot.db \\
        --target postgresql://royalbot:password@localhost:5432/royalbot
"""

import argparse
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
import sys


class DatabaseMigrator:
    """数据库迁移器"""

    def __init__(self, source_db: str, target_url: str):
        self.source_db = source_db
        self.target_url = target_url
        self.source_conn = None
        self.target_conn = None

    def connect(self):
        """连接源数据库和目标数据库"""
        # 连接 SQLite
        self.source_conn = sqlite3.connect(self.source_db)
        self.source_conn.row_factory = sqlite3.Row

        # 连接 PostgreSQL
        self.target_conn = psycopg2.connect(self.target_url)
        self.target_conn.autocommit = False

        print(f"✓ 已连接源数据库: {self.source_db}")
        print(f"✓ 已连接目标数据库: PostgreSQL")

    def close(self):
        """关闭数据库连接"""
        if self.source_conn:
            self.source_conn.close()
        if self.target_conn:
            self.target_conn.close()
        print("✓ 数据库连接已关闭")

    def create_tables(self):
        """创建 PostgreSQL 表结构"""
        cur = self.target_conn.cursor()

        # 创建枚举类型
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscription_status_enum') THEN
                    CREATE TYPE subscription_status_enum AS ENUM ('active', 'expired', 'cancelled', 'pending');
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'request_status_enum') THEN
                    CREATE TYPE request_status_enum AS ENUM ('pending', 'approved', 'rejected', 'completed');
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_status_enum') THEN
                    CREATE TYPE order_status_enum AS ENUM ('pending', 'paid', 'failed', 'cancelled');
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_method_enum') THEN
                    CREATE TYPE payment_method_enum AS ENUM ('yipay', 'alipay', 'wxpay', 'balance');
                END IF;
            END $$;
        """)

        # 创建 web_users 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                telegram_id BIGINT UNIQUE,
                is_active BOOLEAN DEFAULT TRUE,
                is_staff BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_web_users_telegram_id ON web_users(telegram_id);
        """)

        # 创建 subscription_plans 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscription_plans (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                price DECIMAL(10,2) NOT NULL,
                duration_days INTEGER NOT NULL,
                features TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                is_popular BOOLEAN DEFAULT FALSE,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建 recharge_packages 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recharge_packages (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                amount INTEGER NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                bonus INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                is_popular BOOLEAN DEFAULT FALSE,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建 user_subscriptions 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES subscription_plans(id),
                start_date TIMESTAMP,
                end_date TIMESTAMP NOT NULL,
                status subscription_status_enum DEFAULT 'active',
                auto_renew BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user ON user_subscriptions(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_subscriptions_status ON user_subscriptions(status);
        """)

        # 创建 movie_requests 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movie_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                movie_name VARCHAR(255) NOT NULL,
                year VARCHAR(10),
                type VARCHAR(50),
                note TEXT,
                status request_status_enum DEFAULT 'pending',
                admin_note TEXT,
                emby_item_id VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_movie_requests_user ON movie_requests(user_id);
            CREATE INDEX IF NOT EXISTS idx_movie_requests_status ON movie_requests(status);
        """)

        # 创建 recharge_orders 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recharge_orders (
                id SERIAL PRIMARY KEY,
                order_id VARCHAR(64) NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                package_id INTEGER NOT NULL REFERENCES recharge_packages(id),
                amount INTEGER NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                payment_method payment_method_enum,
                status order_status_enum DEFAULT 'pending',
                payment_url VARCHAR(500),
                paid_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_recharge_orders_user ON recharge_orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_recharge_orders_status ON recharge_orders(status);
        """)

        # 创建 subscription_orders 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscription_orders (
                id SERIAL PRIMARY KEY,
                order_id VARCHAR(64) NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                plan_id INTEGER NOT NULL REFERENCES subscription_plans(id),
                item_name VARCHAR(255),
                amount DECIMAL(10,2) NOT NULL,
                payment_method payment_method_enum,
                status order_status_enum DEFAULT 'pending',
                payment_url VARCHAR(500),
                paid_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_subscription_orders_user ON subscription_orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_subscription_orders_status ON subscription_orders(status);
        """)

        # 创建 emby_servers 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS emby_servers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                url VARCHAR(500) NOT NULL,
                host VARCHAR(255),
                port INTEGER,
                api_key VARCHAR(255) NOT NULL,
                max_users INTEGER DEFAULT 0,
                current_users INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建 plan_server_relations 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plan_server_relations (
                id SERIAL PRIMARY KEY,
                plan_id INTEGER NOT NULL REFERENCES subscription_plans(id) ON DELETE CASCADE,
                server_id INTEGER NOT NULL REFERENCES emby_servers(id) ON DELETE CASCADE,
                weight INTEGER DEFAULT 1,
                UNIQUE(plan_id, server_id)
            );
        """)

        # 创建 user_emby_accounts 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_emby_accounts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                server_id INTEGER NOT NULL REFERENCES emby_servers(id) ON DELETE CASCADE,
                emby_user_id VARCHAR(100),
                username VARCHAR(100) NOT NULL,
                password VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, server_id)
            );
            CREATE INDEX IF NOT EXISTS idx_user_emby_accounts_user ON user_emby_accounts(user_id);
        """)

        # 创建 announcements 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                type VARCHAR(20) DEFAULT 'system',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建 tickets 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                category VARCHAR(50),
                priority VARCHAR(20) DEFAULT 'normal',
                status VARCHAR(20) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        """)

        # 创建 ticket_messages 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES web_users(id),
                is_admin BOOLEAN DEFAULT FALSE,
                message TEXT NOT NULL,
                attachment_url VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket ON ticket_messages(ticket_id);
        """)

        # 创建 invitation_codes 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invitation_codes (
                id SERIAL PRIMARY KEY,
                code VARCHAR(20) NOT NULL UNIQUE,
                user_id INTEGER REFERENCES web_users(id) ON DELETE SET NULL,
                max_uses INTEGER DEFAULT -1,
                use_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建 invitation_records 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invitation_records (
                id SERIAL PRIMARY KEY,
                inviter_id INTEGER NOT NULL REFERENCES web_users(id),
                invitee_id INTEGER REFERENCES web_users(id),
                code VARCHAR(20),
                reward_points INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_invitation_records_inviter ON invitation_records(inviter_id);
        """)

        # 创建 system_configs 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_configs (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建 admin_users 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'admin',
                is_active BOOLEAN DEFAULT TRUE,
                last_login TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建 admin_logs 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id SERIAL PRIMARY KEY,
                admin_id INTEGER NOT NULL REFERENCES admin_users(id),
                admin_username VARCHAR(50),
                action VARCHAR(100) NOT NULL,
                resource VARCHAR(100),
                resource_id VARCHAR(100),
                details JSONB,
                ip_address VARCHAR(50),
                user_agent VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id);
            CREATE INDEX IF NOT EXISTS idx_admin_logs_action ON admin_logs(action);
        """)

        self.target_conn.commit()
        print("✓ PostgreSQL 表结构创建完成")

    def migrate_table(self, table_name: str, columns: list, batch_size: int = 1000):
        """迁移单个表的数据"""
        source_cur = self.source_conn.cursor()
        target_cur = self.target_conn.cursor()

        # 获取源数据总数
        source_cur.execute(f"SELECT COUNT(*) as count FROM {table_name}")
        total = source_cur.fetchone()['count']

        if total == 0:
            print(f"  ⚠ 表 {table_name} 无数据，跳过")
            return

        print(f"  → 迁移表 {table_name} ({total} 条记录)...")

        # 获取源数据
        source_cur.execute(f"SELECT * FROM {table_name}")

        # 构建插入 SQL
        columns_str = ', '.join(columns)
        placeholders = ', '.join(['%s'] * len(columns))
        insert_sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        batch = []
        migrated = 0

        for row in source_cur.fetchall():
            batch.append([row[col] for col in columns])

            if len(batch) >= batch_size:
                target_cur.executemany(insert_sql, batch)
                self.target_conn.commit()
                migrated += len(batch)
                print(f"    进度: {migrated}/{total}", end='\r')
                batch = []

        # 插入剩余数据
        if batch:
            target_cur.executemany(insert_sql, batch)
            self.target_conn.commit()
            migrated += len(batch)

        print(f"    完成: {migrated}/{total}")

    def reset_sequences(self):
        """重置 PostgreSQL 序列"""
        cur = self.target_conn.cursor()

        tables = [
            'web_users', 'subscription_plans', 'recharge_packages',
            'user_subscriptions', 'movie_requests', 'recharge_orders',
            'subscription_orders', 'emby_servers', 'plan_server_relations',
            'user_emby_accounts', 'announcements', 'tickets',
            'ticket_messages', 'invitation_codes', 'invitation_records',
            'admin_users', 'admin_logs'
        ]

        for table in tables:
            cur.execute(f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1),
                    true
                );
            """)

        self.target_conn.commit()
        print("✓ 序列重置完成")

    def migrate(self):
        """执行迁移"""
        print("\n开始迁移数据...")

        # 迁移用户端表
        migrations = [
            ('web_users', ['id', 'username', 'password_hash', 'email', 'telegram_id', 'is_active', 'is_staff', 'created_at', 'updated_at']),
            ('subscription_plans', ['id', 'name', 'description', 'price', 'duration_days', 'features', 'is_active', 'is_popular', 'sort_order', 'created_at']),
            ('recharge_packages', ['id', 'name', 'amount', 'price', 'bonus', 'is_active', 'is_popular', 'sort_order', 'created_at']),
            ('user_subscriptions', ['id', 'user_id', 'plan_id', 'start_date', 'end_date', 'status', 'auto_renew', 'created_at']),
            ('movie_requests', ['id', 'user_id', 'movie_name', 'year', 'type', 'note', 'status', 'admin_note', 'emby_item_id', 'created_at', 'updated_at']),
            ('recharge_orders', ['id', 'order_id', 'user_id', 'package_id', 'amount', 'price', 'payment_method', 'status', 'payment_url', 'paid_at', 'created_at']),
            ('subscription_orders', ['id', 'order_id', 'user_id', 'plan_id', 'item_name', 'amount', 'payment_method', 'status', 'payment_url', 'paid_at', 'created_at']),
        ]

        for table, columns in migrations:
            try:
                self.migrate_table(table, columns)
            except Exception as e:
                print(f"  ✗ 迁移表 {table} 失败: {e}")

        self.reset_sequences()
        print("\n✓ 数据迁移完成")


def main():
    parser = argparse.ArgumentParser(description='从 SQLite 迁移到 PostgreSQL')
    parser.add_argument('--source', default='/root/RoyalBot-Portal/user_backend/royalbot.db',
                        help='SQLite 数据库路径')
    parser.add_argument('--target', default='postgresql://royalbot:royalbot_change_me@localhost:5432/royalbot',
                        help='PostgreSQL 连接 URL')

    args = parser.parse_args()

    print("=" * 50)
    print("RoyalBot Portal 数据库迁移工具")
    print("=" * 50)

    try:
        migrator = DatabaseMigrator(args.source, args.target)
        migrator.connect()
        migrator.create_tables()
        migrator.migrate()
        migrator.close()

        print("\n" + "=" * 50)
        print("✓ 迁移成功完成！")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
