"""
订阅相关 Schemas
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class SubscriptionPlanResponse(BaseModel):
    """订阅套餐响应"""
    id: int
    name: str
    description: Optional[str] = None
    price: float
    duration_days: int
    features: List[str] = []
    is_popular: bool = False

    class Config:
        from_attributes = True


class UserSubscriptionResponse(BaseModel):
    """用户订阅响应"""
    id: int
    plan: SubscriptionPlanResponse
    start_date: datetime
    end_date: datetime
    status: str
    days_remaining: int = 0

    class Config:
        from_attributes = True


class CreateSubscriptionOrder(BaseModel):
    """创建订阅订单"""
    plan_id: int
    payment_method: str = "xunhu"


class OrderResponse(BaseModel):
    """订单响应"""
    order_id: str
    item_name: str
    amount: float
    payment_method: str
    status: str
    payment_url: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True
