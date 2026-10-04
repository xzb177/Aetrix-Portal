"""封面「新片入库后自动更新」（v2.43.1，v2.48.0 起改为**异步入队**）

开关本身很简单，真正要钉住的是**它什么时候做、什么时候不做**：

- 默认关闭，不开就一个字节的行为都不变；
- 开了但**本轮没新增条目** → 不排队（“自动更新”该跟“新片”绑定，
  否则每次扫一下都白白渲染一次 + 让客户端缓存失效）；
- 开了但**没选封面样式** → 不排队（没有可复用的配置，重画必然失败）；
- **扫描与封面渲染彻底解耦**：扫描尾部只入队，渲染交给后台线程；
- 排队期间同一个库再来多少次都只算**一个**任务（转场 200 个文件 → 1 次渲染）；
- 画不出来（库里没海报 / 没装 Pillow / 渲染崩了）**绝不能影响扫描结果落库**，
  也不能把已经生成的旧封面弄丢。

不碰网络、不碰生产库：渲染函数与文件写入都在这里打桩。
"""
import os
import threading
import time

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import models as em
from backend.emby_server import scanner
from backend.integrations import store


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    store.invalidate()
    yield session
    store.invalidate()
    session.close()


def _library(db, **kw):
    name = kw.pop("name", "电影库")
    lib = em.Library(guid=f"g-{name}", name=name, collection_type="movies", **kw)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


# ==================== 开关的默认值与存取 ====================

def test_column_defaults_to_off():
    assert em.Library.__table__.c.cover_auto_regen.default.arg is False


def test_old_row_without_column_reads_as_off(db):
    """老库补列后是 0 / NULL：不能因此报错，也不能默认变成开启"""
    lib = _library(db, name="老库")
    db.execute(text("UPDATE emby_libraries SET cover_auto_regen = NULL"))
    db.commit()
    db.expire_all()
    db.refresh(lib)

    assert bool(getattr(lib, "cover_auto_regen", False)) is False


# ==================== 什么时候该排队 ====================

class _RecordingQueue:
    """记录封面重生成被**入队**了几次

    打在 :func:`enqueue_cover_regeneration` 上：扫描器是**延迟导入**这个函数的
    （否则 backend.api 与 emby_server 会成环），所以打模块属性一样能拦住——这也
    顺带证明了自动路径走的就是这一段，而不是另外抄了一份同步渲染。
    """

    def __init__(self, created=True):
        self.calls = []
        self._created = created

    def __call__(self, lib_id):
        self.calls.append(lib_id)
        return self._created


@pytest.fixture()
def cover(monkeypatch):
    from backend.api import library_cover as lc

    rec = _RecordingQueue()
    monkeypatch.setattr(lc, "enqueue_cover_regeneration", rec)
    return rec


def _run_scan(db, lib, **stats):
    """只跑 finish_scan 那一段：扫描本身在别的测试里覆盖，这里只关心扫完之后"""
    scanner.finish_scan(db, lib, {"added": 0, "updated": 0, **stats}, None)


def test_nothing_happens_when_switch_off(db, cover):
    lib = _library(db, name="关着", cover_template="poster")

    _run_scan(db, lib, added=10)

    assert cover.calls == []


def test_nothing_happens_without_template(db, cover):
    """开了开关但没选样式：没有可复用的配置，重画必然失败，不如什么都不做"""
    lib = _library(db, name="没样式", cover_auto_regen=True)

    _run_scan(db, lib, added=10)

    assert cover.calls == []


def test_nothing_happens_when_no_new_items(db, cover):
    """本轮没新增 → 封面本来就是最新的，重画只是白白花渲染时间"""
    lib = _library(db, name="没新片", cover_template="poster", cover_auto_regen=True)

    _run_scan(db, lib, added=0, updated=7)

    assert cover.calls == []


def test_enqueues_when_switch_on_and_has_new_items(db, cover):
    lib = _library(db, name="自动", cover_template="poster", cover_auto_regen=True)

    _run_scan(db, lib, added=3)

    assert cover.calls == [lib.id]
    # 扫描不再同步渲染：这一行还停在原样，封面由后台线程写
    db.expire_all()
    db.refresh(lib)
    assert lib.cover_path is None


