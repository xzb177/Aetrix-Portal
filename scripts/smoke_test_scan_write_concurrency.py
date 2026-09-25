#!/usr/bin/env python3
"""扫描 × 写接口并发冒烟（v2.38.0）：写事务里不再等网络

要解决的问题是线上现场：后台点一次媒体库**全量扫描**，前端点什么都要转 30 秒，
最后是 ``sqlite3.OperationalError: database is locked``（2 分钟内 9 次），
WAL 文件 4.3MB 长期不 checkpoint。

根因不是 WAL、也不是 ``busy_timeout`` 配置（`backend/database.py` 里那 30 秒是对的），
而是**事务范围**：扫描器在写事务还没提交的时候去等网络（rclone 列目录 / TMDB 刮削 /
ffprobe），SQLite 只有一个写者，写锁就被按在网络 RTT 上；别的写请求一路等到
``busy_timeout`` 耗尽才报错，前端看到的就是 30 秒超时。

这个脚本钉住三条事实（都在真实扫描与真实 HTTP 路由上量，不靠“看起来没问题”）：

1. **写事务里零 IO**（原子判据）。给扫描器真正会走的 IO 出口（``os.listdir`` /
   ffprobe / TMDB 会话）装上探针，探针只看一件事：**当前线程是不是正持有一个
   未提交的写事务**——是就记一次违规。旧形态（写事务里 ``db.flush()`` 之后列目录、
   或者刮削段 ``search`` / ``enrich`` / ``refresh_images`` 与 session 写操作交错）
   必然记到违规。探针本身先自证有效：人为在写事务里做一次同样的 IO，必须被记到。
2. **扫描与写接口并发不互相拖死**。一边跑整库全量扫描，一边循环打真实写接口
   （``POST /api/admin/economy/plans``），逐个请求量延迟：全部成功、没有 5xx、
   没有 ``database is locked``，而且每一次都远在前端 30 秒超时以内。
3. **批次数不止一个**（``SCAN_BATCH=40``）：让「预取 IO → 纯写事务 → 预取 IO」
   交替出现，这才是线上真正发生的节奏——一批一段写锁窗口。

用法：python scripts/smoke_test_scan_write_concurrency.py
"""
from __future__ import annotations

