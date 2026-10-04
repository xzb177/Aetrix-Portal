"""封面「新片入库后自动更新」（v2.43.1）

开关本身很简单，真正要钉住的是**它什么时候做、什么时候不做**：

- 默认关闭，不开就一个字节的行为都不变；
- 开了但**本轮没新增条目** → 不重画（“自动更新”该跟“新片”绑定，
  否则每次扫一下都白白渲染一次 + 让客户端缓存失效）；
- 开了但**没选封面样式** → 不重画（没有可复用的配置，重画必然失败）；
- 真的重画时走的是**和手动「按最新海报重新生成」完全相同**的那段代码；
- 封面画不出来（库里没海报 / 没装 Pillow）**绝不能影响扫描结果落库**——
  封面是锦上添花，不能因为它把一轮扫描拖下水。

不碰网络、不碰生产库：渲染函数与文件写入都在这里打桩。
"""
import os
from types import SimpleNamespace

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


# ==================== 什么时候该重画 ====================

class _RecordingCover:
    """记录重生成到底被调了几次

    打在 :func:`regenerate_cover_for_library` 上：扫描器是**延迟导入**这个函数的
    （否则 backend.api 与 emby_server 会成环），所以打模块属性一样能拦住——这也
    顺带证明了自动路径走的确实是这一段，而不是另外抄了一份。
    """

    def __init__(self):
        self.calls = []

    def __call__(self, db, lib):
        self.calls.append(lib.id)
        lib.cover_path = f"library-covers/{lib.guid}.webp"
        return lib.cover_path


@pytest.fixture()
def cover(monkeypatch):
    from backend.api import library_cover as lc

    rec = _RecordingCover()
    monkeypatch.setattr(lc, "regenerate_cover_for_library", rec)
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


def test_regenerates_when_switch_on_and_has_new_items(db, cover):
    lib = _library(db, name="自动", cover_template="poster", cover_auto_regen=True)

    _run_scan(db, lib, added=3)

    assert cover.calls == [lib.id]
    db.expire_all()
    db.refresh(lib)
    assert lib.cover_path.endswith(f"{lib.guid}.webp")


def test_regenerates_on_partial_scan_too(db, cover):
    """部分来源读不到（partial）也算“扫完了”：新片确实进来了就更新

    封面不该因为这一轮有个目录没挂上就停摆——那正是最需要新海报的时候。
    """
    lib = _library(db, name="部分", cover_template="visual", cover_auto_regen=True)

    _run_scan(db, lib, added=1, removal_skipped=True, failed_roots=["/gone"])

    assert cover.calls == [lib.id]


# ==================== 画不出来不能影响扫描结果 ====================

def test_cover_failure_does_not_break_scan_result(db, monkeypatch):
    from backend.api import library_cover as lc

    def boom(db_, lib):
        raise RuntimeError("Pillow 没装")

    monkeypatch.setattr(lc, "regenerate_cover_for_library", boom)
    lib = _library(db, name="会失败", cover_template="poster", cover_auto_regen=True)

    status = scanner.finish_scan(db, lib, {"added": 5}, None)

    # 扫描结果照样落库
    assert status == scanner.SCAN_STATUS_SUCCESS
    assert lib.scan_status == scanner.SCAN_STATUS_SUCCESS
    assert lib.last_scan_at is not None


def test_cover_failure_rolls_back_so_scan_state_is_not_lost(db, monkeypatch):
    """封面失败后必须回滚：否则 Session 带着半截事务，后面谁用谁炸"""
    from backend.api import library_cover as lc

    def boom(db_, lib):
        db_.execute(text("UPDATE emby_libraries SET name = '被封面弄脏了'"))
        raise RuntimeError("写一半挂了")

    monkeypatch.setattr(lc, "regenerate_cover_for_library", boom)
    lib = _library(db, name="回滚", cover_template="poster", cover_auto_regen=True)

    scanner.finish_scan(db, lib, {"added": 5}, None)
    db.rollback()

    db.expire_all()
    db.refresh(lib)
    assert lib.name == "回滚"
    assert lib.scan_status == scanner.SCAN_STATUS_SUCCESS


# ==================== 手动与自动真的是同一段代码 ====================

def test_manual_and_auto_share_the_same_regenerate_helper(db, monkeypatch):
    """抽 :func:`regenerate_cover_for_library` 就是为了这个：两条路不许各画各的

    手动路径直接调它；自动路径（扫描完成后）走同一个函数、同一套渲染参数。
    """
    from backend.api import library_cover as lc

    rendered, written = [], []
    monkeypatch.setattr(lc, "render_cover_bytes",
                        lambda db_, lib_, **kw: rendered.append(kw) or b"fake")
    monkeypatch.setattr(lc, "_write_generated_cover", lambda lib_, data: (
        written.append((lib_.guid, data)),
        setattr(lib_, "cover_path", "library-covers/x.webp"),
        "library-covers/x.webp")[2])

    manual = _library(db, name="手动", cover_template="poster", cover_title="{library}")
    lc.regenerate_cover_for_library(db, manual)

    auto = _library(db, name="自动", cover_template="poster", cover_title="{library}",
                    cover_auto_regen=True)
    scanner.finish_scan(db, auto, {"added": 4}, None)

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