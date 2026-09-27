"""限流 IP 防伪造测试。

验证 get_client_ip 的可信代理逻辑：
1. 不可信来源伪造 XFF → 忽略伪造头，用直连 IP（限流不被绕过）
2. 可信代理的 XFF → 正常解析出真实客户端 IP
3. 可信代理的 X-Real-IP → 优先使用
"""
import os
from unittest.mock import MagicMock

import pytest

from backend.ratelimit import get_client_ip, client_ip, _is_trusted_proxy


def _make_request(direct_ip, xff=None, x_real_ip=None):
    """构造一个模拟的 FastAPI Request"""
    req = MagicMock()
    req.client.host = direct_ip
    headers = {}
    if xff:
        headers["x-forwarded-for"] = xff
    if x_real_ip:
        headers["x-real-ip"] = x_real_ip
    req.headers.get = lambda k, default="": headers.get(k.lower(), default)
    # 兼容直接 headers[k] 访问
    req.headers.__getitem__ = lambda self, k: headers[k.lower()]
    return req


class TestUntrustedSource:
    """不可信来源：伪造头必须被忽略"""

    def test_forged_xff_ignored(self):
        """攻击者直连并伪造 XFF → 必须用直连 IP，不能用伪造的"""
        req = _make_request("203.0.113.99", xff="1.2.3.4")
        assert get_client_ip(req) == "203.0.113.99"

    def test_forged_xff_multi_hops_ignored(self):
        """伪造多段 XFF 也一样被忽略"""
        req = _make_request("203.0.113.99", xff="1.2.3.4, 5.6.7.8, 9.10.11.12")
        assert get_client_ip(req) == "203.0.113.99"

    def test_forged_x_real_ip_ignored(self):
        """伪造 X-Real-IP 也被忽略"""
        req = _make_request("203.0.113.99", x_real_ip="1.2.3.4")
        assert get_client_ip(req) == "203.0.113.99"

    def test_no_headers_uses_direct(self):
        """无头时用直连 IP"""
        req = _make_request("203.0.113.99")
        assert get_client_ip(req) == "203.0.113.99"

    def test_client_ip_alias_same(self):
        """兼容函数 client_ip 行为一致"""
        req = _make_request("203.0.113.99", xff="1.2.3.4")
        assert client_ip(req) == "203.0.113.99"


class TestTrustedProxy:
    """可信代理：头可信，正常解析"""

    def test_trusted_proxy_xff_last_hop(self):
        """nginx 在 127.0.0.1（默认可信），XFF 取最后一段"""
        req = _make_request(
            "127.0.0.1",
            xff="1.2.3.4, 5.6.7.8",  # 客户端伪造了 1.2.3.4，nginx 追加了真实的 5.6.7.8
        )
        assert get_client_ip(req) == "5.6.7.8"

    def test_trusted_proxy_x_real_ip_priority(self):
        """可信代理下 X-Real-IP 优先"""
        req = _make_request(
            "127.0.0.1",
            xff="9.9.9.9",
            x_real_ip="5.6.7.8",
        )
        assert get_client_ip(req) == "5.6.7.8"

    def test_trusted_proxy_no_headers(self):
        """可信代理但无头 → 用直连 IP（代理自己）"""
        req = _make_request("127.0.0.1")
        assert get_client_ip(req) == "127.0.0.1"


class TestTrustedProxiesConfig:
    """TRUSTED_PROXIES 环境变量配置"""

    def test_custom_trusted_cidr(self, monkeypatch):
        """自定义 CIDR 网段可信"""
        monkeypatch.setenv("TRUSTED_PROXIES", "172.18.0.0/16")
        assert _is_trusted_proxy("172.18.0.10") is True
        assert _is_trusted_proxy("172.19.0.1") is False

    def test_custom_trusted_single_ip(self, monkeypatch):
        """单个 IP 可信"""
        monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.5")
        assert _is_trusted_proxy("10.0.0.5") is True
        assert _is_trusted_proxy("10.0.0.6") is False

    def test_loopback_always_trusted(self, monkeypatch):
        """回环地址默认可信（无需配置）"""
        monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
        assert _is_trusted_proxy("127.0.0.1") is True
        assert _is_trusted_proxy("::1") is True

    def test_invalid_config_ignored(self, monkeypatch):
        """写错的配置不炸服务"""
        monkeypatch.setenv("TRUSTED_PROXIES", "not-an-ip, 999.999.999.999")
        # 回环仍然可信，非法条目被忽略
        assert _is_trusted_proxy("127.0.0.1") is True
        assert _is_trusted_proxy("1.2.3.4") is False

    def test_docker_network_trusted(self, monkeypatch):
        """Docker 网段可信后，容器间调用的 XFF 生效"""
        monkeypatch.setenv("TRUSTED_PROXIES", "172.18.0.0/16")
        req = _make_request("172.18.0.5", xff="203.0.113.7")
        assert get_client_ip(req) == "203.0.113.7"


class TestEdgeCases:
    """边界情况"""

    def test_none_request(self):
        assert get_client_ip(None) == "unknown"

    def test_no_client(self):
        req = MagicMock()
        req.client = None
        req.headers.get = lambda k, default="": default
        assert get_client_ip(req) == "unknown"

    def test_empty_xff(self):
        req = _make_request("127.0.0.1", xff="  ,  ")
        assert get_client_ip(req) == "127.0.0.1"
