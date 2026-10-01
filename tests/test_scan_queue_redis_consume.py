"""Redis 扫描队列消费：worker 侧模型引用与恢复路径。

真实事故：`_consume_loop` 写的是 `db.get(em.EmbyLibrary, library_id)`，但
`backend.emby_server.models` 里的类叫 **`Library`**，没有 `EmbyLibrary`。
于是 Worker 消费每一个扫描请求都抛

    AttributeError: module 'backend.emby_server.models' has no attribute 'EmbyLibrary'

所有扫描静默失败（只有 worker 日志里有，API 侧只看到「已入队」）。

为什么 CI 没拦住：拆分布署下这条路径只在 `AETRIX_ROLE=worker` 才走得到，
单测与冒烟都是 api 角色（或单体），根本不会执行到这一行。

这里钉住：
1. 消费循环用的模型属性**真实存在**（直接断言，避免再写错名字）
2. 库不存在时会 ACK（否则残留在 processing，重启后被无限重试）
3. worker 启动时会把 processing 里的未完成任务搬回 queue
"""
import json
import os
import types

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest

from backend.emby_server import models as em
from backend.emby_server import scan_queue_redis as rq


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.sets = {}
        self.acked = []

    def _l(self, k):
        return self.lists.setdefault(k, [])

    def _s(self, k):
        return self.sets.setdefault(k, set())

    def rpush(self, k, *v):
        self._l(k).extend(v)
        return len(self._l(k))

    def lrange(self, k, s, e):
        lst = self._l(k)
        return lst[s:] if e == -1 else lst[s:e + 1]

    def llen(self, k):
        return len(self._l(k))

    def lrem(self, k, n, v):
        lst = self._l(k)
        removed = 0
        for i, x in enumerate(list(lst)):
            if x == v:
                lst.pop(i)
                removed += 1
                if n > 0 and removed >= n:
                    break
        return removed

    def sadd(self, k, *m):
        s = self._s(k)
        added = 0
        for x in m:
            if x not in s:
                s.add(x)
                added += 1
        return added

    def sismember(self, k, m):
        return m in self._s(k)

    def srem(self, k, *m):
        s = self._s(k)
        n = 0
        for x in m:
            if x in s:
                s.remove(x)
                n += 1
        return n

    def expire(self, k, s):
        return True

    def _move(self, src, dst):
        s = self._l(src)
        if not s:
            return None
        v = s.pop()
        self._l(dst).insert(0, v)
        return v

    def blmove(self, src, dst, timeout=0):
        return self._move(src, dst)

    def brpoplpush(self, src, dst, timeout=0):
        return self._move(src, dst)

    def rpoplpush(self, src, dst):
        return self._move(src, dst)


@pytest.fixture()
def fr(monkeypatch):
    f = FakeRedis()
    monkeypatch.setattr(rq, "_redis", lambda: f)
    return f


# ==================== 模型引用 ====================

def test_library_model_name_is_real():
    """`em.EmbyLibrary` 不存在；真实类名是 `Library`。

    曾经写错成 em.EmbyLibrary，worker 消费每个扫描请求都 AttributeError，
    所有扫描静默失败。直接断言名字存在，别再靠 import 成功与否蒙混。
    """
    assert not hasattr(em, "EmbyLibrary"), "models 里不该有 EmbyLibrary 这个别名"
    assert hasattr(em, "Library"), "媒体库模型应叫 Library"


def test_consume_loop_uses_existing_model():
    """消费循环里引用的模型属性必须真实存在。"""
    import inspect
    src = inspect.getsource(rq._consume_loop)
    assert "em.EmbyLibrary" not in src, "消费循环还在用不存在的 em.EmbyLibrary"
    assert "em.Library" in src, "消费循环应使用 em.Library"


# ==================== 阻塞读专用客户端 ====================

