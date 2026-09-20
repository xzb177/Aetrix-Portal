"""
RoyalBot Portal - 统一后端主入口
整合用户端和管理后台的所有 API，并托管用户前端（Vue SPA）静态资源
"""
import os

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
from datetime import datetime
from pathlib import Path
from prometheus_client import make_asgi_app

from backend.database import engine, get_db, init_db, cache, DATABASE_TYPE
from backend import models  # 导入所有模型
from backend.download_guard import DownloadGuardMiddleware
from backend.websocket import websocket_router, notification_router, manager
from backend.api import user_router, admin_router
from backend.api.admin_ops import admin_ops_router
from backend.emby_server.api import emby_router
from backend.emby_server.portal import user_emby_router, admin_emby_router
from backend.api.emby_portal import auth_router
from backend.api.economy import router as economy_router
from backend.api.invitation import router as invitation_router

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
    version="2.6.0",
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

# 下载策略兜底（覆盖 /Download 与 /Items/{id}/File 等全部下载类路径）
app.add_middleware(DownloadGuardMiddleware)


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
app.include_router(admin_ops_router)

# 自建 Emby 服务器（Emby 客户端直接连接本后端：https://host:port/emby）
app.include_router(emby_router)

# 自建 Emby 门户 API（用户端账号卡/续看/收藏 + 管理端媒体库管理）
app.include_router(user_emby_router)
app.include_router(admin_emby_router)

# 用户门户认证 API（注册/登录/JWT）
app.include_router(auth_router)

# 用户经济系统（签到/兑换码/支付/订单）与邀请返利
app.include_router(economy_router)
app.include_router(invitation_router)


# ==================== 根路径 ====================

@app.get("/")
async def root():
    """根路径"""
    index_file = _FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {
        "name": "RoyalBot Portal",
        "version": "2.5.4",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "docs": "/api/docs",
    }


# ==================== 用户前端静态资源托管 ====================
# 优先级顺序：先注册 API/WS 路由，再挂载静态资源与 SPA fallback，
# 保证 /api/*、/emby/*、/ws 不被前端兜底路由吞掉。

_FRONTEND_DIST = Path(
    os.getenv(
        "FRONTEND_DIST",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "user_frontend", "dist"),
    )
)

# 管理后台静态资源（/admin/*，Vite base=/admin/，构建产物在 admin_frontend/dist）
_ADMIN_DIST = Path(
    os.getenv(
        "ADMIN_DIST",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin_frontend", "dist"),
    )
)

if _ADMIN_DIST.is_dir():
    app.mount("/admin/assets", StaticFiles(directory=str(_ADMIN_DIST / "assets")), name="admin-assets")

    @app.get("/admin", include_in_schema=False)
    async def admin_root():
        """管理后台根路径（重定向到带斜杠的 SPA 入口）"""
        return RedirectResponse(url="/admin/")

    @app.get("/admin/{full_path:path}", include_in_schema=False)
    async def admin_spa_fallback(full_path: str):
        """管理后台 SPA 兜底路由：/admin/* 返回 admin index.html"""
        candidate = (_ADMIN_DIST / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(_ADMIN_DIST.resolve())):
            return FileResponse(candidate)
        return FileResponse(_ADMIN_DIST / "index.html")

    logger.info("管理后台静态资源已挂载: %s", _ADMIN_DIST)
else:
    logger.warning("管理后台构建产物不存在（%s），/admin 不可用", _ADMIN_DIST)

if _FRONTEND_DIST.is_dir():
    # 注意：/assets 由 StaticFiles 直接服务（构建产物固定输出到 assets/）
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 兜底路由：非 API/WS 路径全部返回前端 index.html"""
        if full_path.startswith(("api/", "emby/", "ws", "metrics")):
            raise HTTPException(status_code=404, detail="Not Found")
        # 真实存在的静态文件直接返回（favicon.ico / manifest.webmanifest 等），并防目录穿越
        candidate = (_FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(_FRONTEND_DIST.resolve())):
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")

    logger.info("用户前端静态资源已挂载: %s", _FRONTEND_DIST)
else:
    logger.warning("前端构建产物不存在（%s），仅提供 API 服务", _FRONTEND_DIST)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
