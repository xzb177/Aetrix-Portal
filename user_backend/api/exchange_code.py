"""
兑换码系统 API - 用户端
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
import secrets
import string
import logging

from database import get_session
from database.models import (
    ExchangeCode, WebUser, UserSubscription, UserEmbyAccount,
    EmbyServer, PlanServerRelation, SubscriptionPlan, SystemConfig, Message,
    BalanceTransaction, ExchangeCodeRecord
)
from schemas.exchange_code import (
    RedeemExchangeCodeRequest,
    RedeemExchangeCodeResponse,
    ExchangeCodeRecordResponse,
    ExchangeCodeType
)
from api.auth import get_current_user
from schemas.auth import UserResponse
from utils.emby_client import EmbyClient, create_emby_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["兑换码"])


def get_trial_days(db: Session) -> int:
    """获取试用天数配置"""
    config = db.query(SystemConfig).filter(
        SystemConfig.key == 'trial.days'
    ).first()
    return int(config.value) if config and config.value else 1


def get_free_trial_plan_id(db: Session) -> int:
    """获取免费试用套餐 ID"""
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.name == '免费试用'
    ).first()
    if plan:
        return plan.id
    # 如果不存在免费试用套餐，创建一个
    trial_days = get_trial_days(db)
    plan = SubscriptionPlan(
        name='免费试用',
        description=f'兑换码激活的 {trial_days} 天试用',
        price=0,
        duration_days=trial_days,
        features='["基础播放", "标准清晰度"]',
        is_active=True,
        is_popular=False,
        sort_order=0
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan.id


def get_available_server(db: Session, plan_id: int) -> EmbyServer:
    """获取可用服务器（负载均衡）"""
    # 获取该套餐关联的服务器
    relations = db.query(PlanServerRelation).filter(
        PlanServerRelation.plan_id == plan_id
    ).all()

    if not relations:
        # 获取所有活跃服务器
        server = db.query(EmbyServer).filter(
            EmbyServer.is_active == True
        ).order_by(EmbyServer.current_users.asc()).first()
        return server

    # 按权重选择服务器
    import random
    total_weight = sum(r.weight for r in relations)
    if total_weight == 0:
        return relations[0].server if relations else None

    rand = random.randint(1, total_weight)
    current_weight = 0
    for relation in relations:
        current_weight += relation.weight
        if rand <= current_weight:
            return relation.server

    return relations[0].server if relations else None


def generate_exchange_code(length: int = 16) -> str:
    """生成兑换码"""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def get_exchange_code_type_name(code_type: int) -> str:
    """获取兑换码类型名称"""
    type_names = {
        1: "激活试用",
        2: "按天续期",
        3: "按月续期",
        4: "充值余额"
    }
    return type_names.get(code_type, "未知")


@router.post("/redeem")
async def redeem_exchange_code(
    data: RedeemExchangeCodeRequest,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    兑换兑换码

    兑换码类型：
    - 1: 激活试用（激活 Emby 账号 N 天）
    - 2: 按天续期（为现有订阅续期 N 天）
    - 3: 按月续期（为现有订阅续期 N 月，30天/月）
    - 4: 充值余额（充值 N 分到用户余额）
    """
    try:
        # 查找兑换码
        code = db.query(ExchangeCode).filter(
            ExchangeCode.code == data.code.upper()
        ).first()

        if not code:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="兑换码不存在"
            )

        # 检查兑换码状态
        if code.status == -1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该兑换码已被禁用"
            )

        if code.status == 1:
            # 检查是否是当前用户使用的
            if code.used_by_user_id == current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="您已经使用过此兑换码"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该兑换码已被使用"
                )

        # 根据类型处理兑换
        result = {}
        message = ""

        if code.type == 1:  # 激活试用
            result, message = await process_activate_trial(db, current_user, code)
        elif code.type == 2:  # 按天续期
            result, message = await process_extend_days(db, current_user, code)
        elif code.type == 3:  # 按月续期
            result, message = await process_extend_months(db, current_user, code)
        elif code.type == 4:  # 充值余额
            result, message = await process_recharge_balance(db, current_user, code)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的兑换码类型"
            )

        # 更新兑换码状态
        code.status = 1
        code.used_by_user_id = current_user.id
        code.used_at = datetime.now()

        # 创建兑换记录
        record = ExchangeCodeRecord(
            user_id=current_user.id,
            exchange_code_id=code.id,
            code_type=code.type,
            code_display=code.code[:4] + "****" + code.code[-4:],
            effect=result,
            description=message
        )
        db.add(record)

        db.commit()

        # 发送站内消息通知（附加动作，失败不影响主流程）
        try:
            send_exchange_message(db, current_user.id, code.type, result)
        except Exception as e:
            logger.warning(f"发送兑换消息失败（不影响兑换）: {e}")

        return {
            "code": 200,
            "message": message,
            "data": {
                "type": code.type,
                "type_name": get_exchange_code_type_name(code.type),
                "result": result
            }
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"兑换兑换码数据库错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="兑换失败，请稍后重试"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"兑换兑换码未知错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"兑换失败: {str(e)}"
        )


