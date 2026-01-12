"""
支付 API 路由
集成易支付接口
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging
import random
import string
import ipaddress
import sqlite3
import os
from typing import Optional

from database import get_session
from database.models import SubscriptionOrder, SubscriptionPlan, UserSubscription, WebUser, EmbyServer, PlanServerRelation, UserEmbyAccount
from schemas.payment import CreatePaymentRequest, PaymentResponse, PaymentStatusResponse
from utils.yi_pay import YiPayClient, TradeStatus
from utils.config import settings
from api.auth import get_current_user

logger = logging.getLogger(__name__)

# 支付回调 IP 白名单（易支付服务器 IP）
# 生产环境请根据实际易支付网关的 IP 地址配置
YIPAY_WHITELIST_IPS: list[str] = [
    # 易支付官方服务器 IP（需要根据实际情况添加）
    # 示例: "127.0.0.1", "::1"
]

# 允许回调的超时时间（秒），防止重放攻击
CALLBACK_TIMEOUT_SECONDS = 300  # 5 分钟


def get_main_db_connection() -> Optional[sqlite3.Connection]:
    """
    获取主数据库连接

    使用环境变量 ROYALBOT_DB_PATH 配置数据库路径
    如果未配置或数据库不存在，返回 None
    """
    db_path = os.getenv("ROYALBOT_DB_PATH", "/root/royalbot/royalbot.db")

    # 检查数据库文件是否存在
    if not os.path.exists(db_path):
        logger.debug(f"主数据库文件不存在: {db_path}")
        return None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.warning(f"连接主数据库失败: {e}")
        return None

router = APIRouter()


def validate_callback_ip(request: Request) -> bool:
    """
    验证支付回调请求的来源 IP

    如果配置了白名单，则只允许白名单 IP 访问
    如果没有配置白名单，则记录警告但允许访问（向后兼容）
    """
    # 获取客户端真实 IP（考虑代理）
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    # 如果配置了白名单，进行严格验证
    if YIPAY_WHITELIST_IPS:
        if client_ip not in YIPAY_WHITELIST_IPS:
            logger.warning(
                f"支付回调来自非白名单 IP: {client_ip}, "
                f"X-Forwarded-For: {forwarded_for}, "
                f"Remote-Addr: {request.headers.get('X-Real-IP')}"
            )
            return False
    else:
        # 没有配置白名单，记录警告但允许
        logger.warning(
            f"⚠️  支付回调 IP 白名单未配置！允许来自 {client_ip} 的请求。"
            "请在生产环境配置 YIPAY_WHITELIST_IPS。"
        )

    logger.info(f"支付回调来自 IP: {client_ip}")
    return True


def validate_callback_timestamp(params: dict) -> bool:
    """
    验证回调时间戳，防止重放攻击

    检查订单创建时间与当前时间的差值
    """
    order_id = params.get('out_trade_no', '')
    if not order_id:
        return False

    # 从订单 ID 中提取时间戳（格式: SUB{YYYYMMDDHHMMSS}{random}）
    try:
        timestamp_str = order_id[3:17]  # 提取时间戳部分
        order_time = datetime.strptime(timestamp_str, '%Y%m%d%H%M%S')
        time_diff = (datetime.now() - order_time).total_seconds()

        # 如果订单创建时间超过回调超时时间，拒绝
        if time_diff > CALLBACK_TIMEOUT_SECONDS:
            logger.warning(f"订单 {order_id} 创建时间过久: {time_diff}秒")
            return False

        # 如果订单创建时间在未来，拒绝
        if time_diff < -60:  # 允许1分钟时钟偏差
            logger.warning(f"订单 {order_id} 创建时间在未来")
            return False

        return True
    except (ValueError, IndexError) as e:
        logger.warning(f"无法解析订单时间戳: {order_id}, {e}")
        return False


def get_yipay_client() -> YiPayClient:
    """获取易支付客户端"""
    return YiPayClient(
        gateway_url=settings.YIPAY_GATEWAY_URL,
        partner_id=settings.YIPAY_PARTNER_ID,
        key=settings.YIPAY_KEY,
        notify_url=settings.YIPAY_NOTIFY_URL,
        return_url=settings.YIPAY_RETURN_URL
    )


def generate_order_id() -> str:
    """生成唯一的订单号"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_str = ''.join(random.choices(string.digits, k=6))
    return f"SUB{timestamp}{random_str}"


