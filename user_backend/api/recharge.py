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


def get_recharge_yipay_client() -> YiPayClient:
    """获取充值专用的易支付客户端"""
    return YiPayClient(
        gateway_url=settings.YIPAY_GATEWAY_URL,
        partner_id=settings.YIPAY_PARTNER_ID,
        key=settings.YIPAY_KEY,
        notify_url=settings.YIPAY_RECHARGE_NOTIFY_URL,
        return_url=settings.YIPAY_RECHARGE_RETURN_URL
    )


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

    - **package_id**: 套餐ID
    - **payment_method**: 支付方式 (alipay=支付宝, wxpay=微信支付)
    """
    # 验证支付方式
    valid_methods = ['alipay', 'wxpay', 'qqpay']
    if data.payment_method not in valid_methods:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的支付方式，请选择: {', '.join(valid_methods)}"
        )

    # 检查易支付配置
    if not settings.YIPAY_GATEWAY_URL or not settings.YIPAY_PARTNER_ID or not settings.YIPAY_KEY:
        raise HTTPException(
            status_code=500,
            detail="支付功能未配置，请联系管理员"
        )

    # 获取套餐
    package = db.query(RechargePackage).filter(
        RechargePackage.id == data.package_id,
        RechargePackage.is_active == True
    ).first()
    if not package:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="套餐不存在或已下架"
        )

    # 生成订单号
    order_id = generate_recharge_order_id()

    # 计算充值金额（基础金额 + 赠送金额）
    total_amount = package.amount + (package.bonus or 0)

    # 创建订单
    order = RechargeOrder(
        order_id=order_id,
        user_id=current_user.id,
        package_id=package.id,
        amount=total_amount,
        price=package.price,
        payment_method=data.payment_method,
        status="pending"
    )
    db.add(order)
    db.commit()

    # 创建易支付参数
    client = get_recharge_yipay_client()
    params = client.create_payment(
        out_trade_no=order_id,
        amount=float(package.price),
        name=f"余额充值 - {package.name}",
        pay_type=data.payment_method,
        param=str(current_user.id)  # 传递用户ID
    )

    # 生成支付URL
    payment_url = client.get_payment_url(params)

    logger.info(f"用户 {current_user.username} 创建充值订单: {order_id}, 金额: {total_amount}")

    return RechargeOrderResponse(
        id=order.id,
        order_id=order_id,
        package=RechargePackageResponse(
            id=package.id,
            name=package.name,
            amount=package.amount,
            price=float(package.price),
            bonus=package.bonus,
            is_popular=package.is_popular,
        ),
        amount=total_amount,
        price=float(order.price),
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

    logger.info(f"收到充值支付回调: {params}")

    # 验证签名
    client = get_recharge_yipay_client()
    if not client.verify_sign(params):
        logger.warning(f"充值支付签名验证失败: {params}")
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

    # 给用户增加余额
    user = db.query(WebUser).filter(WebUser.id == order.user_id).first()
    if user:
        user.points = (user.points or 0) + order.amount
        logger.info(f"用户 {user.username} 余额充值成功: +{order.amount}, 当前余额: {user.points}")

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
        result.append(RechargeOrderResponse(
            id=order.id,
            order_id=order.order_id,
            package=RechargePackageResponse(
                id=order.package.id,
                name=order.package.name,
                amount=order.package.amount,
                price=float(order.package.price),
                bonus=order.package.bonus,
                is_popular=order.package.is_popular,
            ),
            amount=order.amount,
            price=float(order.price),
            payment_method=order.payment_method,
            status=order.status,
            payment_url=order.payment_url,
            created_at=order.created_at,
            paid_at=order.paid_at,
        ))

    return result
