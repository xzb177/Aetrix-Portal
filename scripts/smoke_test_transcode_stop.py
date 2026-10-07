"""HLS 转码停止：不得阻塞事件循环（v2.20.2）

``stop_transcode`` 要 terminate 子进程、等它退出（最多 5 秒）、再递归删掉整场播放的分片目录
（上千个文件，挂载目录上更慢）。它原先被 ``async def`` 路由直接调用（结束播放 / 结束他人会话 /
停掉全部转码），于是「停一次转码」就把整个进程卡住——与 v2.12/v2.13 修掉的是同一类问题，
它是漏网的那一个。

这里钉六件事：

1. **能测出阻塞**：在事件循环里直接调同步版本，后台心跳必须出现 ≥0.5s 的空洞
   （先自证测量方法有效，否则第 2 条没有说服力）；
2. **修复后不阻塞**：``await stop_transcode_async()`` 期间心跳最坏间隔 <0.3s，
   而调用自身确实花了 ≥0.5s（活儿真干了，只是不在循环上）；
   （2026-10-05：阈值从 0.15s 放宽到 0.3s——CI 负载下事件循环心跳抖动超 0.15s
   是常态，3 红 1 绿的系统性 flake；阻塞基线是 ≥0.5s，0.3s 仍有足够区分度）
   （2026-10-06：根因是心跳把 OS 调度抖动和事件循环阻塞混在一起量，绝对阈值在
   共享 CI 上必然 flake。改为时序断言测 3 次取最小——抖动随机、真阻塞确定，
   取最小不损失检出能力；5s 长测试单次测量、阈值放宽到 1.0s（阻塞特征 ~5s）。）
   （2026-10-06 v2：转码停止是摘除式的，非幂等——复用旧会话第 2 次测的是空操作。
   改为 measure_stable_fresh：每次测量都登记全新会话，杜绝空操作。）
3. **路由级**：结束自己的播放 / 管理员结束任意会话 / 停止全部转码三条 ``async`` 路由，
   在同一条事件循环里打进真实 app（ASGITransport），心跳同样只有很小的空洞；
4. **语义不变**：SIGTERM 不理就打 SIGKILL、会话目录被删、异常退出的 ffmpeg 日志尾部进服务日志、
   重复停与停不存在的会话都无害；
5. **并发**：``stop_all_transcodes_async`` 是并发停止（总耗时≈单个会话，不是 N 个之和）；
6. **回归护栏**：静态扫源码——任何 ``async def`` 里出现同步的 stop_transcode /
   stop_all_transcodes / stop_user_transcodes 即失败。

顺带钉住实现过程中发现并修掉的真 bug：结束播放原先拿**播放会话键**（客户端 ``PlaySessionId``，
随机 ``s…``）当转码会话 id 用，而转码会话 id 是 ``start_transcode`` 生成的 uuid、只出现在 HLS
播放列表的 ``?session=`` 上——两者对不上，等于什么都没停到。现在按「用户 + 条目 guid」反查。
"""
import ast
import asyncio
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "transcode-stop-smoke-secret-key-32"
DB = os.path.join(tempfile.mkdtemp(), "transcode-stop.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

import httpx  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import streaming  # noqa: E402
from backend.security import create_access_token  # noqa: E402

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


# ==================== 假 ffmpeg 进程与假会话目录 ====================

class FakeProc:
    """假转码进程：``wait()`` 真的睡（模拟 SIGTERM 之后还要写完手头分片）

    ``hang=True`` 时 ``wait`` 抛 ``TimeoutExpired``（SIGTERM 不理的进程），
    用来验证 ``stop_transcode`` 的 SIGKILL 兜底路径。
    """

    def __init__(self, seconds: float = 0.0, hang: bool = False, exit_code: int = 0):
        self.seconds = seconds
        self.hang = hang
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False
        self.exited = False

    def poll(self):
        return self.exit_code if self.exited else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        time.sleep(self.seconds)
        if self.hang:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        self.exited = True
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exited = True


def fake_session_dir(files: int = 40, log: str = "") -> str:
    """造一个像样的会话目录（分片 + ffmpeg 日志），返回路径"""
    directory = tempfile.mkdtemp(prefix="emby_transcode_smoke_")
    for i in range(files):
        with open(os.path.join(directory, f"seg{i:05d}.ts"), "wb") as handle:
            handle.write(b"\x47" * 188)
    if log:
        with open(os.path.join(directory, "ffmpeg.log"), "w", encoding="utf-8") as handle:
            handle.write(log)
    return directory


def register(proc: FakeProc, item_guid: str = "guid-x", user_id: int = 0,
             files: int = 40, log: str = "") -> tuple:
    """把一个假转码会话登记进 registry（形状与 start_transcode 完全一致）"""
    directory = fake_session_dir(files, log)
    session_id = f"tx{uuid.uuid4().hex[:12]}"
    streaming._TRANSCODE_PROCS[session_id] = {   # noqa: SLF001 — 测试就是要按真实结构登记
        "proc": proc,
        "dir": directory,
        "started": __import__("datetime").datetime.now(),
        "user_id": user_id,
        "item_guid": item_guid,
        "file_path": "/tmp/fake.mkv",
    }
    return session_id, directory


def registry_ids() -> set:
    return set(streaming._TRANSCODE_PROCS)   # noqa: SLF001


# ==================== 心跳：量事件循环被占住多久 ====================

class LoopWatch:
    """后台心跳任务：记录事件循环最坏一次「没能按时醒来」的间隔"""

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


async def measure(awaitable_factory, attempts: int = 1):
    """跑一段协程，返回 (耗时, 心跳最坏空洞)。

    attempts>1 时重复测量、取空洞最小的一次：OS 调度抖动是随机的（单次测量可能
    撞上尖刺），真正的事件循环阻塞是确定性的（每次测量都有）。取最小值不损失对
    真阻塞的检出能力，但把随机抖动造成误报的概率从 p 降到 p**attempts。
    """
    best_elapsed, best_gap = None, None
    for _ in range(max(1, attempts)):
        watch = LoopWatch()
        watch.start()
        # 先让心跳真正跑起来（记下基准时刻），否则第一次 sleep 之前就被阻塞时量不到
        await asyncio.sleep(watch.interval * 2)
        started = time.monotonic()
        await awaitable_factory()
        elapsed = time.monotonic() - started
        # 阻塞的时长是「心跳下一次醒来时才被看见」的，所以这里要再放一拍再收网，
        # 否则刚被卡住的循环还没机会把那段空隙记下来
        await asyncio.sleep(watch.interval * 2)
        gap = watch.stop()
        assert watch.ticks > 0, "心跳任务没跑起来，测量无效"
        if best_gap is None or gap < best_gap:
            best_elapsed, best_gap = elapsed, gap
    return best_elapsed, best_gap


async def measure_stable(awaitable_factory, attempts: int = 3):
    """对时序敏感且无状态的断言用这个（如纯 asyncio.sleep 对照）。

    有状态的操作（停转码：停一次会话即摘除）请用 measure_stable_fresh，
    否则第 2 次起测的是空操作。
    """
    return await measure(awaitable_factory, attempts=attempts)


async def measure_stable_fresh(fresh_factory, attempts: int = 3):
    """对时序敏感且有状态的断言用这个：每次测量都用全新状态。

    fresh_factory() 返回 (op, state)：op 是无参协程工厂（await op() 执行被测操作），
    state 是该次测量的状态（供后置断言用，如 sid/directory）。
    取心跳空洞最小的一次，返回 (elapsed, gap, best_state)。

    为什么必须每次全新：转码停止是摘除式（pop），停过的会话第 2 次调直接返回，
    不会再有 0.6s 的等待——复用旧状态测到的是空操作。
    """
    best = None
    for _ in range(max(1, attempts)):
        op_factory, state = fresh_factory()
        watch = LoopWatch()
        watch.start()
        await asyncio.sleep(watch.interval * 2)
        started = time.monotonic()
        await op_factory()
        elapsed = time.monotonic() - started
        await asyncio.sleep(watch.interval * 2)
        gap = watch.stop()
        assert watch.ticks > 0, "心跳任务没跑起来，测量无效"
        if best is None or gap < best[1]:
            best = (elapsed, gap, state)
    return best


# ==================== 1. 基线：同步版本确实会卡住循环 ====================
async def section_baseline():
    sid, _ = register(FakeProc(seconds=0.6))
    watch = LoopWatch()
    watch.start()
    await asyncio.sleep(watch.interval * 2)     # 先让心跳跑起来，否则量不到阻塞
    streaming.stop_transcode(sid)
    await asyncio.sleep(watch.interval * 2)     # 同上：放一拍再收网
    gap = watch.stop()
    check("基线自证：同步 stop_transcode 会卡住事件循环",
          gap >= 0.5, f"心跳空洞={gap:.3f}s（子进程等了 0.6s）")
    check("基线：同步版本确实把会话摘掉了", sid not in registry_ids())


# ==================== 2. 异步版本：活儿真干了，但循环没被占住 ====================
async def section_async():
    def _fresh():
        sid, directory = register(FakeProc(seconds=0.6))
        async def _op():
            await streaming.stop_transcode_async(sid)
        return _op, (sid, directory)
    elapsed, gap, (sid, directory) = await measure_stable_fresh(_fresh)
    check("异步停止：阻塞部分真的花了时间（0.6s 的等待没被跳过）",
          elapsed >= 0.5, f"耗时={elapsed:.3f}s")
    check("异步停止：期间事件循环保持响应（心跳空洞 <0.3s）",
          gap < 0.3, f"心跳空洞={gap:.3f}s")
    check("异步停止：会话目录已删除", not os.path.isdir(directory))
    check("异步停止：会话已从 registry 摘除", sid not in registry_ids())

    # 心跳任务本身是活的（防止「空洞小」是因为心跳压根没跑）
    _, gap2 = await measure_stable(lambda: asyncio.sleep(0.3))
    check("对照：空闲 0.3s 的心跳空洞同样很小（测量方法可信）",
          gap2 < 0.15, f"心跳空洞={gap2:.3f}s")

    # 真子进程（忽略 SIGTERM 的 python）：真的走完「等 5 秒 → SIGKILL → 删目录」，
    # 而事件循环在这 5 秒里始终是活的——这是最接近生产里 ffmpeg 卡死的形态
    real_dir = fake_session_dir(files=10)
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
    )
    real_id = f"txreal{uuid.uuid4().hex[:8]}"
    streaming._TRANSCODE_PROCS[real_id] = {   # noqa: SLF001
        "proc": child, "dir": real_dir, "started": __import__("datetime").datetime.now(),
        "user_id": 0, "item_guid": "guid-real", "file_path": "/tmp/real.mkv",
    }
    try:
        # 注：这里故意不用 measure_stable——5s x 3 次太慢。单次测量 + 1.0s 阈值：
        # 真阻塞的特征是 ~5s 的空洞（旧写法），1.0s 仍有 5 倍区分度，同时容忍 CI 抖动。
        elapsed, gap = await measure(lambda: streaming.stop_transcode_async(real_id))
        check("真子进程：等满 5 秒超时后才 SIGKILL（真的走完了阻塞路径）",
              elapsed >= 4.5 and child.poll() is not None, f"耗时={elapsed:.2f}s")
        check("真子进程：这 5 秒里事件循环保持响应（心跳空洞 <1.0s）",
              gap < 1.0, f"心跳空洞={gap:.3f}s（旧写法会是 ~5s）")
        check("真子进程：会话目录已删", not os.path.isdir(real_dir))
    finally:
        if child.poll() is None:
            child.kill()
        streaming._TRANSCODE_PROCS.pop(real_id, None)   # noqa: SLF001


