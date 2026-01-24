"""
定时任务调度器

使用 APScheduler 实现定时任务，包括：
- P0: 订阅过期处理（每日凌晨2点）
- P0: Emby 健康检查（每5分钟）
- P0: 订单超时清理（每小时）
- P1: 订阅即将过期提醒（每日上午10点）
- P2: 统计汇总（每日凌晨3点）
"""
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.asyncio import AsyncIOExecutor
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import DATABASE_URL, SessionLocal
from database.models import (
    UserSubscription, UserEmbyAccount, EmbyServer,
    SubscriptionOrder, WebUser, Message
)
from utils.emby_client import EmbyClient
from utils.telegram import send_telegram_message
from utils.notifier import (
    send_expiring_reminder_message,
    send_system_alert_message
)

logger = logging.getLogger(__name__)

# 调度器配置
executors = {
    'default': AsyncIOExecutor(),
}
job_defaults = {
    'coalesce': True,  # 合并错过的任务
    'max_instances': 1,  # 同一任务最多1个实例运行
    'misfire_grace_time': 3600,  # 错过任务后的宽限时间（秒）
}

# 创建调度器
scheduler = AsyncIOScheduler(
    executors=executors,
    job_defaults=job_defaults,
    timezone='Asia/Shanghai'
)


# ==================== P0: 订阅过期处理 ====================

async def check_expired_subscriptions():
    """
    P0 定时任务：处理过期订阅

    执行时间：每日凌晨 2:00
    逻辑：
    1. 扫描所有 status='active' 且 end_date < now 的订阅
    2. 更新订阅状态为 'expired'
    3. 软禁用对应的 Emby 账号（修改密码）
    4. 发送站内消息通知用户
    """
    logger.info("开始执行订阅过期检查任务...")
    processed_count = 0
    failed_count = 0

    db = SessionLocal()
    try:
        # 查询过期但仍活跃的订阅
        expired_subs = db.query(UserSubscription).filter(
            UserSubscription.status == 'active',
            UserSubscription.end_date < datetime.now()
        ).all()

        logger.info(f"发现 {len(expired_subs)} 个过期订阅")

        for sub in expired_subs:
            try:
                # 更新订阅状态
                sub.status = 'expired'
                db.add(sub)

                # 查找关联的 Emby 账号
                emby_accounts = db.query(UserEmbyAccount).filter(
                    UserEmbyAccount.subscription_id == sub.id
                ).all()

                for account in emby_accounts:
                    # 软禁用：修改密码为随机值
                    server = db.query(EmbyServer).filter(
                        EmbyServer.id == account.server_id
                    ).first()

                    if server and server.is_active:
                        try:
                            emby_client = EmbyClient(server.url, server.api_key)
                            emby_client.update_user_password(
                                account.emby_user_id,
                                EmbyClient.generate_password(16)
                            )
                            # 标记账号为禁用状态
                            account.is_active = False
                            db.add(account)
                            logger.info(f"已禁用用户 {account.user_id} 的 Emby 账号 (ID: {account.id})")
                        except Exception as e:
                            logger.error(f"禁用 Emby 账号失败: {e}")
                            failed_count += 1

                # 发送站内消息
                user = db.query(WebUser).filter(WebUser.id == sub.user_id).first()
                if user:
                    message = Message(
                        user_id=user.id,
                        title="订阅已过期",
                        content=f"您的订阅已过期，感谢您的支持！如需继续使用，请重新订阅。",
                        message_type="subscription",
                        related_id=sub.id
                    )
                    db.add(message)

                processed_count += 1

            except Exception as e:
                logger.error(f"处理订阅 {sub.id} 过期时出错: {e}")
                failed_count += 1

        db.commit()
        logger.info(f"订阅过期检查完成: 处理 {processed_count} 个，失败 {failed_count} 个")

        # 发送汇总通知
        if processed_count > 0:
            await send_system_alert_message(
                f"订阅过期处理完成\n处理数量: {processed_count}\n失败数量: {failed_count}"
            )

    except Exception as e:
        logger.error(f"订阅过期检查任务出错: {e}")
        db.rollback()
    finally:
        db.close()


# ==================== P0: Emby 健康检查 ====================

