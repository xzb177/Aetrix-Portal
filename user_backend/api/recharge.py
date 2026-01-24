"""
充值 API 路由
集成易支付接口
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import get_session
from database.models import WebUser, RechargePackage, RechargeOrder
from schemas.recharge import RechargePackageResponse, CreateRechargeOrder, RechargeOrderResponse
from api.auth import get_current_user
from utils.yi_pay import YiPayClient, TradeStatus
from utils.config import settings
from typing import List
import uuid
import random
import string
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def generate_recharge_order_id() -> str:
    """生成唯一的充值订单号"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_str = ''.join(random.choices(string.digits, k=6))
    return f"REC{timestamp}{random_str}"


@router.get("/packages", response_model=List[RechargePackageResponse])
async def get_recharge_packages(db: Session = Depends(get_session)):
    """获取充值套餐列表"""
    packages = db.query(RechargePackage).filter(
        RechargePackage.is_active == True
    ).order_by(RechargePackage.sort_order).all()

    return packages


@router.post("/order", response_model=RechargeOrderResponse)
async def create_recharge_order(
    data: CreateRechargeOrder,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    创建充值订单

    支持两种模式：
    1. 按套餐充值：传入 package_id（有赠送优惠）
    2. 按金额充值：传入 amount（1:1到账，无赠送）

    - **package_id**: 套餐ID（可选，优先使用套餐）
    - **amount**: 充值金额（元，不使用套餐时直接按金额充值）
    - **payment_method**: 支付方式 (alipay=支付宝, wxpay=微信支付)
    """
    # 验证支付方式
    valid_methods = ['alipay', 'wxpay', 'qqpay']
    if data.payment_method not in valid_methods:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的支付方式，请选择: {', '.join(valid_methods)}"
        )

    # 检查易支付配置（从数据库读取）
    from database.models import PaymentConfig
    config = db.query(PaymentConfig).first()
    gateway_url = config.gateway_url if config else settings.YIPAY_GATEWAY_URL
    partner_id = config.partner_id if config else settings.YIPAY_PARTNER_ID
    key = config.key if config else settings.YIPAY_KEY

    if not gateway_url or not partner_id or not key:
        raise HTTPException(
            status_code=503,
            detail="支付功能暂时不可用，请联系管理员配置支付"
        )

    # 解析套餐和金额
    package = None
    recharge_amount = 0  # 到账金额（积分/余额）
    price_yuan = 0  # 支付金额（元）

    if data.package_id:
        # 按套餐充值
        package = db.query(RechargePackage).filter(
            RechargePackage.id == data.package_id,
            RechargePackage.is_active == True
        ).first()
        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="套餐不存在或已下架"
            )
        recharge_amount = package.amount + (package.bonus or 0)
        price_yuan = float(package.price)
    elif data.amount:
        # 按金额充值（1:1到账）
        if data.amount < 1:
            raise HTTPException(
                status_code=400,
                detail="充值金额不能小于 1 元"
            )
        recharge_amount = data.amount
        price_yuan = float(data.amount)
    else:
        raise HTTPException(
            status_code=400,
            detail="请选择套餐或输入充值金额"
        )

    # 生成订单号
    order_id = generate_recharge_order_id()

    # 创建订单
    order = RechargeOrder(
        order_id=order_id,
        user_id=current_user.id,
        package_id=package.id if package else None,
        amount=recharge_amount,
        price=price_yuan,
        payment_method=data.payment_method,
        status="pending"
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # 创建易支付客户端（使用数据库配置）
    client = YiPayClient(
        gateway_url=gateway_url,
        partner_id=partner_id,
        key=key,
        notify_url=settings.YIPAY_RECHARGE_NOTIFY_URL,
        return_url=settings.YIPAY_RECHARGE_RETURN_URL
    )

    # 创建支付参数
    params = client.create_payment(
        out_trade_no=order_id,
        amount=price_yuan,
        name=f"余额充值 - {package.name if package else f'{recharge_amount}积分'}",
        pay_type=data.payment_method,
        param=str(current_user.id)  # 传递用户ID
    )

    # 生成支付URL
    payment_url = client.get_payment_url(params)

    logger.info(f"用户 {current_user.username} 创建充值订单: {order_id}, 支付金额: {price_yuan}元, 到账: {recharge_amount}")

    # 构建响应
    return RechargeOrderResponse(
        id=order.id,
        order_id=order_id,
        package=RechargePackageResponse(
            id=package.id if package else 0,
            name=package.name if package else f"自定义充值 {recharge_amount}积分",
            amount=recharge_amount,
            price=price_yuan,
            bonus=0,
            is_popular=False,
        ) if package else RechargePackageResponse(
            id=0,
            name=f"自定义充值 {recharge_amount}积分",
            amount=recharge_amount,
            price=price_yuan,
            bonus=0,
            is_popular=False,
        ),
        amount=recharge_amount,
        price=price_yuan,
        payment_method=order.payment_method,
        status=order.status,
        payment_url=payment_url,
        created_at=order.created_at,
    )


@router.post("/notify")
async def recharge_notify(
    request: Request,
    db: Session = Depends(get_session)
):
    """
    充值支付异步回调通知

    易支付服务器在支付成功后会调用此接口
    需要返回字符串 "success" 表示处理成功
    """
    # 获取回调参数
    form_data = await request.form()
    params = dict(form_data)

    # 隐藏敏感信息
    safe_params = {k: v for k, v in params.items() if k not in ['sign', 'key']}
    logger.info(f"收到充值支付回调: {safe_params}")

    # 从数据库读取支付配置
    from database.models import PaymentConfig
    config = db.query(PaymentConfig).first()
    gateway_url = config.gateway_url if config else settings.YIPAY_GATEWAY_URL
    partner_id = config.partner_id if config else settings.YIPAY_PARTNER_ID
    key = config.key if config else settings.YIPAY_KEY

    if not gateway_url or not partner_id or not key:
        logger.warning("支付配置缺失")
        return HTMLResponse(content="fail", status_code=200)

    # 验证签名
    client = YiPayClient(
        gateway_url=gateway_url,
        partner_id=partner_id,
        key=key
    )
    if not client.verify_sign(params):
        logger.warning(f"充值支付签名验证失败: {safe_params}")
        return HTMLResponse(content="fail", status_code=200)

    # 解析回调数据
    callback_data = client.parse_callback(params)
    if not callback_data['valid']:
        logger.warning(f"充值支付回调数据无效: {params}")
        return HTMLResponse(content="fail", status_code=200)

    # 检查交易状态
    if not client.is_trade_success(callback_data['trade_status']):
        logger.info(f"充值交易未成功: {callback_data['trade_status']}")
        return HTMLResponse(content="success", status_code=200)

    # 查找订单
    order = db.query(RechargeOrder).filter(
        RechargeOrder.order_id == callback_data['out_trade_no']
    ).first()
    if not order:
        logger.warning(f"充值订单不存在: {callback_data['out_trade_no']}")
        return HTMLResponse(content="fail", status_code=200)

    # 检查订单是否已处理
    if order.status == 'completed':
        logger.info(f"充值订单已处理: {order.order_id}")
        return HTMLResponse(content="success", status_code=200)

    # 验证金额
    if float(order.price) != float(callback_data['money']):
        logger.warning(f"充值订单金额不匹配: {order.price} vs {callback_data['money']}")
        return HTMLResponse(content="fail", status_code=200)

    # 更新订单状态
    order.status = 'completed'
    order.paid_at = datetime.now()

    # 给用户增加余额（balance 单位是分，需要转换）
    user = db.query(WebUser).filter(WebUser.id == order.user_id).first()
    if user:
        old_balance = user.balance or 0
        # order.amount 是积分数量，1积分 = 1分（人民币1分）
        recharge_fen = order.amount  # 充值金额转分
        user.balance = old_balance + recharge_fen

        # 创建余额交易记录
        from database.models import BalanceTransaction
        transaction = BalanceTransaction(
            user_id=user.id,
            amount=recharge_fen,  # 正数表示增加
            balance_before=old_balance,
            balance_after=user.balance,
            transaction_type='recharge',
            source_type='recharge_order',
            source_id=order.id,
            description=f"充值到账 {order.amount}积分"
        )
        db.add(transaction)

        logger.info(f"用户 {user.username} 充值成功: +{order.amount}积分, 余额: {old_balance} -> {user.balance}")

    db.commit()

    logger.info(f"充值订单支付成功: {order.order_id}")

    return HTMLResponse(content="success", status_code=200)


@router.get("/status/{order_id}")
async def get_recharge_status(
    order_id: str,
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    查询充值订单状态
    """
    order = db.query(RechargeOrder).filter(
        RechargeOrder.order_id == order_id,
        RechargeOrder.user_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    return {
        "order_id": order.order_id,
        "status": order.status,
        "amount": order.amount,
        "price": float(order.price),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None
    }


@router.get("/history", response_model=List[RechargeOrderResponse])
async def get_recharge_history(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """获取充值记录"""
    orders = db.query(RechargeOrder).filter(
        RechargeOrder.user_id == current_user.id
    ).order_by(RechargeOrder.created_at.desc()).all()

    result = []
    for order in orders:
        # 处理按套餐充值和按金额充值两种情况
        if order.package_id:
            # 按套餐充值
            package_info = RechargePackageResponse(
                id=order.package.id,
                name=order.package.name,
                amount=order.package.amount,
                price=float(order.package.price),
                bonus=order.package.bonus,
                is_popular=order.package.is_popular,
            )
        else:
            # 按金额充值（自定义金额）
            package_info = RechargePackageResponse(
                id=0,
                name=f"自定义充值 {order.amount}积分",
                amount=order.amount,
                price=float(order.price),
                bonus=0,
                is_popular=False,
            )

        result.append(RechargeOrderResponse(
            id=order.id,
            order_id=order.order_id,
            package=package_info,
            amount=order.amount,
            price=float(order.price),
            payment_method=order.payment_method,
            status=order.status,
            payment_url=order.payment_url,
            created_at=order.created_at,
            paid_at=order.paid_at,
        ))

    return result
