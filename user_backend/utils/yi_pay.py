"""
易支付接口工具类
支持标准的易支付协议（MD5签名）
"""
import hashlib
import urllib.parse
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class YiPayClient:
    """易支付客户端"""

    def __init__(
        self,
        gateway_url: str,
        partner_id: str,
        key: str,
        notify_url: str = None,
        return_url: str = None
    ):
        """
        初始化易支付客户端

        Args:
            gateway_url: 支付网关地址，如 https://pay.example.com/submit.php
            partner_id: 商户ID (pid)
            key: 商户密钥
            notify_url: 异步回调地址
            return_url: 同步跳转地址
        """
        self.gateway_url = gateway_url
        self.partner_id = partner_id
        self.key = key
        self.notify_url = notify_url
        self.return_url = return_url

    def _generate_sign(self, params: Dict[str, str]) -> str:
        """
        生成MD5签名

        签名规则：
        1. 按参数名ASCII码从小到大排序（a-z）
        2. sign、sign_type和空值不参与签名
        3. 拼接成 key=value&key2=value2 格式
        4. 在末尾加上商户密钥KEY
        5. MD5加密（小写）

        Args:
            params: 参数字典

        Returns:
            32位小写MD5签名
        """
        # 过滤不参与签名的参数
        filtered_params = {}
        for k, v in sorted(params.items()):
            # 跳过 sign, sign_type 和空值
            if k not in ['sign', 'sign_type'] and v is not None and v != '':
                filtered_params[k] = str(v)

        # 拼接字符串
        sign_str = '&'.join([f"{k}={v}" for k, v in filtered_params.items()])
        # 末尾加上密钥
        sign_str += self.key

        # MD5加密（小写）
        return hashlib.md5(sign_str.encode('utf-8')).hexdigest()

    def verify_sign(self, params: Dict[str, str]) -> bool:
        """
        验证回调签名

        Args:
            params: 回调参数字典

        Returns:
            签名是否有效
        """
        received_sign = params.get('sign', '')
        if not received_sign:
            return False

        calculated_sign = self._generate_sign(params)
        return received_sign.lower() == calculated_sign.lower()

    def create_payment(
        self,
        out_trade_no: str,
        amount: float,
        name: str,
        pay_type: str = 'alipay',
        param: str = None
    ) -> Dict[str, str]:
        """
        创建支付订单

        Args:
            out_trade_no: 商户订单号（需唯一）
            amount: 订单金额（元，精确到分）
            name: 商品名称
            pay_type: 支付类型 (alipay=支付宝, wxpay=微信支付)
            param: 自定义参数（原样返回）

        Returns:
            包含签名和表单参数的字典
        """
        params = {
            'pid': self.partner_id,
            'type': pay_type,
            'out_trade_no': out_trade_no,
            'notify_url': self.notify_url,
            'return_url': self.return_url,
            'name': name,
            'money': f"{amount:.2f}",
        }

        if param:
            params['param'] = param

        # 生成签名
        params['sign'] = self._generate_sign(params)
        params['sign_type'] = 'MD5'

        return params

    def get_payment_url(self, params: Dict[str, str]) -> str:
        """
        获取支付跳转URL

        Args:
            params: create_payment 返回的参数

        Returns:
            支付URL
        """
        # 移除 sign 重新生成（因为 URL 编码可能会改变签名字符串）
        sign = params.pop('sign', '')
        params.pop('sign_type', None)

        # 重新生成签名（URL编码后的参数）
        # 注意：易支付规范要求参数值不要进行URL编码后再签名
        # 所以这里使用原始签名
        params['sign'] = sign
        params['sign_type'] = 'MD5'

        # 构建查询字符串（参数需要URL编码）
        query_parts = []
        for k, v in params.items():
            if v is not None and v != '':
                query_parts.append(f"{k}={urllib.parse.quote(str(v), safe='')}")

        query_string = '&'.join(query_parts)
        return f"{self.gateway_url}?{query_string}"

    def parse_callback(self, params: Dict[str, str]) -> Dict[str, any]:
        """
        解析支付回调

        Args:
            params: 回调参数

        Returns:
            解析后的回调信息
        """
        if not self.verify_sign(params):
            logger.warning(f"无效的支付签名: {params.get('out_trade_no')}")
            return {'valid': False}

        # 易支付回调参数
        return {
            'valid': True,
            'trade_no': params.get('trade_no', ''),  # 平台订单号
            'out_trade_no': params.get('out_trade_no', ''),  # 商户订单号
            'type': params.get('type', ''),  # 支付方式
            'name': params.get('name', ''),  # 商品名称
            'money': params.get('money', ''),  # 订单金额
            'trade_status': params.get('trade_status', ''),  # 支付状态
            'param': params.get('param', ''),  # 自定义参数
        }

    def is_trade_success(self, trade_status: str) -> bool:
        """
        判断交易是否成功

        Args:
            trade_status: 交易状态

        Returns:
            是否成功
        """
        return trade_status == 'TRADE_SUCCESS'


# 支付类型枚举
class PayType:
    """支付类型常量"""
    ALIPAY = 'alipay'  # 支付宝
    WXPAY = 'wxpay'  # 微信支付
    ALIPAY_PC = 'alipaypc'  # 支付宝扫码（模拟器）
    WXPAY_PC = 'wxpaypc'  # 微信扫码（模拟器）
    QQPAY = 'qqpay'  # QQ支付


# 订单状态
class TradeStatus:
    """交易状态常量"""
    TRADE_SUCCESS = 'TRADE_SUCCESS'  # 交易成功