def test_enqueues_on_partial_scan_too(db, cover):
    """部分来源读不到（partial）也算“扫完了”：新片确实进来了就更新

    封面不该因为这一轮有个目录没挂上就停摆——那正是最需要新海报的时候。
    """
    lib = _library(db, name="部分", cover_template="visual", cover_auto_regen=True)

    _run_scan(db, lib, added=1, removal_skipped=True, failed_roots=["/gone"])

    assert cover.calls == [lib.id]


# ==================== 与扫描解耦：扫描线程里一次都不渲染 ====================

def test_scan_thread_never_renders_cover_itself(db, monkeypatch):
    """渲染必须发生在后台线程：慢的渲染器不许拖住一轮扫描

    同步渲染时这里会真的去调 render_cover_bytes —— 现在扫描线程一次都不碰它。
    """
    from backend.api import library_cover as lc

    def boom(*args, **kwargs):
        raise AssertionError("扫描线程里不允许渲染封面")

    monkeypatch.setattr(lc, "render_cover_bytes", boom)
    monkeypatch.setattr(lc, "_write_generated_cover", boom)
    rec = _RecordingQueue()
    monkeypatch.setattr(lc, "enqueue_cover_regeneration", rec)
    lib = _library(db, name="解耦", cover_template="poster", cover_auto_regen=True)

    status = scanner.finish_scan(db, lib, {"added": 2}, None)

    assert status == scanner.SCAN_STATUS_SUCCESS
    assert rec.calls == [lib.id]


# ==================== 画不出来不能影响扫描结果 ====================

def test_enqueue_failure_does_not_break_scan_result(db, monkeypatch):
    """入队就炸（Pillow 没装 / 队列模块坏了）→ 扫描结果照样落库"""
    from backend.api import library_cover as lc

    def boom(lib_id):
        raise RuntimeError("Pillow 没装")

    monkeypatch.setattr(lc, "enqueue_cover_regeneration", boom)
    lib = _library(db, name="会失败", cover_template="poster", cover_auto_regen=True)

    status = scanner.finish_scan(db, lib, {"added": 5}, None)

    # 扫描结果照样落库
    assert status == scanner.SCAN_STATUS_SUCCESS
    assert lib.scan_status == scanner.SCAN_STATUS_SUCCESS
    assert lib.last_scan_at is not None


def test_enqueue_runs_after_scan_state_is_already_committed(db, monkeypatch):
    """入队钩子跑在两次提交**之后**

    以前封面渲染就在这条路径上，出错时还要回滚一次会话——回滚会把刚落库的扫描结果
    一起带回去。异步之后钩子只做「记一笔 + 返回」，观察它被调用时扫描状态**已经**
    在库里了，这条路就不可能再把扫描结果拖下水。
    """
    from backend.api import library_cover as lc

    seen = {}

    def enqueue(lib_id):
        row = db.execute(
            text("SELECT scan_status FROM emby_libraries WHERE id = :i"),
            {"i": lib_id},
        ).first()
        seen["scan_status"] = row[0] if row else None
        return True

    monkeypatch.setattr(lc, "enqueue_cover_regeneration", enqueue)
    lib = _library(db, name="提交后", cover_template="poster", cover_auto_regen=True)

    scanner.finish_scan(db, lib, {"added": 5}, None)

    assert seen["scan_status"] == scanner.SCAN_STATUS_SUCCESS


# ==================== 异步队列本身的行为 ====================

class _SessionProxy:
    """把后台 worker 的 db 指到测试会话，且 ``close()`` 不真的关掉它

    worker 自己开 SessionLocal 并在结束时 close；测试里我们共用一条连接
    （StaticPool），让它关掉会话只会把用例的后半段一起带走。
    """

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


