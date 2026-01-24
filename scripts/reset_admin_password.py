#!/usr/bin/env python3
"""
管理员密码重置脚本

用法:
    python scripts/reset_admin_password.py [username] [new_password]

如果不提供参数，会重置 admin 用户的密码为随机密码并输出
"""
import sys
import os
import secrets
import string

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'admin_backend'))

from admin_database import AdminSessionLocal
from admin_utils.models_loader import AdminUser
from admin_utils.auth import get_password_hash


def reset_admin_password(username: str = "admin", new_password: str = None):
    """重置管理员密码"""
    db = AdminSessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.username == username).first()

        if not admin:
            print(f"❌ 用户 '{username}' 不存在")
            return False

        # 如果没有提供新密码，生成一个随机密码
        if not new_password:
            new_password = ''.join(secrets.choice(string.ascii_letters + string.digits + '!@#$%') for _ in range(16))

        # 更新密码
        admin.password_hash = get_password_hash(new_password)
        db.commit()

        print(f"✅ 用户 '{username}' 密码已重置成功！")
        print(f"   新密码: {new_password}")
        print(f"   请尽快登录并修改密码！")
        return True

    except Exception as e:
        db.rollback()
        print(f"❌ 重置密码失败: {e}")
        return False
    finally:
        db.close()


def create_admin_if_not_exists(username: str = "admin", password: str = None):
    """如果管理员不存在则创建"""
    db = AdminSessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.username == username).first()

        if admin:
            print(f"ℹ️  用户 '{username}' 已存在，使用 reset_admin_password() 重置密码")
            return False

        # 如果没有提供密码，生成一个随机密码
        if not password:
            password = ''.join(secrets.choice(string.ascii_letters + string.digits + '!@#$%') for _ in range(16))

        # 创建管理员
        admin = AdminUser(
            username=username,
            password_hash=get_password_hash(password),
            role="super_admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()

        print(f"✅ 用户 '{username}' 创建成功！")
        print(f"   密码: {password}")
        print(f"   请尽快登录并修改密码！")
        return True

    except Exception as e:
        db.rollback()
        print(f"❌ 创建管理员失败: {e}")
        return False
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python scripts/reset_admin_password.py <username> [new_password]")
        print("  python scripts/reset_admin_password.py admin          # 重置 admin 密码为随机密码")
        print("  python scripts/reset_admin_password.py admin MyPass123  # 重置 admin 密码为指定密码")
        print("\n检查现有管理员:")
        print("  python scripts/reset_admin_password.py --list")
        sys.exit(1)

    command = sys.argv[1]

    if command == "--list":
        db = AdminSessionLocal()
        admins = db.query(AdminUser).all()
        print("现有管理员列表:")
        for a in admins:
            has_password = "✓" if a.password_hash else "✗ (无密码!)"
            status = "启用" if a.is_active else "禁用"
            print(f"  - {a.username} ({a.role}) [{status}] 密码: {has_password}")
        db.close()
        sys.exit(0)

    if command == "--create":
        username = sys.argv[2] if len(sys.argv) > 2 else "admin"
        password = sys.argv[3] if len(sys.argv) > 3 else None
        create_admin_if_not_exists(username, password)
        sys.exit(0)

    username = command
    password = sys.argv[2] if len(sys.argv) > 2 else None
    reset_admin_password(username, password)
