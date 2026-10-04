"""扫描器撞 ``emby_items.guid`` 唯一键时的行为

背景（2026-10-04 生产事故）：库 17（国产剧）扫到 ``兰香如故 S01E42``，
该 guid 已由 8 秒前那次**被容器重启打断的**扫描提交入库，本轮扫描再插一次
→ ``UniqueViolation`` → 整批回滚、整库扫描 abort，一个文件拖垮整个库。

守卫 ``ctx.seen_guids`` 只防「同一个遍历器吐出两遍」，防不了跨 Session /
跨进程 / 跨重启的重复，所以这里测的是两层新防护：

1. ``_claim_guid``：插之前让数据库原子占位 guid（PG/SQLite 的 upsert）
2. ``commit_batch`` 的 IntegrityError 兜底：真撞了也不 abort 整库
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.emby_server import scanner
from backend.emby_server import models as emby_models


@pytest.fixture()
def db():
    """每测试一个独立的内存 SQLite 库（MediaItem 表结构走真实的建表逻辑）"""
    engine = create_engine("sqlite://")
    # 建**全部** emby 表：只建 MediaItem 的话，扫描器一碰到目录指纹就会去查
    # emby_scan_dirs，报「no such table」——那是 fixture 的锅，不是被测代码的。
    emby_models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _guid_of(path: str) -> str:
    return scanner.item_guid(path)


# ==================== 第 1 层：_claim_guid 原子占位 ====================

def test_claim_guid_inserts_when_absent(db):
    """库里没有 → 占位成功（返回 True），行确实落库了"""
    assert scanner._claim_guid(db, "g1", 17, {"item_type": "episode", "name": "x"}) is True
    assert db.query(emby_models.MediaItem).filter_by(guid="g1").count() == 1


def test_claim_guid_returns_false_when_taken(db):
    """guid 已存在 → 占位失败（返回 False），且**不**改动已有行

    DO NOTHING 的语义：绝不能因为占位失败就把别人的行覆盖掉。
    """
    db.add(emby_models.MediaItem(guid="g1", library_id=17,
                             item_type="episode", name="原名"))
    db.commit()

    assert scanner._claim_guid(db, "g1", 17, {"item_type": "movie", "name": "新名"}) is False

    row = db.query(emby_models.MediaItem).filter_by(guid="g1").one()
    assert row.name == "原名", "占位失败时不允许覆盖已有条目"


def test_claim_guid_is_atomic_against_a_second_connection(db):
    """核心场景：另一个 Session 在「查过之后、插入之前」抢先插了同一个 guid

    这正是生产事故的时序——批次开头 _load_items 说没有，之后另一个事务插了。
    占位必须失败（False），而不是两个人都以为自己是赢家。
    """
    guid = _guid_of("/mnt/mp/剧集/国产剧/兰香如故 - S01E42.mkv")
    other = sessionmaker(bind=db.bind)()

    # 模拟另一个 Session 先提交
    other.add(emby_models.MediaItem(guid=guid, library_id=17,
                                  item_type="episode", name="抢先的"))
    other.commit()

    # 本 Session 占位：必须失败
    assert scanner._claim_guid(db, guid, 17, {"item_type": "episode", "name": "本轮的"}) is False

    # 且库里仍然只有一行，名字没被覆盖
    assert other.query(emby_models.MediaItem).filter_by(guid=guid).count() == 1
    assert other.query(emby_models.MediaItem).filter_by(guid=guid).one().name == "抢先的"
    other.close()


def test_resolve_conflict_returns_the_winning_row(db):
    """没抢到时能取回那行，扫描器随后走 update 分支补全字段"""
    db.add(emby_models.MediaItem(guid="g1", library_id=17,
                             item_type="episode", name="别人插的"))
    db.commit()

    row = scanner._resolve_conflict(db, "g1")
    assert row is not None
    assert row.name == "别人插的"


# ==================== 第 2 层：IntegrityError 兜底 ====================

def test_is_unique_violation_recognises_pg_and_sqlite():
    """PG 的 'duplicate key value violates unique constraint' 与
    SQLite 的 'UNIQUE constraint failed' 都要认出来"""
    class FakePG(Exception):
        pass
    class FakeLite(Exception):
        pass

    def _wrap(inner):
        class Wrapper(Exception):
            orig = inner
        return Wrapper()

    pg = _wrap(Exception(
        'duplicate key value violates unique constraint "ix_emby_items_guid"'))
    lite = _wrap(Exception("UNIQUE constraint failed: emby_items.guid"))

    assert scanner._is_unique_violation(pg) is True
    assert scanner._is_unique_violation(lite) is True


def test_is_unique_violation_rejects_other_integrity_errors():
    """NOT NULL / 外键违规**不能**降级重试：那是扫描器自己算错了，
    属于真 bug，应该原样抛出让整库失败、留下证据"""
    class Wrapper(Exception):
        orig = Exception('null value in column "item_id" violates not-null constraint')

    assert scanner._is_unique_violation(Wrapper()) is False


def test_batch_conflict_rewinds_seen_guids_so_retry_actually_reruns(monkeypatch):
    """最容易写漏的一环：回滚后本批 guid 仍留在 seen_guids 里

    不摘掉的话，重试会被 _prepare_and_prefetch 当成「遍历器重复产出」全部跳过——
    表现为**静默丢条目**：扫描「成功」了但那一集永远没入库，比报错更难查。

    这里直接测重试语义，不去跑整条扫描管线（管线要 mock provider / 挂载 / IO，
    成本远大于它能证明的东西）。判据是三个可观察的事实：
    第一次提交撞键 → 走重写路径 → 第二次真正提交成功。
    """
    prepared_batches = []

    class _Pending:
        def __init__(self, guid, scan_file=None):
            self.guid = guid
            self.scan_file = scan_file
            self.skipped = False
            self.fast_skipped = False

    guids = ["g1", "g2", "g3"]

    def fake_prepare(db, batch, ctx, pool):
        # 只记「本轮准备了这批哪些 guid」——模拟 _prepare_and_prefetch 的入队语义
        prepared_batches.append([sg.stored_path for sg in batch])
        out = []
        for sf in batch:
            guid = scanner.item_guid(sf.stored_path)
            if guid in ctx.seen_guids:
                # 真实实现里这条会记 duplicate_files 并 continue；这里照做，
                # 产出物会被 emit_batch 的 `if not p.skipped` 过滤掉
                continue
            ctx.seen_guids.add(guid)
            out.append(_Pending(guid, scan_file=sf))
        return out

    monkeypatch.setattr(scanner, "_prepare_and_prefetch", fake_prepare)
    monkeypatch.setattr(scanner, "_store_dir_states", lambda db, ctx: None)
    monkeypatch.setattr(scanner, "_library_exists", lambda db, lib_id: True)

    commits = {"n": 0}

    class FakeDb:
        """只需要 _iter_prepared 真正用到的那几个方法

        注意 ``commit`` 与 ``flush`` 要分成两个方法：_iter_prepared 开头会把
        ``db.commit`` 换成 ``db.flush``（主体里的每文件提交退化成 flush），
        并在 commit_batch 里用提前存下的 real_commit 做真正的批次提交。
        两个混成一个方法就测不到这条路径了。
        """
        lib_id = 17
        def __init__(self):
            self.seen_guids = set()
            self.rolled_back = 0
            self.flushed = 0
        def flush(self):
            self.flushed += 1
        def commit(self):
            commits["n"] += 1
            if commits["n"] == 1:
                raise scanner.IntegrityError(
                    "INSERT", {}, Exception(
                        'duplicate key value violates unique constraint "ix_emby_items_guid"'))
        def rollback(self):
            self.rolled_back += 1

    class _Ctx:
        def __init__(self):
            self.lib_id = 17
            self.seen_guids = set()
            self.stats = {}

    ctx = _Ctx()
    db = FakeDb()

    files = [type("SF", (), {"stored_path": f"/m/{g}.mkv"})() for g in guids]

    # _iter_preferred 需要一个真实 db 才能跑 _iter_prepared 的批循环；
    # 这里直接调用它的内部批处理语义：构造一个最小可用调用。
    # 用 SCAN_BATCH=1 保证每个文件一批，冲突必然在第一批就发生。
    monkeypatch.setattr(scanner, "SCAN_BATCH", 1)

    consumed = []
    def _run():
        yield from scanner._iter_prepared(ctx, files, None, db)

    # 第一次：整批抛 IntegrityError 是**不允许**的——必须被兜住
    try:
        list(_run())
        raised = None
    except scanner.IntegrityError as exc:
        raised = exc

    assert raised is None, "冲突必须被兜住，不能冒泡成整库失败"
    assert db.rolled_back >= 1, "冲突后必须回滚本批"
    assert commits["n"] >= 2, "冲突后必须真正再提交一次"

    # 关键断言：重试时这三个 guid 都被重新准备了（没被 seen_guids 挡掉）
    first, *rest = prepared_batches
    assert [p for p in prepared_batches] == [
        ["/m/g1.mkv"],
        ["/m/g1.mkv"],   # 重试：g1 再次被准备（不是被 seen_guids 跳过）
        ["/m/g2.mkv"],
        ["/m/g3.mkv"],
    ], f"重试必须重新准备本批，实际：{prepared_batches}"
