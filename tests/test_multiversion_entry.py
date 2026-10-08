# -*- coding: utf-8 -*-
"""多版本用户入口测试：unmerge 逻辑。

使用 unittest.mock.patch.dict 来隔离 sys.modules，避免污染其他测试。
"""
import os
import sys
import types
from unittest.mock import patch


def _make_models_mock():
    models = types.ModuleType("backend.emby_server.models")

    class _Col:
        def __eq__(self, other): return ("eq", self, other)
        def __ne__(self, other): return ("ne", self, other)

    class MediaItem:
        id = _Col()
        merged_into_id = _Col()
        guid = _Col()

    models.MediaItem = MediaItem
    return models


def _make_item(**kw):
    class FakeItem:
        pass
    it = FakeItem()
    it.id = kw.get("id", 1)
    it.guid = kw.get("guid", "abc123")
    it.name = kw.get("name", "测试电影")
    it.merged_into_id = kw.get("merged_into_id", None)
    return it


def _fake_db(item=None, items=None):
    class FakeQuery:
        def filter(self, *a, **k): return self
        def first(self): return item
        def all(self): return items or []
    class FakeDB:
        def query(self, *a, **k): return FakeQuery()
    return FakeDB()


def _load_worker_isolated():
    """加载 worker 模块，mock 掉 backend 依赖。返回 (mod, patcher)。"""
    import importlib.util

    path = os.path.join(os.path.dirname(__file__), "..",
                        "backend", "emby_server", "merge_versions_worker.py")

    backend = types.ModuleType("backend")
    # 标记为包，避免 import 子模块时走文件系统
    backend.__path__ = []
    emby_server = types.ModuleType("backend.emby_server")
    emby_server.__path__ = []
    models = _make_models_mock()
    dedup = types.ModuleType("backend.emby_server.dedup")
    dedup.pick_primary = lambda group: group[0]
    # env_util：merge_versions_worker 导入 env_float/env_int（R3 打磨统一）
    env_util = types.ModuleType("backend.emby_server.env_util")
    env_util.env_int = lambda name, default, lo, hi: default
    env_util.env_float = lambda name, default, lo: default

    mocks = {
        "backend": backend,
        "backend.emby_server": emby_server,
        "backend.emby_server.models": models,
        "backend.emby_server.dedup": dedup,
        "backend.emby_server.env_util": env_util,
    }
    patcher = patch.dict(sys.modules, mocks)
    patcher.start()

    spec = importlib.util.spec_from_file_location("mvw_test_iso", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, patcher


def test_unmerge_version_not_merged():
    mod, patcher = _load_worker_isolated()
    try:
        db = _fake_db(item=_make_item(id=1, merged_into_id=None))
        assert mod.unmerge_version(db, 1) is False
    finally:
        patcher.stop()


def test_unmerge_version_success():
    mod, patcher = _load_worker_isolated()
    try:
        it = _make_item(id=2, merged_into_id=1)
        db = _fake_db(item=it)
        assert mod.unmerge_version(db, 2) is True
        assert it.merged_into_id is None
    finally:
        patcher.stop()


def test_unmerge_all():
    mod, patcher = _load_worker_isolated()
    try:
        items = [_make_item(id=2, merged_into_id=1),
                 _make_item(id=3, merged_into_id=1)]
        db = _fake_db(items=items)
        count = mod.unmerge_all(db, 1)
        assert count == 2
        assert all(i.merged_into_id is None for i in items)
    finally:
        patcher.stop()


def test_get_alternate_versions_empty():
    mod, patcher = _load_worker_isolated()
    try:
        db = _fake_db(item=None, items=[])
        assert mod.get_alternate_versions(db, 999) == []
    finally:
        patcher.stop()
