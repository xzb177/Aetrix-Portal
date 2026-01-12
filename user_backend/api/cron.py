"""
定时任务 API

提供手动触发定时任务的接口（带 CRON_SECRET 鉴权）
"""
import logging
from fastapi import APIRouter, Header, HTTPException, Request
from typing import Optional

from services import (
    scheduler,
    run_job_manually,
    check_expired_subscriptions,
    check_emby_server_health,
    cleanup_pending_orders,
    send_expiring_reminders,
    generate_daily_stats
)
from services.delivery_service import AccountDeliveryService
from database import SessionLocal
from utils.config import settings, get_cron_secret

router = APIRouter()
logger = logging.getLogger(__name__)


async def verify_cron_secret(request: Request, x_cron_secret: Optional[str] = Header(None)):
    """
    验证 CRON_SECRET

    Args:
        request: FastAPI Request
        x_cron_secret: 请求头中的密钥

    Raises:
        HTTPException: 鉴权失败
    """
    # 从数据库/环境变量获取密钥
    CRON_SECRET = get_cron_secret()

    # 检查 Header
    if x_cron_secret and x_cron_secret == CRON_SECRET:
        return

    # 检查 Query 参数
    query_secret = request.query_params.get('secret')
    if query_secret and query_secret == CRON_SECRET:
        return

    # 如果没有设置 CRON_SECRET，在非生产环境允许通过
    if not CRON_SECRET and settings.DEBUG:
        logger.warning("CRON_SECRET 未设置，允许跳过鉴权（仅开发环境）")
        return

    raise HTTPException(
        status_code=403,
        detail="Forbidden: Invalid or missing CRON_SECRET"
    )


@router.get("/cron/status")
async def get_cron_status(request: Request):
    """
    获取调度器状态

    不需要鉴权，仅返回基本信息
    """
    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None
            })

    return {
        'running': scheduler.running,
        'jobs': jobs
    }


@router.post("/cron/run/{job_id}")
async def run_cron_job(job_id: str, request: Request):
    """
    手动执行定时任务

    需要提供 CRON_SECRET 鉴权

    Args:
        job_id: 任务ID

    可用任务:
    - check_expired_subscriptions: 订阅过期处理
    - check_emby_server_health: Emby 健康检查
    - cleanup_pending_orders: 订单超时清理
    - send_expiring_reminders: 订阅过期提醒
    - generate_daily_stats: 每日统计汇总
    - retry_account_delivery: 账号发放重试
    """
    await verify_cron_secret(request)

    valid_jobs = [
        'check_expired_subscriptions',
        'check_emby_server_health',
        'cleanup_pending_orders',
        'send_expiring_reminders',
        'generate_daily_stats',
        'retry_account_delivery',
    ]

    if job_id not in valid_jobs:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job_id. Valid options: {', '.join(valid_jobs)}"
        )

    # 特殊处理账号发放重试
    if job_id == 'retry_account_delivery':
        db = SessionLocal()
        try:
            stats = await AccountDeliveryService.retry_pending_deliveries(db)
            return {
                'success': True,
                'job_id': job_id,
                'result': stats
            }
        finally:
            db.close()

    # 执行定时任务
    try:
        await run_job_manually(job_id)
        return {
            'success': True,
            'job_id': job_id,
            'message': f'Task {job_id} executed successfully'
        }
    except Exception as e:
        logger.error(f"执行任务 {job_id} 失败: {e}")
        return {
            'success': False,
            'job_id': job_id,
            'message': str(e)
        }


@router.post("/cron/start")
async def start_cron_scheduler(request: Request):
    """
    启动调度器

    需要提供 CRON_SECRET 鉴权
    """
    await verify_cron_secret(request)

    if scheduler.running:
        return {
            'success': True,
            'message': 'Scheduler is already running'
        }

    try:
        start_scheduler()
        return {
            'success': True,
            'message': 'Scheduler started successfully'
        }
    except Exception as e:
        logger.error(f"启动调度器失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start scheduler: {str(e)}"
        )


@router.post("/cron/stop")
async def stop_cron_scheduler(request: Request):
    """
    停止调度器

    需要提供 CRON_SECRET 鉴权
    """
    await verify_cron_secret(request)

    if not scheduler.running:
        return {
            'success': True,
            'message': 'Scheduler is not running'
        }

    try:
        stop_scheduler()
        return {
            'success': True,
            'message': 'Scheduler stopped successfully'
        }
    except Exception as e:
        logger.error(f"停止调度器失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop scheduler: {str(e)}"
        )


@router.get("/cron/queue")
async def get_delivery_queue(request: Request):
    """
    获取账号发放队列状态

    需要提供 CRON_SECRET 鉴权
    """
    await verify_cron_secret(request)

    from database.models import AccountDeliveryQueue

    db = SessionLocal()
    try:
        pending = db.query(AccountDeliveryQueue).filter(
            AccountDeliveryQueue.status == 'pending'
        ).count()

        processing = db.query(AccountDeliveryQueue).filter(
            AccountDeliveryQueue.status == 'processing'
        ).count()

        failed = db.query(AccountDeliveryQueue).filter(
            AccountDeliveryQueue.status == 'failed'
        ).count()

        completed = db.query(AccountDeliveryQueue).filter(
            AccountDeliveryQueue.status == 'completed'
        ).count()

        return {
            'pending': pending,
            'processing': processing,
            'failed': failed,
            'completed': completed
        }

    finally:
        db.close()
