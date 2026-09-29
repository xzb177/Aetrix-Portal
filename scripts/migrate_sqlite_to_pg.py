#!/usr/bin/env python3
"""
Aetrix-Portal：SQLite → PostgreSQL 一次性全量迁移脚本。

设计原则：
- 表结构永远以 ``backend.models`` / ``backend.emby_server.models`` 的
  SQLAlchemy metadata 为准（``init_db()`` 的 create_all + _auto_migrate），
  不手写 DDL——模型变了脚本不用改。
- 按 metadata 的外键依赖顺序导表，不会违反外键约束。
- 校验：每张表导完比对源/目标行数，对不上就报错退出（fail-closed）。
- 幂等：``--clean`` 会先 TRUNCATE ... CASCADE 清空目标库再导；
  不带 ``--clean`` 时目标表必须为空（有一行数据就拒绝，避免主键冲突）。

用法：
    # 1. 目标 PG 先建好空库（compose 里已有 postgres 服务）
    # 2. 停机（迁移期间不能有新写入，否则丢数据）
    python scripts/migrate_sqlite_to_pg.py \\
        --source /data/aetrix_unified.db \\
        --target postgresql://aetrix:SECRET@127.0.0.1:5432/aetrix \\
        --clean

注意：
- 只做一次性全量迁移，不做增量同步。生产切换前必须停机。
- 密码不要写进命令行历史：用环境变量 PG_TARGET_URL 或 --target 传。
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from decimal import Decimal

BATCH_SIZE = 2000


def parse_args():
    p = argparse.ArgumentParser(description="SQLite → PostgreSQL 全量迁移")
    p.add_argument("--source", required=True, help="SQLite 数据库文件路径")
    p.add_argument(
        "--target",
        default=os.getenv("PG_TARGET_URL"),
        help="PostgreSQL 连接串（默认读 PG_TARGET_URL 环境变量）",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="先清空目标库所有表再导（TRUNCATE ... CASCADE）",
    )
    p.add_argument(
        "--tables",
        default="",
        help="只导这些表（逗号分隔，默认全部）",
    )
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = p.parse_args()
    if not args.target:
        p.error("--target 未给且 PG_TARGET_URL 环境变量为空")
    if not os.path.isfile(args.source):
        p.error(f"源库文件不存在: {args.source}")
    return args


# ---------------------------------------------------------------------------
# 值转换：SQLite 存的是弱类型（TEXT/INTEGER/REAL），PG 是强类型。
# 统一转成 Python 原生值，再交给 SQLAlchemy 的列类型去编码。
# ---------------------------------------------------------------------------

def _convert_value(col_type, value):
    if value is None:
        return None
    type_name = type(col_type).__name__
    if type_name == "Boolean":
        return bool(value)
    if type_name == "DateTime":
        if isinstance(value, datetime):
            return value
        # SQLite 存 "YYYY-MM-DD HH:MM:SS.ffffff" 或 "YYYY-MM-DD HH:MM:SS"
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except (ValueError, TypeError):
                continue
        raise ValueError(f"无法解析 datetime: {value!r}")
    if type_name == "JSON":
        if isinstance(value, str):
            return json.loads(value)
        return value
    if type_name == "Numeric":
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if type_name in ("Integer", "BigInteger"):
        return int(value)
    if type_name == "Float":
        return float(value)
    return value


def _convert_row(table, col_names, row):
    """把 sqlite3 的一行转成 {列名: Python值}。"""
    out = {}
    for name, value in zip(col_names, row):
        col = table.columns.get(name)
        if col is None:
            # 源库有多余列（模型已删）：跳过，不导
            continue
        out[name] = _convert_value(col.type, value)
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # PG 引擎：必须先设环境变量再 import backend.database（模块 import 期读 env）
    os.environ["DATABASE_TYPE"] = "postgresql"
    os.environ["DATABASE_URL"] = args.target
    # 迁移脚本不需要 Redis
    os.environ["REDIS_ENABLED"] = "false"
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    from sqlalchemy import text as sa_text
    from backend import database as dbmod

    print(f"源库: {args.source}")
    print(f"目标: {args.target.split('@')[-1]}")  # 不打印密码

    # 1. 目标库建表（create_all + _auto_migrate，幂等）
    print("\n[1/5] 目标库建表（init_db）...")
    dbmod.init_db()

    # 2. 按外键依赖顺序拿表清单
    tables = list(dbmod.Base.metadata.sorted_tables)
    only = {t.strip() for t in args.tables.split(",") if t.strip()}
    if only:
        tables = [t for t in tables if t.name in only]
    print(f"[2/5] 共 {len(tables)} 张表（按外键依赖排序）")

    src = sqlite3.connect(args.source)
    src.row_factory = sqlite3.Row
    src_cur = src.cursor()
    src_tables = {r[0] for r in src_cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    engine = dbmod.engine

    # 3. --clean：先清空目标表（反向依赖顺序 + CASCADE）
    if args.clean:
        print("[3/5] --clean：清空目标库...")
        with engine.begin() as conn:
            for table in reversed(tables):
                conn.execute(sa_text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
        print("      已清空")
    else:
        print("[3/5] 跳过清空（目标表必须为空）")
        for table in tables:
            if table.name not in src_tables:
                continue
            with engine.begin() as conn:
                n = conn.execute(sa_text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
            if n:
                print(f"      ✗ 目标表 {table.name} 非空（{n} 行），请加 --clean 或先手动清空")
                sys.exit(2)

    # 4. 逐表导数据
    print(f"[4/5] 导数据（batch={args.batch_size}）...")
    total_src, total_dst = 0, 0
    failed = []
    for table in tables:
        if table.name not in src_tables:
            print(f"      - {table.name}: 源库无此表，跳过")
            continue
        col_names = [r[1] for r in src_cur.execute(f'PRAGMA table_info("{table.name}")')]
        src_n = src_cur.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()[0]
        total_src += src_n
        if src_n == 0:
            print(f"      - {table.name}: 0 行，跳过")
            continue
        ins = table.insert()
        done = 0
        # 自引用外键（如 emby_items.parent_id → emby_items.id）：按单调递增的
        # 整数主键排序后导，父行一定先于子行（扫描入库时父先建，id 更小）。
        pk_cols = [c.name for c in table.primary_key.columns]
        order_by = ""
        if len(pk_cols) == 1 and type(table.columns[pk_cols[0]].type).__name__ in ("Integer", "BigInteger"):
            order_by = f' ORDER BY "{pk_cols[0]}"'
        with engine.begin() as conn:
            cur = src_cur.execute(f'SELECT * FROM "{table.name}"{order_by}')
            batch = []
            for row in cur:
                batch.append(_convert_row(table, col_names, tuple(row)))
                if len(batch) >= args.batch_size:
                    conn.execute(ins, batch)
                    done += len(batch)
                    batch = []
                    print(f"      … {table.name}: {done}/{src_n}", end="\r")
            if batch:
                conn.execute(ins, batch)
                done += len(batch)
        # 行数校验
        with engine.begin() as conn:
            dst_n = conn.execute(sa_text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
        total_dst += dst_n
        mark = "✓" if dst_n == src_n else "✗"
        print(f"      {mark} {table.name}: {src_n} → {dst_n}")
        if dst_n != src_n:
            failed.append(table.name)

    # 5. 重置 PG 自增序列（SERIAL/IDENTITY），否则新插入会主键冲突。
    # 表名/列名来自 metadata（可信来源）直接拼 SQL；pg_get_serial_sequence
    # 拿不到序列名的表（如自然主键）返回 NULL，跳过。
    print("[5/5] 重置自增序列...")
    with engine.begin() as conn:
        for table in tables:
            pk_cols = [c.name for c in table.primary_key.columns]
            if len(pk_cols) != 1:
                continue
            pk = table.columns[pk_cols[0]]
            if type(pk.type).__name__ not in ("Integer", "BigInteger"):
                continue
            seq = conn.execute(sa_text(
                f"SELECT pg_get_serial_sequence('\"{table.name}\"', '{pk.name}')")).scalar()
            if seq:
                conn.execute(sa_text(
                    f"SELECT setval('{seq}', COALESCE((SELECT MAX(\"{pk.name}\") "
                    f"FROM \"{table.name}\"), 1), true)"))

    print(f"\n源库总行数: {total_src}, 目标库总行数: {total_dst}")
    if failed:
        print(f"✗ 以下表行数不一致: {failed}")
        sys.exit(1)
    print("✓ 迁移完成，行数全部一致")


if __name__ == "__main__":
    main()
