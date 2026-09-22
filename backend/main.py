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

try:  # Starlette ≥ 0.47 提供默认排除表（老版本没有该常量，行为保持原样）
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES as _GZIP_DEFAULTS
except ImportError:  # pragma: no cover
    _GZIP_DEFAULTS = ()
from contextlib import asynccontextmanager
import logging
from datetime import datetime
from pathlib import Path
from prometheus_client import make_asgi_app

from backend.metrics_guard import MetricsGuard
from sqlalchemy import text

from backend.database import SessionLocal, engine, get_db, init_db, DATABASE_TYPE
from backend import models  # 导入所有模型
from backend.download_guard import DownloadGuardMiddleware
from backend.websocket import websocket_router, notification_router, manager
from backend.api import user_router, admin_router
from backend.api.emby_servers import router as emby_servers_router
from backend.api.realms import router as realms_router
from backend.api.servers import router as servers_router
from backend import realms
from backend.emby_server import nodes as node_lib
from backend.emby_server import maintenance
from backend import reminders
from backend.api.admin_ops import admin_ops_router
from backend.api.reminders_admin import admin_reminders_router
from backend.api.orders_admin import admin_orders_router
from backend.api.coupons_admin import admin_coupons_router
from backend.emby_server.api import emby_router

# v2.15.0：分类关联表（筛选走索引）。导入即注册 ORM flush 钩子——
# 任何写 genres/studios/tags/platforms 的代码（扫描器、图片修复…）都会在同一个事务里
# 把关联行同步好，不需要每个调用点各自记得调一次。
from backend.emby_server import facets  # noqa: F401

# v2.13.0：api.py 拆分出来的协议路由模块。导入即把路由注册到同一个 emby_router 上，
# 这里的顺序（media → compat → stream）与拆分前的定义顺序一致，不能调换。
from backend.emby_server import media_routes  # noqa: F401
from backend.emby_server import compat_routes  # noqa: F401
from backend.emby_server import stream_routes  # noqa: F401
from backend.emby_server.image_routes import install_image_routes
from backend.emby_server.mount_routes import install_mount_routes
from backend.emby_server.session_routes import install_session_routes
from backend.emby_server.search_api import search_router
from backend.emby_server.portal import user_emby_router, admin_emby_router, configured_emby_url
from backend.api.emby_portal import auth_router
from backend.api.economy import router as economy_router
from backend.api.invitation import router as invitation_router
from backend.emby_server import transfer115

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

    # 内容可见性：面板自带的网关按「服」过滤（默认服 → 与单服部署完全一致）。
    # 多服部署时各服的 EA 各自提供本服内容，这里只保证面板不会把别的服的内容也端出去。
    try:
        node_lib.install_scope("em")
    except Exception as e:  # noqa: BLE001 — 过滤装不上也不能阻止面板启动
        logger.warning(f"内容可见性未生效（按不过滤处理）: {e}")

    # 恢复未完成的 115 转存/下载任务：running 说明上次进程被杀，回到 pending 续跑，
    # 已完成文件靠 done_keys 跳过，不会重复转存
    try:
        transfer115.cleanup_stale_tmp()  # 上次被强杀留下的临时文件
        transfer115.resume_pending_tasks()
    except Exception as e:  # noqa: BLE001 — 业务表异常不应阻塞面板启动
        logger.warning(f"恢复 115 任务失败（可忽略）: {e}")

    # 崩溃残留的收尾 + 长期运行的后台维护（扫描标志 / 过期会话 / 转码目录 / 字幕缓存），
    # 见 backend/emby_server/maintenance.py。维护失败不影响启动。
    try:
        maintenance.run_startup_maintenance()
        maintenance.start_janitor()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"启动维护失败（可忽略）: {e}")

    # 订阅到期提醒：会员到期前按 7/3/1 天提前通知（否则只能等用户自己想起来续费）。
    # 与维护一样是后台线程，失败不影响启动；EA 侧不启动（见 backend/reminders.py）。
    try:
        reminders.start_reminder_scheduler()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"启动到期提醒失败（可忽略）: {e}")

    logger.info("✅ RoyalBot Portal 启动完成")

    yield

    # 关闭时：先收掉子进程与临时文件，避免 ffmpeg 变成孤儿继续吃 CPU/磁盘
    logger.info("👋 RoyalBot Portal 正在关闭...")
    try:
        maintenance.shutdown_cleanup()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"退出收尾失败（可忽略）: {e}")


# 创建 FastAPI 应用
app = FastAPI(
    title="RoyalBot Portal",
    description="RoyalBot 统一门户 API",
    version="2.15.0",
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
    path = request.url.path
    if path.startswith(("/api/", "/emby/")):
        response.headers.setdefault("Cache-Control", "no-store")
    elif response.status_code == 200 and path.startswith(("/assets/", "/admin/assets/")):
        # Vite 产物文件名带内容哈希：内容不变则文件名不变，可以长期强缓存
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif "text/html" in response.headers.get("content-type", ""):
        # SPA 入口每次都要回源校验：发了新版本用户刷新就能拿到新构建
        response.headers.setdefault("Cache-Control", "no-cache")
    return response

# GZip 压缩：JSON / HTML / 接口响应走压缩，已压缩或大块二进制内容不再压缩。
# Starlette 默认排除 video/*、image/* 等；这里补上 application/octet-stream ——
# 挂载代理转发的媒体文件若按 level 9 压缩会白白吃满 CPU，且对已压缩容器毫无收益。
_GZIP_EXCLUDES = (*_GZIP_DEFAULTS, "application/octet-stream", "application/zip")
try:
    app.add_middleware(GZipMiddleware, minimum_size=1000, exclude_content_types=_GZIP_EXCLUDES)
except TypeError:  # pragma: no cover — 老版 Starlette 没有按内容类型排除的参数
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
# 默认只允许本机/内网采集：指标会把全部路由与计数摊开，不该裸挂公网
app.mount("/metrics", MetricsGuard(metrics_app))


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
        "service": "em",
        "version": app.version,
        "emby_gateway": _ENABLE_EMBY_GATEWAY,
        # 长期运行的体检口径：正在扫描的库 / 转码会话 / 临时目录占用 / 磁盘余量
        "runtime": _runtime_report(),
    }