# ==================== 3. 语义：与同步版本逐条一致 ====================
async def section_semantics():
    # SIGTERM 不理 → SIGKILL 兜底
    log_text = "Error while opening encoder for output stream #0:0\nConversion failed\n"
    proc = FakeProc(seconds=0.2, hang=True, exit_code=-9)
    sid, directory = register(proc, files=5, log=log_text)
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    streaming_logger = logging.getLogger("backend.emby_server.streaming")
    streaming_logger.addHandler(handler)
    try:
        await streaming.stop_transcode_async(sid)
    finally:
        streaming_logger.removeHandler(handler)
    check("SIGTERM 不理时打 SIGKILL 兜底", proc.killed and proc.terminated)
    check("异常退出（-9）会把 ffmpeg 日志尾部提到服务日志",
          any("异常退出" in r and "encoder" in r for r in records), str(records)[:120])
    check("会话目录照样删掉", not os.path.isdir(directory))

    # 进程已退出 → 不再 terminate
    quiet = FakeProc(exit_code=0)
    quiet.exited = True
    sid, _ = register(quiet)
    await streaming.stop_transcode_async(sid)
    check("进程已退出时不再 terminate", not quiet.terminated)

    # 重复停 / 停不存在的会话都是无害的
    await streaming.stop_transcode_async(sid)
    await streaming.stop_transcode_async("tx-not-exist")
    streaming.stop_transcode("tx-not-exist")
    check("重复停 / 停不存在的会话都无害（幂等）", True)

    # 只停「这个人这个条目」的转码，不误伤别人
    sid_mine, dir_mine = register(FakeProc(seconds=0.05), item_guid="guid-a", user_id=7)
    sid_other_item, dir_other = register(FakeProc(seconds=0.05), item_guid="guid-b", user_id=7)
    sid_other_user, dir_other_user = register(FakeProc(seconds=0.05), item_guid="guid-a", user_id=8)
    stopped = await streaming.stop_transcodes_for_async(7, item_guid="guid-a")
    check("按「用户 + 条目 guid」只停目标转码", stopped == 1, f"停了 {stopped} 个")
    check("同一用户的别的条目不受影响", sid_other_item in registry_ids())
    check("别的用户的同一条目不受影响", sid_other_user in registry_ids())
    await streaming.stop_all_transcodes_async()
    check("清理：收尾把剩余会话都停掉", not registry_ids(), str(registry_ids()))


