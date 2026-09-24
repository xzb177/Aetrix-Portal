"""分类关联表（item ↔ genre/studio/tag/platform）冒烟测试（v2.15.0）

覆盖：

- **写入侧**：ORM 新建 / 更新条目自动同步关联行（不依赖每个调用点记得调一次），
  删除条目不留孤儿行；
- **读取侧**：分类筛选（`Genres=` / 合成 GenreIds / StudioIds / 虚拟媒体库平台）
  与升级前在逗号分隔文本列上做 `LIKE '%x%'` 的结果**逐条一致**（含大小写与部分名匹配）；
- **老库升级**：Core 写入的「没有关联行」的条目，回填前走旧路径、回填后走索引路径，
  两条路径结果相同；筛选路径自己也会按预算补块（不用等运维动手）；
- **索引证据**：筛选用的关联表查询走 `idx_item_facet_kind_value`（EXPLAIN QUERY PLAN），
  主查询按主键取条目，不再扫 `emby_items` 文本列。

用法: python scripts/smoke_test_item_facets.py
"""
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "e2e-test-secret-key-not-for-production"

DB = os.path.join(tempfile.mkdtemp(), "item-facets.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, engine, init_db  # noqa: E402
from backend.emby_server import facets  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server.api import _guid_of, invalidate_filters_cache  # noqa: E402

init_db()

from backend.main import app  # noqa: E402

client = TestClient(app)

failures: list[str] = []
TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


suffix = str(random.randint(100000, 999999))

# ==================== 播种 ====================

# 覆盖「多值 / 部分名重叠 / 大小写 / 平台」几种情况
SEED = [
    ("动作片 A", "动作,惊悚", "华纳", "Netflix"),
    ("动作片 B", "动作", "华纳", "Netflix"),
    ("冒险片 C", "动作,冒险", "迪士尼", "Disney+"),
    ("科幻片 D", "科幻", "迪士尼", "Disney+"),
    ("喜剧片 E", "喜剧", "环球", ""),
    ("惊悚片 F", "惊悚", "环球", ""),
    ("爱情片 G", "爱情", "华纳", ""),
]
# 包含关系的取值：旧实现里传 "Action" 会连这一条一起命中，新路径必须一致
DASH = "Action-Adventure"

with SessionLocal() as db:
    user = models.WebUser(username=f"facet{suffix}", password_hash="not-used", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.add(em.EmbyApiToken(token=f"tok-{suffix}", user_id=user.id, device_id=f"dev-{suffix}"))
    lib = em.Library(guid=f"lib{suffix}", name="分类测试库", collection_type="movies")
    db.add(lib)
    db.commit()
    db.refresh(lib)
    lib_id = lib.id

    for name, genres, studio, platform in SEED:
        db.add(em.MediaItem(
            guid=f"g-{suffix}-{name}", library_id=lib.id, item_type="movie",
            name=name, sort_name=name.lower(), genres=genres, studios=studio,
            platforms=platform, production_year=2024,
        ))
    db.add(em.MediaItem(
        guid=f"g-{suffix}-dash", library_id=lib.id, item_type="movie",
        name="混合动作片 H", sort_name="h", genres=f"动作,{DASH}", studios="华纳",
        platforms="Netflix", production_year=2023,
    ))
    db.commit()

    # 虚拟媒体库（跨库的发行平台视图）：按 platforms 标签聚合
    vlib = em.Library(guid=f"vlib{suffix}", name="Netflix 视图", collection_type="movies",
                      is_virtual=True, platform="Netflix", is_enabled=True)
    db.add(vlib)
    db.commit()
    db.refresh(vlib)
    vlib_guid = vlib.guid

    # 老库条目：绕过 ORM 钩子直接 Core 写入，模拟「升级上来、关联表还没回填」的缺口
    legacy_guid = f"g-{suffix}-legacy"
    db.execute(text(
        "INSERT INTO emby_items (guid, library_id, item_type, name, sort_name, genres, studios, "
        "platforms, is_hidden, production_year) VALUES (:g, :lib, 'movie', :n, :n2, :ge, :st, '', 0, 2022)"
    ), {"g": legacy_guid, "lib": lib_id, "n": "老片 I", "n2": "legacy i",
        "ge": f"动作,{DASH}", "st": "华纳"})
    db.commit()

H = {"X-Emby-Token": f"tok-{suffix}"}


def item_names(payload: dict) -> set:
    return {i.get("Name") for i in (payload.get("Items") or [])}


def query_names(**params) -> set:
    params.setdefault("Limit", 500)
    r = client.get(f"/emby/Users/{user_id}/Items", headers=H, params=params)
    assert r.status_code == 200, r.text
    return item_names(r.json())


def facet_rows(kind: str) -> dict:
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT f.value, COUNT(*) FROM emby_item_facets f WHERE f.kind = :k GROUP BY f.value"
        ), {"k": kind}).all()
    return {value: int(count) for value, count in rows}


