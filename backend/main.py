"""
RoyalBot Portal - 统一后端主入口
整合用户端和管理后台的所有 API
"""
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime
from prometheus_client import make_asgi_app

from backend.database import engine, get_db, init_db, cache, DATABASE_TYPE
from backend import models  # 导入所有模型
from backend.websocket import websocket_router, notification_router, manager
from backend.api import user_router, admin_router
from backend.emby_server.api import emby_router
from backend.emby_server.portal import user_emby_router, admin_emby_router
from backend.api.emby_portal import auth_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("🚀 RoyalBot Portal 正在启动...")
    logger.info(f"📊 数据库类型: {DATABASE_TYPE}")

    # 初始化数据库
    try:
        init_db()
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")

    logger.info("✅ RoyalBot Portal 启动完成")

    yield

    # 关闭时
    logger.info("👋 RoyalBot Portal 正在关闭...")


# 创建 FastAPI 应用
app = FastAPI(
    title="RoyalBot Portal",
    description="RoyalBot 统一门户 API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


# ==================== 中间件配置 ====================

# CORS 中间件（生产环境请设置 CORS_ORIGINS 环境变量限制具体域名）
_cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins_env.split(",") if o.strip()] or ["*"],
    allow_credentials=bool(_cors_origins_env),  # 通配源时禁用 credentials（避免无效组合）
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Emby-Authorization", "X-Emby-Token",
                   "X-MediaBrowser-Token", "X-Device-Id"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# 安全响应头
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith(("/api/", "/emby/")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response

# GZip 压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ==================== 异常处理 ====================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "服务器内部错误",
            "detail": str(exc) if app.debug else None,
        }
    )


# ==================== Prometheus 监控 ====================

# 挂载 Prometheus metrics 端点
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database": DATABASE_TYPE,
        "online_users": manager.get_online_count(),
        "emby_server": os.getenv("EMBY_SERVER_NAME", "RoyalBot Media Server"),
    }


@app.get("/api/health/detailed")
async def detailed_health_check():
    """详细健康检查"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {}
    }

    # 检查数据库
    try:
        db = next(get_db())
        db.execute("SELECT 1")
        health_status["services"]["database"] = {"status": "healthy"}
        db.close()
    except Exception as e:
        health_status["services"]["database"] = {"status": "unhealthy", "error": str(e)}
        health_status["status"] = "unhealthy"

    # 检查 Redis
    try:
        if cache.redis_client:
            cache.redis_client.ping()
            health_status["services"]["redis"] = {"status": "healthy"}
        else:
            health_status["services"]["redis"] = {"status": "disabled"}
    except Exception as e:
        health_status["services"]["redis"] = {"status": "unhealthy", "error": str(e)}
        health_status["status"] = "degraded"

    # WebSocket 连接数
    health_status["services"]["websocket"] = {
        "status": "healthy",
        "online_users": manager.get_online_count()
    }

    return health_status


# ==================== 路由注册 ====================

# WebSocket 路由
app.include_router(websocket_router)
app.include_router(notification_router)

# 用户端 API 路由
app.include_router(user_router)

# 管理后台 API 路由
app.include_router(admin_router)

# 自建 Emby 服务器（Emby 客户端直接连接本后端：https://host:port/emby）
app.include_router(emby_router)

# 自建 Emby 门户 API（用户端账号卡/续看/收藏 + 管理端媒体库管理）
app.include_router(user_emby_router)
app.include_router(admin_emby_router)

# 用户门户认证 API（注册/登录/JWT）
app.include_router(auth_router)


# ==================== 根路径 ====================

@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "RoyalBot Portal",
        "version": "2.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "docs": "/api/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
