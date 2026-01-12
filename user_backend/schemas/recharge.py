"""
充值相关 Schemas
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class RechargePackageResponse(BaseModel):
    """充值套餐响应"""
    id: int
    name: str
    amount: int
    price: float
    bonus: int = 0
    is_popular: bool = False

    class Config:
        from_attributes = True


class CreateRechargeOrder(BaseModel):
    """创建充值订单"""
    package_id: int
    payment_method: str = "xunhu"


class RechargeOrderResponse(BaseModel):
    """充值订单响应"""
    id: int
    order_id: str
    package: RechargePackageResponse
    amount: int
    price: float
    payment_method: str
    status: str
    payment_url: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True