# ==================== 4. 并发：全部转码一起停 ====================
async def section_concurrency():
    def _fresh():
        for _ in range(4):
            register(FakeProc(seconds=0.4))
        async def _op():
            await streaming.stop_all_transcodes_async()
        return _op, None
    elapsed, gap, _ = await measure_stable_fresh(_fresh)
    check("停掉全部转码是并发执行（4×0.4s 的会话总耗时 <1s，逐个等会是 1.6s+）",
          elapsed < 1.0, f"耗时={elapsed:.3f}s")
    check("并发停止期间事件循环同样保持响应", gap < 0.3, f"心跳空洞={gap:.3f}s")
    check("并发停止把 4 个会话都摘掉了", not registry_ids(), str(registry_ids()))


# ==================== 5. 路由级：真实 app + 同一条事件循环 ====================

suffix = uuid.uuid4().hex[:6]
with SessionLocal() as db:
    owner = models.WebUser(username=f"tx_owner{suffix}", password_hash="x", is_active=True)
    staff = models.WebUser(username=f"tx_staff{suffix}", password_hash="x", is_active=True, is_staff=True, admin_role="super")
    db.add_all([owner, staff])
    db.commit()
    db.refresh(owner)
    db.refresh(staff)

    library = em.Library(guid=f"lib-tx-{suffix}", name="转码停止测试库", collection_type="movies", paths="/tmp")
    db.add(library)
    db.commit()
    db.refresh(library)
    movie = em.MediaItem(guid=f"item-tx-{suffix}", library_id=library.id, item_type="movie",
                         name="转码停止测试片", duration_ticks=60_000_000_000)
    db.add(movie)
    db.commit()
    db.refresh(movie)

    owner_key = f"s{owner.id}-{suffix}"
    staff_key = f"t{staff.id}-{suffix}"
    db.add_all([
        em.PlaybackSession(session_key=owner_key, user_id=owner.id, item_id=movie.id),
        em.PlaybackSession(session_key=staff_key, user_id=staff.id, item_id=movie.id),
    ])
    db.commit()
    movie_guid, owner_id, staff_id = movie.guid, owner.id, staff.id

