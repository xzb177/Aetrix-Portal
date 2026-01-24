"""
支付管理 API - 管理后台
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime
import json
import os
import logging

logger = logging.getLogger(__name__)

from admin_database_user import (
    get_user_db, SubscriptionOrder, SubscriptionPlan, WebUser, user_engine
)
from admin_utils.auth import get_current_admin
from admin_utils.config import settings
from admin_database import admin_engine

router = APIRouter()


def read_payment_config():
    """从数据库读取支付配置"""
    config = {
        "gateway_url": "",
        "partner_id": "",
        "key": "",
        "notify_url": "",
        "return_url": ""
    }

    try:
        with admin_engine.connect() as conn:
            result = conn.execute(text("SELECT gateway_url, partner_id, key, notify_url, return_url FROM payment_config ORDER BY id DESC LIMIT 1"))
            row = result.fetchone()
            if row:
                config['gateway_url'] = row[0] or ""
                config['partner_id'] = row[1] or ""
                # 脱敏显示密钥
                key_value = row[2] or ""
                config['key'] = key_value if len(key_value) <= 8 else key_value[:4] + '****' + key_value[-4:]
                config['notify_url'] = row[3] or ""
                config['return_url'] = row[4] or ""
    except Exception as e:
        # 表可能不存在，返回空配置
        pass

    return config


def write_payment_config(config: dict):
    """写入支付配置到数据库（同时写入 admin 和 user 数据库）"""
    # 1. 写入 admin_backend 数据库
    with admin_engine.connect() as conn:
        # 先检查是否有现有配置
        result = conn.execute(text("SELECT id FROM payment_config"))
        existing = result.fetchone()

        if existing:
            # 更新现有配置
            conn.execute(text("""
                UPDATE payment_config
                SET gateway_url = :gateway_url,
                    partner_id = :partner_id,
                    key = :key,
                    notify_url = :notify_url,
                    return_url = :return_url,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (SELECT id FROM payment_config ORDER BY id DESC LIMIT 1)
            """), {
                'gateway_url': config.get('gateway_url', ''),
                'partner_id': config.get('partner_id', ''),
                'key': config.get('key', ''),
                'notify_url': config.get('notify_url', ''),
                'return_url': config.get('return_url', '')
            })
        else:
            # 插入新配置
            conn.execute(text("""
                INSERT INTO payment_config (gateway_url, partner_id, key, notify_url, return_url)
                VALUES (:gateway_url, :partner_id, :key, :notify_url, :return_url)
            """), {
                'gateway_url': config.get('gateway_url', ''),
                'partner_id': config.get('partner_id', ''),
                'key': config.get('key', ''),
                'notify_url': config.get('notify_url', ''),
                'return_url': config.get('return_url', '')
            })
        conn.commit()

    # 2. 同时写入 user_backend SQLite 数据库
    try:
        import sqlite3
        # user_backend SQLite 数据库路径
        sqlite_db_path = os.getenv("USER_BACKEND_DB_PATH", "/app/royalbot.db")

        # 先确保表存在
        conn = sqlite3.connect(sqlite_db_path)
        cursor = conn.cursor()

        # 创建表（如果不存在）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gateway_url TEXT NOT NULL,
                partner_id TEXT NOT NULL,
                key TEXT NOT NULL,
                notify_url TEXT,
                return_url TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 检查是否有现有配置
        cursor.execute("SELECT id FROM payment_config ORDER BY id DESC LIMIT 1")
        existing = cursor.fetchone()

        if existing:
            # 更新现有配置
            cursor.execute("""
                UPDATE payment_config
                SET gateway_url = ?,
                    partner_id = ?,
                    key = ?,
                    notify_url = ?,
                    return_url = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                config.get('gateway_url', ''),
                config.get('partner_id', ''),
                config.get('key', ''),
                config.get('notify_url', ''),
                config.get('return_url', ''),
                existing[0]
            ))
        else:
            # 插入新配置
            cursor.execute("""
                INSERT INTO payment_config (gateway_url, partner_id, key, notify_url, return_url)
                VALUES (?, ?, ?, ?, ?)
            """, (
                config.get('gateway_url', ''),
                config.get('partner_id', ''),
                config.get('key', ''),
                config.get('notify_url', ''),
                config.get('return_url', '')
            ))

        conn.commit()
        conn.close()
        logger.info(f"支付配置已同步到 user_backend SQLite 数据库: {sqlite_db_path}")
    except Exception as e:
        logger.error(f"同步支付配置到 user_backend SQLite 失败: {e}")
        # 不影响主流程，admin 数据库已保存成功


@router.get("/payment/config")
async def get_payment_config(
    admin = Depends(get_current_admin)
):
    """获取支付配置"""
    config = read_payment_config()

    # 检查配置是否完整
    is_configured = all([
        config['gateway_url'],
        config['partner_id'],
        config['key']
    ])

    return {
        "code": 200,
        "message": "success",
        "data": {
            "is_configured": is_configured,
            "gateway_url": config['gateway_url'],
            "partner_id": config['partner_id'],
            "key": config['key'],  # 已脱敏
            "notify_url": config['notify_url'],
            "return_url": config['return_url']
        }
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
        write_payment_config(config)
        return {"code": 200, "message": "配置保存成功", "data": None}
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
    config = read_payment_config()

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
            "code": 200,
            "message": "支付网关连接成功",
            "data": {
                "success": True,
                "gateway_url": config['gateway_url']
            }
        }
    except requests.exceptions.Timeout:
        return {
            "code": 200,
            "message": "支付网关连接超时，请检查网络",
            "data": {"success": False}
        }
    except requests.exceptions.ConnectionError:
        return {
            "code": 200,
            "message": "支付网关无法连接，请检查地址是否正确",
            "data": {"success": False}
        }
    except Exception as e:
        return {
            "code": 200,
            "message": f"连接失败: {str(e)}",
            "data": {"success": False}
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
            "transaction_id": order.order_id  # 使用 order_id 作为交易 ID
        })

    return {
        "code": 200,
        "message": "success",
        "data": {
            "total": total,
            "orders": result
        }
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
        "code": 200,
        "message": "success",
        "data": {
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "paid_orders": paid_orders,
            "total_revenue": total_revenue,
            "today_revenue": today_revenue,
            "month_revenue": month_revenue
        }
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
        "code": 200,
        "message": "success",
        "data": {
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
            "transaction_id": order.order_id,  # 使用 order_id 作为交易 ID
            "paid_at": order.paid_at,
            "created_at": order.created_at,
            "updated_at": order.updated_at
        }
    }
