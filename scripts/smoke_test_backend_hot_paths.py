#!/usr/bin/env python3
"""后端热路径：同步写库不占事件循环 + 分类菜单走索引（v2.35.0）

三条都是「用户能感觉到的卡」的直接来源，所以每条都量出数字或数出 SQL，不靠“看起来没问题”：

1. **分类菜单端点**（``/Genres``、``/Studios``）。旧实现每个请求都把整库的
   ``genres`` / ``studios`` 文本列读回来再切分：十万级库约 190ms，而且随库**线性增长**
   （客户端每打开一次筛选面板就付一次）。现在走 ``emby_item_facets`` 的覆盖索引
   （带取值缓存），老库没回填完才退回旧口径。这里数 SQL：请求菜单时**不允许**出现
   「从 emby_items 读整列」，必须是关联表上的 DISTINCT；两条路的取值必须逐条一致。

2. **筛选菜单缓存**（``GET /Items/Filters``）。菜单取值同样来自全库，原先只能等 TTL
   （默认 300 秒）自然过期——刚扫完的片子在客户端的「类型 / 制片公司」里最长 5 分钟
   看不到。现在分类值一变就被安排成过期，且带最小重建间隔。这里钉两件事：
   改动在下一次「到点」的请求里就能看见；连续改动**不会**退化成“每次请求都重建”
   （用 SQL 计数证明）。

3. **会话进度上报**（``POST /Sessions/Playing/Progress``）。每个正在播放的客户端每 10 秒
   上报一次，一次上报要读会话 / 写位置 / 写观看进度。它跑在**事件循环**上时会卡住
   全站所有请求（包括别人的播放），所以现在整段同步写库都下放线程池。这里用后台心跳
   量「事件循环被占住多久」：
   - 基线自证：把同样的同步活儿直接跑在事件循环上，心跳必须出现 ≥0.3s 的空洞
     （这就是改动前的形态，先证明测量方法有效）；
   - 现在：一次 0.35 秒的慢写走真实路由进来，心跳空洞 < 0.15s，而且会话与观看进度
     确实写进去了（活儿真干了，只是不在循环上）。
"""
import asyncio
import os
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "hot-paths-smoke-secret-key-32b"
DB = os.path.join(tempfile.mkdtemp(prefix="hot-paths-"), "hot-paths.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
# 最小重建间隔压到 1 秒：验的是机制（到点才重建 / 不每请求重建），不是那个默认值本身
os.environ["EMBY_FILTERS_MIN_REFRESH"] = "1"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event as sa_event  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, engine, init_db  # noqa: E402
from backend.emby_server import api as emby_api  # noqa: E402
from backend.emby_server import compat_routes, facets  # noqa: E402
from backend.emby_server import models as em  # noqa: E402

init_db()

from backend.main import app  # noqa: E402

failures: list[str] = []
TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


# ==================== SQL 计数（数「做了什么」，不靠时间猜）====================

STATEMENTS: list[str] = []


def _record_statement(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
    STATEMENTS.append(statement)


sa_event.listen(engine, "before_cursor_execute", _record_statement)

GENRE_MENU_SQL = "DISTINCT emby_item_facets.value"


def menu_rebuilds() -> int:
    """关联表取值上的 DISTINCT 次数 = 筛选菜单真的重建了几次"""
    return sum(1 for s in STATEMENTS if GENRE_MENU_SQL in s)


def full_column_reads() -> list[str]:
    """从 emby_items 里把分类文本列整列读回来的语句（旧实现的那条路）"""
    return [
        s for s in STATEMENTS
        if "FROM emby_items" in s and ("emby_items.genres" in s or "emby_items.studios" in s)
    ]


# ==================== 数据准备 ====================

suffix = uuid.uuid4().hex[:6]
with SessionLocal() as db:
    user = models.WebUser(username=f"hot{suffix}", password_hash="x", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id          # 会话一关实体就过期，后面只认这个裸 id

    library = em.Library(guid=f"lib-hot-{suffix}", name="热路径测试库",
                         collection_type="movies", paths="/tmp")
    db.add(library)
    db.commit()
    db.refresh(library)

    items = [
        em.MediaItem(guid=f"hot-{suffix}-{i}", library_id=library.id, item_type="movie",
                     name=f"热路径测试片 {i}", sort_name=f"hot {i}",
                     genres="动作" if i % 2 == 0 else "喜剧",
                     studios="华纳" if i % 3 == 0 else "环球",
                     tags="4K", production_year=2000 + (i % 10),
                     official_rating="PG-13" if i % 2 else "R",
                     duration_ticks=60_000_000_000)
        for i in range(60)
    ]
    db.add_all(items)
    db.commit()

    token = f"hot-{suffix}-" + "b" * 12
    db.add(em.EmbyApiToken(token=token, user_id=user.id, device_id="hot-paths-device"))
    db.commit()
    item_guid = items[0].guid
    item_id = items[0].id
    library_id = library.id

H = {"X-Emby-Token": token}

client = TestClient(app)


def legacy_menu(kind: str, column: str) -> list[str]:
    """旧口径（读整列）算一遍，用来做逐条比对"""
    with engine.connect() as conn:
        raw = conn.execute(text(f"SELECT {column} FROM emby_items")).scalars().all()
    return sorted({v for row in raw for v in (row or "").split(",") if v})


# ==================== 1. 菜单端点：不读整列 + 取值一致 ====================
print("\n=== 1. /Genres、/Studios 走关联表索引 ===")

client.get("/emby/Items/Filters", headers=H)  # 预热：第一次可能带一小块回填
# 先扔进程内取值缓存：否则 /Genres 直接给出缓存，量不到「这条路到底怎么查的」。
# 冷读才看得见真正的 SQL（有缓存时 0 条 SQL 也**正确**，见下面的分支）。
facets.invalidate_values_cache()
STATEMENTS.clear()
resp = client.get("/emby/Genres", headers=H)
check("/Genres → 200", resp.status_code == 200, f"HTTP {resp.status_code}")
names = [i["Name"] for i in resp.json().get("Items", [])]
cold = menu_rebuilds() >= 1
check("菜单走关联表（冷读是覆盖索引上的 DISTINCT；有缓存则 0 条 SQL，都不读整列）",
      (cold or not full_column_reads()) and not full_column_reads(),
      f"冷读索引查询 {menu_rebuilds()} 条 · 整列读 {len(full_column_reads())} 条")
check("/Genres 取值与旧口径逐条一致", names == legacy_menu("genre", "genres"),
      f"接口 {names} · 旧口径 {legacy_menu('genre', 'genres')}")

facets.invalidate_values_cache()
STATEMENTS.clear()
resp = client.get("/emby/Studios", headers=H)
studios = [i["Name"] for i in resp.json().get("Items", [])]
check("/Studios 不再读整列", not full_column_reads(),
      f"整列读 {len(full_column_reads())} 条")
check("/Studios 取值与旧口径逐条一致", studios == legacy_menu("studio", "studios"),
      f"接口 {studios} · 旧口径 {legacy_menu('studio', 'studios')}")

# 老库（关联表还没回填完）必须退回旧口径，结果一样对：
_real_ready, _real_attempt = facets.ready, facets._last_filter_attempt  # noqa: SLF001
try:
    facets.ready = lambda db: False                      # noqa: ARG005 — 模拟“还没补完”
    facets._last_filter_attempt = time.monotonic()       # noqa: SLF001 — 冷却窗口内：不在读请求里补块
    STATEMENTS.clear()
    resp = client.get("/emby/Genres", headers=H)
    fallback = [i["Name"] for i in resp.json().get("Items", [])]
    check("老库退回旧口径时结果一致（升级前后不会出现「筛选空白」）",
          fallback == legacy_menu("genre", "genres") and len(full_column_reads()) >= 1,
          f"退回 {len(full_column_reads())} 条整列读 · 取值 {len(fallback)} 个")
finally:
    facets.ready, facets._last_filter_attempt = _real_ready, _real_attempt  # noqa: SLF001

# /Items/Counts：一次 GROUP BY 的结果必须与直接计数一致
STATEMENTS.clear()
counts = client.get("/emby/Items/Counts", headers=H).json()
with engine.connect() as conn:
    expected_movies = int(conn.execute(text(
        "SELECT COUNT(*) FROM emby_items WHERE item_type = 'movie' AND is_hidden = 0"
    )).scalar() or 0)
check("/Items/Counts 计数正确（合并 GROUP BY 后没算错）",
      counts["MovieCount"] == expected_movies and counts["ItemCount"] >= counts["MovieCount"],
      f"MovieCount={counts['MovieCount']} 期望 {expected_movies} · ItemCount={counts['ItemCount']}")


# ==================== 2. 筛选菜单缓存：改动看得见，但不会每请求重建 ====================
print("\n=== 2. /Items/Filters 变更后刷新 + 最小重建间隔 ===")

client.get("/emby/Items/Filters", headers=H)             # 先把菜单建出来
menu = client.get("/emby/Items/Filters", headers=H).json()
check("菜单里能看到条目自带的类型", "动作" in menu["Genres"], str(menu["Genres"][:6]))

with SessionLocal() as db:
    row = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
    row.genres = "动作,科幻"
    db.commit()

statements_before = menu_rebuilds()
cached = client.get("/emby/Items/Filters", headers=H).json()
check("刚改完（还没到最小重建间隔）给出上一份菜单，而不是每个请求都重建",
      "科幻" not in cached["Genres"] and menu_rebuilds() == statements_before,
      f"重建次数 {menu_rebuilds() - statements_before}")

time.sleep(emby_api._FILTERS_MIN_REFRESH + 0.4)          # noqa: SLF001 — 等“到点”
fresh = client.get("/emby/Items/Filters", headers=H).json()
check("到点后菜单立刻含新值（不再等满 TTL）", "科幻" in fresh["Genres"],
      f"Genres={fresh['Genres']}")

# 连续改动 + 连续请求：不能退化成「每次请求都重建」
with SessionLocal() as db:
    row = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
    for i in range(5):
        row.genres = f"动作,连改{i}"
        db.commit()
        client.get("/emby/Items/Filters", headers=H)
    row.genres = "动作"
    db.commit()

statements_before = menu_rebuilds()
for _ in range(5):
    client.get("/emby/Items/Filters", headers=H)
burst = menu_rebuilds() - statements_before
# 一次重建会打两条 DISTINCT（类型 + 标签），所以「最多重建一次」= 至多 2 条
check("连续请求不会每次重建（最小间隔生效）", burst <= 2,
      f"5 次请求重建相关的 DISTINCT {burst} 条（每重建一次是 2 条）")


# ==================== 3. 会话进度上报：慢写不占事件循环 ====================
print("\n=== 3. /Sessions/Playing/Progress 的写库不在事件循环上 ===")

SLOW_WRITE = 0.35     # 一次上报里同步写库要花的时间（真实机器上的慢写）
REPORT = {"ItemId": item_guid, "PlaySessionId": f"hot-session-{suffix}",
          "PositionTicks": 12_000_000_000, "IsPaused": False}


class LoopWatch:
    """后台心跳：记录事件循环最坏一次「没能按时醒来」的间隔"""

    def __init__(self, interval: float = 0.01):
        self.interval = interval
        self.max_gap = 0.0
        self.ticks = 0
        self._task = None

    async def _beat(self):
        last = time.monotonic()
        while True:
            await asyncio.sleep(self.interval)
            now = time.monotonic()
            self.max_gap = max(self.max_gap, now - last)
            self.ticks += 1
            last = now

    def start(self):
        self.max_gap = 0.0
        self.ticks = 0
        self._task = asyncio.ensure_future(self._beat())

    def stop(self) -> float:
        if self._task:
            self._task.cancel()
        return self.max_gap


async def measure(awaitable_factory):
    """跑一段协程，返回 (耗时, 心跳最坏空洞)"""
    watch = LoopWatch()
    watch.start()
    await asyncio.sleep(watch.interval * 2)
    started = time.monotonic()
    await awaitable_factory()
    elapsed = time.monotonic() - started
    await asyncio.sleep(watch.interval * 2)
    gap = watch.stop()
    assert watch.ticks > 0, "心跳任务没跑起来，测量无效"
    return elapsed, gap


async def blocking_baseline() -> float:
    """基线自证：同步活儿直接跑在事件循环上（改动前就是这个形态）"""
    watch = LoopWatch()
    watch.start()
    await asyncio.sleep(watch.interval * 2)
    time.sleep(SLOW_WRITE)
    await asyncio.sleep(watch.interval * 2)
    gap = watch.stop()
    return gap


async def section_hot_path():
    # 3.1 先自证测量方法有效
    gap = await blocking_baseline()
    check("基线自证：同步写库跑在事件循环上会卡住全站（心跳空洞 ≥0.3s）",
          gap >= SLOW_WRITE * 0.8, f"心跳空洞={gap:.3f}s")

    real_record = compat_routes._record_progress          # noqa: SLF001

    def slow_record(request, user, db, body):
        """模拟「这台机器的写库就是慢」：真实的写入照做，只是先慢 0.35 秒"""
        time.sleep(SLOW_WRITE)
        return real_record(request, user, db, body)

    compat_routes._record_progress = slow_record          # noqa: SLF001
    box: dict = {}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
            async def report():
                box["resp"] = await api.post("/Sessions/Playing/Progress",
                                             headers=H, json=REPORT)

            elapsed, gap = await measure(report)
    finally:
        compat_routes._record_progress = real_record      # noqa: SLF001

    resp = box.get("resp")
    check("进度上报 → 200", resp is not None and resp.status_code == 200,
          f"HTTP {getattr(resp, 'status_code', '—')}")
    check("慢写确实发生了（0.35s 的活儿没被跳过）", elapsed >= SLOW_WRITE * 0.8,
          f"耗时={elapsed:.3f}s")
    check("这 0.35s 里事件循环保持响应（心跳空洞 < 0.15s）", gap < 0.15,
          f"心跳空洞={gap:.3f}s（改动前 ≈ {SLOW_WRITE:.2f}s）")

    with SessionLocal() as db:
        session = (db.query(em.PlaybackSession)
                   .filter(em.PlaybackSession.session_key == REPORT["PlaySessionId"]).first())
        umd = (db.query(em.UserMediaData)
               .filter(em.UserMediaData.user_id == user_id,
                       em.UserMediaData.item_id == item_id).first())
        check("会话真的落库了（下放线程池没耽误写）",
              session is not None and session.position_ticks == REPORT["PositionTicks"],
              f"position={getattr(session, 'position_ticks', None)}")
        check("观看进度真的落库了（「继续观看」的起点）",
              umd is not None and umd.playback_position_ticks == REPORT["PositionTicks"],
              f"position={getattr(umd, 'playback_position_ticks', None)}")

    # 不打补丁的真路由：一次正常上报同样写得进去（改动不改变语义）
    box.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as api:
        REPORT2 = dict(REPORT, PositionTicks=30_000_000_000)
        resp = await api.post("/Sessions/Playing/Progress", headers=H, json=REPORT2)
        check("正常上报 → 200", resp.status_code == 200, f"HTTP {resp.status_code}")
    with SessionLocal() as db:
        umd = (db.query(em.UserMediaData)
               .filter(em.UserMediaData.user_id == user_id,
                       em.UserMediaData.item_id == item_id).first())
        check("正常上报把位置更新到了新值",
              umd is not None and umd.playback_position_ticks == 30_000_000_000,
              f"position={getattr(umd, 'playback_position_ticks', None)}")

    # 结束播放：同样下放线程池，且真的把会话标结束
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as api:
        resp = await api.post("/Sessions/Playing/Stopped", headers=H, json=REPORT)
        check("结束上报 → 200", resp.status_code == 200, f"HTTP {resp.status_code}")
    with SessionLocal() as db:
        session = (db.query(em.PlaybackSession)
                   .filter(em.PlaybackSession.session_key == REPORT["PlaySessionId"]).first())
        check("结束上报把会话标成已结束", session is not None and session.ended_at is not None)


asyncio.run(section_hot_path())


# ==================== 收尾 ====================
print()
with SessionLocal() as db:
    db.query(em.UserMediaData).filter(em.UserMediaData.user_id == user_id).delete()
    db.query(em.PlaybackSession).filter(em.PlaybackSession.user_id == user_id).delete()
    for it in db.query(em.MediaItem).filter(em.MediaItem.library_id == library_id).all():
        db.query(em.MediaStream).filter(em.MediaStream.item_id == it.id).delete()
        db.delete(it)
    db.flush()
    db.query(em.Library).filter(em.Library.id == library_id).delete()
    db.query(em.EmbyApiToken).filter(em.EmbyApiToken.token == token).delete()
    db.query(models.WebUser).filter(models.WebUser.id == user_id).delete()
    db.commit()

for path in (DB, DB + "-wal", DB + "-shm"):
    try:
        os.remove(path)
    except OSError:
        pass

if failures:
    print(f"FAILED {len(failures)}/{TOTAL}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"ALL PASS {TOTAL}/{TOTAL}")