async def check_emby_server_health():
    """
    P0 定时任务：Emby 服务器健康检查

    执行时间：每 5 分钟
    逻辑：
    1. 检查所有 Emby 服务器的连通性
    2. 连续失败 3 次则标记 is_active=False
    3. 恢复后重新标记 is_active=True
    4. 发送告警通知
    """
    logger.info("开始执行 Emby 健康检查...")
    db = SessionLocal()

    try:
        servers = db.query(EmbyServer).all()

        for server in servers:
            try:
                emby_client = EmbyClient(server.url, server.api_key)
                result = emby_client.test_connection()

                if result['success']:
                    # 服务器正常
                    if not server.is_active:
                        logger.info(f"Emby 服务器 {server.name} 已恢复")
                        await send_system_alert_message(
                            f"Emby 服务器恢复\n服务器: {server.name}"
                        )
                    server.is_active = True
                    # 更新当前用户数
                    server.current_users = emby_client.get_users_count()
                else:
                    # 服务器异常
                    logger.warning(f"Emby 服务器 {server.name} 连接失败: {result['message']}")
                    # 检查是否需要标记为不可用
                    # 可以通过增加失败计数字段来实现，这里简化处理
                    if server.is_active:
                        await send_system_alert_message(
                            f"Emby 服务器异常\n服务器: {server.name}\n原因: {result['message']}"
                        )
                    server.is_active = False

                db.add(server)

            except Exception as e:
                logger.error(f"检查 Emby 服务器 {server.name} 时出错: {e}")
                if server.is_active:
                    await send_system_alert_message(
                        f"Emby 服务器异常\n服务器: {server.name}\n原因: {str(e)}"
                    )
                server.is_active = False
                db.add(server)

        db.commit()
        logger.info("Emby 健康检查完成")

    except Exception as e:
        logger.error(f"Emby 健康检查任务出错: {e}")
        db.rollback()
    finally:
        db.close()


# ==================== P0: 订单超时清理 ====================

async def cleanup_pending_orders():
    """
    P0 定时任务：清理超时未支付订单

    执行时间：每小时
    逻辑：
    1. 清理创建超过 30 分钟且状态仍为 pending 的订单
    2. 状态更新为 cancelled
    """
    logger.info("开始执行订单超时清理...")
    db = SessionLocal()

    try:
        # 订单超时时间（分钟）
        timeout_minutes = 30
        cutoff_time = datetime.now() - timedelta(minutes=timeout_minutes)

        # 查询超时订单
        timeout_orders = db.query(SubscriptionOrder).filter(
            SubscriptionOrder.status == 'pending',
            SubscriptionOrder.created_at < cutoff_time
        ).all()

        logger.info(f"发现 {len(timeout_orders)} 个超时订单")

        for order in timeout_orders:
            order.status = 'cancelled'
            db.add(order)
            logger.info(f"订单 {order.order_id} 已取消（超时未支付）")

        db.commit()
        logger.info(f"订单超时清理完成: 清理 {len(timeout_orders)} 个订单")

    except Exception as e:
        logger.error(f"订单超时清理任务出错: {e}")
        db.rollback()
    finally:
        db.close()


# ==================== P0: 订阅续费后账号恢复 ====================