import logging
import os
import statistics
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "scan-write-concurrency-smoke-key-32b"
WORK = tempfile.mkdtemp(prefix="scan-write-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(WORK, 'scan-write.db')}"
# 多批次：写锁的占用窗口才看得清（默认 400 的文件量会挤成一批）
os.environ["SCAN_BATCH"] = "40"
os.environ["SCAN_WORKERS"] = "4"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event as sa_event  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, engine, init_db  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import scanner as sc  # noqa: E402
from backend.security import hash_password  # noqa: E402

init_db()

from backend.main import app  # noqa: E402

failures: list[str] = []
TOTAL_CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global TOTAL_CHECKS
    TOTAL_CHECKS += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


# ==================== 观测装置 ====================
# 「线程正持有未提交写事务」= 该线程执行过写语句（INSERT/UPDATE/DELETE），
# 并且还没等到 commit / rollback。写在 before_cursor_execute 上认语句，
# 清在引擎的 commit / rollback 事件上——与扫描器里 db.commit = db.flush 的
# monkeypatch 无关（那个 patch 只换 Python 方法，事务边界仍在数据库层）。

_STATE_LOCK = threading.Lock()
_WRITE_TXN: set[int] = set()
IO_IN_WRITE_TXN: list[str] = []
WRITE_TXN_SPANS: list[tuple[str, float]] = []   # (线程名, 持续时间) —— 写给谁看的都一样
_TXN_STARTED: dict[int, float] = {}
_WRITE_HEADS = ("INSERT", "UPDATE", "DELETE", "REPLACE")


def _io_probe(kind: str) -> None:
    ident = threading.get_ident()
    with _STATE_LOCK:
        if ident in _WRITE_TXN:
            IO_IN_WRITE_TXN.append(f"{kind}@{threading.current_thread().name}")


def _on_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
    head = statement.lstrip()[:8].upper()
    if not head.startswith(_WRITE_HEADS):
        return
    ident = threading.get_ident()
    with _STATE_LOCK:
        if ident not in _WRITE_TXN:
            _TXN_STARTED[ident] = time.perf_counter()
        _WRITE_TXN.add(ident)


def _close_txn() -> None:
    ident = threading.get_ident()
    with _STATE_LOCK:
        if ident in _WRITE_TXN:
            _WRITE_TXN.discard(ident)
            started = _TXN_STARTED.pop(ident, None)
            if started is not None:
                WRITE_TXN_SPANS.append((threading.current_thread().name,
                                        time.perf_counter() - started))


sa_event.listen(engine, "before_cursor_execute", _on_cursor_execute)
sa_event.listen(engine, "commit", lambda conn: _close_txn())
sa_event.listen(engine, "rollback", lambda conn: _close_txn())

# 「database is locked」与写锁兜底重试都从日志里数：前者一次都不许有，
# 后者（commit_with_retry 的退避重试）是观测值——它意味着有人短暂占着写锁，但请求救回来了。


class LockLogRecorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.locked: list[str] = []
        self.retries: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001 — 日志格式化失败不该影响被测行为
            return
        if "database is locked" in text:
            self.locked.append(text)
        if "SQLite 写锁" in text:
            self.retries.append(text)


recorder = LockLogRecorder()
logging.getLogger().addHandler(recorder)
# 逐条请求的 httpx INFO 会把输出淹掉；它的 WARNING（连接异常之类）照旧进 recorder
logging.getLogger("httpx").setLevel(logging.WARNING)

# ==================== 造一批假媒体 ====================
MOVIES = 120
SERIES = 2
EPISODES = 6
PROBE_DELAY = 0.03    # 模拟 ffprobe 的等待
TMDB_DELAY = 0.03     # 模拟 TMDB 的网络往返
LISTDIR_DELAY = 0.01  # 模拟远程挂载列目录

LIB_DIR = tempfile.mkdtemp(prefix="scanwrite_")
movie_dir = os.path.join(LIB_DIR, "Movies")
os.makedirs(movie_dir, exist_ok=True)
for i in range(MOVIES):
    name = f"Concurrency Movie {i:03d} (2021)"
    with open(os.path.join(movie_dir, f"{name}.mkv"), "wb") as f:
        f.write(b"\x00" * 2048)
    # 外挂字幕：旧实现在写事务里 flush 之后才去列目录找它
    with open(os.path.join(movie_dir, f"{name}.chi.srt"), "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

for s in range(SERIES):
    sdir = os.path.join(LIB_DIR, f"Concurrency Show {s}", "Season 1")
    os.makedirs(sdir, exist_ok=True)
    for e in range(1, EPISODES + 1):
        with open(os.path.join(sdir, f"Concurrency Show {s} S01E{e:02d}.mkv"), "wb") as f:
            f.write(b"\x00" * 2048)

TOTAL_FILES = MOVIES + SERIES * EPISODES


# ---- IO 出口装探针 ----
real_listdir = os.listdir


def guarded_listdir(path):  # noqa: ANN001
    _io_probe("os.listdir")
    if isinstance(path, str) and path.startswith(LIB_DIR):
        time.sleep(LISTDIR_DELAY)
    return real_listdir(path)


def fake_probe_metadata(path, headers=None, size=0):  # noqa: ANN001, ARG001
    _io_probe("ffprobe")
    time.sleep(PROBE_DELAY)  # 真实场景是几十到几百毫秒，远程挂载上更久
    return {
        "duration_ticks": 600_000_000, "bitrate": 1_000_000, "width": 1920, "height": 1080,
        "video_codec": "H264", "audio_codec": "AAC", "audio_languages": "chi",
        "subtitle_languages": "", "size": size or 2048,
        "streams": [
            {"stream_index": 0, "stream_type": "Video", "codec": "h264", "language": "",
             "display_title": None, "title": None, "channels": None, "bit_rate": 1_000_000},
            {"stream_index": 1, "stream_type": "Audio", "codec": "aac", "language": "chi",
             "display_title": None, "title": None, "channels": 2, "bit_rate": 128_000},
        ],
    }


class FakeResp:
    def __init__(self, payload) -> None:  # noqa: ANN001
        self.status_code = 200
        self._payload = payload

    def json(self):  # noqa: ANN201
        return self._payload


class ProbedTmdbSession:
    """TMDB 会话：先记探针（旧形态里这些请求发生在写事务内），再返回假数据"""

    def get(self, url, params=None):  # noqa: ANN001
        _io_probe("TMDB")
        time.sleep(TMDB_DELAY)
        if "/search/" in url:
            query = (params or {}).get("query") or ""
            return FakeResp({"results": [{"id": abs(hash(query)) % 900000 + 1,
                                          "title": query, "name": query, "vote_average": 7.0}]})
        return FakeResp({
            "poster_path": "/poster.jpg", "backdrop_path": "/backdrop.jpg",
            "external_ids": {"imdb_id": "tt0000001"},
            "alternative_titles": {"titles": [{"title": "别名"}]},
        })


# ==================== 播种 ====================
with SessionLocal() as db:
    staff = models.WebUser(username="scanwrite_staff",
                           password_hash=hash_password("scanwritepass123"),
                           is_staff=True, is_active=True)
    db.add(staff)
    db.commit()
    library = em.Library(guid="c" * 32, name="并发扫描库", collection_type="movies",
                         paths=LIB_DIR)
    db.add(library)
    db.commit()
    lib_id = library.id

client = TestClient(app)

r = client.post("/api/user/auth/login",
                json={"username": "scanwrite_staff", "password": "scanwritepass123"})
ADMIN_H = {"Authorization": f"Bearer {r.json()['access_token']}"}

# ==================== 0. 探针自证：写事务里做 IO 必须被记到 ====================
# 先证明测量方法有效：如果探针永远记不到违规，那第 1 节的 0 次违规什么也不能说明。
proof_before = len(IO_IN_WRITE_TXN)
with SessionLocal() as db:
    db.add(models.SubscriptionPlan(name="探针自证用套餐", price=1, duration_days=1,
                                   is_active=True))
    db.flush()                            # 写事务由此打开
    guarded_listdir(tempfile.gettempdir())  # 旧形态：事务没提交就去做 IO
    db.rollback()
proof = len(IO_IN_WRITE_TXN) - proof_before
check("探针自证：写事务里做 IO 会被记到违规", proof == 1, f"记到 {proof} 次")

# ==================== 1. 扫描 + 并发写接口 ====================
sc.probe_metadata = fake_probe_metadata
sc.tmdb_client.session = ProbedTmdbSession()
sc.tmdb_client.api_keys = ["fake-key"]
sc.tmdb_client.api_key = "fake-key"
sc.tmdb_client._cache.clear()
os.listdir = guarded_listdir

violations_before = len(IO_IN_WRITE_TXN)
spans_before = len(WRITE_TXN_SPANS)

write_results: list[tuple[int, float, str]] = []
stop_writer = threading.Event()


def writer_loop() -> None:
    """循环打真实写接口（管理员建套餐）——就是用户报告里「前端点一下」的那条路"""
    i = 0
    while not stop_writer.is_set():
        i += 1
        started = time.perf_counter()
        try:
            resp = client.post("/api/admin/economy/plans", headers=ADMIN_H,
                               json={"name": f"并发套餐 {i:03d}", "price": 9.9,
                                     "duration_days": 30})
            write_results.append((resp.status_code, time.perf_counter() - started,
                                  resp.text[:200]))
        except Exception as exc:  # noqa: BLE001 — 5xx / 超时都从这里冒出来
            write_results.append((0, time.perf_counter() - started,
                                  f"{type(exc).__name__}: {exc}"[:200]))
        time.sleep(0.02)


writer = threading.Thread(target=writer_loop, name="api-writer", daemon=True)
writer.start()
deadline = time.time() + 20
while len(write_results) < 3 and time.time() < deadline:   # 预热：先让接口热起来
    time.sleep(0.02)

db = SessionLocal()
lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
scan_started = time.time()
stats = sc.scan_library_sync(db, lib)
scan_elapsed = time.time() - scan_started
db.close()

stop_writer.set()
writer.join(timeout=15)
os.listdir = real_listdir

# ==================== 2. 断言 ====================
violations = IO_IN_WRITE_TXN[violations_before:]
spans = WRITE_TXN_SPANS[spans_before:]

with SessionLocal() as db:
    by_kind: dict[str, int] = {}
    for item_type in ("movie", "series", "episode"):
        by_kind[item_type] = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == lib_id,
            em.MediaItem.item_type == item_type,
        ).count()
    subtitle_tracks = db.query(em.MediaStream).filter(
        em.MediaStream.is_external.is_(True)).count()
    created_plans = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.name.like("并发套餐 %")).count()

