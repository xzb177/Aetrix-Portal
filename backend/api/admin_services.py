"""后端服务状态 API：API 服务 + Worker 服务的健康状态"""
import json
import logging
import os
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.admin_core import get_current_admin
from backend.database import get_db

logger = logging.getLogger(__name__)

services_router = APIRouter(prefix="/api/admin", tags=["管理后台·服务状态"])


def _get_redis():
    """获取 Redis 连接，失败返回 None"""
    try:
        import redis
        url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        # 容器内 redis 主机名可能是 redis 或 aetrix-redis
        for u in [url, "redis://redis:6379/0", "redis://aetrix-redis:6379/0", "redis://localhost:6379/0"]:
            try:
                r = redis.from_url(u, socket_timeout=2)
                r.ping()
                return r
            except Exception:
                continue
    except Exception:
        pass
    return None


@services_router.get("/services/status")
def get_services_status(admin=Depends(get_current_admin), db: Session = Depends(get_db)):
    """返回后端服务状态：API 自身 + Worker 心跳"""
    now = time.time()

    # API 自身状态
    api_status = {
        "name": "aetrix-api",
        "role": "api",
        "status": "healthy",
        "timestamp": now,
    }

    # Worker 心跳（Redis）
    worker_status = {
        "name": "aetrix-worker",
        "role": "worker",
        "status": "unknown",
        "last_heartbeat": None,
        "lag_seconds": None,
    }
    r = _get_redis()
    if r:
        try:
            raw = r.get("aetrix:worker:heartbeat")
            if raw:
                hb = json.loads(raw)
                updated = hb.get("updated_at", 0)
                lag = now - updated
                worker_status["last_heartbeat"] = updated
                worker_status["lag_seconds"] = round(lag, 1)
                # 心跳 60 秒内算 healthy
                worker_status["status"] = "healthy" if lag < 60 else "stale"
                worker_status["pid"] = hb.get("pid")
                worker_status["started_at"] = hb.get("started_at")
            else:
                worker_status["status"] = "no_heartbeat"
        except Exception as e:
            logger.warning(f"读取 worker 心跳失败: {e}")
            worker_status["status"] = "error"
    else:
        worker_status["status"] = "redis_unavailable"

    return {
        "success": True,
        "services": [api_status, worker_status],
        "timestamp": now,
    }


@services_router.get("/quota-breaker/status")
def get_quota_breaker_status(admin=Depends(get_current_admin)):
    """熔断器状态（供管理后台展示）"""
    from backend.emby_server.probe_worker import quota_breaker_status
    st = quota_breaker_status()
    return {"success": True, "breaker": st}


@services_router.post("/quota-breaker/reset")
def reset_quota_breaker(admin=Depends(get_current_admin)):
    """手动重置熔断器（配额恢复后调用）"""
    from backend.emby_server.probe_worker import quota_breaker_reset
    quota_breaker_reset()
    logger.info("管理员手动重置了配额熔断器")
    return {"success": True, "message": "熔断器已重置，worker 恢复工作"}


__all__ = ["services_router"]
