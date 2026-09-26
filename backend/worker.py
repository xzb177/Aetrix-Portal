"""
Aetrix Worker - 后台任务独立进程入口

与 API 进程（backend/main.py）分离：只跑后台任务，不监听 HTTP。
通过环境变量 AETRIX_ROLE=worker 标识身份。

启动的后台任务：
- maintenance：崩溃恢复 + 定时维护（janitor）
- probe_worker：两阶段扫描 Phase 2 探测
- enrich_worker：分层扫描 L2/L3 补全
- reminders：订阅到期提醒
- auto_scan：定时扫描调度
- change_watcher：追新
- scan_queue：Redis 扫描队列消费（API 进程入队，worker 消费执行）

单实例保护：Redis 分布式锁（SET NX PX），防止多 worker 重复消费。
优雅关闭：SIGTERM/SIGINT → 停止接受新任务 → 等待当前任务完成 → 退出。

用法：
    AETRIX_ROLE=worker python3 -m backend.worker
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("aetrix-worker")

# 优雅关闭标志
_shutdown_event = threading.Event()

# Redis 单实例锁
_WORKER_LOCK_KEY = "aetrix:worker:lock"
_WORKER_LOCK_TTL_MS = 30000  # 30 秒，靠心跳续期
_worker_lock_token: str | None = None
_lock_renew_thread: threading.Thread | None = None


def _handle_signal(signum, frame):
    """信号处理：优雅关闭"""
    sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    logger.info(f"收到信号 {sig_name}，开始优雅关闭...")
    _shutdown_event.set()


def _acquire_worker_lock(redis_client) -> bool:
    """获取 worker 单实例锁（Redis SET NX PX）"""
    global _worker_lock_token
    import uuid
    token = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        acquired = redis_client.set(
            _WORKER_LOCK_KEY, token, nx=True, px=_WORKER_LOCK_TTL_MS
        )
        if acquired:
            _worker_lock_token = token
            logger.info(f"已获取 worker 单实例锁（token={token}）")
            return True
        else:
            holder = redis_client.get(_WORKER_LOCK_KEY)
            logger.error(f"已有 worker 实例在运行（锁持有者={holder}），本实例退出")
            return False
    except Exception as e:
        logger.error(f"获取 worker 锁失败：{e}")
        return False


def _renew_worker_lock(redis_client):
    """后台线程：定期续期 worker 锁"""
    global _worker_lock_token
    while not _shutdown_event.is_set():
        try:
            # 只续自己的锁（Lua 脚本保证原子性）
            renewed = redis_client.eval(
                "if redis.call(get, KEYS[1]) == ARGV[1] then "
                "return redis.call(pexpire, KEYS[1], ARGV[2]) else return 0 end",
                1, _WORKER_LOCK_KEY, _worker_lock_token, _WORKER_LOCK_TTL_MS,
            )
            if not renewed:
                logger.error("worker 锁续期失败（锁已丢失），准备退出")
                _shutdown_event.set()
                break
        except Exception as e:
            logger.warning(f"worker 锁续期异常：{e}")
        # 每 TTL/3 续期一次
        _shutdown_event.wait(_WORKER_LOCK_TTL_MS / 3000.0)


def _release_worker_lock(redis_client):
    """释放 worker 锁（只释放自己的）"""
    global _worker_lock_token
    if not _worker_lock_token:
        return
    try:
        redis_client.eval(
            "if redis.call(get, KEYS[1]) == ARGV[1] then "
            "return redis.call(del, KEYS[1]) else return 0 end",
            1, _WORKER_LOCK_KEY, _worker_lock_token,
        )
        logger.info("已释放 worker 单实例锁")
    except Exception as e:
        logger.warning(f"释放 worker 锁失败：{e}")
    finally:
        _worker_lock_token = None


_WORKER_STARTED_AT = time.time()

def _write_heartbeat(redis_client):
    """写 worker 心跳（供监控/健康检查）"""
    try:
        import json
        heartbeat = {
            "pid": os.getpid(),
            "started_at": _WORKER_STARTED_AT,
            "updated_at": time.time(),
            "role": "worker",
        }
        redis_client.setex("aetrix:worker:heartbeat", 60, json.dumps(heartbeat))
    except Exception as e:
        logger.warning(f"写 worker 心跳失败：{e}")


def main() -> int:
    """Worker 主入口"""
    logger.info("🚀 Aetrix Worker 正在启动...")

    # 1. 密钥校验（fail-closed）
    from backend.security import validate_secret_key
    try:
        validate_secret_key()
    except Exception:
        logger.exception("JWT 密钥校验失败，worker 拒绝启动")
        return 1

    # 2. 数据库初始化
    from backend.database import init_db, DATABASE_TYPE
    logger.info(f"📊 数据库类型: {DATABASE_TYPE}")
    try:
        init_db()
    except Exception:
        logger.exception("数据库初始化失败，worker 拒绝启动")
        return 1

    # 3. Redis 连接（worker 必须有 Redis：单实例锁 + 扫描队列都依赖它）
    from backend.database import redis_client
    if redis_client is None:
        logger.error("Redis 不可用（REDIS_ENABLED=true 且 REDIS_URL 可达是 worker 的硬要求），worker 拒绝启动")
        return 1
    logger.info("✅ Redis 连接正常")

    # 4. 单实例锁
    if not _acquire_worker_lock(redis_client):
        return 1

    # 5. 信号处理
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # 6. 启动锁续期线程
    global _lock_renew_thread
    _lock_renew_thread = threading.Thread(
        target=_renew_worker_lock, args=(redis_client,), daemon=True, name="worker-lock-renew"
    )
    _lock_renew_thread.start()

    # 7. 启动所有后台任务（与 main.py lifespan 的 worker 部分保持一致）
    started = []
    try:
        from backend.emby_server import maintenance
        try:
            maintenance.run_startup_maintenance()
            if maintenance.start_janitor():
                started.append("janitor")
                logger.info("✅ 维护任务已启动")
        except Exception as e:
            logger.warning(f"启动维护任务失败（可忽略）: {e}")

        try:
            from backend.emby_server import probe_worker
            if probe_worker.start_probe_worker():
                started.append("probe_worker")
                logger.info("✅ 后台探测 worker 已启动")
        except Exception as e:
            logger.warning(f"启动探测 worker 失败（可忽略）: {e}")

        try:
            from backend.emby_server import enrich_worker
            enrich_worker.start()
            started.append("enrich_worker")
            logger.info("✅ 后台补全 worker 已启动")
        except Exception as e:
            logger.warning(f"启动补全 worker 失败（可忽略）: {e}")

        try:
            from backend import reminders
            if reminders.start_reminder_scheduler():
                started.append("reminders")
                logger.info("✅ 到期提醒已启动")
        except Exception as e:
            logger.warning(f"启动到期提醒失败（可忽略）: {e}")

        try:
            from backend.emby_server import auto_scan
            if auto_scan.start_auto_scan_scheduler():
                started.append("auto_scan")
                logger.info("✅ 定时扫描已启动")
        except Exception as e:
            logger.warning(f"启动定时扫描失败（可忽略）: {e}")

        try:
            from backend.emby_server import change_watcher
            change_watcher.start_chase_new_watcher()
            started.append("change_watcher")
            logger.info("✅ 追新已启动")
        except Exception as e:
            logger.warning(f"启动追新失败（可忽略）: {e}")

        # 8. 启动 Redis 扫描队列消费（API 进程入队，worker 消费执行）
        try:
            from backend.emby_server import scan_queue
            scan_queue.start_redis_consumer()
            started.append("scan_queue_consumer")
            logger.info("✅ Redis 扫描队列消费已启动")
        except Exception as e:
            logger.warning(f"启动扫描队列消费失败（可忽略）: {e}")

    except Exception:
        logger.exception("启动后台任务时发生未预期错误")
        _release_worker_lock(redis_client)
        return 1

    logger.info("✅ Aetrix Worker 启动完成（已启动 %d 个后台任务）" % len(started))
    _write_heartbeat(redis_client)

    # 9. 主循环：等关闭信号，定期写心跳
    try:
        while not _shutdown_event.is_set():
            _write_heartbeat(redis_client)
            _shutdown_event.wait(30)  # 每 30 秒写一次心跳
    except KeyboardInterrupt:
        logger.info("收到 KeyboardInterrupt，开始关闭...")
        _shutdown_event.set()

    # 10. 优雅关闭：停后台任务
    logger.info("👋 Aetrix Worker 正在关闭...")
    try:
        from backend.emby_server import scan_queue as _sq
        _sq.stop_redis_consumer(timeout=5.0)
    except Exception as e:
        logger.warning(f"停止 Redis 扫描消费失败：{e}")
    try:
        from backend.emby_server import probe_worker as _pw
        _pw.stop_probe_worker(timeout=10.0)
    except Exception as e:
        logger.warning(f"停止探测 worker 失败：{e}")
    try:
        from backend.emby_server import enrich_worker as _ew
        _ew.stop()
    except Exception as e:
        logger.warning(f"停止补全 worker 失败：{e}")
    try:
        from backend.emby_server import maintenance as _m
        _m.shutdown_cleanup()
    except Exception as e:
        logger.warning(f"退出收尾失败：{e}")

    _release_worker_lock(redis_client)
    logger.info("✅ Aetrix Worker 已关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())