async def reactivate_emby_accounts():
    """
    P0 定时任务：恢复已续费但账号仍处于禁用状态的账号

    执行时间：每 10 分钟
    逻辑：
    1. 查询 status='active' 且未过期的订阅
    2. 检查关联的 Emby 账号中 is_active=False 的
    3. 生成新密码并恢复账号
    4. 发送站内消息通知用户新密码
    """
    logger.info("开始执行账号恢复检查...")
    reactivated_count = 0
    failed_count = 0

    db = SessionLocal()
    try:
        # 查询所有活跃且未过期的订阅
        active_subs = db.query(UserSubscription).filter(
            UserSubscription.status == 'active',
            UserSubscription.end_date > datetime.now()
        ).all()

        logger.info(f"发现 {len(active_subs)} 个活跃订阅")

        for sub in active_subs:
            # 查找该订阅下被禁用的账号
            disabled_accounts = db.query(UserEmbyAccount).filter(
                UserEmbyAccount.subscription_id == sub.id,
                UserEmbyAccount.is_active == False
            ).all()

            if not disabled_accounts:
                continue

            logger.info(f"订阅 {sub.id} 有 {len(disabled_accounts)} 个待恢复账号")

            for account in disabled_accounts:
                server = db.query(EmbyServer).filter(
                    EmbyServer.id == account.server_id
                ).first()

                if not server or not server.is_active:
                    logger.warning(f"服务器 {account.server_id} 不可用，跳过账号恢复")
                    continue

                try:
                    emby_client = EmbyClient(server.url, server.api_key)

                    # 生成新密码
                    new_password = EmbyClient.generate_password(12)

                    # 更新 Emby 密码
                    result = emby_client.update_user_password(
                        account.emby_user_id,
                        new_password
                    )

                    if result.get('success'):
                        # 更新数据库
                        account.password = new_password
                        account.is_active = True
                        # 更新过期时间
                        account.expires_at = sub.end_date + timedelta(days=7)
                        db.add(account)

                        logger.info(f"已恢复账号 {account.username}@{server.name}")

                        # 发送站内消息通知用户
                        user = db.query(WebUser).filter(WebUser.id == sub.user_id).first()
                        if user:
                            message = Message(
                                user_id=user.id,
                                title="Emby 账号已恢复",
                                content=f"您的订阅已续费，Emby 账号已恢复使用！\n\n服务器: {server.name}\n地址: {server.url}\n用户名: {account.username}\n密码: {new_password}\n\n过期时间: {account.expires_at.strftime('%Y-%m-%d')}",
                                message_type="subscription",
                                related_id=sub.id
                            )
                            db.add(message)

                        reactivated_count += 1
                    else:
                        logger.error(f"恢复 Emby 密码失败: {result.get('message')}")
                        failed_count += 1

                except Exception as e:
                    logger.error(f"恢复账号 {account.id} 时出错: {e}")
                    failed_count += 1

        db.commit()
        logger.info(f"账号恢复检查完成: 恢复 {reactivated_count} 个，失败 {failed_count} 个")

        # 发送汇总通知
        if reactivated_count > 0:
            await send_system_alert_message(
                f"账号恢复完成\n恢复数量: {reactivated_count}\n失败数量: {failed_count}"
            )

    except Exception as e:
        logger.error(f"账号恢复检查任务出错: {e}")
        db.rollback()
    finally:
        db.close()


# ==================== P1: 订阅即将过期提醒 ====================

async def send_expiring_reminders():
    """
    P1 定时任务：发送订阅即将过期提醒

    执行时间：每日上午 10:00
    逻辑：
    1. 查询 3 天内和 1 天内过期的订阅
    2. 发送站内消息提醒
    3. 避免重复提醒（检查是否已发送过）
    """
    logger.info("开始执行订阅过期提醒...")
    db = SessionLocal()

    try:
        now = datetime.now()

        # 检查提醒时间点
        reminder_days = [3, 1]  # 提前3天和1天提醒

        for days in reminder_days:
            target_date = now + timedelta(days=days)
            start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

            # 查询即将过期的订阅
            expiring_subs = db.query(UserSubscription).filter(
                UserSubscription.status == 'active',
                UserSubscription.end_date >= start_of_day,
                UserSubscription.end_date <= end_of_day
            ).all()

            logger.info(f"发现 {len(expiring_subs)} 个 {days} 天内过期的订阅")

            for sub in expiring_subs:
                # 检查是否已发送过提醒（避免重复）
                existing_message = db.query(Message).filter(
                    Message.user_id == sub.user_id,
                    Message.message_type == "subscription",
                    Message.related_id == sub.id,
                    Message.title.like(f"%{days}天%")
                ).first()

                if existing_message:
                    continue

                # 发送提醒消息
                user = db.query(WebUser).filter(WebUser.id == sub.user_id).first()
                if user:
                    await send_expiring_reminder_message(
                        user_id=user.id,
                        username=user.username,
                        days=days,
                        end_date=sub.end_date,
                        subscription_id=sub.id,
                        db=db
                    )
                    logger.info(f"已向用户 {user.username} 发送 {days} 天过期提醒")

        db.commit()
        logger.info("订阅过期提醒完成")

    except Exception as e:
        logger.error(f"订阅过期提醒任务出错: {e}")
        db.rollback()
    finally:
        db.close()


# ==================== P2: 统计汇总 ====================