def _runtime_report() -> dict:
    """运行期资源快照（健康检查用；任何异常都不该让健康检查变 500）"""
    try:
        report = maintenance.resource_report()
        report["active_scans"] = maintenance.active_scan_count()
        return report
    except Exception as e:  # noqa: BLE001
        logger.debug(f"读取运行期资源失败: {e}")
        return {}


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
        db = SessionLocal()
        try:
            # 必须用 text() 包装：SQLAlchemy 2.0 不再接受裸字符串，
            # 之前这里恒抛异常导致数据库永远报 unhealthy（狼来了）
            db.execute(text("SELECT 1"))
            health_status["services"]["database"] = {"status": "healthy"}
        finally:
            db.close()
    except Exception as e:
        health_status["services"]["database"] = {"status": "unhealthy", "error": str(e)}
        health_status["status"] = "unhealthy"

    # 检查 Redis
    # 必须读 backend.database 的模块级 redis_client：CacheManager 上并没有
    # redis_client 属性，之前这里恒抛 AttributeError，导致整体状态永远是 degraded
    try:
        from backend import database as _db_module

        if _db_module.redis_client:
            _db_module.redis_client.ping()
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
# 订阅到期提醒的面板口径与手动执行（见 backend/api/reminders_admin.py）
app.include_router(admin_reminders_router)
# 订单关单与退款（见 backend/api/orders_admin.py）
app.include_router(admin_orders_router)
# 优惠券管理（v2.10.0）：券的 CRUD / 核销记录 / 开关，见 backend/api/coupons_admin.py
app.include_router(admin_coupons_router)
# 多服运营：服的增删改查 / 每服运营数据 / 切换当前服（见 backend/realms.py）
app.include_router(realms_router)
app.include_router(emby_servers_router)
app.include_router(servers_router)

# ==================== 自建 Emby 协议网关 ====================
# 默认由 EM 一并提供（单进程模式，现有部署行为不变）；
# 分离部署时置 ENABLE_EMBY_GATEWAY=false，协议面交给独立的 EA 服务，见 docs/deploy-ea.md
_ENABLE_EMBY_GATEWAY = os.getenv("ENABLE_EMBY_GATEWAY", "true").strip().lower() not in {
    "0", "false", "no", "off",
}

if _ENABLE_EMBY_GATEWAY:
    # 搜索接口先注册：FastAPI 按注册顺序取第一个匹配，
    # 这样 /Search/Hints 走 search_api 的相关度排序版（api.py 里的同名历史实现会被遮蔽）
    app.include_router(search_router)
    # 挂载来源：把只认本机文件的 /Items/{id}/File 换成挂载感知实现（必须在 include_router 前）
    install_mount_routes(emby_router)
    # 会话端点：补鉴权（普通用户只看/只能停自己）并把会话键改为随机（必须在 include_router 前）
    install_session_routes(emby_router)
    # 图片端点：接上条件请求（客户端缓存仍有效时 304），媒体库滚动/切页不再重传同一张海报
    install_image_routes(emby_router)
    # Emby 客户端直接连接本后端：https://host:port/emby（另含裸根路径 /System/Info 等）
    app.include_router(emby_router)
    logger.info("Emby 协议网关已挂载于 EM（单进程模式）")
else:
    logger.info("Emby 协议网关未在 EM 启用（分离部署）；客户端请连接 EA")

    async def _ea_pointer():
        """分离部署下，客户端误连面板时给出明确指引，而不是返回 SPA 的 HTML

        地址优先取管理后台「Emby 服务入口」里保存的分离部署地址（每次请求实时解析），
        没有再回退到环境变量，保证管理员在面板上改完地址后这里的指引也跟着变。
        """
        hint = (
            configured_emby_url()
            or os.getenv("EMBY_API_PUBLIC_URL", "").strip().rstrip("/")
            or os.getenv("EMBY_PUBLIC_URL", "").strip().rstrip("/")
            or "EA 服务地址"
        )
        raise HTTPException(
            status_code=404,
            detail=f"本地址（EM 面板）不提供 Emby 协议面，请把客户端指向 EA：{hint}",
        )

    # 裸根协议路径（/System/Info、/Users/AuthenticateByName …）与 /emby/* 各注册一份指引
    for _route in emby_router.routes:
        _route_path = getattr(_route, "path", "")
        if _route_path and not _route_path.startswith("/emby"):
            app.api_route(
                _route_path,
                methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
                include_in_schema=False,
            )(_ea_pointer)
    app.api_route(
        "/emby/{rest:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        include_in_schema=False,
    )(_ea_pointer)

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
        "version": app.version,
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