@router.post("/create", response_model=PaymentResponse)
async def create_payment(
    request: CreatePaymentRequest,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    创建订阅支付订单

    - **plan_id**: 套餐ID
    - **payment_method**: 支付方式 (alipay=支付宝, wxpay=微信支付)
    """
    # 验证支付方式
    valid_methods = ['alipay', 'wxpay', 'qqpay']
    if request.payment_method not in valid_methods:
        raise HTTPException(status_code=400, detail=f"不支持的支付方式，请选择: {', '.join(valid_methods)}")

    # 检查易支付配置
    if not settings.YIPAY_GATEWAY_URL or not settings.YIPAY_PARTNER_ID or not settings.YIPAY_KEY:
        raise HTTPException(status_code=500, detail="支付功能未配置，请联系管理员")

    # 查询套餐
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == request.plan_id,
        SubscriptionPlan.is_active == True
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在或已下架")

    # 生成订单号
    order_id = generate_order_id()

    # 检查是否有未支付的相同订单（5分钟内）
    recent_order = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.user_id == current_user.id,
        SubscriptionOrder.plan_id == request.plan_id,
        SubscriptionOrder.status == 'pending',
        SubscriptionOrder.created_at >= datetime.now() - timedelta(minutes=5)
    ).first()
    if recent_order:
        # 返回已有订单的支付链接
        client = get_yipay_client()
        params = client.create_payment(
            out_trade_no=recent_order.order_id,
            amount=float(recent_order.amount),
            name=f"VIP订阅 - {plan.name}",
            pay_type=request.payment_method
        )
        payment_url = client.get_payment_url(params)
        return PaymentResponse(
            order_id=recent_order.order_id,
            payment_url=payment_url,
            amount=recent_order.amount
        )

    # 创建订单
    order = SubscriptionOrder(
        order_id=order_id,
        user_id=current_user.id,
        plan_id=request.plan_id,
        item_name=f"VIP订阅 - {plan.name}",
        amount=plan.price,
        payment_method=request.payment_method,
        status='pending'
    )
    db.add(order)
    db.commit()

    # 创建支付参数
    client = get_yipay_client()
    params = client.create_payment(
        out_trade_no=order_id,
        amount=float(plan.price),
        name=f"VIP订阅 - {plan.name}",
        pay_type=request.payment_method,
        param=str(current_user.id)  # 传递用户ID
    )

    # 生成支付URL
    payment_url = client.get_payment_url(params)

    logger.info(f"用户 {current_user.username} 创建支付订单: {order_id}, 金额: {plan.price}")

    return PaymentResponse(
        order_id=order_id,
        payment_url=payment_url,
        amount=plan.price
    )


@router.post("/notify")
async def payment_notify(
    request: Request,
    db: Session = Depends(get_session)
):
    """
    支付异步回调通知

    易支付服务器在支付成功后会调用此接口
    需要返回字符串 "success" 表示处理成功

    安全措施：
    1. IP 白名单验证
    2. 签名验证
    3. 时间戳验证（防止重放攻击）
    4. 金额验证
    5. 订单状态验证
    """
    # ========== 1. IP 白名单验证 ==========
    if not validate_callback_ip(request):
        logger.error("支付回调 IP 验证失败")
        return HTMLResponse(content="fail", status_code=200)

    # 获取回调参数
    form_data = await request.form()
    params = dict(form_data)

    # 隐藏敏感信息
    safe_params = {k: v for k, v in params.items() if k not in ['sign', 'key']}
    logger.info(f"收到支付回调: {safe_params}")

    # ========== 2. 签名验证 ==========
    client = get_yipay_client()
    if not client.verify_sign(params):
        logger.warning(f"支付签名验证失败: {safe_params}")
        return HTMLResponse(content="fail", status_code=200)

    # ========== 3. 时间戳验证（防止重放攻击）==========
    if not validate_callback_timestamp(params):
        logger.warning(f"支付回调时间戳验证失败: {params.get('out_trade_no')}")
        return HTMLResponse(content="fail", status_code=200)

    # 解析回调数据
    callback_data = client.parse_callback(params)
    if not callback_data['valid']:
        logger.warning(f"支付回调数据无效: {safe_params}")
        return HTMLResponse(content="fail", status_code=200)

    # ========== 4. 检查交易状态 ==========
    if not client.is_trade_success(callback_data['trade_status']):
        logger.info(f"交易未成功: {callback_data['trade_status']}")
        return HTMLResponse(content="success", status_code=200)

    # ========== 5. 查找并验证订单 ==========
    order = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.order_id == callback_data['out_trade_no']
    ).first()
    if not order:
        logger.warning(f"订单不存在: {callback_data['out_trade_no']}")
        return HTMLResponse(content="fail", status_code=200)

    # 检查订单是否已处理（防止重复处理）
    if order.status == 'paid':
        logger.info(f"订单已处理，忽略重复回调: {order.order_id}")
        return HTMLResponse(content="success", status_code=200)

    # ========== 6. 验证金额 ==========
    try:
        order_amount = float(order.amount)
        callback_amount = float(callback_data['money'])
        if abs(order_amount - callback_amount) > 0.01:  # 允许1分钱误差
            logger.warning(
                f"订单金额不匹配: 订单金额 ¥{order_amount}, 回调金额 ¥{callback_amount}"
            )
            return HTMLResponse(content="fail", status_code=200)
    except (ValueError, TypeError) as e:
        logger.warning(f"金额格式错误: {e}")
        return HTMLResponse(content="fail", status_code=200)

    # 所有验证通过，更新订单状态
    order.status = 'paid'
    order.paid_at = datetime.now()
    db.commit()

    logger.info(f"✓ 订单支付成功: {order.order_id}, 用户ID: {order.user_id}")

    # 激活用户订阅
    try:
        # 查找用户的现有订阅
        existing_sub = db.query(UserSubscription).filter(
            UserSubscription.user_id == order.user_id,
            UserSubscription.status == 'active'
        ).first()

        # 计算订阅时间
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == order.plan_id).first()
        if not plan:
            logger.error(f"套餐不存在: {order.plan_id}")
            return HTMLResponse(content="success", status_code=200)

        if existing_sub:
            # 续费：从现有订阅结束时间延长
            start_date = existing_sub.end_date
            end_date = start_date + timedelta(days=plan.duration_days)
            existing_sub.end_date = end_date
            existing_sub.plan_id = order.plan_id
            subscription = existing_sub
            logger.info(f"用户 {order.user_id} 续费订阅至 {end_date}")
        else:
            # 新订阅
            start_date = datetime.now()
            end_date = start_date + timedelta(days=plan.duration_days)
            subscription = UserSubscription(
                user_id=order.user_id,
                plan_id=order.plan_id,
                start_date=start_date,
                end_date=end_date,
                status='active'
            )
            db.add(subscription)
            db.flush()
            logger.info(f"用户 {order.user_id} 新订阅至 {end_date}")

        db.commit()

        # 创建/更新 Emby 账号
        try:
            # 获取套餐关联的服务器（按权重分配）
            relations = db.query(PlanServerRelation).filter(
                PlanServerRelation.plan_id == order.plan_id
            ).all()

            if not relations:
                logger.warning(f"套餐 {order.plan_id} 未关联服务器")

            # 构建权重列表
            servers = []
            for rel in relations:
                server = db.query(EmbyServer).filter(
                    EmbyServer.id == rel.server_id,
                    EmbyServer.is_active == True
                ).first()
                if server:
                    for _ in range(rel.weight):
                        servers.append(server)

            if servers:
                import random
                selected_server = random.choice(servers)

                # 检查是否已有此服务器的账号
                existing_account = db.query(UserEmbyAccount).filter(
                    UserEmbyAccount.user_id == order.user_id,
                    UserEmbyAccount.server_id == selected_server.id,
                    UserEmbyAccount.subscription_id == subscription.id
                ).first()

                if not existing_account:
                    # 创建 Emby 账号
                    from utils.emby_client import create_emby_user
                    username = f"user{order.user_id}_{random.randint(1000, 9999)}"
                    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

                    emby_user_id = await create_emby_user(
                        server_url=selected_server.url,
                        api_key=selected_server.api_key,
                        username=username,
                        password=password
                    )

                    if emby_user_id:
                        account = UserEmbyAccount(
                            user_id=order.user_id,
                            server_id=selected_server.id,
                            subscription_id=subscription.id,
                            emby_user_id=emby_user_id,
                            username=username,
                            password=password,
                            expires_at=end_date
                        )
                        db.add(account)

                        # 更新服务器用户数
                        selected_server.current_users += 1
                        db.commit()

                        logger.info(f"为用户 {order.user_id} 创建 Emby 账号: {username}@{selected_server.name}")
        except Exception as e:
            logger.error(f"创建 Emby 账号失败: {e}")

    except Exception as e:
        logger.error(f"激活订阅失败: {e}")
        db.rollback()

    return HTMLResponse(content="success", status_code=200)


@router.get("/status/{order_id}", response_model=PaymentStatusResponse)
async def get_payment_status(
    order_id: str,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    查询订单支付状态
    """
    order = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.order_id == order_id,
        SubscriptionOrder.user_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    return PaymentStatusResponse(
        order_id=order.order_id,
        status=order.status,
        amount=order.amount,
        paid_at=order.paid_at.isoformat() if order.paid_at else None
    )


@router.get("/my-orders")
async def get_my_orders(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session),
    skip: int = 0,
    limit: int = 10
):
    """
    获取我的订单列表
    """
    orders = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.user_id == current_user.id
    ).order_by(SubscriptionOrder.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": len(orders),
        "items": [
            {
                "order_id": o.order_id,
                "item_name": o.item_name,
                "amount": float(o.amount),
                "status": o.status,
                "payment_method": o.payment_method,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                "created_at": o.created_at.isoformat()
            }
            for o in orders
        ]
    }


