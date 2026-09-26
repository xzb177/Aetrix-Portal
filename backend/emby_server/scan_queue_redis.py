"""
扫描队列 Redis 桥接（后端拆分 v2.41.0）

API 进程与 Worker 进程分离后，扫描触发必须跨进程：
- API 进程（AETRIX_ROLE=api）：enqueue() 把 {library_id, trigger} 推入 Redis list
- Worker 进程（AETRIX_ROLE=worker）：start_redis_consumer() 用 BLPOP 消费，
  拿到 library_id 后查 DB 取 library 对象，再走 scan_queue 原有的进程内入队逻辑

Redis key：
- aetrix:scan:queue      扫描请求队列（list，FIFO：RPUSH 入队 / BLPOP 消费）
- aetrix:scan:dedup      去重集合（set，library_id，防止重复入队）

单体模式（不设 AETRIX_ROLE）下本模块不启用，走原有进程内队列。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_SCAN_QUEUE_KEY = "aetrix:scan:queue"
REDIS_SCAN_DEDUP_KEY = "aetrix:scan:dedup"
# 去重集合的过期时间（秒）：防止 worker 崩溃后 dedup 残留导致永远入队失败
DEDUP_TTL_SECONDS = 3600

_consumer_thread: threading.Thread | None = None
_consumer_stop = threading.Event()


def _redis():
    """拿 Redis 客户端（backend.database.redis_client）"""
    from backend.database import redis_client
    return redis_client


def is_redis_mode() -> bool:
    """当前进程是否应该用 Redis 桥接（API 角色且 Redis 可用）"""
    role = os.getenv("AETRIX_ROLE", "").strip().lower()
    if role != "api":
        return False
    return _redis() is not None


def push_scan_request(library_id: int, trigger: str = "manual") -> dict:
    """API 进程：把扫描请求推入 Redis 队列

    返回 {"created": bool, "task": {...}}，与 scan_queue.enqueue() 的返回形状一致。
    """
    r = _redis()
    if r is None:
        raise RuntimeError("Redis 不可用，无法跨进程入队")
    library_id = int(library_id)
    # 去重：已在队列里就不再推
    added = r.sadd(REDIS_SCAN_DEDUP_KEY, library_id)
    if not added:
        # 已在队列中，返回当前位置
        position = _position_of(library_id)
        return {
            "created": False,
            "task": {
                "library_id": library_id,
                "trigger": trigger,
                "state": "queued",
                "position": position,
                "via": "redis",
            },
        }
    payload = json.dumps({
        "library_id": library_id,
        "trigger": str(trigger or "manual"),
        "enqueued_at": time.time(),
    })
    r.rpush(REDIS_SCAN_QUEUE_KEY, payload)
    r.expire(REDIS_SCAN_DEDUP_KEY, DEDUP_TTL_SECONDS)
    position = r.llen(REDIS_SCAN_QUEUE_KEY)
    logger.info("扫描请求已推入 Redis 队列：库 id=%s 触发=%s（队列长度 %s）",
                library_id, trigger, position)
    return {
        "created": True,
        "task": {
            "library_id": library_id,
            "trigger": trigger,
            "state": "queued",
            "position": position,
            "via": "redis",
        },
    }


def _position_of(library_id: int) -> int | None:
    """查某个库在 Redis 队列中的位置（1-based），不在队列返回 None"""
    r = _redis()
    if r is None:
        return None
    try:
        items = r.lrange(REDIS_SCAN_QUEUE_KEY, 0, -1)
        for idx, raw in enumerate(items):
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if int(data.get("library_id", -1)) == int(library_id):
                return idx + 1
    except Exception as e:
        logger.warning(f"查询 Redis 队列位置失败：{e}")
    return None


def queue_length() -> int:
    """Redis 队列当前长度"""
    r = _redis()
    if r is None:
        return 0
    try:
        return int(r.llen(REDIS_SCAN_QUEUE_KEY))
    except Exception:
        return 0


def cancel_scan_request(library_id: int) -> str:
    """API 进程：从 Redis 队列取消排队中的扫描

    返回 canceled / running / missing（语义与 scan_queue.cancel 一致）。
    """
    r = _redis()
    if r is None:
        return "missing"
    library_id = int(library_id)
    try:
        # worker 消费时会先从 dedup 集合删除；如果 dedup 里没有，说明已在跑或不在队列
        if not r.sismember(REDIS_SCAN_DEDUP_KEY, library_id):
            return "missing"
        # 从 list 里删除该库的所有排队项
        items = r.lrange(REDIS_SCAN_QUEUE_KEY, 0, -1)
        removed = 0
        for raw in items:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if int(data.get("library_id", -1)) == library_id:
                r.lrem(REDIS_SCAN_QUEUE_KEY, 1, raw)
                removed += 1
        r.srem(REDIS_SCAN_DEDUP_KEY, library_id)
        if removed:
            logger.info(f"已从 Redis 队列取消扫描：库 id={library_id}")
            return "canceled"
        # dedup 里有但 list 里没有：worker 刚取走正在跑
        return "running"
    except Exception as e:
        logger.warning(f"从 Redis 队列取消扫描失败：{e}")
        return "missing"


def pop_scan_request(timeout: int = 5) -> Optional[dict]:
    """Worker 进程：阻塞取出一个扫描请求（BLPOP）

    返回 {"library_id": int, "trigger": str}，超时返回 None。
    取出后自动从 dedup 集合删除（取消去重标记）。
    """
    r = _redis()
    if r is None:
        return None
    try:
        result = r.blpop(REDIS_SCAN_QUEUE_KEY, timeout=timeout)
        if not result:
            return None
        _, raw = result
        data = json.loads(raw)
        library_id = int(data["library_id"])
        r.srem(REDIS_SCAN_DEDUP_KEY, library_id)
        return {"library_id": library_id, "trigger": data.get("trigger", "manual")}
    except Exception as e:
        logger.warning(f"从 Redis 取扫描请求失败：{e}")
        return None


def start_redis_consumer() -> bool:
    """Worker 进程：启动 Redis 扫描队列消费线程

    循环 BLPOP，拿到请求后查 DB 取 library，再调 scan_queue 的进程内入队。
    返回 True 表示消费线程已启动。
    """
    global _consumer_thread
    if _consumer_thread is not None and _consumer_thread.is_alive():
        return True
    r = _redis()
    if r is None:
        logger.error("Redis 不可用，无法启动扫描队列消费")
        return False
    _consumer_stop.clear()
    _consumer_thread = threading.Thread(
        target=_consume_loop, daemon=True, name="scan-redis-consumer"
    )
    _consumer_thread.start()
    logger.info("Redis 扫描队列消费线程已启动")
    return True


def stop_redis_consumer(timeout: float = 5.0) -> None:
    """停止消费线程（优雅关闭时调用）"""
    _consumer_stop.set()
    if _consumer_thread is not None and _consumer_thread.is_alive():
        _consumer_thread.join(timeout=timeout)


def _consume_loop():
    """消费循环：BLPOP → 查库 → 进程内入队"""
    logger.info("扫描队列消费循环开始")
    # 延迟导入：避免循环导入
    from backend.database import SessionLocal
    from backend.emby_server import models as em
    from backend.emby_server import scan_queue

    while not _consumer_stop.is_set():
        try:
            req = pop_scan_request(timeout=5)
        except Exception as e:
            logger.warning(f"消费循环取请求异常：{e}")
            _consumer_stop.wait(5)
            continue
        if req is None:
            continue
        library_id = req["library_id"]
        trigger = req["trigger"]
        try:
            with SessionLocal() as db:
                lib = db.get(em.EmbyLibrary, library_id)
                if lib is None:
                    logger.warning(f"Redis 扫描请求：库 id={library_id} 不存在，跳过")
                    continue
                # 走进程内入队（worker 进程内的 scan_queue 完整逻辑：串行化/并发上限）
                result = scan_queue.enqueue_local(lib, trigger=trigger)
                logger.info(f"Redis 扫描请求已转进程内队列：库「{lib.name}」(id={library_id}) "
                            f"触发={trigger} created={result.get('created')}")
                # expunge：enqueue_local 内部会拍快照，lib 不能随 session 关闭失效
                db.expunge(lib)
        except Exception:
            logger.exception(f"处理 Redis 扫描请求失败：库 id={library_id}")
    logger.info("扫描队列消费循环结束")
