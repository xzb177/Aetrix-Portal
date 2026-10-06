# -*- coding: utf-8 -*-
"""多节点健康检查与流量分配测试"""
import sys
from unittest import mock

sys.modules.setdefault('sqlalchemy', mock.MagicMock())
sys.modules.setdefault('sqlalchemy.orm', mock.MagicMock())

import importlib.util
_spec = importlib.util.spec_from_file_location(
    'node_health_mod',
    '/opt/aetrix-portal/backend/emby_server/node_health.py',
)
node_health = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(node_health)


def test_config_constants():
    assert node_health.CONFIG_KEY == 'stream_nodes'
    assert node_health.HEALTH_CHECK_INTERVAL == 30


def test_is_healthy_defaults_true():
    assert node_health.is_healthy('http://never-checked:9999') is True


def test_health_state_transition():
    url = 'http://test-node:18001'
    node_health._node_health.pop(url, None)
    assert node_health.is_healthy(url) is True
    node_health._node_health[url] = {'healthy': False, 'last_check': 0, 'fail_count': 2}
    assert node_health.is_healthy(url) is False
    node_health._node_health[url] = {'healthy': True, 'last_check': 0, 'fail_count': 0}
    assert node_health.is_healthy(url) is True
    node_health._node_health.pop(url, None)


def test_pick_node_single():
    db = mock.MagicMock()
    single = [{'url': 'http://127.0.0.1:8000', 'weight': 100, 'name': 'local'}]
    with mock.patch.object(node_health, 'healthy_nodes', return_value=single):
        assert node_health.pick_node(db)['url'] == 'http://127.0.0.1:8000'


def test_pick_node_excludes_unhealthy():
    db = mock.MagicMock()
    with mock.patch.object(node_health, 'healthy_nodes',
                           return_value=[{'url': 'http://n1:8000', 'weight': 50}]):
        for _ in range(10):
            assert node_health.pick_node(db)['url'] == 'http://n1:8000'


def test_pick_node_fallback():
    db = mock.MagicMock()
    all_nodes = [{'url': 'http://n1:8000', 'weight': 100}]
    with mock.patch.object(node_health, 'healthy_nodes', return_value=[]):
        with mock.patch.object(node_health, 'get_nodes', return_value=all_nodes):
            assert node_health.pick_node(db)['url'] == 'http://n1:8000'


def test_pick_node_weighted():
    db = mock.MagicMock()
    nodes = [
        {'url': 'http://heavy:8000', 'weight': 90},
        {'url': 'http://light:8000', 'weight': 10},
    ]
    with mock.patch.object(node_health, 'healthy_nodes', return_value=nodes):
        c = {'http://heavy:8000': 0, 'http://light:8000': 0}
        for _ in range(200):
            c[node_health.pick_node(db)['url']] += 1
    assert c['http://heavy:8000'] > c['http://light:8000'] * 3


def test_daemon_idempotent():
    node_health.start_health_daemon(lambda: mock.MagicMock())
    node_health.start_health_daemon(lambda: mock.MagicMock())