def legacy_count(column: str, name: str) -> int:
    """升级前的口径：在逗号分隔文本列上做 LIKE '%name%'"""
    with SessionLocal() as db:
        return int(db.execute(text(
            f"SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND {column} LIKE :p"
        ), {"p": f"%{name}%"}).scalar() or 0)


def facet_row_count(item_id: int) -> int:
    with SessionLocal() as db:
        return int(db.execute(text(
            "SELECT COUNT(*) FROM emby_item_facets WHERE item_id = :i"
        ), {"i": item_id}).scalar() or 0)


# ==================== 1. 写入侧：ORM 写条目 → 关联行自动同步 ====================
print("\n=== 写入侧：关联行随条目自动同步 ===")

by_genre = facet_rows(facets.KIND_GENRE)
by_studio = facet_rows(facets.KIND_STUDIO)
by_platform = facet_rows(facets.KIND_PLATFORM)

check("新建条目自动写入流派关联行（动作 4 条 / 科幻 1 条）",
      by_genre.get("动作") == 4 and by_genre.get("科幻") == 1,
      f"动作={by_genre.get('动作')} 科幻={by_genre.get('科幻')}")
check("多值列按逗号拆成多行（惊悚 2 / 冒险 1 / Action-Adventure 1）",
      by_genre.get("惊悚") == 2 and by_genre.get("冒险") == 1
      and by_genre.get(DASH) == 1,
      f"惊悚={by_genre.get('惊悚')} 冒险={by_genre.get('冒险')} {DASH}={by_genre.get(DASH)}")
check("工作室与发行平台也建了关联行（华纳 4 / Netflix 3 / Disney+ 2）",
      by_studio.get("华纳") == 4 and by_platform.get("Netflix") == 3
      and by_platform.get("Disney+") == 2,
      f"华纳={by_studio.get('华纳')} Netflix={by_platform.get('Netflix')} Disney+={by_platform.get('Disney+')}")

# 老库条目还没有关联行，关联表也就还没法代表全库（这一步必须在任何筛选请求之前看）
with SessionLocal() as db:
    ready_before = facets.ready(db)
    legacy_facets = db.execute(text(
        "SELECT COUNT(*) FROM emby_item_facets f JOIN emby_items i ON i.id = f.item_id "
        "WHERE i.name = '老片 I'"
    )).scalar()
check("老库条目（Core 写入）暂时没有关联行", int(legacy_facets) == 0, f"实际 {legacy_facets} 行")
check("关联表尚未代表全库（水位还没追上老条目）", ready_before is False)


# ==================== 2. 读取侧：与旧口径逐条同结果 ====================
print("\n=== 读取侧：筛选结果与旧的 LIKE 口径一致 ===")

for genre in ("动作", "科幻", "喜剧", "惊悚", "爱情", "冒险"):
    got = query_names(Genres=genre)
    check(f"Genres={genre} 与旧 LIKE 口径一致（{legacy_count('genres', genre)} 条）",
          len(got) == legacy_count("genres", genre),
          f"新={len(got)} 旧={legacy_count('genres', genre)}")

