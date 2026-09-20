#!/usr/bin/env python3
"""创建 / 升级管理后台账号（当前统一后端 EM 的 `web_users`）

管理后台与门户**共用同一套账号**：`web_users.is_staff = true` 才是管理员，
登录入口是 `POST /api/admin/auth/login`（也可以先在门户登录，再从 `/admin/` 免登进去）。

新库里一个账号都没有，而且**第一个注册的用户不会被自动提升为管理员**（有意的安全设计），
所以自建部署的「第一个管理员」用它来造。库由 `DATABASE_URL` 决定
（默认 `sqlite:///./royalbot_unified.db`）。

用法::

    python3 scripts/create_admin.py                            # 创建/升级 admin，随机强密码并打印
    python3 scripts/create_admin.py -u boss -p 'Passw0rd!23'    # 指定账号与密码
    python3 scripts/create_admin.py -u boss --no-password       # 只把已有账号升级为管理员，不改密码

幂等：账号已存在时只升级权限（默认会把密码重置为新的随机密码，`--no-password` 则完全不动密码），
同时补齐 Emby 客户端凭据（门户密码即播放密码）。退出码 0 = 账号已就绪。
"""
from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 不在 .env 里也要能跑：默认单机 SQLite（与 serve.py / deploy_check.py 同口径）
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("DATABASE_URL", "sqlite:///./royalbot_unified.db")

# 与门户注册口径一致（backend/api/emby_portal.py）
PASSWORD_MIN_LENGTH = 6
PASSWORD_RECOMMENDED_LENGTH = 12


class AdminAccountError(RuntimeError):
    """参数或状态不成立，直接给用户看的错误。"""


def generate_password(length: int = 16) -> str:
    """生成同时含大小写、数字与符号的随机密码"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    required = (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*-_=+")
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in group for c in pwd) for group in required):
            return pwd


def validate_username(username: str) -> str:
    """用户名规则与门户注册完全一致，避免造出「后台能建、门户登不上」的账号"""
    from backend.api.emby_portal import USERNAME_RE

    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise AdminAccountError(
            f"用户名不合法：{username!r}（只允许字母 / 数字 / 下划线，长度 3-32，与门户注册一致）"
        )
    return username


def check_password_strength(password: str) -> str | None:
    """返回警告文案（密码够强时为 None）；过短直接拒绝"""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise AdminAccountError(f"密码太短：至少 {PASSWORD_MIN_LENGTH} 位（与门户注册一致）")
    if len(password) < PASSWORD_RECOMMENDED_LENGTH:
        return f"密码短于 {PASSWORD_RECOMMENDED_LENGTH} 位，建议用更长的随机密码"
    return None


def upsert_admin(db, username: str, password: str | None = None,
                 reset_password: bool = False) -> tuple[object, bool, str | None]:
    """创建或升级管理员账号，返回 ``(user, created, applied_password)``

    - 账号不存在：必须给密码（``password`` 或 ``reset_password=True`` 自动生成），否则报错；
    - 账号已存在：只升级 ``is_staff`` / ``is_active``；``password`` 给了就改，
      ``reset_password=True`` 则重置为新的随机密码，两者都没有则**不动密码**；
    - 无论哪条路径，都会补齐 Emby 客户端凭据（``emby_username``）；
      设置了密码时同步 ``emby_password``，门户密码与播放密码保持一致。

    ``applied_password`` 是本次真正写进库的密码（没有改密码时为 None）。
    """
    from backend import models
    from backend.emby_server.auth import ensure_emby_credentials
    from backend.security import hash_password

    applied: str | None = password
    if applied:
        check_password_strength(applied)

    user = db.query(models.WebUser).filter(models.WebUser.username == username).first()
    created = user is None

    if created:
        if not applied:
            applied = generate_password() if reset_password else None
        if not applied:
            raise AdminAccountError("账号不存在：新建管理员必须给密码（-p），或让它自动生成随机密码")
        user = models.WebUser(
            username=username,
            password_hash=hash_password(applied),
            is_staff=True,
            is_active=True,
        )
        db.add(user)
    else:
        if reset_password and not applied:
            applied = generate_password()
        user.is_staff = True
        user.is_active = True
        if applied:
            user.password_hash = hash_password(applied)

    db.commit()
    db.refresh(user)
    # 给了密码就把 Emby 播放密码一起同步（没给则只保证 emby_username 存在）
    ensure_emby_credentials(db, user, password=applied)
    db.refresh(user)
    return user, created, applied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="创建 / 升级管理后台账号（web_users.is_staff = true）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="库由环境变量 DATABASE_URL 决定，默认 sqlite:///./royalbot_unified.db",
    )
    parser.add_argument("-u", "--username", default="admin", help="账号名（默认 admin）")
    parser.add_argument("-p", "--password", default=None,
                        help="密码；不传则账号已存在时不改密码，不存在时自动生成随机密码")
    parser.add_argument("--no-password", action="store_true",
                        help="完全不动密码（只升级权限，账号必须已存在）")
    parser.add_argument("--dry-run", action="store_true", help="只检查参数与账号状态，不写库")
    args = parser.parse_args()

    if args.no_password and args.password:
        parser.error("--no-password 与 -p 不能同时使用")

    from backend import models  # noqa: F401 — 保证建表时注册全部模型
    from backend.database import DATABASE_TYPE, DATABASE_URL, SessionLocal, init_db

    try:
        username = validate_username(args.username)
        password = args.password
        if password:
            warn = check_password_strength(password)
            if warn:
                print(f"⚠️  {warn}")
    except AdminAccountError as exc:
        print(f"❌ {exc}")
        return 1

    if args.dry_run:
        init_db()
        db = SessionLocal()
        try:
            exists = db.query(models.WebUser).filter(
                models.WebUser.username == username).first() is not None
        finally:
            db.close()
        print(f"（dry-run）账号 {username!r} {'已存在，会被升级为管理员' if exists else '不存在，会新建'}；"
              f"库：{DATABASE_TYPE} ({DATABASE_URL})")
        return 0

    init_db()
    db = SessionLocal()
    try:
        user, created, applied = upsert_admin(
            db, username, password=password, reset_password=not args.no_password,
        )
        # 先把要展示的字段取出来（会话关掉后 ORM 实例会 detached，不能再去读属性）
        summary = {
            "username": user.username,
            "id": user.id,
            "is_staff": bool(user.is_staff),
            "is_active": bool(user.is_active),
            "emby_username": user.emby_username,
        }
    except AdminAccountError as exc:
        print(f"❌ {exc}")
        return 1
    finally:
        db.close()

    action = "已创建" if created else "已升级为管理员"
    print(f"\n✅ 管理后台账号{action}")
    print(f"   用户名   : {summary['username']}")
    if applied:
        suffix = "" if created else "   （本次已重置）"
        print(f"   密码     : {applied}{suffix}")
        print("              ⚠️ 仅本次打印，请登录后尽快修改（门户「个人中心」或后台右上角）")
    else:
        print("   密码     : 未改动（--no-password），沿用原密码")
    print(f"   用户 id  : {summary['id']}（is_staff={summary['is_staff']}, "
          f"is_active={summary['is_active']}）")
    print(f"   数据库   : {DATABASE_TYPE} ({DATABASE_URL})")
    if summary["emby_username"]:
        print(f"   Emby 账号: {summary['emby_username']}（播放密码与门户密码一致）")
    print("\n   登录入口 : 门户 / 登录后后台免登进 /admin/，或直接到 /admin/ 用上面的账号密码登录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