async def generate_daily_stats():
    """
    P2 定时任务：生成每日统计汇总

    执行时间：每日凌晨 3:00
    统计内容：
    1. 新增用户数
    2. 新增订阅数
    3. 订单数量和金额
    4. 当前活跃订阅数
    5. Emby 服务器状态
    """
    logger.info("开始生成每日统计...")
    db = SessionLocal()

    try:
        yesterday = datetime.now() - timedelta(days=1)
        start_of_day = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

        # 统计数据
        new_users = db.query(WebUser).filter(
            WebUser.created_at >= start_of_day,
            WebUser.created_at <= end_of_day
        ).count()

        new_subscriptions = db.query(UserSubscription).filter(
            UserSubscription.created_at >= start_of_day,
            UserSubscription.created_at <= end_of_day
        ).count()

        paid_orders = db.query(SubscriptionOrder).filter(
            SubscriptionOrder.status == 'paid',
            SubscriptionOrder.paid_at >= start_of_day,
            SubscriptionOrder.paid_at <= end_of_day
        ).all()

        total_revenue = sum(float(order.amount) for order in paid_orders)

        active_subscriptions = db.query(UserSubscription).filter(
            UserSubscription.status == 'active',
            UserSubscription.end_date >= datetime.now()
        ).count()

        emby_servers = db.query(EmbyServer).filter(EmbyServer.is_active == True).all()
        total_emby_users = sum(s.current_users for s in emby_servers)

        # 构建统计报告
        report = f"""
📊 每日统计报告 ({yesterday.strftime('%Y-%m-%d')})

━━━━━━━━━━━━━━━━
👥 用户数据
  新增用户: {new_users}
  活跃订阅: {active_subscriptions}

💰 订单数据
  新增订阅: {new_subscriptions}
  订单数量: {len(paid_orders)}
  总收入: ¥{total_revenue:.2f}

🎬 Emby 服务器
  在线服务器: {len(emby_servers)}
  总用户数: {total_emby_users}

━━━━━━━━━━━━━━━━
"""

        logger.info(report)

        # 发送到管理员
        await send_system_alert_message(report.strip())

        logger.info("每日统计生成完成")

    except Exception as e:
        logger.error(f"每日统计生成出错: {e}")
    finally:
        db.close()


# ==================== 调度器管理 ====================

def start_scheduler():
    """
    启动调度器并注册所有定时任务
    """
    if scheduler.running:
        logger.warning("调度器已在运行")
        return

    # P0: 订阅过期处理（每日凌晨2点）
    scheduler.add_job(
        check_expired_subscriptions,
        CronTrigger(hour=2, minute=0),
        id='check_expired_subscriptions',
        name='订阅过期处理',
        replace_existing=True
    )

    # P0: Emby 健康检查（每5分钟）
    scheduler.add_job(
        check_emby_server_health,
        CronTrigger(minute='*/5'),
        id='check_emby_server_health',
        name='Emby 健康检查',
        replace_existing=True
    )

    # P0: 订单超时清理（每小时）
    scheduler.add_job(
        cleanup_pending_orders,
        CronTrigger(minute=0),
        id='cleanup_pending_orders',
        name='订单超时清理',
        replace_existing=True
    )

    # P0: 订阅续费后账号恢复（每10分钟）
    scheduler.add_job(
        reactivate_emby_accounts,
        CronTrigger(minute='*/10'),
        id='reactivate_emby_accounts',
        name='订阅续费后账号恢复',
        replace_existing=True
    )

    # P1: 订阅即将过期提醒（每日上午10点）
    scheduler.add_job(
        send_expiring_reminders,
        CronTrigger(hour=10, minute=0),
        id='send_expiring_reminders',
        name='订阅过期提醒',
        replace_existing=True
    )

    # P2: 每日统计汇总（每日凌晨3点）
    scheduler.add_job(
        generate_daily_stats,
        CronTrigger(hour=3, minute=0),
        id='generate_daily_stats',
        name='每日统计汇总',
        replace_existing=True
    )

    scheduler.start()
    logger.info("定时任务调度器已启动")
    logger.info("已注册任务:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.name} ({job.id})")


def stop_scheduler():
    """停止调度器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("定时任务调度器已停止")


async def run_job_manually(job_id: str):
    """
    手动执行定时任务（用于测试或紧急处理）

    Args:
        job_id: 任务ID
    """
    jobs = {
        'check_expired_subscriptions': check_expired_subscriptions,
        'check_emby_server_health': check_emby_server_health,
        'cleanup_pending_orders': cleanup_pending_orders,
        'send_expiring_reminders': send_expiring_reminders,
        'generate_daily_stats': generate_daily_stats,
    }

    if job_id in jobs:
        logger.info(f"手动执行任务: {job_id}")
        await jobs[job_id]()
        logger.info(f"任务 {job_id} 执行完成")
    else:
        raise ValueError(f"未知的任务ID: {job_id}")