for studio in ("华纳", "迪士尼", "环球"):
    got = query_names(StudioIds=_guid_of("Studio", studio))
    check(f"StudioIds={studio} 与旧 LIKE 口径一致",
          len(got) == legacy_count("studios", studio),
          f"新={len(got)} 旧={legacy_count('studios', studio)}")

check("部分名 / 大小写（'act'）与旧口径一致",
      len(query_names(Genres="act")) == legacy_count("genres", "act"),
      f"新={len(query_names(Genres='act'))} 旧={legacy_count('genres', 'act')}")
check("包含关系的取值也一致（'动作' 命中 '动作' 与 'Action-Adventure' 两条）",
      len(query_names(Genres="动作")) == legacy_count("genres", "动作"))

# 筛选请求自己按预算补齐了关联表（升级后不用等运维/重启）
with SessionLocal() as db:
    ready_after_filter = facets.ready(db)
    summary = facets.summary(db)
check("筛选路径自动把老库补块并推进到可代表全库", ready_after_filter is True,
      f"summary={summary}")
with SessionLocal() as db:
    legacy_id = db.query(em.MediaItem.id).filter(em.MediaItem.name == "老片 I").scalar()
check("补块后老条目也有了关联行（2 个流派 + 1 个工作室）",
      facet_row_count(int(legacy_id)) == 3, f"实际 {facet_row_count(int(legacy_id))} 行")


# ==================== 3. 回填：重复调用幂等、结果不变 ====================
print("\n=== 回填幂等 ===")

with SessionLocal() as db:
    again = facets.ensure_backfill(db)
    ready_now = facets.ready(db)
check("已代表全库时再回填不做事（幂等）", again == 0 and ready_now is True, f"处理 {again} 条")
check("重复回填不会重复计数（动作仍为 5 = 4 + 老片 I 的 1）",
      facet_rows(facets.KIND_GENRE).get("动作") == 5,
      f"实际 {facet_rows(facets.KIND_GENRE).get('动作')}")

# 再插一条 Core 条目，验证「显式回填」这条路也把它补上
with SessionLocal() as db:
    db.execute(text(
        "INSERT INTO emby_items (guid, library_id, item_type, name, sort_name, genres, studios, "
        "platforms, is_hidden, production_year) VALUES (:g, :lib, 'movie', :n, :n2, :ge, :st, '', 0, 2021)"
    ), {"g": f"g-{suffix}-legacy2", "lib": lib_id, "n": "老片 J", "n2": "legacy j",
        "ge": "纪录", "st": "国家地理"})
    db.commit()
    filled = facets.ensure_backfill(db)
check("显式回填补齐新老条目", filled == 1, f"处理 {filled} 条")
check("新补的条目参与筛选", query_names(Genres="纪录") == {"老片 J"},
      f"{sorted(query_names(Genres='纪录'))}")

for genre in ("动作", "科幻", "惊悚", "act", "纪录", "动作冒险"):
    check(f"索引路径下 Genres={genre} 与旧口径一致",
          len(query_names(Genres=genre)) == legacy_count("genres", genre),
          f"新={len(query_names(Genres=genre))} 旧={legacy_count('genres', genre)}")

for studio in ("华纳", "迪士尼", "国家地理"):
    check(f"索引路径下 StudioIds={studio} 与旧口径一致",
          len(query_names(StudioIds=_guid_of("Studio", studio))) == legacy_count("studios", studio))

# ==================== 4. 合成 Id（客户端点「类型/制作公司」） ====================
print("\n=== 合成 Id 与虚拟媒体库平台 ===")

check("ParentId=合成流派 Id 与 Genres= 同一结果集",
      query_names(ParentId=_guid_of("Genre", "科幻")) == query_names(Genres="科幻") == {"科幻片 D"},
      f"{sorted(query_names(ParentId=_guid_of('Genre', '科幻')))}")
check("ParentId=合成工作室 Id 命中该工作室的片子",
      query_names(ParentId=_guid_of("Studio", "迪士尼")) == {"冒险片 C", "科幻片 D"},
      f"{sorted(query_names(ParentId=_guid_of('Studio', '迪士尼')))}")