async def process_activate_trial(
    db: Session,
    user: UserResponse,
    code: ExchangeCode
) -> tuple[dict, str]:
    """
    处理激活试用类型兑换码

    为用户创建订阅（如果有服务器则创建 Emby 账号）
    """
    trial_days = code.exchange_count or get_trial_days(db)

    # 检查用户是否已有激活的订阅
    existing_subscription = db.query(UserSubscription).filter(
        UserSubscription.user_id == user.id,
        UserSubscription.status == 'active'
    ).first()

    if existing_subscription:
        # 如果已有活跃订阅，续期而不是新建
        return await process_extend_days(db, user, code)

    # 获取或创建免费试用套餐
    plan_id = get_free_trial_plan_id(db)
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()

    # 创建订阅（即使没有服务器也创建订阅）
    end_date = datetime.now() + timedelta(days=trial_days)
    subscription = UserSubscription(
        user_id=user.id,
        plan_id=plan_id,
        start_date=datetime.now(),
        end_date=end_date,
        status='active'
    )
    db.add(subscription)
    db.flush()

    # 获取可用服务器
    server = get_available_server(db, plan_id)

    if server:
        # 有服务器，在 Emby 服务器上创建用户
        # 生成用户名（使用时间戳后缀提高唯一性）
        import time
        emby_username = f"rb{user.id}{int(time.time() % 10000):04d}"
        emby_password = secrets.token_urlsafe(12)

        # 调用 Emby API 创建用户
        emby_user_id = None
        try:
            client = EmbyClient(server.url, server.api_key)

            # 优化：使用缓存的用户名集合确保唯一性
            existing_usernames = client.get_usernames_set(use_cache=True)
            counter = 0
            while emby_username in existing_usernames and counter < 10:
                counter += 1
                emby_username = f"rb{user.id}{int(time.time() % 10000):04d}_{counter}"

            create_result = client.create_user(emby_username, emby_password)
            if create_result.get('success'):
                emby_user_id = create_result.get('user_id')
                logger.info(f"兑换码激活试用: Emby 用户创建成功 - {emby_username}@{server.name}")
            else:
                logger.warning(f"兑换码激活试用: Emby 用户创建失败 - {create_result.get('message')}")
                # 继续执行，在数据库中记录账号信息
        except Exception as e:
            logger.error(f"兑换码激活试用: Emby API 调用异常 - {e}", exc_info=True)
            # 继续执行，在数据库中记录账号信息

        # 在数据库中创建账号记录
        emby_account = UserEmbyAccount(
            user_id=user.id,
            server_id=server.id,
            subscription_id=subscription.id,
            username=emby_username,
            password=emby_password,
            emby_user_id=emby_user_id,  # 保存 Emby 返回的用户 ID
            is_active=True,
            expires_at=end_date
        )
        db.add(emby_account)

        # 更新服务器用户数
        server.current_users += 1

        db.commit()

        if emby_user_id:
            return {
                "trial_days": trial_days,
                "expires_at": end_date.isoformat(),
                "emby_server": server.name,
                "emby_server_url": server.url,
                "emby_username": emby_username,
                "emby_password": emby_password
            }, f"成功激活 {trial_days} 天试用"
        else:
            # Emby API 创建失败，但数据库记录已保存
            return {
                "trial_days": trial_days,
                "expires_at": end_date.isoformat(),
                "emby_server": server.name,
                "emby_server_url": server.url,
                "emby_username": emby_username,
                "emby_password": emby_password,
                "api_failed": True
            }, f"成功激活 {trial_days} 天试用（Emby 账号已记录，但服务器创建可能失败，请联系管理员）"
    else:
        # 没有服务器，只创建订阅，不创建 Emby 账号
        db.commit()

        return {
            "trial_days": trial_days,
            "expires_at": end_date.isoformat(),
            "no_server": True
        }, f"成功激活 {trial_days} 天试用（暂无可用服务器，请联系管理员配置后获取账号）"


