"""
支付管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import json
import os

from admin_database_user import (
    get_user_db, SubscriptionOrder, SubscriptionPlan, WebUser
)
from admin_utils.auth import get_current_admin
from admin_utils.config import settings

router = APIRouter()

# 配置文件路径（使用 settings 中的配置）
USER_BACKEND_DIR = settings.USER_BACKEND_DIR
ENV_FILE = os.path.join(USER_BACKEND_DIR, ".env")


def read_env_config():
    """读取用户后端的 .env 配置"""
    config = {
        "gateway_url": "",
        "partner_id": "",
        "key": "",
        "notify_url": "",
        "return_url": ""
    }

    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if key == 'YIPAY_GATEWAY_URL':
                        config['gateway_url'] = value
                    elif key == 'YIPAY_PARTNER_ID':
                        config['partner_id'] = value
                    elif key == 'YIPAY_KEY':
                        # 脱敏显示
                        config['key'] = value if len(value) <= 8 else value[:4] + '****' + value[-4:]
                    elif key == 'YIPAY_NOTIFY_URL':
                        config['notify_url'] = value
                    elif key == 'YIPAY_RETURN_URL':
                        config['return_url'] = value

    return config


def write_env_config(config: dict):
    """写入支付配置到 .env 文件"""
    if not os.path.exists(ENV_FILE):
        # 创建新的 .env 文件
        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.write("# 易支付配置\n")
            f.write(f"YIPAY_GATEWAY_URL={config.get('gateway_url', '')}\n")
            f.write(f"YIPAY_PARTNER_ID={config.get('partner_id', '')}\n")
            f.write(f"YIPAY_KEY={config.get('key', '')}\n")
            f.write(f"YIPAY_NOTIFY_URL={config.get('notify_url', '')}\n")
            f.write(f"YIPAY_RETURN_URL={config.get('return_url', '')}\n")
        return

    # 读取现有配置
    lines = []
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 更新配置
    updated_lines = []
    config_keys = {
        'YIPAY_GATEWAY_URL': config.get('gateway_url'),
        'YIPAY_PARTNER_ID': config.get('partner_id'),
        'YIPAY_KEY': config.get('key'),
        'YIPAY_NOTIFY_URL': config.get('notify_url'),
        'YIPAY_RETURN_URL': config.get('return_url')
    }
    updated_keys = set()

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in config_keys:
                if config_keys[key] is not None:
                    updated_lines.append(f"{key}={config_keys[key]}\n")
                updated_keys.add(key)
                continue
        updated_lines.append(line)

    # 添加新配置
    for key, value in config_keys.items():
        if key not in updated_keys and value is not None:
            updated_lines.append(f"{key}={value}\n")

    # 写回文件
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.writelines(updated_lines)


@router.get("/payment/config")
async def get_payment_config(
    admin = Depends(get_current_admin)
):
    """获取支付配置"""
    config = read_env_config()

    # 检查配置是否完整
    is_configured = all([
        config['gateway_url'],
        config['partner_id'],
        config['key']
    ])

    return {
        "is_configured": is_configured,
        "gateway_url": config['gateway_url'],
        "partner_id": config['partner_id'],
        "key": config['key'],  # 已脱敏
        "notify_url": config['notify_url'],
        "return_url": config['return_url']
    }


@router.post("/payment/config")
async def update_payment_config(
    data: dict,
    admin = Depends(get_current_admin)
):
    """更新支付配置"""
    gateway_url = data.get('gateway_url', '').strip()
    partner_id = data.get('partner_id', '').strip()
    key = data.get('key', '').strip()
    notify_url = data.get('notify_url', '').strip()
    return_url = data.get('return_url', '').strip()

    # 验证必填字段
    if not all([gateway_url, partner_id, key]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="支付网关地址、商户ID和商户密钥为必填项"
        )

    # 构建配置
    config = {
        'gateway_url': gateway_url,
        'partner_id': partner_id,
        'key': key,
        'notify_url': notify_url or f"http://154.40.33.2:8001/payment/notify",
        'return_url': return_url or f"http://154.40.33.2/payment/return"
    }

    try:
        write_env_config(config)
        return {"message": "支付配置更新成功"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"配置保存失败: {str(e)}"
        )


@router.post("/payment/test")
async def test_payment(
    admin = Depends(get_current_admin)
):
    """测试支付连接"""
    config = read_env_config()

    if not all([config['gateway_url'], config['partner_id'], config['key']]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先完成支付配置"
        )

    try:
        # 尝试连接支付网关
        import requests
        response = requests.get(
            config['gateway_url'].rstrip('/'),
            timeout=10
        )

        return {
            "success": True,
            "message": "支付网关连接成功",
            "gateway_url": config['gateway_url']
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "支付网关连接超时，请检查网络"
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "message": "支付网关无法连接，请检查地址是否正确"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"连接失败: {str(e)}"
        }


@router.get("/payment/orders")
async def get_payment_orders(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取支付订单列表"""
    query = db.query(SubscriptionOrder)

    if status:
        query = query.filter(SubscriptionOrder.status == status)

    total = query.count()
    orders = query.order_by(
        SubscriptionOrder.created_at.desc()
    ).offset(skip).limit(limit).all()

    result = []
    for order in orders:
        user = db.query(WebUser).filter(WebUser.id == order.user_id).first()
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == order.plan_id).first()

        result.append({
            "id": order.id,
            "order_id": order.order_id,
            "user_id": order.user_id,
            "username": user.username if user else "未知用户",
            "plan_name": plan.name if plan else "未知套餐",
            "amount": float(order.amount),
            "payment_method": order.payment_method or "未选择",
            "status": order.status,
            "paid_at": order.paid_at,
            "created_at": order.created_at,
            "transaction_id": order.transaction_id
        })

    return {
        "total": total,
        "orders": result
    }


