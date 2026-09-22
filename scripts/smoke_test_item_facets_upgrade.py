#!/usr/bin/env python3
"""分类关联表的老库升级演练（回填中断续跑 / 降级口径 / 读请求补块）

`smoke_test_item_facets.py` 守的是「功能与索引证据」，这条守的是**升级现场**——
老库刚升级上来时关联表是空的，这一刻正是故障最容易咬人的时候：

1. **降级口径**：还没回填完时筛选走旧路径 `ILIKE '%x%'`，结果集必须与升级前逐条一致
   （`ensure_ready` 的冷却窗口正好可以稳定地把路径钉在降级分支上）；
2. **回填中途被打断**（进程被杀 / 写库报错）：已提交的块保留、水位停在块边界、
   不会把自己误判成「已能代表全库」；
3. **换个 Session 接着跑**（等价于重启）：补齐、幂等、关联行与条目列逐行一致，
   不留重复行、不留孤儿行；
4. **回填是按块提交的**：每块不超过预算（内存有界），冷却窗口内的并发请求
   不会一起抢写锁，而补块过程本身不影响这次筛选的正确性。

用法：python scripts/smoke_test_item_facets_upgrade.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

from sqlalchemy import or_, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import backend.database as database  # noqa: E402
from backend.database import engine  # noqa: E402
database.init_db()
from backend.emby_server import facets  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server.api import _facet_or_legacy  # noqa: E402

Session = sessionmaker(bind=engine)

FAILED = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(label)


# 老库的行：含「包含关系」「重复取值」「空值」「多余空格」「尾随逗号」
LEGACY_ROWS = [
    ("老片 A", "动作,冒险", "华纳", "4K", "Netflix"),
    ("老片 B", "动作", "华纳,环球", "", "Netflix"),
    ("老片 C", "Action-Adventure", "A24", "杜比", ""),
    ("老片 D", "纪录", "国家地理", "", "Disney+"),
    ("老片 E", "", "", "", ""),                      # 完全没有分类值
    ("老片 F", "动作,动作", " 华纳 ", "4K,4K", ""),   # 重复取值 / 带空格
    ("老片 G", "喜剧,", "", "", ""),                  # 尾随逗号
]

# 客户端一次可以传多个分类名，所以探测器里既有单个名字也有组合
PROBES = [
    (facets.KIND_GENRE, em.MediaItem.genres, ["动作"]),
    (facets.KIND_GENRE, em.MediaItem.genres, ["动作", "冒险"]),
    (facets.KIND_GENRE, em.MediaItem.genres, ["action"]),      # 大小写不敏感
    (facets.KIND_GENRE, em.MediaItem.genres, ["Action-Adventure"]),
    (facets.KIND_GENRE, em.MediaItem.genres, ["不存在流派"]),
    (facets.KIND_STUDIO, em.MediaItem.studios, ["华纳"]),
    (facets.KIND_STUDIO, em.MediaItem.studios, ["环"]),
]


SEEDED = {"n": 0}


def seed_legacy_db(count: int = 0, include_base: bool = True) -> None:
    """建一个「升级上来」的库：条目用 Core 写入（绕过 ORM 钩子），关联表是空的"""
    with Session() as db:
        lib = db.query(em.Library).filter(em.Library.guid == "lib-upgrade").first()
        if lib is None:
            lib = em.Library(guid="lib-upgrade", name="升级演练库", collection_type="movies")
            db.add(lib)
            db.commit()
            db.refresh(lib)
        rows = list(LEGACY_ROWS) if include_base else []
        for i in range(count):
            rows.append((f"批量片 {i:03d}", "动作" if i % 2 else "喜剧", "华纳", "", ""))
        for name, genres, studios, tags, platforms in rows:
            SEEDED["n"] += 1
            db.execute(text(
                "INSERT INTO emby_items (guid, library_id, item_type, name, sort_name, genres, "
                "studios, tags, platforms, is_hidden, production_year) "
                "VALUES (:g, :lib, 'movie', :n, :n2, :ge, :st, :tg, :pf, 0, 2020)"
            ), {"g": f"g-legacy-{SEEDED['n']}", "lib": lib.id, "n": name,
                "n2": name.lower(), "ge": genres, "st": studios, "tg": tags, "pf": platforms})
        db.commit()
    facets.invalidate_values_cache()   # Core 写入走不到钩子：取值缓存要手工失效


def pin_cooldown() -> None:
    """把冷却窗口钉住：让 `ensure_ready` 稳定地返回 False（本次筛选走降级路径）

    真实场景里这就是「上一个请求刚补过块、还没到下次尝试时间」的时刻。
    """
    facets._last_filter_attempt = time.monotonic()


def ids_via_api(column, kind, names) -> set:
    """生产路径：关联表可用就走索引，没回填完就退回旧 LIKE"""
    with Session() as db:
        cond = _facet_or_legacy(column, kind, names, db)
        if cond is None:
            return set()
        return {int(i) for (i,) in db.query(em.MediaItem.id).filter(cond).all()}


def ids_via_legacy(column, names) -> set:
    """升级前的口径：逗号文本列上的 ILIKE '%x%'（独立重算，不复用生产代码）"""
    with Session() as db:
        cond = or_(*[column.ilike(f"%{name}%") for name in names])
        return {int(i) for (i,) in db.query(em.MediaItem.id).filter(cond).all()}


def all_item_ids() -> set:
    with Session() as db:
        return {int(i) for (i,) in db.query(em.MediaItem.id).all()}


def facet_row_set() -> set:
    with Session() as db:
        return {
            (int(item_id), kind, value)
            for item_id, kind, value in db.execute(
                text("SELECT item_id, kind, value FROM emby_item_facets")
            ).all()
        }


def expected_row_set() -> set:
    """按条目当前列值应有的关联行（用生产的解析函数，测试不自己实现一遍解析）"""
    with Session() as db:
        return {
            (int(item.id), kind, value)
            for item in db.query(em.MediaItem).all()
            for kind, values in facets.values_of(item).items()
            for value in values
        }


def watermark() -> int:
    with Session() as db:
        return facets._watermark(db)


def assert_paths_agree(stage: str, expect_index: bool) -> None:
    """两条路径的结果集合必须一致；同时确认这次真的走了预期的那条路"""
    with Session() as db:
        using_index = facets.ready(db)
    check(f"[{stage}] 走的是{'索引' if using_index else '降级'}路径",
          using_index is expect_index, f"ready={using_index}")
    for kind, column, names in PROBES:
        got = ids_via_api(column, kind, names)
        want = ids_via_legacy(column, names)
        check(f"[{stage}] 「{'|'.join(names)}」筛选结果与旧口径一致", got == want,
              f"新={len(got)} 旧={len(want)}")


# ==================== 1. 升级现场：关联表是空的，筛选走降级 ====================
print("=== 1. 老库刚升级上来（关联表为空，筛选降级） ===")
seed_legacy_db()

with Session() as db:
    first = facets.summary(db)
check("老库条目的分类值都在文本列里、关联表还没有行",
      first["by_kind"] == {} and first["ready"] is False, f"summary={first}")

pin_cooldown()
assert_paths_agree("未回填", expect_index=False)
check("降级分支不会顺手把整库补掉（本次请求只是读）", watermark() == 0, f"水位={watermark()}")


# ==================== 2. 回填中途被打断 ====================
print("\n=== 2. 回填中途被打断（模拟进程被杀 / 写库报错） ===")
BATCH = 3
real_sync = facets.sync_items
seen = {"n": 0}


def flaky_sync(db, items):
    seen["n"] += 1
    if seen["n"] == 2:            # 第 2 块写到一半就“死掉”（第 1 块已提交）
        raise RuntimeError("模拟进程被杀")
    return real_sync(db, items)


facets.sync_items = flaky_sync
failure = ""
try:
    with Session() as db:
        facets.ensure_backfill(db, batch_size=BATCH, commit=True)
except Exception as exc:  # noqa: BLE001 — 这里就是要看到异常往上冒
    failure = type(exc).__name__
finally:
    facets.sync_items = real_sync

check("回填中途真的断了（异常向上抛出，不被吞掉）", failure == "RuntimeError",
      f"异常={failure or '（没有抛出）'} sync 调用={seen['n']} 次")
check("断点前的块已提交、水位停在块边界", watermark() == BATCH,
      f"水位={watermark()} 期望={BATCH}")
with Session() as db:
    first_chunk = {
        int(i) for (i,) in db.query(em.MediaItem.id).order_by(em.MediaItem.id).limit(BATCH).all()
    }
covered = {item_id for item_id, _k, _v in facet_row_set()}
check("断点前的条目有行、断点后的条目还没有", covered == first_chunk,
      f"有行的条目={sorted(covered)} 第一块={sorted(first_chunk)}")
check("此时仍不算「可代表全库」（不会被误判成回填完）", facets.ready(Session()) is False,
      f"水位={watermark()} 最新 id={max(all_item_ids())}")

# 断点处筛选仍然正确（冷却期内走降级路径）
pin_cooldown()
assert_paths_agree("回填一半", expect_index=False)

# 换个 Session 接着跑：等价于进程重启后继续
with Session() as db:
    resumed = facets.ensure_backfill(db, batch_size=BATCH)
    done = facets.ready(db)
check("重启后接着回填完成", done is True, f"本次处理 {resumed} 条")
check("最终水位追上最新条目", watermark() == max(all_item_ids()), f"水位={watermark()}")


# ==================== 3. 回填后的不变量与口径 ====================
print("\n=== 3. 回填后的不变量 ===")
check("关联行与条目列逐行一致（无重复、无遗漏、无孤儿）",
      facet_row_set() == expected_row_set(),
      f"实际 {len(facet_row_set())} 行 期望 {len(expected_row_set())} 行")

with Session() as db:
    orphans = facets.orphan_count(db)
    pruned = facets.prune_orphans(db)
    again = facets.ensure_backfill(db)
check("没有指向不存在条目的孤儿行", orphans == 0 and pruned == 0,
      f"孤儿={orphans} 清理={pruned}")
check("已补齐时再回填不做事（幂等）", again == 0, f"处理 {again} 条")
check("幂等回填不会改变关联行集合", facet_row_set() == expected_row_set())

assert_paths_agree("回填完成", expect_index=True)

with Session() as db:
    values = {
        kind: set(facets.kind_values(db, kind))
        for kind in (facets.KIND_GENRE, facets.KIND_STUDIO, facets.KIND_TAG)
    }
check("取值菜单与旧口径集合相同（流派）",
      values[facets.KIND_GENRE] == {"动作", "冒险", "Action-Adventure", "纪录", "喜剧"},
      f"{sorted(values[facets.KIND_GENRE])}")
check("取值菜单里没有重复取值（'动作,动作' 只算一个）",
      len([v for v in values[facets.KIND_GENRE] if v == "动作"]) == 1)
check("取值菜单里没有空值（尾随逗号不会留空串）",
      "" not in values[facets.KIND_GENRE] and "" not in values[facets.KIND_STUDIO],
      f"流派={sorted(values[facets.KIND_GENRE])}")


# ==================== 4. 筛选路径的补块：按预算分块 + 冷却不抢写锁 ====================
print("\n=== 4. 筛选路径的补块预算与冷却 ===")
BUDGET = 5
sizes: list[int] = []
recording_sync = facets.sync_items


def recording(db, items):
    sizes.append(len(items))
    return recording_sync(db, items)


def reset_legacy_state() -> None:
    """把库打回「刚升级上来」：清空关联行与回填水位（升级现场的等价状态）"""
    with Session() as db:
        db.execute(text("DELETE FROM emby_item_facets"))
        db.execute(text(
            "DELETE FROM system_configs WHERE key = :k"
        ), {"k": facets.BACKFILL_KEY})
        db.commit()
    facets.invalidate_values_cache()


seed_legacy_db(count=25, include_base=False)   # 追 25 条 Core 条目，一起等回填
reset_legacy_state()

# (a) 冷却窗口内：请求不补块、不动状态（并发请求不会一起抢写锁）
pin_cooldown()
facets.sync_items = recording
try:
    with Session() as db:
        blocked = facets.ensure_ready(db, budget=BUDGET)
finally:
    facets.sync_items = recording_sync
check("冷却窗口内的请求不抢写锁（不补块、也不改状态）",
      blocked is False and sizes == [] and watermark() == 0 and facet_row_set() == set(),
      f"ready={blocked} 补块={sizes} 水位={watermark()} 关联行={len(facet_row_set())}")

# (b) 冷却过后：一次筛选请求按预算分块把老库补完
facets._last_filter_attempt = 0.0
sizes.clear()
facets.sync_items = recording
try:
    with Session() as db:
        first_call = facets.ensure_ready(db, budget=BUDGET)
finally:
    facets.sync_items = recording_sync

check("一次筛选请求就把老库补完（读请求不会被回填长期卡住）",
      first_call is True and facets.ready(Session()) is True, f"ready={first_call}")
check(f"补块按预算分块（每块 ≤ {BUDGET} 条，内存有界）", bool(sizes) and max(sizes) <= BUDGET,
      f"每块条数={sizes}")
check("补块覆盖了全部待补条目（无遗漏）", sum(sizes) == len(all_item_ids()),
      f"合计={sum(sizes)} 条目={len(all_item_ids())}")
check("补完后的关联行逐行正确", facet_row_set() == expected_row_set(),
      f"实际 {len(facet_row_set())} 行 期望 {len(expected_row_set())} 行")
assert_paths_agree("预算补齐后", expect_index=True)

with Session() as db:
    facets.prune_orphans(db)


print()
if FAILED:
    print(f"❌ 分类关联表升级演练失败 {len(FAILED)} 项：")
    for label in FAILED:
        print(f"   - {label}")
    sys.exit(1)
print("✅ 分类关联表升级演练全部通过")