async def process_extend_days(
    db: Session,
    user: UserResponse,
    code: ExchangeCode
) -> tuple[dict, str]:
    """
    处理按天续期类型兑换码
    """
    # 获取用户活跃订阅
    subscription = db.query(UserSubscription).filter(
        UserSubscription.user_id == user.id,
        UserSubscription.status == 'active'
    ).first()

    if not subscription:
        # 如果没有活跃订阅，创建一个新的试用订阅
        return await process_activate_trial(db, user, code)

    # 计算新的过期时间
    days = code.exchange_count
    if subscription.end_date > datetime.now():
        # 订阅未过期，从结束时间续期
        new_end_date = subscription.end_date + timedelta(days=days)
    else:
        # 订阅已过期，从今天开始续期
        new_end_date = datetime.now() + timedelta(days=days)

    subscription.end_date = new_end_date
    db.commit()

    # 更新 Emby 账号过期时间并恢复被禁用的账号
    emby_accounts = db.query(UserEmbyAccount).filter(
        UserEmbyAccount.user_id == user.id
    ).all()

    for account in emby_accounts:
        account.expires_at = new_end_date

    db.commit()

    # 恢复被禁用的账号
    try:
        from utils.account_recovery import reactivate_subscription_accounts
        recovery_result = await reactivate_subscription_accounts(db, subscription)
        logger.info(f"兑换码续费账号恢复结果: {recovery_result}")
    except Exception as e:
        logger.error(f"兑换码续费账号恢复失败: {e}")

    return {
        "extended_days": days,
        "new_end_date": new_end_date.isoformat()
    }, f"成功续期 {days} 天"


async def process_extend_months(
    db: Session,
    user: UserResponse,
    code: ExchangeCode
) -> tuple[dict, str]:
    """
    处理按月续期类型兑换码（每月30天）
    """
    months = code.exchange_count
    days = months * 30

    # 获取用户活跃订阅
    subscription = db.query(UserSubscription).filter(
        UserSubscription.user_id == user.id,
        UserSubscription.status == 'active'
    ).first()

    if not subscription:
        # 如果没有活跃订阅，创建一个新的试用订阅
        code.exchange_count = days  # 临时修改为天数
        result = await process_activate_trial(db, user, code)
        code.exchange_count = months  # 恢复
        return result, f"成功激活 {months} 个月（{days}天）试用"

    # 计算新的过期时间
    if subscription.end_date > datetime.now():
        new_end_date = subscription.end_date + timedelta(days=days)
    else:
        new_end_date = datetime.now() + timedelta(days=days)

    subscription.end_date = new_end_date
    db.commit()

    # 更新 Emby 账号过期时间并恢复被禁用的账号
    emby_accounts = db.query(UserEmbyAccount).filter(
        UserEmbyAccount.user_id == user.id
    ).all()

    for account in emby_accounts:
        account.expires_at = new_end_date

    db.commit()

    # 恢复被禁用的账号
    try:
        from utils.account_recovery import reactivate_subscription_accounts
        recovery_result = await reactivate_subscription_accounts(db, subscription)
        logger.info(f"兑换码续月账号恢复结果: {recovery_result}")
    except Exception as e:
        logger.error(f"兑换码续月账号恢复失败: {e}")

    return {
        "extended_months": months,
        "extended_days": days,
        "new_end_date": new_end_date.isoformat()
    }, f"成功续期 {months} 个月（{days}天）"


