#!/usr/bin/env python3
"""分类关联表的实测基准（v2.15.0）：读侧省了多少、写侧多花了多少

「把分类筛选从全表 LIKE 换成关联表 + 索引」这件事，收益在**读**（客户端会反复点筛选、
每次打开筛选菜单），代价在**写**（条目变化时多维护几行）。这个脚本把两头都量出来，
免得只有一句「应该更快」。

跑法：python scripts/benchmark_item_facets.py [条目数]（默认 100000）

测量项：

1. 筛选（两种查询形状）：
   - 只计数：全表 ``genres LIKE '%动作%'`` vs 关联表子查询；
   - 列表页（真实形状）：``ORDER BY sort_name LIMIT 50``；
   并区分**常见取值**（命中约 30% 库）与**少见取值**（命中几十条）。
2. 筛选菜单取值：``SELECT genres``（全表） vs ``SELECT DISTINCT value``（覆盖索引）。
3. 写入代价：ORM 新建条目（钩子开 / 关）——扫描器就是这条路径。
4. 看护周期兜底清理 ``prune_orphans``（全库无孤儿行 = 最坏情况）。
5. 稳定态常数开销：``ensure_ready`` + 取值匹配（含 5000 个取值的最坏情况）。
6. 老库一次性回填吞吐。

只在临时库上造数据，不碰任何现有库。
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bench-facet-secret-0123456789abcdef")
_DB = os.path.join(tempfile.mkdtemp(prefix="bench-facets-"), "bench.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"

from sqlalchemy import event as sa_event  # noqa: E402
from sqlalchemy import insert, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, engine, init_db  # noqa: E402
from backend.emby_server import facets  # noqa: E402
from backend.emby_server import models as em  # noqa: E402

TOTAL = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
GENRES = ("动作", "喜剧", "科幻", "惊悚", "爱情", "冒险", "纪录")
STUDIOS = ("华纳", "环球", "迪士尼", "A24")
COMMON = "动作"          # 命中约 2/7 的库
RARE = "冷门流派"        # 每 5000 条命中 1 条
ROUNDS = 20

init_db()


def timeit(sql: str, rounds: int = ROUNDS) -> float:
    with engine.connect() as conn:
        conn.execute(text(sql)).all()  # 预热
        started = time.perf_counter()
        for _ in range(rounds):
            conn.execute(text(sql)).all()
        return (time.perf_counter() - started) * 1000 / rounds


print(f"=== 造数据：{TOTAL} 条条目（Core 写入，绕过 ORM 钩子，随后由回填统一建关联行）===")
with SessionLocal() as db:
    lib = em.Library(guid="b" * 32, name="基准库", collection_type="movies")
    db.add(lib)
    db.commit()
    lib_id = lib.id


def _row(i: int, library_id: int) -> dict:
    genres = f"{GENRES[i % len(GENRES)]},{GENRES[(i + 3) % len(GENRES)]}"
    if i % 5000 == 0:
        genres += f",{RARE}"
    return {
        "guid": f"bench{i:08d}", "library_id": library_id, "item_type": "movie",
        "name": f"基准片 {i}", "sort_name": f"bench {i:08d}", "genres": genres,
        "studios": STUDIOS[i % len(STUDIOS)],
        "platforms": ("Netflix", "Disney+", "")[i % 3],
        "is_hidden": 0, "production_year": 1990 + (i % 35),
    }


started = time.perf_counter()
with engine.begin() as conn:
    for start in range(0, TOTAL, 5000):
        conn.execute(insert(em.MediaItem.__table__),
                     [_row(i, lib_id) for i in range(start, min(start + 5000, TOTAL))])
insert_items_s = time.perf_counter() - started

print(f"  条目写入 {insert_items_s:.2f}s；关联行由回填建立：", end="")
started = time.perf_counter()
with SessionLocal() as db:
    filled = facets.ensure_backfill(db)
backfill_s = time.perf_counter() - started
with SessionLocal() as db:
    facet_rows = db.execute(text("SELECT COUNT(*) FROM emby_item_facets")).scalar()
    ready = facets.ready(db)
    common_hits = db.execute(text(
        "SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND genres LIKE '%动作%'"
    )).scalar()
    rare_hits = db.execute(text(
        "SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND genres LIKE '%冷门流派%'"
    )).scalar()
print(f"{filled} 条 / {facet_rows} 行，耗时 {backfill_s:.2f}s"
      f"（{TOTAL / max(backfill_s, 1e-6):,.0f} 条/秒）· ready={ready}")
print(f"  命中规模：常见取值 {common_hits} 条（{common_hits / TOTAL:.0%} 库）· "
      f"少见取值 {rare_hits} 条")


def subq(value: str) -> str:
    return (f"id IN (SELECT item_id FROM emby_item_facets "
            f"WHERE kind = 'genre' AND value IN ('{value}'))")


def exists(value: str) -> str:
    return (f"EXISTS (SELECT 1 FROM emby_item_facets f WHERE f.item_id = emby_items.id "
            f"AND f.kind = 'genre' AND f.value IN ('{value}'))")


print(f"\n=== 1. 筛选：只计数（{ROUNDS} 次均值）===")
for label, value in (("常见取值", COMMON), ("少见取值", RARE)):
    like_ms = timeit(f"SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND genres LIKE '%{value}%'")
    sub_ms = timeit(f"SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND {subq(value)}")
    exists_ms = timeit(f"SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND {exists(value)}")
    join_ms = timeit(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT i.id FROM emby_items i "
        f"JOIN emby_item_facets f ON f.item_id = i.id "
        f"WHERE i.is_hidden = 0 AND f.kind = 'genre' AND f.value IN ('{value}'))")
    print(f"  {label}：全表 LIKE {like_ms:7.2f} ms · 关联表 IN {sub_ms:7.2f} ms"
          f" · 关联表 EXISTS {exists_ms:7.2f} ms · JOIN {join_ms:7.2f} ms")

print(f"\n=== 2. 筛选：列表页真实形状（ORDER BY sort_name LIMIT 50，{ROUNDS} 次均值）===")
for label, value in (("常见取值", COMMON), ("少见取值", RARE)):
    like_ms = timeit(
        f"SELECT id, name FROM emby_items WHERE is_hidden = 0 AND genres LIKE '%{value}%' "
        f"ORDER BY sort_name LIMIT 50")
    sub_ms = timeit(
        f"SELECT id, name FROM emby_items WHERE is_hidden = 0 AND {subq(value)} "
        f"ORDER BY sort_name LIMIT 50")
    join_ms = timeit(
        f"SELECT DISTINCT i.id, i.name FROM emby_items i "
        f"JOIN emby_item_facets f ON f.item_id = i.id "
        f"WHERE i.is_hidden = 0 AND f.kind = 'genre' AND f.value IN ('{value}') "
        f"ORDER BY i.sort_name LIMIT 50")
    print(f"  {label}：全表 LIKE {like_ms:7.2f} ms · 关联表 IN {sub_ms:7.2f} ms"
          f" · JOIN {join_ms:7.2f} ms")

print(f"\n=== 3. 筛选菜单取值（{ROUNDS} 次均值）===")
legacy_menu = timeit("SELECT genres FROM emby_items WHERE is_hidden = 0")
indexed_menu = timeit("SELECT DISTINCT value FROM emby_item_facets WHERE kind = 'genre'")
print(f"  读全库文本列（旧）    : {legacy_menu:8.2f} ms")
print(f"  覆盖索引 DISTINCT（新）: {indexed_menu:8.2f} ms"
      f"   → {legacy_menu / max(indexed_menu, 1e-6):.1f}x")

print("\n=== 4. 写入代价：ORM 新建条目（扫描器路径，钩子开 / 关）===")
WRITE_N = 5_000


def orm_write(tag: str) -> float:
    with SessionLocal() as db:
        started_at = time.perf_counter()
        db.add_all([
            em.MediaItem(
                guid=f"{tag}{i:08d}", library_id=lib_id, item_type="movie",
                name=f"ORM 片 {i}", sort_name=f"{tag} {i:08d}",
                genres=GENRES[i % len(GENRES)], studios=STUDIOS[i % len(STUDIOS)],
                platforms="", is_hidden=0, production_year=2020 + (i % 5),
            )
            for i in range(WRITE_N)
        ])
        db.commit()
        return time.perf_counter() - started_at


sa_event.remove(Session, "before_flush", facets._facets_before_flush)
sa_event.remove(Session, "after_flush", facets._facets_after_flush)
try:
    without_hook = orm_write("nohook")
finally:
    sa_event.listen(Session, "before_flush", facets._facets_before_flush)
    sa_event.listen(Session, "after_flush", facets._facets_after_flush)
with_hook = orm_write("withhook")
with SessionLocal() as db:
    db.execute(text("DELETE FROM emby_items WHERE item_type = 'movie' AND name LIKE 'ORM 片%'"))
    db.commit()

print(f"  钩子关（旧行为）      : {without_hook * 1000:8.0f} ms / {WRITE_N} 条"
      f"（{WRITE_N / max(without_hook, 1e-9):,.0f} 条/秒）")
print(f"  钩子开（新行为）      : {with_hook * 1000:8.0f} ms / {WRITE_N} 条"
      f"（{WRITE_N / max(with_hook, 1e-9):,.0f} 条/秒）")
print(f"  → 每条多花 {(with_hook - without_hook) * 1e6 / WRITE_N:.0f} µs"
      f"（{with_hook / max(without_hook, 1e-9):.2f}x）")

print("\n=== 5. 看护周期的兜底清理 prune_orphans（无孤儿行 = 最坏情况）===")
samples = []
removed = 0
for _ in range(3):
    with SessionLocal() as db:
        started_at = time.perf_counter()
        removed = facets.prune_orphans(db)
        samples.append((time.perf_counter() - started_at) * 1000)
print(f"  清理 {removed} 行，耗时 {statistics.median(samples):.1f} ms"
      f"（默认每 MAINTENANCE_INTERVAL=600s 一次）")

print("\n=== 6. 稳定态：一次筛选请求多花的常数开销 ===")
with SessionLocal() as db:
    started_at = time.perf_counter()
    for _ in range(ROUNDS):
        facets.ensure_ready(db)
        facets.candidate_condition(facets.KIND_GENRE, [COMMON], db)
    per_call = (time.perf_counter() - started_at) * 1000 / ROUNDS
    values = facets.distinct_values(db, facets.KIND_GENRE)
print(f"  ensure_ready + 取值匹配（本库 {len(values)} 个取值）: {per_call:.2f} ms/次")
# 最坏情况：取值特别多（真实站点几千个流派/工作室不罕见）
facets._values_cache[facets.KIND_STUDIO] = (
    time.monotonic(), tuple(f"工作室 {i}" for i in range(5000))
)
with SessionLocal() as db:
    started_at = time.perf_counter()
    for _ in range(ROUNDS):
        facets.match_values(db, facets.KIND_STUDIO, ["工作室 42"])
    worst = (time.perf_counter() - started_at) * 1000 / ROUNDS
print(f"  取值 5000 个时的名称匹配（最坏情况）: {worst:.2f} ms/次（纯内存字符串比较）")

print("\n=== 参考：旧口径的代价随库增长（全表扫描）===")
_list_sql = (f"SELECT id, name FROM emby_items WHERE is_hidden = 0 "
             f"AND genres LIKE '%{COMMON}%' ORDER BY sort_name LIMIT 50")
_list_ms = timeit(_list_sql)
for factor, label in ((1, "当前"), (2, "翻倍"), (5, "五倍")):
    print(f"  {label:>4}（约 {TOTAL * factor:,} 条）: 列表页约 {_list_ms * factor:7.1f} ms/次")
print("\n注：关联表路径的耗时随**命中条数**增长，与库总量基本无关。")