OWNER_H = {"Authorization": f"Bearer {create_access_token(owner_id, {'username': 'owner'})}"}
STAFF_H = {"Authorization": f"Bearer {create_access_token(staff_id, {'username': 'staff'})}"}


def session_row(key: str):
    with SessionLocal() as db:
        return (db.query(em.PlaybackSession)
                .filter(em.PlaybackSession.session_key == key).first())


async def section_routes():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:

        # 5.1 结束自己的播放：真的释放转码进程，且不卡循环
        #     （播放会话键与转码会话 id 不同 —— 这条同时是那个真 bug 的回归护栏）
        box: dict = {}

        def _fresh_mine():
            # 每次测量前重新登记转码会话（上一次的已被停掉摘除）；播放会话在 DB 里，
            # 路由对已结束的会话仍返回 200（幂等），可复用。
            sid, directory = register(FakeProc(seconds=0.5), item_guid=movie_guid, user_id=owner_id)
            async def _op():
                box["resp"] = await api.delete(
                    f"/api/user/emby/sessions/{owner_key}", headers=OWNER_H)
            return _op, (sid, directory)

        elapsed, gap, (sid, directory) = await measure_stable_fresh(_fresh_mine)
        resp = box["resp"]
        check("结束自己的播放 → 200", resp.status_code == 200, f"实际 {resp.status_code}")
        check("结束播放真的停掉了对应转码（播放会话键 ≠ 转码 id）",
              sid not in registry_ids(), str(registry_ids()))
        check("结束播放后转码目录被清理", not os.path.isdir(directory))
        check("结束播放这条 async 路由不阻塞事件循环", gap < 0.3, f"心跳空洞={gap:.3f}s")
        check("结束播放的会话已标记结束", session_row(owner_key).ended_at is not None)

        # 5.2 管理员结束他人会话
        box = {}

        def _fresh_admin():
            sid, _ = register(FakeProc(seconds=0.5), item_guid=movie_guid, user_id=staff_id)
            async def _op():
                box["resp"] = await api.delete(
                    f"/api/admin/emby/sessions/{staff_key}", headers=STAFF_H)
            return _op, sid

        elapsed, gap, sid = await measure_stable_fresh(_fresh_admin)
        resp = box["resp"]
        check("管理员结束会话 → 200", resp.status_code == 200, f"实际 {resp.status_code}")
        check("管理员结束会话同样释放转码", sid not in registry_ids(), str(registry_ids()))
        check("管理员结束会话这条 async 路由不阻塞事件循环", gap < 0.3, f"心跳空洞={gap:.3f}s")

        # 5.3 停止全部转码（N 路一起停）
        box = {}

        def _fresh_all():
            for _ in range(3):
                register(FakeProc(seconds=0.4), item_guid=movie_guid, user_id=owner_id)
            async def _op():
                box["resp"] = await api.post(
                    "/api/admin/emby/transcodes/stop-all", headers=STAFF_H)
            return _op, None

        elapsed, gap, _ = await measure_stable_fresh(_fresh_all)
        resp = box["resp"]
        check("停止全部转码 → 200 且报了数量",
              resp.status_code == 200 and resp.json()["stopped"] == 3, resp.text[:120])
        check("停止全部转码真的清空 registry", not registry_ids(), str(registry_ids()))
        check("停止全部转码是并发 + 不阻塞事件循环（3×0.4s <1s）",
              elapsed < 1.0 and gap < 0.3, f"耗时={elapsed:.3f}s 空洞={gap:.3f}s")

        # 5.4 兼容路径（同步 def 路由，走线程池）：同样能停掉转码
        sid, _ = register(FakeProc(seconds=0.3), item_guid=movie_guid, user_id=owner_id)
        resp = await api.delete(f"/Sessions/{owner_key}", headers=OWNER_H)
        check("兼容端点 DELETE /Sessions/{key} → 200", resp.status_code == 200,
              f"实际 {resp.status_code}")
        check("兼容端点同样按「用户 + 条目」释放转码", sid not in registry_ids(), str(registry_ids()))


