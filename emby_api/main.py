"""EA · Emby API —— Emby 协议网关（独立部署单元）

与 EM（面板，`backend/main.py`）配对运行：

- 客户端（Infuse / Fileball / Forward+ / Hills / SenPlayer / 官方 App）直连本服务，
  对外就是一个 Emby 服务器：协议面同时提供 `/emby/*` 与**裸根路径**（`/System/Info`、
  `/Users/AuthenticateByName` …），所以 EA 必须独占一个地址（子域名或独立端口）。
- 用户、媒体库、套餐与订阅状态、设备风控与限流策略、下载开关，全部来自 EM 写入的
  **共享数据库**——EM 是"推下来"的一方，EA 不自己定义业务策略。
- 因此 **EA 不能脱离 EM 单独运行**：缺 `SECRET_KEY`（EM 签发 token、EA 校验，必须同一个）
  或共享库里还没有 EM 的表时，启动即拒绝，而不是带病跑起来。

部署与域名规划见 `docs/deploy-ea.md`。
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from sqlalchemy import inspect

from backend.database import DATABASE_TYPE, SessionLocal, engine
from backend import models  # noqa: F401 — 注册全部模型，保证 ORM 关系可解析
from backend.emby_server import models as _emby_models  # noqa: F401
from backend.download_guard import DownloadGuardMiddleware
from backend.emby_server import nodes as node_lib
from backend.emby_server import maintenance
from backend.emby_server.api import emby_router
from backend.emby_server.mount_health import panel_router as mount_health_router
from backend.emby_server.mount_routes import install_mount_routes
from backend.emby_server.nodes import node_router
from backend.emby_server.session_routes import install_session_routes
from backend.emby_server.search_api import search_router
from backend.subscriptions import set_process_realm_resolver

EA_VERSION = "2.10.4"
SERVICE_NAME = "EA · Emby API"

logger = logging.getLogger(__name__)

# EM 初始化后才会存在的表：缺任何一个都说明 EM 还没在这套库上跑过
_REQUIRED_EM_TABLES = ("web_users", "emby_libraries", "emby_api_tokens")


class PanelDependencyError(RuntimeError):
    """EA 与 EM 的配对关系不成立，禁止启动。"""


def _missing_em_tables() -> list[str]:
    existing = set(inspect(engine).get_table_names())
    return [t for t in _REQUIRED_EM_TABLES if t not in existing]


def ensure_paired_with_em() -> None:
    """启动前校验：EA 必须有 EM 签发的凭据与 EM 建好的共享库"""
    if not os.getenv("SECRET_KEY", "").strip():
        raise PanelDependencyError(
            "SECRET_KEY 未设置。EA 与 EM 必须使用同一个 SECRET_KEY"
            "（客户端 token 由 EM 签发、由 EA 校验），请复用 EM 的 .env。"
        )

    missing = _missing_em_tables()
    if missing:
        raise PanelDependencyError(
            f"共享数据库缺少 EM 的表：{', '.join(missing)}（当前 DATABASE_URL 指向 {DATABASE_TYPE}）。"
            "EA 不能脱离 EM 单独运行：请先在 EM 上完成初始化（python serve.py）并至少建一个媒体库，"
            "再让 EA 指向同一个 DATABASE_URL。"
        )


def _panel_url() -> str:
    return os.getenv("EM_PANEL_URL", "").strip().rstrip("/")


async def _probe_panel() -> None:
    """探测 EM 是否可达（仅日志，不阻断）

    EM 短暂重启不应该让正在播放的客户端断开，所以这里只告警；真正的硬依赖是
    共享密钥与共享库（见 ensure_paired_with_em）。
    """
    url = _panel_url()
    if not url:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/api/health")
        logger.info("EM 面板可达（%s）: %s", url, resp.status_code)
    except Exception as exc:  # noqa: BLE001 — 探测失败不影响 EA 自身服务
        logger.warning("EM 面板当前不可达（%s）: %s；已有 token 的客户端仍可继续播放", url, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 %s 正在启动（v%s）...", SERVICE_NAME, EA_VERSION)
    logger.info("📊 共享数据库: %s", DATABASE_TYPE)

    # 硬依赖：不满足就不启动，避免出现"能连上但谁都播不了"的假服务
    ensure_paired_with_em()
    logger.info("✅ 已确认与 EM 配对（共享密钥 + 共享库）")

    _claim_identity()
    await _probe_panel()

    # 崩溃残留的收尾 + 长期运行的后台维护（扫描标志 / 过期会话 / 转码目录 / 字幕缓存）。
    # 同一套库可能同时被 EM 与多台 EA 打开，这里做的是幂等且带阈值判断的清理。
    try:
        maintenance.run_startup_maintenance()
        maintenance.start_janitor()
    except Exception as exc:  # noqa: BLE001 — 维护失败不影响出流
        logger.warning("启动维护失败（可忽略）: %s", exc)

    logger.info("✅ %s 启动完成", SERVICE_NAME)
    yield
    # 关闭时：收掉 ffmpeg 子进程与临时分片，不留孤儿进程占着 CPU/磁盘
    logger.info("👋 %s 正在关闭...", SERVICE_NAME)
    try:
        maintenance.shutdown_cleanup()
    except Exception as exc:  # noqa: BLE001
        logger.warning("退出收尾失败（可忽略）: %s", exc)


def _claim_identity() -> None:
    """认领本机的节点 / 服身份，并装好内容可见性与订阅闸门

    多台 EA 同时出流靠这三件事：

    1. ``NODE_KEY`` 认领面板里的一条服务器记录（认领不到就自动登记一条，方便分配媒体库）；
    2. ``REALM``（或在面板里给这台服务器指定的服）决定**只提供哪个服的内容**；
    3. 订阅闸门按本机的服判定——甲服的会员不能在乙服的 EA 上白瞟。

    两件都没配时什么都不做：单机单服部署行为与以前完全一致。
    """
    db = SessionLocal()
    try:
        if node_lib.configured_key():
            node_lib.register_self(db, url=_public_url())
        scope = node_lib.install_scope("ea")
        if scope.get("active"):
            logger.info("本节点只提供：服 #%s 的内容（来自 REALM/节点归属）", scope.get("realm_id"))
    except Exception as exc:  # noqa: BLE001 — 认领失败不能阻止 EA 提供服务
        logger.warning("认领节点身份失败（按不过滤处理）: %s", exc)
    finally:
        db.close()

    # 订阅闸门：把「本进程的服」传给 backend.subscriptions，播放时按服校验会员
    def _realm():
        session = SessionLocal()
        try:
            return node_lib.self_realm_id(session)
        finally:
            session.close()

    set_process_realm_resolver(_realm)


def _public_url() -> str:
    """本节点对外地址（面板登记时用）：优先环境变量，其次拼端口"""
    explicit = os.getenv("EMBY_API_PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("HOST", "0.0.0.0")
    if host in ("0.0.0.0", "::"):
        return ""
    return f"http://{host}:{os.getenv('EMBY_API_PORT', '8001')}"


app = FastAPI(
    title="EA · Emby API",
    description="Emby 协议网关（由 EM 面板下发用户、媒体库与策略）",
    version=EA_VERSION,
    # 协议面不需要对外暴露交互式文档
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# ==================== 中间件 ====================
# Emby 客户端不走浏览器 CORS，但网页播放器与第三方 Web 播放页会；沿用 EM 的口径
_cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins_env.split(",") if o.strip()] or ["*"],
    allow_credentials=bool(_cors_origins_env),
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type", "Authorization", "X-Emby-Authorization", "X-Emby-Token",
        "X-MediaBrowser-Token", "X-Device-Id", "Range",
    ],
    # 直连流与 HLS 依赖这些响应头能被前端读取
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/emby/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.add_middleware(GZipMiddleware, minimum_size=1000)

# 下载策略兜底：站点关闭下载时，/Download 与 /Items/{id}/File 等路径在网关层拦截
app.add_middleware(DownloadGuardMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("未处理的异常: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


# ==================== 监控与健康检查 ====================

app.mount("/metrics", make_asgi_app())


@app.get("/api/health")
async def health_check():
    """EA 健康检查：同时报告与 EM 的配对状态"""
    missing = _missing_em_tables()
    return {
        "service": "ea",
        "status": "healthy" if not missing else "unpaired",
        "version": EA_VERSION,
        "timestamp": datetime.now().isoformat(),
        "database": DATABASE_TYPE,
        "paired_with_em": not missing,
        "missing_em_tables": missing,
        "em_panel_url": _panel_url() or None,
        "emby_server_name": os.getenv("EMBY_SERVER_NAME", "RoyalBot Media Server"),
        # 多机 / 多服部署的关键信息：这台 EA 是谁、属于哪个服、只提供什么内容
        "node": _node_info(),
        # 长期运行的体检口径：正在扫描的库 / 转码会话 / 临时目录占用 / 磁盘余量
        "runtime": _runtime_report(),
    }


def _runtime_report() -> dict:
    """运行期资源快照（健康检查用；任何异常都不该让健康检查变 500）"""
    try:
        report = maintenance.resource_report()
        report["active_scans"] = maintenance.active_scan_count()
        return report
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取运行期资源失败: %s", exc)
        return {}


def _node_info() -> dict:
    """本进程的节点 / 服身份（探活与排查用；查不到库时返回空结构）"""
    db = SessionLocal()
    try:
        return node_lib.describe(db)
    except Exception as exc:  # noqa: BLE001 — 健康检查不能被身份解析拖垮
        logger.debug("读取节点身份失败: %s", exc)
        return {}
    finally:
        db.close()


@app.get("/", include_in_schema=False)
async def service_root():
    """根路径不是 Emby 协议的一部分，给运维一个可读的识别点"""
    return {
        "service": SERVICE_NAME,
        "version": EA_VERSION,
        "hint": "客户端请把本地址作为 Emby 服务器地址；面板在 EM（见 EM_PANEL_URL）",
        "health": "/api/health",
    }


# ==================== Emby 协议面 ====================
# 注意：emby_router 同时声明了 /emby/* 与裸根路径（/System/Info、/Users/AuthenticateByName …），
# 因此 EA 必须独占一个地址，不能与 EM 的 SPA 兜底路由共用一个根路径。
# 搜索接口先注册（FastAPI 按注册顺序取第一个匹配）：/Search/Hints 走相关度排序版。
app.include_router(search_router)
# 挂载体检（EM 保存服务入口 / 手动刷新时调用）：EA 视角跑一遍 resolve 与路径检查，
# 让面板能显示「这台 EA 到底碰不碰得到你配的存储」。用共享 SECRET_KEY 鉴权，不是管理员 JWT。
app.include_router(mount_health_router)
# 节点身份 / 由归属节点扫描媒体库：面板在保存服务器与分配媒体库时调用，同样是共享 SECRET_KEY 鉴权。
app.include_router(node_router)
# 挂载来源：把只认本机文件的 /Items/{id}/File 换成挂载感知实现（必须在 include_router 前）
install_mount_routes(emby_router)
# 会话端点：补鉴权（普通用户只看/只能停自己）并把会话键改为随机（必须在 include_router 前）
install_session_routes(emby_router)
app.include_router(emby_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "emby_api.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("EMBY_API_PORT", "8001")),
        log_level=os.getenv("LOG_LEVEL", "info"),
        # 单进程：转码子进程与会话管理在同一进程内闭环，多 worker 会重复 fork
        workers=1,
    )