@router.get("/payment/stats")
async def get_payment_stats(
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取支付统计数据"""
    # 总订单数
    total_orders = db.query(SubscriptionOrder).count()

    # 待支付订单
    pending_orders = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.status == 'pending'
    ).count()

    # 已支付订单
    paid_orders = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.status == 'paid'
    ).count()

    # 总收入
    total_amount = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.status == 'paid'
    ).all()

    total_revenue = sum(float(o.amount) for o in total_amount)

    # 今日收入
    from datetime import date, timedelta
    today = date.today()
    today_orders = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.status == 'paid',
        SubscriptionOrder.paid_at >= today
    ).all()
    today_revenue = sum(float(o.amount) for o in today_orders)

    # 本月收入
    month_start = today.replace(day=1)
    month_orders = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.status == 'paid',
        SubscriptionOrder.paid_at >= month_start
    ).all()
    month_revenue = sum(float(o.amount) for o in month_orders)

    return {
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "paid_orders": paid_orders,
        "total_revenue": total_revenue,
        "today_revenue": today_revenue,
        "month_revenue": month_revenue
    }


@router.get("/payment/orders/{order_id}")
async def get_payment_order_detail(
    order_id: str,
    db: Session = Depends(get_user_db),
    admin = Depends(get_current_admin)
):
    """获取订单详情"""
    order = db.query(SubscriptionOrder).filter(
        SubscriptionOrder.order_id == order_id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="订单不存在"
        )

    user = db.query(WebUser).filter(WebUser.id == order.user_id).first()
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == order.plan_id).first()

    return {
        "id": order.id,
        "order_id": order.order_id,
        "user": {
            "id": user.id if user else None,
            "username": user.username if user else "未知用户",
            "email": user.email if user else ""
        } if user else None,
        "plan": {
            "id": plan.id if plan else None,
            "name": plan.name if plan else "未知套餐",
            "price": float(plan.price) if plan else 0
        } if plan else None,
        "amount": float(order.amount),
        "payment_method": order.payment_method,
        "status": order.status,
        "transaction_id": order.transaction_id,
        "paid_at": order.paid_at,
        "created_at": order.created_at,
        "updated_at": order.updated_at
    }