check("虚拟媒体库按平台聚合条目",
      query_names(ParentId=vlib_guid) == {"动作片 A", "动作片 B", "混合动作片 H"},
      f"{sorted(query_names(ParentId=vlib_guid))}")

with SessionLocal() as db:
    vlib = db.query(em.Library).filter(em.Library.guid == vlib_guid).first()
    count = facets.count_virtual_items(db, vlib)
check("虚拟库条目数（索引版）与旧口径一致", count == legacy_count("platforms", "Netflix"),
      f"新={count} 旧={legacy_count('platforms', 'Netflix')}")

r = client.get("/emby/Items/Filters", headers=H)
genres_menu = set((r.json() or {}).get("Genres") or [])
with SessionLocal() as db:
    legacy_menu = {
        g
        for (raw,) in db.execute(text("SELECT genres FROM emby_items WHERE is_hidden = 0")).all()
        for g in (raw or "").split(",")
        if g
    }
check("筛选菜单的流派取值与旧口径一致（来自关联表索引）",
      genres_menu == legacy_menu, f"新={sorted(genres_menu)} 旧={sorted(legacy_menu)}")

# ==================== 5. 更新与删除 ====================
print("\n=== 更新与删除 ===")

with SessionLocal() as db:
    item = db.query(em.MediaItem).filter(em.MediaItem.name == "科幻片 D").first()
    item.genres = "悬疑"
    db.commit()
    item_id = item.id
check("改条目流派后关联行跟着换（不留旧值）",
      facet_rows(facets.KIND_GENRE).get("科幻") is None
      and facet_rows(facets.KIND_GENRE).get("悬疑") == 1,
      f"科幻={facet_rows(facets.KIND_GENRE).get('科幻')} 悬疑={facet_rows(facets.KIND_GENRE).get('悬疑')}")
check("筛选立刻按新流派命中", query_names(Genres="悬疑") == {"科幻片 D"},
      f"{sorted(query_names(Genres='悬疑'))}")

with SessionLocal() as db:
    victim = db.query(em.MediaItem).filter(em.MediaItem.name == "爱情片 G").first()
    victim_id = victim.id
    db.delete(victim)
    db.commit()
check("ORM 删除条目后关联行一并清掉", facet_row_count(victim_id) == 0,
      f"剩余 {facet_row_count(victim_id)} 行")

# 批量 Core 删除（扫描清理走的就是这条路）：先制造孤儿行，再靠 prune_orphans 兜底
with SessionLocal() as db:
    bulk = db.query(em.MediaItem).filter(em.MediaItem.name == "喜剧片 E").first()
    bulk_id = bulk.id
    db.query(em.MediaItem).filter(em.MediaItem.id == bulk_id).delete(synchronize_session=False)
    db.commit()
    orphans = facets.orphan_count(db)
    pruned = facets.prune_orphans(db)
    after = facets.orphan_count(db)
check("批量删除留下的孤儿行被 prune_orphans 全部清掉",
      orphans > 0 and pruned == orphans and after == 0,
      f"孤儿={orphans} 清理={pruned} 剩余={after}")

check("被删条目不再出现在筛选结果里",
      "爱情片 G" not in query_names(Genres="爱情")
      and "喜剧片 E" not in query_names(Genres="喜剧"),
      f"爱情={sorted(query_names(Genres='爱情'))} 喜剧={sorted(query_names(Genres='喜剧'))}")

# ==================== 6. 索引证据 ====================
print("\n=== 索引证据 ===")

with engine.connect() as conn:
    plan = conn.execute(text(
        "EXPLAIN QUERY PLAN "
        "SELECT item_id FROM emby_item_facets WHERE kind = 'genre' AND value IN ('动作')"
    )).all()
plan_text = " ".join(str(row[-1]) for row in plan)
check("关联表查询走 idx_item_facet_kind_value（不是全表扫描）",
      "idx_item_facet_kind_value" in plan_text, plan_text[:120])

