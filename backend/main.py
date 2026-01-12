"""
RoyalBot Portal - 统一后端主入口
整合用户端和管理后台的所有 API
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
from datetime import datetime
from prometheus_client import make_asgi_app

from backend.database import engine, get_db, init_db, cache, DATABASE_TYPE
from backend import models  # 导入所有模型
from backend.websocket import websocket_router, notification_router, manager
from backend.api import user_router, admin_router

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

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
