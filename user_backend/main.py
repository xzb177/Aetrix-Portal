"""
RoyalBot 用户端后端服务
FastAPI 应用
"""
import sys
import os

# 添加当前项目路径（必须在主项目路径之前）
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 添加主项目路径（用于访问主项目的数据库）
sys.path.append("/root/royalbot")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from utils.config import settings
from database import init_db

# Rate limiting middleware
from middleware import RateLimitMiddleware

# 导入 API 路由
from api import auth, subscription, request, recharge, emby, announcement, ticket, invitation, payment, stats, message, exchange_code, cron, analytics, badges, routes

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("正在启动 RoyalBot 用户端后端服务...")
    init_db()
    logger.info("数据库连接成功")

    # Initialize Redis client for rate limiting
    from utils.redis_client import get_redis_client
    redis_client = await get_redis_client()
    if redis_client:
        logger.info("Redis 已连接，限流功能已启用")
    else:
        logger.warning("Redis 未连接，限流功能将降级运行")

    # 启动定时任务调度器
    try:
        from services import start_scheduler
        start_scheduler()
        logger.info("定时任务调度器已启动")
    except Exception as e:
        logger.error(f"启动定时任务调度器失败: {e}")

    yield
    # 关闭时
    logger.info("用户端后端服务已停止")

    # 停止定时任务调度器
    try:
        from services import stop_scheduler
        stop_scheduler()
        logger.info("定时任务调度器已停止")
    except Exception as e:
        logger.error(f"停止定时任务调度器失败: {e}")

    # Close Redis connection
    from utils.redis_client import close_redis
    await close_redis()


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    description="RoyalBot 用户端 API 接口",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_URLS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware (must be after CORS)
app.add_middleware(RateLimitMiddleware)


# 注册路由
app.include_router(auth.router, prefix="/api/user/auth", tags=["认证"])
app.include_router(stats.router, prefix="/api/user", tags=["统计"])
app.include_router(subscription.router, prefix="/api/user/subscriptions", tags=["订阅"])
app.include_router(request.router, prefix="/api/user/requests", tags=["求片"])
app.include_router(recharge.router, prefix="/api/user/recharge", tags=["充值"])
app.include_router(emby.router, prefix="/api/user/emby", tags=["Emby"])
app.include_router(announcement.router, prefix="/api/user/announcements", tags=["公告"])
app.include_router(ticket.router, prefix="/api/user/tickets", tags=["工单"])
app.include_router(invitation.router, prefix="/api/user/invitation", tags=["邀请"])
app.include_router(exchange_code.router, prefix="/api/user/exchange-code", tags=["兑换码"])
app.include_router(payment.router, prefix="/api/user/payment", tags=["支付"])
app.include_router(message.router, prefix="/api/user/messages", tags=["站内消息"])
app.include_router(analytics.router, prefix="/api/user/analytics", tags=["数据埋点"])
app.include_router(badges.router, prefix="/api/user/badges", tags=["徽章系统"])
app.include_router(routes.router, prefix="/api/user/routes", tags=["线路选择"])
# 定时任务 API（需要 CRON_SECRET 鉴权）
app.include_router(cron.router, prefix="/api", tags=["定时任务"])


# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "RoyalBot User Portal is running"}


# 根路径
@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
