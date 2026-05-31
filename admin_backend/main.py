"""
RoyalBot Emby 后台管理系统
FastAPI 后端服务
"""
import sys
import os
import traceback

# 加载 .env 文件（必须在其他导入之前）
from dotenv import load_dotenv
load_dotenv()

# 添加主项目路径（优先从环境变量读取，回退到上级目录）
parent_project = os.getenv("PARENT_PROJECT_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if parent_project not in sys.path:
    sys.path.insert(0, parent_project)

# 添加当前项目路径到 sys.path，并设置优先级
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    # 插入到 sys.path[1]，让主项目路径仍然优先（因为主项目有 database 等模块）
    sys.path.insert(1, current_dir)

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
import logging

# 使用绝对路径导入以避免模块冲突
import importlib.util

# 加载 config 模块
config_path = os.path.join(current_dir, "admin_utils", "config.py")
spec = importlib.util.spec_from_file_location("admin_config", config_path)
config_module = importlib.util.module_from_spec(spec)
sys.modules['admin_config'] = config_module
spec.loader.exec_module(config_module)
settings = config_module.settings

# 加载 admin_database 模块
db_path = os.path.join(current_dir, "admin_database.py")
spec = importlib.util.spec_from_file_location("admin_database", db_path)
db_module = importlib.util.module_from_spec(spec)
sys.modules['admin_database'] = db_module
spec.loader.exec_module(db_module)
init_db = db_module.init_db
engine = db_module.admin_engine  # 管理后台使用 admin_engine

# 加载 API 路由
api_modules = {}
api_path = os.path.join(current_dir, "api")
for api_file in os.listdir(api_path):
    if api_file.endswith(".py") and api_file != "__init__.py":
        module_name = api_file[:-3]
        module_path = os.path.join(api_path, api_file)
        spec = importlib.util.spec_from_file_location(f"api_{module_name}", module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[f'api_{module_name}'] = module
        spec.loader.exec_module(module)
        api_modules[module_name] = module

# 获取 API 路由
auth = api_modules['auth']
users = api_modules['users']
emby = api_modules['emby']
push = api_modules['push']
activities = api_modules['activities']
stats = api_modules['stats']
portal_subscriptions = api_modules['portal_subscriptions']
emby_servers = api_modules['emby_servers']
announcements = api_modules['announcements']
tickets = api_modules['tickets']
invitations = api_modules['invitations']
exchange_codes = api_modules.get('exchange_codes')  # 兑换码管理
portal_users = api_modules['portal_users']
payment = api_modules.get('payment')  # 支付管理
admins = api_modules.get('admins')  # 管理员管理
security_api = api_modules.get('security')  # 安全管理
messages = api_modules.get('messages')  # 站内消息管理
media_requests = api_modules.get('media_requests')  # 求片管理
downloads = api_modules.get('downloads')  # 下载管理
settings_api = api_modules.get('settings')  # 系统配置管理 API
emby_sessions = api_modules.get('emby_sessions')  # Emby 会话和转码管理

# 日志配置 - 设置更安全的日志级别
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

# 容器内日志路径
log_path = os.getenv('LOG_PATH', '/app/logs/app.log')
os.makedirs(os.path.dirname(log_path), exist_ok=True)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_path)
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("正在启动 RoyalBot Emby 后台管理系统...")
    init_db()
    # 初始化用户端数据库表（求片、消息等）
    import admin_database_user
    admin_database_user.init_user_db()
    logger.info("数据库连接成功")
    yield
    # 关闭时
    logger.info("正在关闭数据库连接...")
    engine.dispose()
    logger.info("后台管理系统已停止")


# 创建 FastAPI 应用
app = FastAPI(
    title="RoyalBot Emby 后台管理系统",
    description="RoyalBot Emby 功能的可视化后台管理接口",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,  # 生产环境隐藏文档
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS 中间件 - 更严格的配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_URLS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)

# 性能和安全中间件
from middleware.performance import (
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
    PerformanceMiddleware,
)
from middleware.security import CSRFMiddleware

# 安全响应头（最外层）
app.add_middleware(SecurityHeadersMiddleware)

# CSRF 保护（在 SecurityHeadersMiddleware 之后）
if settings.ENABLE_CSRF_PROTECTION:
    app.add_middleware(CSRFMiddleware)

# 请求限流
if settings.ENABLE_RATE_LIMIT:
    app.add_middleware(RateLimitMiddleware)

# 性能监控
app.add_middleware(PerformanceMiddleware)

# 添加统一错误处理中间件
from middleware.error_handler import ErrorHandlerMiddleware
app.add_middleware(ErrorHandlerMiddleware)


# 安全异常处理 - 不泄露敏感信息
class SecurityError(Exception):
    """安全相关异常"""
    def __init__(self, message: str, code: str = "SECURITY_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


@app.exception_handler(SecurityError)
async def security_exception_handler(request: Request, exc: SecurityError):
    """安全异常处理"""
    logger.warning(f"Security exception on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": exc.message, "code": exc.code}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求验证异常处理"""
    logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "请求参数验证失败", "errors": exc.errors()}
    )


# 全局异常处理 - 不泄露敏感信息
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    # 记录完整错误到日志
    logger.error(
        f"Exception on {request.url.path}: {type(exc).__name__}",
        exc_info=True
    )

    # 生产环境不返回详细错误信息
    if settings.DEBUG:
        detail = str(exc)
    else:
        detail = "服务器内部错误，请稍后重试"

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": detail}
    )


# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/users", tags=["用户管理"])
app.include_router(emby.router, prefix="/api/emby", tags=["Emby数据"])
app.include_router(push.router, prefix="/api/push", tags=["推送管理"])
app.include_router(activities.router, prefix="/api/activities", tags=["活动管理"])
app.include_router(stats.router, prefix="/api/stats", tags=["统计分析"])
# 新增 Portal 管理路由
app.include_router(portal_users.router, prefix="/api", tags=["门户用户"])
app.include_router(portal_subscriptions.router, prefix="/api", tags=["订阅套餐"])
app.include_router(emby_servers.router, prefix="/api/emby-servers", tags=["Emby服务器"])
app.include_router(announcements.router, prefix="/api", tags=["公告管理"])
app.include_router(tickets.router, prefix="/api", tags=["工单管理"])
app.include_router(invitations.router, prefix="/api", tags=["邀请管理"])
# 兑换码管理路由
if exchange_codes:
    app.include_router(exchange_codes.router, prefix="/api", tags=["兑换码管理"])
# 站内消息管理路由
if messages:
    app.include_router(messages.router, prefix="/api", tags=["消息管理"])
# 支付管理路由
if payment:
    app.include_router(payment.router, prefix="/api", tags=["支付管理"])
# 管理员管理路由
if admins:
    app.include_router(admins.router, prefix="/api", tags=["管理员管理"])
# 安全管理路由
if security_api:
    app.include_router(security_api.router, prefix="/api/auth", tags=["安全管理"])
# 求片管理路由
if media_requests:
    app.include_router(media_requests.router, prefix="/api", tags=["求片管理"])
# 下载管理路由
if downloads:
    app.include_router(downloads.router, prefix="/api/downloads", tags=["下载管理"])
# 系统配置管理路由
if settings_api:
    app.include_router(settings_api.router, prefix="/api/settings", tags=["系统配置"])
# Emby 会话和转码管理路由
if emby_sessions:
    app.include_router(emby_sessions.router, prefix="/api/emby-sessions", tags=["Emby会话管理"])
# 系统日志查看路由
system_logs = api_modules.get('system_logs')
if system_logs:
    app.include_router(system_logs.router, prefix="/api", tags=["系统日志"])
# 运营中控台路由
admin_ops = api_modules.get('admin_ops')
if admin_ops:
    app.include_router(admin_ops.router, tags=["运营中控台"])
# 线路管理路由
routes_api = api_modules.get('routes')
if routes_api:
    app.include_router(routes_api.router, prefix="/api/routes", tags=["线路管理"])


# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "RoyalBot Emby 后台管理系统运行中"}


# 根路径 - 生产环境隐藏详细信息
@app.get("/")
async def root():
    if settings.DEBUG:
        return {
            "name": "RoyalBot Emby 后台管理系统",
            "version": "1.0.0",
            "docs": "/docs"
        }
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