with engine.connect() as conn:
    plan_main = conn.execute(text(
        "EXPLAIN QUERY PLAN "
        "SELECT id FROM emby_items WHERE is_hidden = 0 AND id IN "
        "(SELECT item_id FROM emby_item_facets WHERE kind = 'genre' AND value IN ('动作'))"
    )).all()
main_text = " ".join(str(row[-1]) for row in plan_main)
check("主查询按主键取条目（子查询走索引，文本列上不再有 LIKE）",
      "INTEGER PRIMARY KEY" in main_text and "LIKE" not in main_text.upper(),
      main_text[:160])

with engine.connect() as conn:
    tables = {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )).all()}
    indexes = {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'emby_item_facets'"
    )).all()}
check("关联表与两个索引都已建出（老库靠 create_all 自动补表）",
      "emby_item_facets" in tables
      and {"idx_item_facet_kind_value", "idx_item_facet_item"} <= indexes,
      f"indexes={sorted(indexes)}")

# ==================== 7. 规模：3000 条库上依然走索引 ====================
print("\n=== 规模验证（3000 条） ===")

import time  # noqa: E402

big_lib = em.Library(guid=f"big{suffix}", name="规模库", collection_type="movies")
with SessionLocal() as db:
    db.add(big_lib)
    db.commit()
    db.refresh(big_lib)
    big_id = big_lib.id
    big_guid = big_lib.guid
    db.add_all([
        em.MediaItem(
            guid=f"big{suffix}-{i}", library_id=big_lib.id, item_type="movie",
            name=f"规模片 {i}", sort_name=f"big {i}",
            genres="动作" if i % 3 == 0 else "喜剧",
            studios="华纳" if i % 5 == 0 else "环球",
        )
        for i in range(3000)
    ])
    db.commit()
    big_facets = int(db.execute(text(
        "SELECT COUNT(*) FROM emby_item_facets f JOIN emby_items i ON i.id = f.item_id "
        "WHERE i.library_id = :l"
    ), {"l": big_id}).scalar() or 0)
check("3000 条一次性写入时关联行也全部建好（3000 流派 + 3000 工作室）",
      big_facets == 6000, f"实际 {big_facets} 行")


def timed(sql: str, rounds: int = 20) -> float:
    with engine.connect() as conn:
        conn.execute(text(sql)).all()  # 预热
        started = time.perf_counter()
        for _ in range(rounds):
            conn.execute(text(sql)).all()
        return (time.perf_counter() - started) * 1000 / rounds


legacy_ms = timed("SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND genres LIKE '%动作%'")
indexed_ms = timed(
    "SELECT COUNT(*) FROM emby_items WHERE is_hidden = 0 AND id IN "
    "(SELECT item_id FROM emby_item_facets WHERE kind = 'genre' AND value IN ('动作'))"
)
print(f"参考数据（不判定）：3000 条库上 LIKE 全表匹配 {legacy_ms:.2f} ms/次，"
      f"关联表索引匹配 {indexed_ms:.2f} ms/次")

with engine.connect() as conn:
    plan_big = conn.execute(text(
        "EXPLAIN QUERY PLAN SELECT id FROM emby_items WHERE is_hidden = 0 AND id IN "
        "(SELECT item_id FROM emby_item_facets WHERE kind = 'genre' AND value IN ('动作'))"
    )).all()
big_plan = " ".join(str(row[-1]) for row in plan_big)
check("3000 条规模下仍然走索引（没有退化成全表扫描）",
      "idx_item_facet_kind_value" in big_plan and "SCAN emby_items" not in big_plan,
      big_plan[:140])

with SessionLocal() as db:
    indexed_count = int(db.execute(text(
        "SELECT COUNT(*) FROM emby_items WHERE library_id = :l AND is_hidden = 0 AND id IN "
        "(SELECT item_id FROM emby_item_facets WHERE kind = 'genre' AND value = '动作')"
    ), {"l": big_id}).scalar() or 0)
    legacy_big = int(db.execute(text(
        "SELECT COUNT(*) FROM emby_items WHERE library_id = :l AND is_hidden = 0 "
        "AND genres LIKE '%动作%'"
    ), {"l": big_id}).scalar() or 0)
