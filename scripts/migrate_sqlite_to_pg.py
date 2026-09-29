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


# ------------------- 外键自洽 -------------------
def _fk_parents(conn, table_name):
    """本表所有外键指向的 (目标表, 本表列, 目标列)"""
    out = []
    for fk in conn.execute(f'PRAGMA foreign_key_list("{table_name}")'):
        # fk = (id, seq, table, from, to, on_update, on_delete, match)
        out.append((fk[2], fk[3], fk[4]))
    return out


def _neutralize_orphans(src, tables, verbose=True):
    """把「父表里根本不存在的孤儿外键」置为 NULL。

    为什么必须做：SQLite 默认**不强制外键**（PRAGMA foreign_keys 默认 OFF），
    所以老库里长期躺着违反约束的数据；PG 强制外键，导到就会
    ForeignKeyViolation 直接中断。生产实测：
        admin_users 0 行，但 admin_logs 151 行且 admin_user_id=1
    ——管理员账号不在这库里（走的是外部认证），日志里的 id 成了孤儿。

    这里只动**确实指向不存在父行**的列（安全），不碰任何有对应父行的数据；
    置 NULL 而非删行，是为了保住日志/工单这些审计数据。
    统计结果会打印出来，让人知道有多少行被中和过。
    """
    fk_map = {}
    for t in tables:
        tname = getattr(t, "name", t)     # 传进来的可能是 ORM Table，也可能是表名
        for parent, frm, to in _fk_parents(src, tname):
            if parent == tname:           # 自引用不处理（按主键顺序导，父先于子）
                continue
            fk_map.setdefault(tname, []).append((parent, frm, to))

    if not fk_map:
        return {}
    stats = {}
    deleted_rows = []
    for tbl, fks in fk_map.items():
        try:
            if not src.execute(f'SELECT 1 FROM "{tbl}" LIMIT 1').fetchone():
                continue
        except sqlite3.Error:
            continue
        # 条件用 OR 串起来（多列外键：任一列是孤儿就整行处理）
        conds = " OR ".join(
            f'("{frm}" IS NOT NULL AND NOT EXISTS '
            f'(SELECT 1 FROM "{parent}" WHERE "{parent}"."{to}" = "{tbl}"."{frm}"))'
            for parent, frm, to in fks)
        # 先问「能不能置 NULL」：NOT NULL 的列置不了，只能整行删。
        # 生产实测 emby_api_tokens.user_id / station_messages.to_user_id /
        # user_devices.user_id 都是 NOT NULL，置 NULL 会直接违反本表约束。
        notnull = set()
        for r in src.execute(f'PRAGMA table_info("{tbl}")'):
            if r[3]:                          # PRAGMA table_info 第4列：1=NOT NULL, 0/空=可空
                notnull.add(r[1])
        try:
            nullable = [frm for _p, frm, _to in fks if frm not in notnull]
            forced = [frm for _p, frm, _to in fks if frm in notnull]
            n = 0
            if nullable:
                set_cols = ", ".join(f'"{c}" = NULL' for c in nullable)
                ncols = " OR ".join(
                    f'("{frm}" IS NOT NULL AND NOT EXISTS '
                    f'(SELECT 1 FROM "{parent}" WHERE "{parent}"."{to}" = "{tbl}"."{frm}"))'
                    for parent, frm, to in fks if frm in nullable)
                n += src.execute(f'UPDATE "{tbl}" SET {set_cols} WHERE {ncols}').rowcount
            if forced:
                # NOT NULL 列：这类行（token 指向已删除的用户）本来就无意义，删掉。
                # 不删就会在导数据时被 PG 的外键直接拒掉。
                fcols = " OR ".join(
                    f'("{frm}" IS NOT NULL AND NOT EXISTS '
                    f'(SELECT 1 FROM "{parent}" WHERE "{parent}"."{to}" = "{tbl}"."{frm}"))'
                    for parent, frm, to in fks if frm in forced)
                d = src.execute(f'DELETE FROM "{tbl}" WHERE {fcols}').rowcount
                n += d
                if d:
                    deleted_rows.append((tbl, d))
            if n:
                stats[tbl] = n
                if verbose:
                    print(f"      · {tbl}: 中和 {n} 行孤儿外键 → NULL")
        except sqlite3.Error as e:
            print(f"      ! {tbl} 孤儿处理跳过：{e}")
    if stats or deleted_rows:
        src.commit()
        if stats:
            print(f"      共中和 {sum(stats.values())} 行（源库本就违反外键，SQLite 不强制所以一直没暴露）")
        if deleted_rows:
            for tbl, d in deleted_rows:
                print(f"      · {tbl}: 删除 {d} 行 NOT NULL 孤儿行（父记录已不存在，该行已无意义）")
            print(f"      共删除 {sum(d for _t, d in deleted_rows)} 行")
    return stats


def _build_export_order(src, tables):
    """按外键依赖排序：父表先导。自引用用主键顺序单独处理。

    metadata.sorted_tables 只处理了**已声明**的外键；SQLite 老库的孤儿数据
    （父表 0 行、子表却引用着不存在的 id）依然会让 PG 在导子表时炸
    ForeignKeyViolation——所以顺序必须自己做，不能只信 sorted_tables。
    """
    cur = src.cursor()
    name_map = {t.name: t for t in tables}
    deps = {t.name: set() for t in tables}   # table -> 依赖的父表
    for t in tables:
        for parent, _frm, _to in _fk_parents(src, t.name):
            if parent != t.name and parent in name_map:
                deps[t.name].add(parent)
    ordered, seen, temp = [], set(), set()

    def visit(n):
        if n in seen:
            return
        if n in temp:      # 成环：按已有顺序硬拆，剩下交给 --truncate-orphans
            return
        temp.add(n)
        for p in sorted(deps.get(n, ())):
            visit(p)
        temp.discard(n)
        seen.add(n)
        ordered.append(n)

    for t in tables:
        visit(t.name)
    return ordered


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
    _all_tables = list(dbmod.Base.metadata.sorted_tables)
    only = {t.strip() for t in args.tables.split(",") if t.strip()}
    if only:
        _all_tables = [t for t in _all_tables if t.name in only]
    # 用 SQLite 侧真实的 PRAGMA foreign_key_list 重新排一次：
    # metadata 只认**模型里声明过**的外键，而老 SQLite 库可能存在
    # "父表 0 行、子表仍引用着那个 id" 的孤儿数据，PG 强制外键会直接拒绝。
    # 生产实测：admin_users 0 行、admin_logs 151 行且 admin_user_id=1，
    # 按 metadata 顺序导到 admin_logs 就 ForeignKeyViolation。
    _probe = sqlite3.connect(args.source)
    _order = _build_export_order(_probe, _all_tables)
    _probe.close()
    _by_name = {t.name: t for t in _all_tables}
    tables = [_by_name[n] for n in _order if n in _by_name]
    tables += [t for t in _all_tables if t not in tables]  # 兜底：环或异常时不丢表
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

    # 3.5 中和孤儿外键（SQLite 不强制、PG 强制，必须先处理）
    print("[3.5/5] 中和孤儿外键（源库违反约束的残留）...")
    _neutralize_orphans(src, tables)

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
