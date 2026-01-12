"""
账号发放服务

处理 Emby 账号的发放、重试和策略映射
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from database.models import (
    UserSubscription, UserEmbyAccount, EmbyServer,
    PlanServerRelation, AccountDeliveryQueue, SubscriptionPlan, WebUser
)
from utils.emby_client import EmbyClient
from services.audit_service import log_account_action

logger = logging.getLogger(__name__)


class AccountDeliveryService:
    """账号发放服务"""

    @staticmethod
    def select_server_by_weight(db: Session, plan_id: int) -> Optional[EmbyServer]:
        """
        按权重选择服务器

        Args:
            db: 数据库会话
            plan_id: 套餐ID

        Returns:
            选中的服务器，无可用服务器返回 None
        """
        # 获取该套餐关联的服务器列表
        relations = db.query(PlanServerRelation).filter(
            PlanServerRelation.plan_id == plan_id
        ).all()

        if not relations:
            logger.warning(f"套餐 {plan_id} 没有关联服务器")
            return None

        # 筛选可用的服务器
        available_servers = []
        total_weight = 0

        for relation in relations:
            server = relation.server
            if server and server.is_active:
                # 检查是否超过最大用户数
                if server.max_users > 0 and server.current_users >= server.max_users:
                    continue
                available_servers.append((server, relation.weight))
                total_weight += relation.weight

        if not available_servers:
            logger.warning(f"套餐 {plan_id} 没有可用的服务器")
            return None

        # 加权随机选择
        import random
        rand = random.uniform(0, total_weight)
        cumulative = 0

        for server, weight in available_servers:
            cumulative += weight
            if rand <= cumulative:
                return server

        # 兜底返回第一个
        return available_servers[0][0]

    @staticmethod
    def deliver_account(
        db: Session,
        user_id: int,
        subscription_id: int,
        plan_id: int
    ) -> Dict[str, Any]:
        """
        发放 Emby 账号

        Args:
            db: 数据库会话
            user_id: 用户ID
            subscription_id: 订阅ID
            plan_id: 套餐ID

        Returns:
            发放结果
        """
        try:
            # 1. 检查是否已有账号
            existing = db.query(UserEmbyAccount).filter(
                UserEmbyAccount.subscription_id == subscription_id
            ).first()

            if existing:
                return {
                    'success': True,
                    'message': '已领取过账号',
                    'account': {
                        'server_name': existing.server.name,
                        'server_url': existing.server.url,
                        'username': existing.username,
                        'password': existing.password,
                    }
                }

            # 2. 选择服务器
            server = AccountDeliveryService.select_server_by_weight(db, plan_id)
            if not server:
                # 没有可用服务器，加入重试队列
                queue_item = AccountDeliveryQueue(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    plan_id=plan_id,
                    status='pending',
                    last_error='无可用服务器'
                )
                db.add(queue_item)
                db.commit()
                return {
                    'success': False,
                    'message': '暂无可用服务器，已加入等待队列',
                    'queued': True
                }

            # 3. 创建 Emby 用户
            emby_client = EmbyClient(server.url, server.api_key)
            username = EmbyClient.generate_username(user_id)
            password = EmbyClient.generate_password()

            # 确保用户名唯一
            counter = 0
            while emby_client.user_exists(username) and counter < 10:
                counter += 1
                username = f"{EmbyClient.generate_username(user_id)}_{counter}"

            result = emby_client.create_user(username, password)

            if not result['success']:
                # 创建失败，加入重试队列
                queue_item = AccountDeliveryQueue(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    plan_id=plan_id,
                    status='pending',
                    last_error=result['message']
                )
                db.add(queue_item)
                db.commit()
                return {
                    'success': False,
                    'message': f'账号创建失败: {result["message"]}',
                    'queued': True
                }

            # 4. 保存账号信息
            emby_user_id = result['user_id']
            subscription = db.query(UserSubscription).filter(
                UserSubscription.id == subscription_id
            ).first()

            account = UserEmbyAccount(
                user_id=user_id,
                server_id=server.id,
                subscription_id=subscription_id,
                emby_user_id=emby_user_id,
                username=username,
                password=password,
                expires_at=subscription.end_date if subscription else None
            )
            db.add(account)

            # 5. 更新服务器用户数
            server.current_users += 1
            db.add(server)

            # 6. 设置用户策略（根据套餐）
            plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
            if plan:
                # 从套餐的 features 解析策略配置
                import json
                try:
                    features = json.loads(plan.features) if plan.features else {}
                    max_sessions = features.get('max_sessions', 3)
                    max_bitrate = features.get('max_bitrate', 150000000)
                    enable_download = features.get('enable_download', False)

                    emby_client.set_user_policy(
                        user_id=emby_user_id,
                        max_active_sessions=max_sessions,
                        max_streaming_bitrate=max_bitrate,
                        enable_content_downloading=enable_download
                    )
                except Exception as e:
                    logger.warning(f"设置用户策略失败: {e}")

            db.commit()

            # 7. 记录审计日志
            log_account_action(
                db=db,
                user_id=user_id,
                action='account_claimed',
                server_name=server.name,
                emby_username=username
            )

            return {
                'success': True,
                'message': '账号领取成功',
                'account': {
                    'server_name': server.name,
                    'server_url': server.url,
                    'username': username,
                    'password': password,
                }
            }

        except Exception as e:
            logger.error(f"发放账号失败: {e}")
            db.rollback()
            return {
                'success': False,
                'message': f'发放失败: {str(e)}',
                'queued': False
            }

    @staticmethod
    async def retry_pending_deliveries(db: Session) -> Dict[str, int]:
        """
        重试待处理的账号发放

        Args:
            db: 数据库会话

        Returns:
            处理统计
        """
        stats = {
            'processed': 0,
            'success': 0,
            'failed': 0,
            'still_pending': 0
        }

        # 获取待处理的重试队列
        queue_items = db.query(AccountDeliveryQueue).filter(
            AccountDeliveryQueue.status == 'pending',
            AccountDeliveryQueue.retry_count < AccountDeliveryQueue.max_retries
        ).limit(50).all()

        logger.info(f"发现 {len(queue_items)} 个待重试的账号发放任务")

        for item in queue_items:
            try:
                # 标记为处理中
                item.status = 'processing'
                db.add(item)
                db.commit()

                # 尝试发放
                result = AccountDeliveryService.deliver_account(
                    db=db,
                    user_id=item.user_id,
                    subscription_id=item.subscription_id,
                    plan_id=item.plan_id
                )

                if result['success']:
                    # 发放成功
                    item.status = 'completed'
                    item.processed_at = datetime.now()
                    stats['success'] += 1
                else:
                    # 发放失败
                    item.retry_count += 1
                    item.last_error = result.get('message', '未知错误')
                    item.updated_at = datetime.now()

                    if item.retry_count >= item.max_retries:
                        item.status = 'failed'
                        stats['failed'] += 1
                    else:
                        item.status = 'pending'
                        stats['still_pending'] += 1

                db.add(item)
                db.commit()
                stats['processed'] += 1

            except Exception as e:
                logger.error(f"处理账号发放队列项 {item.id} 失败: {e}")
                item.status = 'pending'
                item.retry_count += 1
                item.last_error = str(e)
                db.add(item)
                db.commit()
                stats['processed'] += 1

        logger.info(f"账号发放重试完成: {stats}")
        return stats

    @staticmethod
    def reset_user_password(
        db: Session,
        user_id: int,
        subscription_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        重置用户 Emby 账号密码

        Args:
            db: 数据库会话
            user_id: 用户ID
            subscription_id: 订阅ID（可选，指定则只重置该订阅的账号）

        Returns:
            操作结果
        """
        try:
            query = db.query(UserEmbyAccount).filter(
                UserEmbyAccount.user_id == user_id
            )

            if subscription_id:
                query = query.filter(
                    UserEmbyAccount.subscription_id == subscription_id
                )

            accounts = query.all()

            if not accounts:
                return {
                    'success': False,
                    'message': '未找到 Emby 账号'
                }

            reset_count = 0
            for account in accounts:
                server = account.server
                if not server or not server.is_active:
                    continue

                emby_client = EmbyClient(server.url, server.api_key)
                new_password = EmbyClient.generate_password()

                if emby_client.update_user_password(account.emby_user_id, new_password):
                    account.password = new_password
                    db.add(account)
                    reset_count += 1

                    # 记录审计日志
                    log_account_action(
                        db=db,
                        user_id=user_id,
                        action='account_reset',
                        server_name=server.name
                    )

            db.commit()

            return {
                'success': True,
                'message': f'已重置 {reset_count} 个账号密码',
                'count': reset_count
            }

        except Exception as e:
            logger.error(f"重置密码失败: {e}")
            db.rollback()
            return {
                'success': False,
                'message': f'重置失败: {str(e)}'
            }