check("3000 条规模下索引路径与 LIKE 口径结果完全一致（0/3/6… 共 1000 条）",
      indexed_count == legacy_big == 1000, f"新={indexed_count} 旧={legacy_big}")
big_name_page = query_names(ParentId=big_guid, Genres="动作")
page_is_action_only = bool(big_name_page) and all(
    n.startswith("规模片 ") and int(n.split(" ")[-1]) % 3 == 0 for n in big_name_page
)
check("规模库下按流派筛出的页内条目全部命中（i % 3 == 0），无错漏",
      page_is_action_only, f"页内 {len(big_name_page)} 条，示例 {sorted(big_name_page)[:3]}")

# ==================== 5. 分级与标签筛选 ====================
# 真实起因：`/Items/Filters` 一直把 OfficialRatings 与 Tags 列进筛选菜单（那正是客户端
# 渲染筛选面板的依据），但列表端点完全忽略这两个参数——照着菜单选了，拿到的还是全量结果，
# 看着像「筛选没生效」。这里把「菜单里列出来的维度都真的能筛」钉住。
#
# 播在这一节而不是文件开头：上面的断言多处是精确计数（动作 4 条等），
# 中途加条目会把它们全部打偏。
print("\n=== 分级与标签筛选（菜单里列出来的维度必须真的能筛）===")

with SessionLocal() as db:
    db.add_all([
        em.MediaItem(
            guid=f"g-{suffix}-rate", library_id=lib_id, item_type="movie",
            name="分级片 K", sort_name="分级片 k", genres="", studios="",
            tags="中字,4K", official_rating="PG-13", production_year=2024,
        ),
        em.MediaItem(
            guid=f"g-{suffix}-rate2", library_id=lib_id, item_type="movie",
            name="分级片 L", sort_name="分级片 l", genres="", studios="",
            tags="中字", official_rating="R", production_year=2021,
        ),
    ])
    db.commit()

# 筛选菜单自己有一份 TTL 缓存（默认 5 分钟），扫描 / 条目变更时才失效；这里直接造条目、
# 没走扫描路径，所以手工失效一次（与 smoke_test_item_facets_upgrade 同一套做法）。
invalidate_filters_cache()
menu = client.get("/emby/Items/Filters", headers=H).json()
check("筛选菜单里有分级与标签两个维度（客户端据此渲染筛选面板）",
      "PG-13" in (menu.get("OfficialRatings") or [])
      and "4K" in (menu.get("Tags") or []),
      f"分级={menu.get('OfficialRatings')} 标签={menu.get('Tags')}")

check("OfficialRatings=PG-13 只回该分级的条目",
      query_names(OfficialRatings="PG-13") == {"分级片 K"},
      f"{sorted(query_names(OfficialRatings='PG-13'))}")
check("OfficialRatings 多个值取并集",
      query_names(OfficialRatings="PG-13,R") == {"分级片 K", "分级片 L"},
      f"{sorted(query_names(OfficialRatings='PG-13,R'))}")
check("分级里不存在的值回空集（而不是退回全量）",
      query_names(OfficialRatings="这个分级不存在") == set(),
      f"{sorted(query_names(OfficialRatings='这个分级不存在'))}")

check("Tags=4K 只回带该标签的条目",
      query_names(Tags="4K") == {"分级片 K"},
      f"{sorted(query_names(Tags='4K'))}")
check("Tags 与旧 LIKE 口径一致（'中字' 命中两条）",
      len(query_names(Tags="中字")) == legacy_count("tags", "中字") == 2,
      f"新={len(query_names(Tags='中字'))} 旧={legacy_count('tags', '中字')}")
check("标签与分级可以叠加（两个条件同时生效）",
      query_names(Tags="中字", OfficialRatings="R") == {"分级片 L"},
      f"{sorted(query_names(Tags='中字', OfficialRatings='R'))}")


# ==================== 汇总 ====================
print()
if failures:
    print(f"FAILED  {len(failures)}/{TOTAL}：")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"ALL PASS  {TOTAL}/{TOTAL}")