@pytest.fixture()
def cover_worker(db, monkeypatch):
    """真的把后台封面线程跑起来（渲染打桩），用完停掉并清空队列状态"""
    from backend import database as db_mod
    from backend.api import library_cover as lc

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: _SessionProxy(db))
    monkeypatch.setattr(lc, "COVER_MIN_INTERVAL_SEC", 0.0)
    lc.stop_cover_worker(timeout=2.0)
    with lc._COVER_LOCK:
        lc._COVER_PENDING.clear()
        lc._COVER_RUNNING.clear()
        lc._COVER_STATUS.clear()
    yield lc
    lc.stop_cover_worker(timeout=5.0)
    with lc._COVER_LOCK:
        lc._COVER_PENDING.clear()
        lc._COVER_RUNNING.clear()
        lc._COVER_STATUS.clear()


def _wait_state(lc, lib_id, states, timeout=10.0):
    deadline = time.time() + timeout
    seen = {}
    while time.time() < deadline:
        seen = lc.cover_status(lib_id)
        if seen.get("state") in states:
            return seen
        time.sleep(0.02)
    raise AssertionError(f"封面任务没等到状态 {states}，最后一次是 {seen}")


def test_repeated_scans_merge_into_one_render_task(db, cover_worker, monkeypatch):
    """同一库在排队/渲染期间反复入队 → 只渲染一次

    转场一批新片时每轮扫描收尾都会想更新封面；不合并就是同一轮连着渲染十几次。
    """
    rendered = []

    def render(db_, lib):
        rendered.append(lib.id)
        lib.cover_path = f"library-covers/{lib.guid}.webp"
        return lib.cover_path

    monkeypatch.setattr(cover_worker, "regenerate_cover_for_library", render)
    lib = _library(db, name="合并", cover_template="poster", cover_auto_regen=True)
    db.commit()

    first = cover_worker.enqueue_cover_regeneration(lib.id)
    # 第二次发生在任务还没跑完时：必须被合并掉
    second = cover_worker.enqueue_cover_regeneration(lib.id)
    _wait_state(cover_worker, lib.id, {"done"})

    assert first is True
    assert second is False
    assert rendered == [lib.id]


def test_status_reports_pending_while_queued(db, cover_worker, monkeypatch):
    """排队中就能看到 pending：前端不用等刷新才知道封面在重画"""
    gate = threading.Event()

    def render(db_, lib):
        gate.wait(5)
        return lib.cover_path

    monkeypatch.setattr(cover_worker, "regenerate_cover_for_library", render)
    lib = _library(db, name="状态", cover_template="poster", cover_auto_regen=True)
    db.commit()

    cover_worker.enqueue_cover_regeneration(lib.id)
    try:
        assert cover_worker.cover_status(lib.id)["state"] in ("pending", "running")
    finally:
        gate.set()
    _wait_state(cover_worker, lib.id, {"done"})
    assert cover_worker.cover_status(lib.id)["state"] == "done"


def test_unknown_library_never_blocks_the_queue(db, cover_worker):
    """库里已经没有这个库了 → 记成完成，不要让 worker 一直重试它"""
    cover_worker.enqueue_cover_regeneration(999999)
    _wait_state(cover_worker, 999999, {"done"})


def test_render_failure_keeps_the_old_cover(db, cover_worker, monkeypatch):
    """画不出来 → 保留旧封面，只记失败原因

    绝不能出现「封面从有变成没有」：渲染失败发生在写文件之前，
    ``_write_generated_cover`` 是 os.replace 原子替换，旧文件原封不动。
    """
    from backend.api.library_cover import CoverRegenError

    def boom(db_, lib):
        raise CoverRegenError("生成失败：这个库还没有可用海报（等刮削补完再试）", 422)

    monkeypatch.setattr(cover_worker, "regenerate_cover_for_library", boom)
    lib = _library(db, name="保旧", cover_template="poster", cover_auto_regen=True)
    lib.cover_path = "library-covers/old.webp"
    db.commit()

    cover_worker.enqueue_cover_regeneration(lib.id)
    status = _wait_state(cover_worker, lib.id, {"failed"})

    assert "海报" in status["error"]
    db.expire_all()
    db.refresh(lib)
    assert lib.cover_path == "library-covers/old.webp"