@router.get("/methods")
async def get_payment_methods():
    """
    获取支持的支付方式列表
    """
    return {
        "methods": [
            {
                "id": "alipay",
                "name": "支付宝",
                "icon": "alipay",
                "enabled": True
            },
            {
                "id": "wxpay",
                "name": "微信支付",
                "icon": "wechat",
                "enabled": True
            },
            {
                "id": "qqpay",
                "name": "QQ支付",
                "icon": "qq",
                "enabled": False
            }
        ]
    }


@router.post("/balance-pay")
async def balance_pay(
    request: CreatePaymentRequest,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    余额支付订阅

    直接扣除用户充值余额来购买订阅套餐
    余额单位：分
    """
    try:
        # 查询套餐
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == request.plan_id,
            SubscriptionPlan.is_active == True
        ).first()
        if not plan:
            raise HTTPException(status_code=404, detail="套餐不存在或已下架")

        # 获取用户余额（从 web_users.balance 字段，单位是分）
        db_user = db.query(WebUser).filter(WebUser.id == current_user.id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 确保 balance 字段存在
        user_balance = getattr(db_user, 'balance', 0) or 0

        # 套餐价格转换为分
        plan_price_fen = int(float(plan.price) * 100)

        # 检查余额是否足够
        if user_balance < plan_price_fen:
            shortage = plan_price_fen - user_balance
            raise HTTPException(
                status_code=400,
                detail=f"余额不足，当前余额 ¥{user_balance / 100:.2f}，需要 ¥{plan.price}，还差 ¥{shortage / 100:.2f}"
            )

        # 扣除余额
        old_balance = user_balance
        db_user.balance = user_balance - plan_price_fen
        new_balance = db_user.balance

        # 创建余额流水记录
        from database.models import BalanceTransaction
        transaction = BalanceTransaction(
            user_id=current_user.id,
            amount=-plan_price_fen,  # 负数表示扣除
            balance_before=old_balance,
            balance_after=new_balance,
            transaction_type='payment',
            source_type='subscription',
            source_id=request.plan_id,
            description=f"购买订阅套餐: {plan.name}"
        )
        db.add(transaction)

        # 创建订单（状态为已支付）
        order_id = generate_order_id()
        order = SubscriptionOrder(
            order_id=order_id,
            user_id=current_user.id,
            plan_id=request.plan_id,
            item_name=f"VIP订阅 - {plan.name} (余额支付)",
            amount=plan.price,
            payment_method='balance',
            status='paid',
            paid_at=datetime.now()
        )
        db.add(order)
        db.commit()

        logger.info(f"用户 {current_user.username} 余额支付 ¥{plan.price}，扣除 {plan_price_fen} 分")

        # 激活用户订阅
        # 查找用户的现有订阅
        existing_sub = db.query(UserSubscription).filter(
            UserSubscription.user_id == current_user.id,
            UserSubscription.status == 'active'
        ).first()

        # 计算订阅时间
        if existing_sub:
            # 续费：从现有订阅结束时间延长
            start_date = existing_sub.end_date
            end_date = start_date + timedelta(days=plan.duration_days)
            existing_sub.end_date = end_date
            existing_sub.plan_id = request.plan_id
            subscription = existing_sub
            logger.info(f"用户 {current_user.id} 余额续费订阅至 {end_date}")
        else:
            # 新订阅
            start_date = datetime.now()
            end_date = start_date + timedelta(days=plan.duration_days)
            subscription = UserSubscription(
                user_id=current_user.id,
                plan_id=request.plan_id,
                start_date=start_date,
                end_date=end_date,
                status='active'
            )
            db.add(subscription)
            db.flush()
            logger.info(f"用户 {current_user.id} 余额新订阅至 {end_date}")

        db.commit()

        # 创建/更新 Emby 账号
        try:
            # 获取套餐关联的服务器（按权重分配）
            relations = db.query(PlanServerRelation).filter(
                PlanServerRelation.plan_id == request.plan_id
            ).all()

            if not relations:
                logger.warning(f"套餐 {request.plan_id} 未关联服务器")
            else:
                # 构建权重列表
                servers = []
                for rel in relations:
                    server = db.query(EmbyServer).filter(
                        EmbyServer.id == rel.server_id,
                        EmbyServer.is_active == True
                    ).first()
                    if server:
                        for _ in range(rel.weight):
                            servers.append(server)

                if servers:
                    # 随机选择服务器
                    import random
                    selected_server = random.choice(servers)

                    # 生成随机账号密码
                    random_username = f"rb{current_user.id}{random.randint(1000, 9999)}"
                    random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))

                    # 计算过期时间
                    expires_at = end_date + timedelta(days=7)  # 订阅到期后7天账号过期

                    # 查找现有账号
                    existing_account = db.query(UserEmbyAccount).filter(
                        UserEmbyAccount.user_id == current_user.id,
                        UserEmbyAccount.server_id == selected_server.id
                    ).first()

                    if existing_account:
                        # 更新现有账号（先删除 Emby 上的旧用户）
                        try:
                            from utils.emby_client import EmbyClient
                            client = EmbyClient(selected_server.url, selected_server.api_key)
                            old_emby_id = existing_account.emby_user_id
                            if old_emby_id:
                                client.delete_user(old_emby_id)
                        except Exception as e:
                            logger.warning(f"删除旧 Emby 用户失败: {e}")

                        # 在 Emby 上创建新用户
                        try:
                            from utils.emby_client import EmbyClient
                            client = EmbyClient(selected_server.url, selected_server.api_key)
                            result = client.create_user(random_username, random_password)
                            if result.get('success'):
                                emby_user_id = result.get('user_id')
                                existing_account.username = random_username
                                existing_account.password = random_password
                                existing_account.emby_user_id = emby_user_id
                                existing_account.expires_at = expires_at
                                existing_account.subscription_id = subscription.id
                                logger.info(f"更新 Emby 账号: {random_username}@{selected_server.name}, ID: {emby_user_id}")
                            else:
                                logger.error(f"创建 Emby 用户失败: {result.get('message')}")
                        except Exception as e:
                            logger.error(f"创建 Emby 用户异常: {e}")
                    else:
                        # 创建新账号 - 先在 Emby 上创建用户
                        try:
                            from utils.emby_client import EmbyClient
                            client = EmbyClient(selected_server.url, selected_server.api_key)
                            result = client.create_user(random_username, random_password)
                            if result.get('success'):
                                emby_user_id = result.get('user_id')
                                emby_account = UserEmbyAccount(
                                    user_id=current_user.id,
                                    server_id=selected_server.id,
                                    subscription_id=subscription.id,
                                    emby_user_id=emby_user_id,
                                    username=random_username,
                                    password=random_password,
                                    expires_at=expires_at
                                )
                                db.add(emby_account)
                                logger.info(f"创建 Emby 账号成功: {random_username}@{selected_server.name}, ID: {emby_user_id}")
                            else:
                                logger.error(f"创建 Emby 用户失败: {result.get('message')}")
                        except Exception as e:
                            logger.error(f"创建 Emby 用户异常: {e}")

                    db.commit()

        except Exception as e:
            logger.error(f"创建 Emby 账号失败: {e}")
            # 订阅已创建，Emby 账号失败不影响主流程

        return {
            "code": 200,
            "message": "订阅成功！",
            "data": {
                "success": True,
                "order_id": order_id,
                "end_date": end_date.isoformat(),
                "old_balance": old_balance,
                "new_balance": new_balance,
                "paid_amount": plan_price_fen
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"余额支付失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"余额支付失败: {str(e)}")