# ==================== 6. 静态护栏：async 里不许出现同步停止 ====================

SYNC_STOP_NAMES = {"stop_transcode", "stop_all_transcodes", "stop_user_transcodes"}


def scan_async_blocking_stops(root: str = "backend") -> list:
    """找出「async 函数里调用了同步停止实现」的地方（AST 精确匹配，不受注释/文档字符串干扰）"""
    found = []
    for path in sorted(pathlib.Path(root).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover — 语法错误另有检查
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                func = sub.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in SYNC_STOP_NAMES:
                    found.append(f"{path}:{sub.lineno} async def {node.name} → {name}()")
    return found


def section_static_guard():
    bad = scan_async_blocking_stops()
    check("没有任何 async 函数调用同步的 stop_transcode / stop_all_transcodes / stop_user_transcodes",
          not bad, "; ".join(bad))
    portal = pathlib.Path("backend/emby_server/portal.py").read_text()
    check("结束播放/结束会话/停止全部转码三条路由都用了异步变体",
          "stop_transcodes_for_async(" in portal and "stop_all_transcodes_async(" in portal)
    check("stop_transcode 的文档字符串写明了「不要在 async def 里直接调它」",
          "不要在 ``async def`` 里直接调它" in pathlib.Path(
              "backend/emby_server/streaming.py").read_text())


async def main():
    await section_baseline()
    await section_async()
    await section_semantics()
    await section_concurrency()
    await section_routes()
    section_static_guard()


asyncio.run(main())

streaming._TRANSCODE_PROCS.clear()   # noqa: SLF001 — 收尾，别把假会话留在进程里

print()
if failures:
    print(f"❌ 转码停止冒烟失败（{len(failures)}/{TOTAL} 项失败）：{failures}")
    sys.exit(1)
print(f"✅ 转码停止冒烟全部通过（{TOTAL} 项）")
