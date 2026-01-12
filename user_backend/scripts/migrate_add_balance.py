"""
数据库迁移脚本：添加余额系统

功能：
1. 在 web_users 表添加 balance 字段（充值余额，单位分）
2. 创建 balance_transactions 表（余额流水）
3. 创建 exchange_code_records 表（兑换记录）

执行方式：
    cd /root/RoyalBot-Portal/user_backend
    python scripts/migrate_add_balance.py
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 数据库配置
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://royalbot:royalbot_prod_2026_secure@127.0.0.1:5432/royalbot'
)

engine = create_engine(DATABASE_URL, echo=False)
Session = sessionmaker(bind=engine)


def check_column_exists(table_name: str, column_name: str) -> bool:
    """检查列是否存在"""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def check_table_exists(table_name: str) -> bool:
    """检查表是否存在"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def migrate():
    """执行迁移"""
    session = Session()
    try:
        # 1. 添加 balance 字段到 web_users 表
        logger.info("步骤 1/3: 检查并添加 web_users.balance 字段...")

        if not check_column_exists('web_users', 'balance'):
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE web_users ADD COLUMN balance INTEGER DEFAULT 0"
                ))
                conn.commit()
            logger.info("✓ 已添加 web_users.balance 字段")
        else:
            logger.info("✓ web_users.balance 字段已存在，跳过")

        # 2. 创建 balance_transactions 表
        logger.info("步骤 2/3: 检查并创建 balance_transactions 表...")

        if not check_table_exists('balance_transactions'):
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE balance_transactions (
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
                conn.execute(text(
                    "CREATE INDEX idx_bt_user ON balance_transactions(user_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX idx_bt_type ON balance_transactions(transaction_type)"
                ))
                conn.execute(text(
                    "CREATE INDEX idx_bt_source ON balance_transactions(source_type)"
                ))
                conn.commit()
            logger.info("✓ 已创建 balance_transactions 表")
        else:
            logger.info("✓ balance_transactions 表已存在，跳过")

        # 3. 创建 exchange_code_records 表
        logger.info("步骤 3/3: 检查并创建 exchange_code_records 表...")

        if not check_table_exists('exchange_code_records'):
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE exchange_code_records (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES web_users(id),
                        exchange_code_id INTEGER NOT NULL REFERENCES exchange_codes(id),
                        code_type INTEGER NOT NULL,
                        code_display VARCHAR(100),
                        effect JSON,
                        description VARCHAR(500),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX idx_ecr_user ON exchange_code_records(user_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX idx_ecr_code ON exchange_code_records(exchange_code_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX idx_ecr_created ON exchange_code_records(created_at)"
                ))
                conn.commit()
            logger.info("✓ 已创建 exchange_code_records 表")
        else:
            logger.info("✓ exchange_code_records 表已存在，跳过")

        logger.info("=" * 50)
        logger.info("迁移完成！")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"迁移失败: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def rollback():
    """回滚迁移"""
    logger.info("开始回滚迁移...")
    session = Session()
    try:
        # 1. 删除 exchange_code_records 表
        if check_table_exists('exchange_code_records'):
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS exchange_code_records"))
                conn.commit()
            logger.info("✓ 已删除 exchange_code_records 表")

        # 2. 删除 balance_transactions 表
        if check_table_exists('balance_transactions'):
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS balance_transactions"))
                conn.commit()
            logger.info("✓ 已删除 balance_transactions 表")

        # 3. 删除 balance 字段（可选，建议保留）
        # if check_column_exists('web_users', 'balance'):
        #     with engine.connect() as conn:
        #         conn.execute(text("ALTER TABLE web_users DROP COLUMN balance"))
        #         conn.commit()
        #     logger.info("✓ 已删除 web_users.balance 字段")

        logger.info("回滚完成！")

    except Exception as e:
        logger.error(f"回滚失败: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='数据库迁移脚本')
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')

    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