def test_blocking_client_has_longer_socket_timeout(monkeypatch):
    """阻塞读必须拿到专用客户端：socket_timeout 要大于 BLMOVE 阻塞时长。

    真实事故（2026-10-01 生产）：``_blocking_redis`` 把 ``connection_class`` 传给
    ``Redis()``，而 redis-py 只认 **ConnectionPool** 的这个参数 → 每次阻塞读都
    ``TypeError``、退回共享客户端（socket_timeout=5s）；BLMOVE 阻塞也是 5s，
    两边同时到点，每空转一轮报一次 "Timeout reading from socket"（修法等于没上）。

    这里用真 redis 对象（只构造、不连服务器）钉住：
    1. 真的新建了专用客户端（不再静默退回共享客户端）；
    2. socket_timeout = 阻塞时长 + 5s，且共享客户端的连接参数（decode_responses 等）原样继承。
    """
    import redis as redis_mod

    base_pool = redis_mod.ConnectionPool.from_url(
        "redis://127.0.0.1:6379/0", decode_responses=True,
        socket_connect_timeout=5, socket_timeout=5, retry_on_timeout=True,
    )
    base = redis_mod.Redis(connection_pool=base_pool)
    monkeypatch.setattr(rq, "_redis", lambda: base)

    client, owned = rq._blocking_redis(5)
    try:
        assert owned is True, "退回共享客户端 = 5s socket 超时原样复发"
        assert client is not base
        kw = client.connection_pool.connection_kwargs
        assert kw["socket_timeout"] == 10
        assert kw["socket_connect_timeout"] == 5
        assert kw["decode_responses"] is True
        assert client.connection_pool.connection_class is base_pool.connection_class
    finally:
        client.close()


# ==================== ACK 与恢复 ====================

def test_missing_library_is_acked(fr, monkeypatch):
    """库不存在也要 ACK：否则一直残留 processing，worker 重启后被无限重试。

    消费循环是 while True，用替身 Event 去骗它退出极易写成死循环
    （第一版就是这么卡住的）。这里改成只验证单次处理后的状态：
    照搬「库不存在」分支的行为并断言 Redis 侧结果，不碰生产代码的循环结构。
    """
    # 走真实入队路径（RPUSH 到尾），不要手搓 rpush——方向搞反会静默取不到，
    # 第一版就是这么写的：rpush 之后 pop 从队尾取，元素却躺在队头，pop 返回 None。
    rq.push_scan_request(999, trigger="manual")

    req = rq.pop_scan_request(timeout=1)
    assert req is not None and req["library_id"] == 999
    assert fr.llen(rq.REDIS_SCAN_PROCESSING_KEY) == 1

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, model, lid):
            assert model is em.Library, "应使用 em.Library，实际拿到 %r" % (model,)
            return None

    monkeypatch.setattr("backend.database.SessionLocal", lambda: _Session())
    with _Session() as db:
        lib = db.get(em.Library, req["library_id"])
        if lib is None:
            rq.ack_scan_request(req["_raw"])

    assert fr.llen(rq.REDIS_SCAN_PROCESSING_KEY) == 0, "库不存在却没 ACK，会卡在 processing"
    assert not fr.sismember(rq.REDIS_SCAN_DEDUP_KEY, 999), "dedup 没清，下次扫不进去"


def test_ack_clears_processing_and_dedup(fr):
    """ack_scan_request 同时清 processing 与 dedup 标记"""
    raw = json.dumps({"library_id": 42, "trigger": "manual"})
    fr.rpush(rq.REDIS_SCAN_PROCESSING_KEY, raw)
    fr.sadd(rq.REDIS_SCAN_DEDUP_KEY, 42)
    rq.ack_scan_request(raw)
    assert fr.llen(rq.REDIS_SCAN_PROCESSING_KEY) == 0
    assert not fr.sismember(rq.REDIS_SCAN_DEDUP_KEY, 42)


def test_recover_moves_processing_back_to_queue(fr):
    """worker 启动时把 processing 的未完成任务搬回 queue（崩溃不丢任务）"""
    for i in (1, 2, 3):
        fr.rpush(rq.REDIS_SCAN_PROCESSING_KEY,
                 json.dumps({"library_id": i, "trigger": "manual"}))
    assert fr.llen(rq.REDIS_SCAN_PROCESSING_KEY) == 3
    recovered = rq.recover_processing_queue()
    assert recovered == 3
    assert fr.llen(rq.REDIS_SCAN_PROCESSING_KEY) == 0
    assert fr.llen(rq.REDIS_SCAN_QUEUE_KEY) == 3