async def process_recharge_balance(
    db: Session,
    user: UserResponse,
    code: ExchangeCode
) -> tuple[dict, str]:
    """
    处理充值余额类型兑换码

    amount 单位为分（exchange_count 存储的是分）
    """
    amount = code.exchange_count  # 单位：分

    # 更新用户余额
    db_user = db.query(WebUser).filter(WebUser.id == user.id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 确保用户有 balance 字段（兼容旧数据）
    if not hasattr(db_user, 'balance'):
        # 如果没有 balance 字段，初始化为 0
        db_user.balance = 0

    old_balance = db_user.balance or 0
    db_user.balance += amount
    new_balance = db_user.balance

    # 创建余额流水记录
    transaction = BalanceTransaction(
        user_id=user.id,
        amount=amount,
        balance_before=old_balance,
        balance_after=new_balance,
        transaction_type='exchange',
        source_type='exchange_code',
        source_id=code.id,
        description=f"兑换码充值余额"
    )
    db.add(transaction)

    return {
        "recharge_amount": amount,
        "old_balance": old_balance,
        "new_balance": new_balance
    }, f"成功充值 {amount / 100:.2f} 元余额"


def send_exchange_message(db: Session, user_id: int, code_type: int, result: dict):
    """发送兑换成功消息"""
    type_messages = {
        1: "激活试用成功",
        2: "续期成功",
        3: "续期成功",
        4: "充值成功"
    }

    title = type_messages.get(code_type, "兑换成功")

    # 构建消息内容
    if code_type == 1:  # 激活试用
        content = f"您已成功激活 {result.get('trial_days', 0)} 天试用，有效期至 {result.get('expires_at', '')}"
    elif code_type in [2, 3]:  # 续期
        content = f"您的订阅已成功续期，有效期至 {result.get('new_end_date', '')}"
    elif code_type == 4:  # 充值余额
        amount = result.get('recharge_amount', 0)
        content = f"您已成功充值 {amount / 100:.2f} 元余额，当前余额 {result.get('new_balance', 0) / 100:.2f} 元"
    else:
        content = "兑换成功"

    message = Message(
        user_id=user_id,
        title=title,
        content=content,
        message_type='exchange_code'
    )
    db.add(message)
    db.commit()


@router.get("/my-records")
async def get_my_exchange_records(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_session),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    获取我的兑换记录
    """
    try:
        # 优先从 ExchangeCodeRecord 表读取
        records = db.query(ExchangeCodeRecord).filter(
            ExchangeCodeRecord.user_id == current_user.id
        ).order_by(
            ExchangeCodeRecord.created_at.desc()
        ).offset(skip).limit(limit).all()

        result = []
        for record in records:
            result.append({
                "id": record.id,
                "code": record.code_display,
                "type": record.code_type,
                "type_name": get_exchange_code_type_name(record.code_type),
                "description": record.description,
                "effect": record.effect,
                "created_at": record.created_at.isoformat() if record.created_at else None
            })

        return {
            "code": 200,
            "message": "获取成功",
            "data": {
                "items": result,
                "total": len(result)
            }
        }
    except Exception as e:
        # 如果新表不存在或查询失败，回退到旧逻辑
        logger.warning(f"从 ExchangeCodeRecord 读取失败，使用旧逻辑: {e}")
        try:
            codes = db.query(ExchangeCode).filter(
                ExchangeCode.used_by_user_id == current_user.id,
                ExchangeCode.status == 1
            ).order_by(
                ExchangeCode.used_at.desc()
            ).offset(skip).limit(limit).all()

            result = []
            for code in codes:
                result.append({
                    "id": code.id,
                    "code": code.code[:8] + "****",  # 隐藏部分兑换码
                    "type": code.type,
                    "type_name": get_exchange_code_type_name(code.type),
                    "description": code.note or "",
                    "created_at": code.used_at.isoformat() if code.used_at else None
                })

            return {
                "code": 200,
                "message": "获取成功",
                "data": {
                    "items": result,
                    "total": len(result)
                }
            }
        except Exception as e2:
            logger.error(f"获取兑换记录失败: {e2}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="获取兑换记录失败"
            )
