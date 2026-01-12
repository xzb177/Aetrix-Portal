"""
支付相关 Pydantic 模型
"""
from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal


class CreatePaymentRequest(BaseModel):
    """创建支付请求"""
    plan_id: int = Field(..., description="套餐ID")
    payment_method: str = Field(default="alipay", description="支付方式: alipay, wxpay")

    class Config:
        json_schema_extra = {
            "example": {
                "plan_id": 1,
                "payment_method": "alipay"
            }
        }


class PaymentResponse(BaseModel):
    """支付响应"""
    order_id: str = Field(..., description="商户订单号")
    payment_url: str = Field(..., description="支付跳转URL")
    amount: Decimal = Field(..., description="支付金额")
    qr_code: Optional[str] = Field(None, description="二维码内容（扫码支付）")


class PaymentNotifyRequest(BaseModel):
    """支付回调通知（用于文档展示）"""
    pid: str
    trade_no: str
    out_trade_no: str
    type: str
    name: str
    money: str
    trade_status: str
    sign: str
    sign_type: str = "MD5"
    param: Optional[str] = None


class PaymentStatusResponse(BaseModel):
    """支付状态查询响应"""
    order_id: str
    status: str
    amount: Decimal
    paid_at: Optional[str] = None
