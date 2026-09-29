#!/usr/bin/env python3
"""
PostgreSQL 兼容性冒烟测试（隔离环境专用，不碰生产库）。

覆盖：
1. init_db() 在 PG 空库上建表 + _auto_migrate 全量跑通
   （含 DATETIME→TIMESTAMP、BOOLEAN DEFAULT 0→FALSE 的方言映射）
2. _auto_migrate 幂等（跑两次不报错）
3. 老库补列路径：在 PG 上建一张"缺列"的旧表，确认补列 SQL 在 PG 下合法
4. JSON 列读写（PG native JSON 返回 dict，不是字符串）
5. Boolean 列读写
6. DateTime 列读写
7. ilike 搜索（优惠券口径）

用法：
    DATABASE_TYPE=postgresql DATABASE_URL=postgresql://... \\
        python scripts/smoke_test_pg_compat.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["DATABASE_TYPE"] = "postgresql"
# DATABASE_URL 由调用方传入（CI service / 本地 PG）
assert os.getenv("DATABASE_URL", "").startswith("postgresql"), \
    "需要 DATABASE_URL=postgresql://..."

os.environ["REDIS_ENABLED"] = "false"

from sqlalchemy import text  # noqa: E402

from backend import database as dbmod  # noqa: E402
import backend.models as models  # noqa: E402


def check(name, cond):
    print(("✓ " if cond else "✗ ") + name)
    if not cond:
        raise SystemExit(f"FAILED: {name}")


def main():
    print("== PG 兼容性冒烟 ==")
    print(f"   目标: {os.environ['DATABASE_URL'].split('@')[-1]}")

    # 1. init_db 全量
    print("\n[1] init_db（create_all + _auto_migrate）...")
    dbmod.init_db()
    db = dbmod.SessionLocal()
    try:
        tables = db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'")).fetchall()
        names = {r[0] for r in tables}
        check("emby_items 表存在", "emby_items" in names)
        check("web_users 表存在", "web_users" in names)
        check(f"表数量合理（{len(names)} 张）", len(names) > 30)

        # DATETIME 映射检查：scan_started_at 在 PG 下必须是 timestamp
        coltype = db.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='emby_libraries' AND column_name='scan_started_at'"
        )).scalar()
        check(f"emby_libraries.scan_started_at 是 timestamp（得 {coltype}）",
              coltype == "timestamp without time zone")

        # BOOLEAN 默认值映射检查
        coldef = db.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name='registration_codes' AND column_name='is_decoy'"
        )).scalar()
        check(f"registration_codes.is_decoy 默认值合法（得 {coldef}）",
              coldef is None or "false" in str(coldef).lower())
    finally:
        db.close()

    # 2. 幂等：再跑一次
    print("\n[2] _auto_migrate 幂等（跑第二次）...")
    dbmod._auto_migrate()
    print("✓ 第二次运行无报错")

    # 3. 老库补列路径：故意删一列再补
    print("\n[3] 老库补列（删列 → _auto_migrate 补回）...")
    db = dbmod.SessionLocal()
    try:
        db.execute(text("ALTER TABLE emby_libraries DROP COLUMN IF EXISTS scan_progress"))
        db.commit()
        dbmod._auto_migrate()
        coltype = db.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='emby_libraries' AND column_name='scan_progress'"
        )).scalar()
        check("scan_progress 补回且类型为 text", coltype == "text")

        # BOOLEAN 补列：删了 is_virtual 再补，验证 DEFAULT FALSE 合法
        db.execute(text("ALTER TABLE emby_libraries DROP COLUMN IF EXISTS is_virtual"))
        db.commit()
        dbmod._auto_migrate()
        coldef = db.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name='emby_libraries' AND column_name='is_virtual'"
        )).scalar()
        check(f"is_virtual 补回且默认值为 false（得 {coldef}）",
              coldef is not None and "false" in str(coldef).lower())

        # DATETIME 映射：删了 scan_started_at 再补，验证 PG 下建成 TIMESTAMP
        #（清单里写的是 DATETIME，PG 没有这个类型）
        db.execute(text("ALTER TABLE emby_libraries DROP COLUMN IF EXISTS scan_started_at"))
        db.commit()
        dbmod._auto_migrate()
        coltype = db.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='emby_libraries' AND column_name='scan_started_at'"
        )).scalar()
        check(f"scan_started_at 补回且类型为 timestamp（得 {coltype}）",
              coltype == "timestamp without time zone")
    finally:
        db.close()

    # 4/5/6. JSON / Boolean / DateTime 读写
    print("\n[4/5/6] JSON / Boolean / DateTime 读写...")
    from datetime import datetime
    db = dbmod.SessionLocal()
    try:
        u = models.WebUser(username="pg_smoke_u", password_hash="x", is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        check("Boolean 写入读取", u.is_active is True)

        # JSON 列：AdminLog.details
        admin = models.AdminUser(username="pg_smoke_admin", password_hash="x")
        db.add(admin)
        db.commit()
        log = models.AdminLog(admin_user_id=admin.id,
                              action="pg_smoke", details={"k": "v", "n": 1})
        db.add(log)
        db.commit()
        db.refresh(log)
        check(f"JSON 列返回 dict（得 {type(log.details).__name__}）",
              isinstance(log.details, dict) and log.details.get("n") == 1)

        # DateTime 列
        check("DateTime 列是 datetime", isinstance(u.created_at, datetime))

        db.delete(log)
        db.delete(admin)
        db.delete(u)
        db.commit()
    finally:
        db.close()

    # 7. ilike 搜索
    print("\n[7] ilike 大小写不敏感搜索...")
    db = dbmod.SessionLocal()
    try:
        c = models.CouponCode(code="PGSMOKEABC", kind="subscription")
        db.add(c)
        db.commit()
        hit = db.query(models.CouponCode).filter(
            models.CouponCode.code.ilike("%pgsmokeabc%")).first()
        check("小写搜大写码能命中", hit is not None and hit.code == "PGSMOKEABC")
        db.delete(c)
        db.commit()
    finally:
        db.close()

    print("\n✓ PG 兼容性冒烟全部通过")


if __name__ == "__main__":
    main()
