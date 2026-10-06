"""Redis 扫描队列 ACK 时机回归测试（P0-0c）。

问题：``scan_queue_redis._consume_loop`` 在把任务转入进程内存队列后**立即**
``ack_scan_request``，但真正的扫描还没跑。worker 在扫描完成前崩溃，
任务既不在 Redis 里（已 ACK），内存队列又随进程消失 → 扫描请求无声丢失
（用户点了扫描但没反应）。

修复：raw 随 ``ScanTask`` 携带，只在扫描真正完成后（``_run_task`` 的 finally）
或取消排队（``cancel()``）时才 ACK。崩溃的任务仍留在 Redis ``processing``，
重启后 ``recover_processing_queue`` 捞回重扫（at-least-once）。

本文件用内存 FakeRedis + 打桩，不依赖真实 Redis / 真实扫描。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import json
import threading
import types

import pytest

from backend.emby_server import scan_queue
from backend.emby_server import scan_queue_redis as rq


# ==================== FakeRedis ====================

class FakeRedis:
    """实现 scan_queue_redis 用到的最小 Redis 命令子集（内存版）"""

    def __init__(self):
        self.lists = {}
        self.sets = {}
        self.lock = threading.Lock()

    # -- set --
    def sadd(self, key, *members):
        with self.lock:
            s = self.sets.setdefault(key, set())
            added = 0
            for m in members:
                if m not in s:
                    s.add(m)
                    added += 1
            return added

    def sismember(self, key, member):
        with self.lock:
            return member in self.sets.get(key, set())

    def srem(self, key, *members):
        with self.lock:
            s = self.sets.get(key, set())
            removed = 0
            for m in members:
                if m in s:
                    s.remove(m)
                    removed += 1
            return removed

    # -- list --
    def rpush(self, key, *values):
        with self.lock:
            lst = self.lists.setdefault(key, [])
            lst.extend(values)
            return len(lst)

    def lrange(self, key, start, end):
        with self.lock:
            lst = self.lists.get(key, [])
            if end == -1:
                end = len(lst)
            else:
                end = end + 1
            return list(lst[start:end])

    def llen(self, key):
        with self.lock:
            return len(self.lists.get(key, []))

    def lrem(self, key, count, value):
        with self.lock:
            lst = self.lists.get(key, [])
            removed = 0
            # count=1：从头删第一个匹配的（与 redis 的 lrem count>0 语义一致）
            for i, v in enumerate(list(lst)):
                if v == value:
                    lst.pop(i)
                    removed += 1
                    if count > 0 and removed >= count:
                        break
            return removed

    def _move_tail_to_head(self, src, dst):
        with self.lock:
            s = self.lists.get(src, [])
            if not s:
                return None
            val = s.pop()  # RPOP：取尾
            d = self.lists.setdefault(dst, [])
            d.insert(0, val)  # LPUSH：放头
            return val

    def blmove(self, src, dst, timeout=0):
        # 测试里不需要真阻塞：有就取，没有返回 None
        return self._move_tail_to_head(src, dst)

    def brpoplpush(self, src, dst, timeout=0):
        return self._move_tail_to_head(src, dst)

    def rpoplpush(self, src, dst):
        return self._move_tail_to_head(src, dst)

    def expire(self, key, seconds):
        return True


@pytest.fixture()
def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(rq, "_redis", lambda: fr)
    return fr


@pytest.fixture()
def stub_snapshot(monkeypatch):
    """打桩 LibrarySnapshot.of：enqueue_local 不需要真实 scanner 快照"""
    from backend.emby_server import scanner as _scanner

    def _fake_of(cls, library):
        return types.SimpleNamespace(
            name=f"库{library.id}", mount_ids=[], paths=[],
        )

    monkeypatch.setattr(_scanner.LibrarySnapshot, "of", classmethod(_fake_of))


@pytest.fixture()
def no_dispatch(monkeypatch):
    """禁止 _pump_locked 立即派发：任务留在 _QUEUE，测试可控"""
    monkeypatch.setattr(scan_queue, "SCAN_MAX_PARALLEL", 0)
    yield
    scan_queue.reset_for_tests()


@pytest.fixture()
def fake_lib():
    def _make(library_id):
        return types.SimpleNamespace(id=int(library_id))
    return _make


def _queue_len(fr):
    return fr.llen(rq.REDIS_SCAN_QUEUE_KEY)


def _processing_len(fr):
    return fr.llen(rq.REDIS_SCAN_PROCESSING_KEY)


# ==================== 测试 ====================

def test_crash_before_complete_does_not_lose_task(fake_redis):
    """崩溃不丢任务：pop 后（未 ACK）直接"崩溃"，重启恢复后能重新消费"""
    fr = fake_redis
    res = rq.push_scan_request(13, trigger="manual")
    assert res["created"] is True
    assert _queue_len(fr) == 1

    req = rq.pop_scan_request(timeout=1)
    assert req is not None and req["library_id"] == 13
    assert _queue_len(fr) == 0
    assert _processing_len(fr) == 1

    # ---- 模拟崩溃：什么都不做（不 ACK、不跑扫描），进程直接没了 ----
    recovered = rq.recover_processing_queue()
    assert recovered == 1
    assert _queue_len(fr) == 1
    assert _processing_len(fr) == 0

    # 重新消费拿到的是同一个任务
    req2 = rq.pop_scan_request(timeout=1)
    assert req2 is not None and req2["library_id"] == 13
    assert json.loads(req2["_raw"])["trigger"] == "manual"


def test_no_premature_ack_after_enqueue_local(fake_redis, stub_snapshot, no_dispatch, fake_lib):
    """转入内存队列后**不**提前 ACK：任务仍在 processing，dedup 标记仍在"""
    fr = fake_redis
    rq.push_scan_request(12, trigger="manual")
    req = rq.pop_scan_request(timeout=1)
    assert req is not None

    result = scan_queue.enqueue_local(fake_lib(12), trigger="manual", redis_raw=req["_raw"])
    assert result["created"] is True

    # 关键断言：还没跑完，Redis 侧必须**没**确认
    assert _processing_len(fr) == 1, "提前 ACK 了！崩溃会丢任务（P0-0c 回归）"
    assert fr.sismember(rq.REDIS_SCAN_DEDUP_KEY, 12), "dedup 被提前清除，重复点击会重复入队"

    # 任务携带了 raw，等待完成时确认
    task = scan_queue._QUEUE[0]
    assert task.redis_raws == [req["_raw"]]


def test_ack_only_after_scan_completes(fake_redis, stub_snapshot, no_dispatch, fake_lib, monkeypatch):
    """扫描真正完成后才 ACK：跑完 _run_task，processing 清空、dedup 清除"""
    fr = fake_redis
    rq.push_scan_request(9, trigger="manual")
    req = rq.pop_scan_request(timeout=1)

    result = scan_queue.enqueue_local(fake_lib(9), trigger="manual", redis_raw=req["_raw"])
    assert result["created"] is True
    task = scan_queue._QUEUE[0]

    # ---- 打桩 _run_task 的重依赖：不跑真实扫描 ----
    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return types.SimpleNamespace(id=9, scan_status="success")

    class _FakeSession:
        def query(self, *a, **k):
            return _FakeQuery()

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(scan_queue, "SessionLocal", lambda: _FakeSession())
    from backend.emby_server import fast_scanner as _fs
    monkeypatch.setattr(_fs, "scan_library_sync", lambda *a, **k: None)

    # 手动把任务从 _QUEUE 取出（模拟派发），直接跑完成路径
    with scan_queue._LOCK:
        scan_queue._QUEUE.remove(task)
    scan_queue._run_task(task)

    assert task.result == "success"
    assert _processing_len(fr) == 0, "扫描完成了但没 ACK"
    assert not fr.sismember(rq.REDIS_SCAN_DEDUP_KEY, 9), "dedup 没清除，下次扫不进去"
    assert task.redis_raws == [], "raw 没清掉会重复 ACK"


def test_merged_request_acks_together(fake_redis, stub_snapshot, no_dispatch, fake_lib, monkeypatch):
    """合并到已有任务的第二个 Redis 请求，等已有任务跑完一起 ACK"""
    fr = fake_redis
    rq.push_scan_request(14, trigger="manual")
    req1 = rq.pop_scan_request(timeout=1)
    # 绕过 dedup 再塞一个同库任务（模拟 dedup 过期等极端情况）
    raw2 = json.dumps({"library_id": 14, "trigger": "auto", "enqueued_at": 0})
    fr.rpush(rq.REDIS_SCAN_QUEUE_KEY, raw2)
    req2 = rq.pop_scan_request(timeout=1)
    assert _processing_len(fr) == 2

    r1 = scan_queue.enqueue_local(fake_lib(14), trigger="manual", redis_raw=req1["_raw"])
    assert r1["created"] is True
    r2 = scan_queue.enqueue_local(fake_lib(14), trigger="auto", redis_raw=req2["_raw"])
    assert r2["created"] is False  # 合并

    task = scan_queue._QUEUE[0]
    assert task.redis_raws == [req1["_raw"], req2["_raw"]]

    # 完成：两个 raw 一起确认
    scan_queue._ack_redis_raws(task)
    assert _processing_len(fr) == 0


def test_cancel_acks_redis_task(fake_redis, stub_snapshot, no_dispatch, fake_lib):
    """取消排队中的任务时 ACK：否则任务滞留 processing，重启后被误重扫"""
    fr = fake_redis
    rq.push_scan_request(11, trigger="manual")
    req = rq.pop_scan_request(timeout=1)
    scan_queue.enqueue_local(fake_lib(11), trigger="manual", redis_raw=req["_raw"])
    assert _processing_len(fr) == 1

    assert scan_queue.cancel(11) == "canceled"
    assert _processing_len(fr) == 0, "取消了但没 ACK，重启后会被误重扫"
    assert not fr.sismember(rq.REDIS_SCAN_DEDUP_KEY, 11)


def test_failed_scan_still_acks(fake_redis, stub_snapshot, no_dispatch, fake_lib, monkeypatch):
    """扫描失败也要 ACK：失败不是"没跑"，不能让任务永远占着 processing"""
    fr = fake_redis
    rq.push_scan_request(15, trigger="manual")
    req = rq.pop_scan_request(timeout=1)
    scan_queue.enqueue_local(fake_lib(15), trigger="manual", redis_raw=req["_raw"])
    task = scan_queue._QUEUE[0]

    class _FakeQuery:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None  # 库被删了 → 失败路径

    class _FakeSession:
        def query(self, *a, **k):
            return _FakeQuery()

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(scan_queue, "SessionLocal", lambda: _FakeSession())
    from backend.emby_server import fast_scanner as _fs
    monkeypatch.setattr(_fs, "scan_library_sync", lambda *a, **k: None)

    with scan_queue._LOCK:
        scan_queue._QUEUE.remove(task)
    scan_queue._run_task(task)

    assert task.result == "failed"
    assert _processing_len(fr) == 0, "失败了但没 ACK，任务会卡在 processing"
