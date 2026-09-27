"""P0-5 回归测试：probe_worker.enabled() 在 layered+inline 下必须为 True。

背景：
- SCAN_PROBE_MODE 默认 "inline"，SCAN_LAYERED 默认开启
- layered+inline+远程文件：enrich_worker 把 probe_status 置 pending
- 修复前 enabled() 只看 PROBE_BACKGROUND（默认 False），worker 不启动，pending 成孤儿
- 修复后：enabled() = PROBE_BACKGROUND or SCAN_LAYERED

本测试只测 enabled() 纯逻辑，不碰 DB。
"""
from unittest import mock

from backend.emby_server import probe_worker
from backend.emby_server import scanner as _sc


def test_enabled_layered_inline_not_orphan():
    """layered+inline 下 worker 必须启用（P0-5 核心回归）"""
    with mock.patch.object(_sc, "PROBE_BACKGROUND", False), \
         mock.patch.object(_sc, "SCAN_LAYERED", True):
        assert probe_worker.enabled() is True


def test_enabled_background_mode():
    """background 模式下 worker 启用（原有行为）"""
    with mock.patch.object(_sc, "PROBE_BACKGROUND", True):
        assert probe_worker.enabled() is True


def test_enabled_fully_disabled():
    """background 关闭且 layered 关闭时才不启用"""
    with mock.patch.object(_sc, "PROBE_BACKGROUND", False), \
         mock.patch.object(_sc, "SCAN_LAYERED", False):
        assert probe_worker.enabled() is False