latencies = [lat for _, lat, _ in write_results]
statuses = [code for code, _, _ in write_results]
bad = [(code, text) for code, _, text in write_results if code != 200]

print("\n—— 扫描 ——")
print(f"  文件 {TOTAL_FILES} 个 | 条目 {by_kind} | 外挂字幕轨 {subtitle_tracks}")
print(f"  耗时 {scan_elapsed:.2f}s | 统计 {stats}")
print("—— 并发写接口 ——")
print(f"  请求 {len(write_results)} 次 | 状态码 {sorted(set(statuses))}"
      f" | 落库套餐 {created_plans} 个")
if latencies:
    print(f"  延迟 中位 {statistics.median(latencies) * 1000:.0f}ms"
          f" / p95 {sorted(latencies)[int(len(latencies) * 0.95) - 1 if len(latencies) > 1 else 0] * 1000:.0f}ms"
          f" / 最大 {max(latencies) * 1000:.0f}ms（前端超时是 30000ms）")
print(f"  扫描期间的写事务 {len(spans)} 段"
      + (f"，最长 {max(s[1] for s in spans) * 1000:.0f}ms" if spans else ""))
print(f"  database is locked 日志 {len(recorder.locked)} 条"
      f" | 写锁兜底重试 {len(recorder.retries)} 次")