def test_unexpected_render_crash_is_contained(db, cover_worker, monkeypatch):
    """渲染里抛未预期异常也不能带崩 worker，更不能弄丢旧封面"""

    def boom(db_, lib):
        raise RuntimeError("Pillow 段错误")

    monkeypatch.setattr(cover_worker, "regenerate_cover_for_library", boom)
    lib = _library(db, name="崩溃", cover_template="poster", cover_auto_regen=True)
    lib.cover_path = "library-covers/old.webp"
    db.commit()

    cover_worker.enqueue_cover_regeneration(lib.id)
    status = _wait_state(cover_worker, lib.id, {"failed"})

    assert "保留原封面" in status["error"]
    db.expire_all()
    db.refresh(lib)
    assert lib.cover_path == "library-covers/old.webp"
    # 会话仍然可用：失败的那次事务已经回滚，没有半截写入
    assert lib.name == "崩溃"


def test_one_failed_library_does_not_block_the_next_one(db, cover_worker, monkeypatch):
    """队列是共享的：一个库渲染失败，后面的库照样能排上"""

    def render(db_, lib):
        if lib.guid == "g-坏的":
            raise RuntimeError("渲染炸了")
        lib.cover_path = f"library-covers/{lib.guid}.webp"
        return lib.cover_path

    monkeypatch.setattr(cover_worker, "regenerate_cover_for_library", render)
    bad = _library(db, name="坏的", cover_template="poster", cover_auto_regen=True)
    good = _library(db, name="好的", cover_template="poster", cover_auto_regen=True)
    db.commit()

    cover_worker.enqueue_cover_regeneration(bad.id)
    cover_worker.enqueue_cover_regeneration(good.id)

    _wait_state(cover_worker, bad.id, {"failed"})
    _wait_state(cover_worker, good.id, {"done"})
    db.expire_all()
    db.refresh(good)
    assert good.cover_path.endswith(f"{good.guid}.webp")


# ==================== 手动与自动真的是同一段代码 ====================

def test_manual_and_auto_share_the_same_regenerate_helper(db, monkeypatch, cover_worker):
    """抽 :func:`regenerate_cover_for_library` 就是为了这个：两条路不许各画各的

    手动路径直接调它；自动路径（扫描完成后 → 异步队列）最终也落到同一个函数、
    同一套渲染参数——只是不再占用扫描线程。
    """
    rendered, written = [], []
    monkeypatch.setattr(cover_worker, "render_cover_bytes",
                        lambda db_, lib_, **kw: rendered.append(kw) or b"fake")
    monkeypatch.setattr(cover_worker, "_write_generated_cover", lambda lib_, data: (
        written.append((lib_.guid, data)),
        setattr(lib_, "cover_path", "library-covers/x.webp"),
        "library-covers/x.webp")[2])

    manual = _library(db, name="手动", cover_template="poster", cover_title="{library}")
    db.commit()
    cover_worker.regenerate_cover_for_library(db, manual)

    auto = _library(db, name="自动", cover_template="poster", cover_title="{library}",
                    cover_auto_regen=True)
    db.commit()
    assert cover_worker.enqueue_cover_regeneration(auto.id) is True
    _wait_state(cover_worker, auto.id, {"done"})

    assert written == [(manual.guid, b"fake"), (auto.guid, b"fake")]
    # 两条路都用库里存的模板与标题，没有谁偷偷换一套参数
    assert rendered[-1]["template"] == "poster"
    assert rendered[-1]["title"] == "{library}"


def test_regenerate_helper_reports_missing_template(db):
    from backend.api.library_cover import CoverRegenError, regenerate_cover_for_library

    lib = _library(db, name="无样式")

    with pytest.raises(CoverRegenError) as excinfo:
        regenerate_cover_for_library(db, lib)

    assert excinfo.value.status_code == 400
    assert "样式" in excinfo.value.detail


def test_regenerate_helper_reports_no_poster(db, monkeypatch):
    from backend.api import library_cover as lc

    monkeypatch.setattr(lc, "render_cover_bytes", lambda *a, **k: b"")
    lib = _library(db, name="没海报", cover_template="poster")

    with pytest.raises(lc.CoverRegenError) as excinfo:
        lc.regenerate_cover_for_library(db, lib)

    assert excinfo.value.status_code == 422