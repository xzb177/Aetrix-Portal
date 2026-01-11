"""
添加求片下载源字段
为求片表添加 download_source, download_url, download_note 字段
用于支持磁力链接、网盘链接等多种下载源
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin_database_user import get_user_db
from sqlalchemy import text
from sqlalchemy.orm import Session


def upgrade():
    """添加新字段"""
    db: Session = next(get_user_db())
    try:
        with db.connect() as conn:
            # 添加下载源字段
            conn.execute(text("ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS download_source VARCHAR(50)"))
            conn.execute(text("ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS download_url TEXT"))
            conn.execute(text("ALTER TABLE movie_requests ADD COLUMN IF NOT EXISTS download_note TEXT"))
            conn.commit()
            print("✅ 成功添加求片下载源字段")
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        raise
    finally:
        db.close()


def downgrade():
    """移除字段"""
    db: Session = next(get_user_db())
    try:
        with db.connect() as conn:
            conn.execute(text("ALTER TABLE movie_requests DROP COLUMN IF EXISTS download_source"))
            conn.execute(text("ALTER TABLE movie_requests DROP COLUMN IF EXISTS download_url"))
            conn.execute(text("ALTER TABLE movie_requests DROP COLUMN IF EXISTS download_note"))
            conn.commit()
            print("✅ 成功移除求片下载源字段")
    except Exception as e:
        print(f"❌ 回滚失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="数据库迁移")
    parser.add_argument("--downgrade", action="store_true", help="回滚迁移")
    args = parser.parse_args()

    if args.downgrade:
        downgrade()
    else:
        upgrade()