check("全量扫描把整库都入库了（不是在空跑）",
      by_kind["movie"] == MOVIES and by_kind["series"] == SERIES
      and by_kind["episode"] == SERIES * EPISODES,
      f"电影={by_kind['movie']}/{MOVIES} 剧={by_kind['series']}/{SERIES}"
      f" 集={by_kind['episode']}/{SERIES * EPISODES}")
check("外挂字幕仍按文件识别入库", subtitle_tracks == MOVIES,
      f"字幕轨={subtitle_tracks} 期望={MOVIES}")
check("扫描全程没有一次 IO 落在未提交的写事务里", not violations,
      f"违规 {len(violations)} 次" + (f"：{violations[:5]}" if violations else ""))
check("扫描与写接口并发时写事务是短窗口（不是被网络按住的 30 秒）",
      not spans or max(s[1] for s in spans) < 3.0,
      f"最长 {max((s[1] for s in spans), default=0.0) * 1000:.0f}ms（旧形态会等于网络 IO 时长）")
check("并发写接口全部成功（没有 5xx / 连接异常）", not bad,
      f"异常响应 {bad[:3]}")

check("并发写接口的请求数够多（真的在扫描期间持续打）", len(write_results) >= 20,
      f"共 {len(write_results)} 次")
check("并发写接口每次都在前端 30 秒超时以内（含最坏一次）",
      bool(latencies) and max(latencies) < 5.0,
      f"最大 {max(latencies, default=0.0):.2f}s（阈值 5s，前端超时 30s）")
check("并发写接口的典型延迟是毫秒级（扫描没能把它拖慢）",
      bool(latencies) and statistics.median(latencies) < 1.0,
      f"中位 {statistics.median(latencies, ) * 1000:.0f}ms" if latencies else "无请求")
check("并发写的套餐真的落库了（接口不是假成功）", created_plans == len(write_results),
      f"落库 {created_plans} 个 / 成功请求 {len(write_results)} 次")
check("全程没有 database is locked", not recorder.locked,
      f"{recorder.locked[:2]}")

print("\n" + "=" * 60)
if failures:
    print(f"❌ 扫描 × 写接口并发冒烟失败（{len(failures)}/{TOTAL_CHECKS} 项）：")
    for name in failures:
        print("   -", name)
    sys.exit(1)
print(f"✅ 扫描 × 写接口并发冒烟全部通过（{TOTAL_CHECKS} 项）")
