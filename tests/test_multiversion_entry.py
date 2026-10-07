# -*- coding: utf-8 -*-
"""多版本用户入口测试：unmerge 逻辑（隔离测试，不依赖 backend 导入）。"""
import sys
import os
import importlib.util


def _load_worker():
    """直接加载 merge_versions_worker.py，避免 backend 包导入。"""
    path = os.path.join(os.path.dirname(__file__), "..",
                        "backend", "emby_server", "merge_versions_worker.py")
    spec = importlib.util.spec_from_file_location("mvw_test", path)
    mod = importlib.util.module_from_spec(spec)
    # 预置 backend.emby_server.models 的 mock，避免 import 时失败
    import types
    backend = types.ModuleType("backend")
    emby_server = types.ModuleType("backend.emby_server")
    models = types.ModuleType("backend.emby_server.models")
    class _Col:
        def __eq__(self, other): return ("eq", self, other)
        def __ne__(self, other): return ("ne", self, other)
    class MediaItem:
        id = _Col()
        merged_into_id = _Col()
        guid = _Col()
    models.MediaItem = MediaItem
    sys.modules["backend"] = backend
    sys.modules["backend.emby_server"] = emby_server
    sys.modules["backend.emby_server.models"] = models
    # dedup 模块 mock（merge_group 里 import 用）
    dedup = types.ModuleType("backend.emby_server.dedup")
    dedup.pick_primary = lambda group: group[0]
    sys.modules["backend.emby_server.dedup"] = dedup
    spec.loader.exec_module(mod)
    return mod


def _make_item(**kw):
    class FakeItem:
        pass
    it = FakeItem()
    it.id = kw.get("id", 1)
    it.guid = kw.get("guid", "abc123")
    it.name = kw.get("name", "测试电影")
    it.merged_into_id = kw.get("merged_into_id", None)
    return it


def test_unmerge_version_not_merged():
    mvw = _load_worker()
    item = _make_item(id=1, merged_into_id=None)

    class FakeQuery:
        def filter(self, *a, **k): return self
        def first(self): return item
    class FakeDB:
        def query(self, *a, **k): return FakeQuery()

    assert mvw.unmerge_version(FakeDB(), 1) is False
    print("✓ test_unmerge_version_not_merged")


def test_unmerge_version_success():
    mvw = _load_worker()
    item = _make_item(id=2, merged_into_id=1)

    class FakeQuery:
        def filter(self, *a, **k): return self
        def first(self): return item
    class FakeDB:
        def query(self, *a, **k): return FakeQuery()

    assert mvw.unmerge_version(FakeDB(), 2) is True
    assert item.merged_into_id is None
    print("✓ test_unmerge_version_success")


def test_unmerge_all():
    mvw = _load_worker()
    items = [_make_item(id=2, merged_into_id=1), _make_item(id=3, merged_into_id=1)]

    class FakeQuery:
        def filter(self, *a, **k): return self
        def all(self): return items
    class FakeDB:
        def query(self, *a, **k): return FakeQuery()

    count = mvw.unmerge_all(FakeDB(), 1)
    assert count == 2
    assert all(i.merged_into_id is None for i in items)
    print("✓ test_unmerge_all")


def test_get_alternate_versions_empty():
    mvw = _load_worker()

    class FakeQuery:
        def filter(self, *a, **k): return self
        def first(self): return None
        def all(self): return []
    class FakeDB:
        def query(self, *a, **k): return FakeQuery()

    assert mvw.get_alternate_versions(FakeDB(), 999) == []
    print("✓ test_get_alternate_versions_empty")


if __name__ == "__main__":
    test_unmerge_version_not_merged()
    test_unmerge_version_success()
    test_unmerge_all()
    test_get_alternate_versions_empty()
    print("\n4/4 通过")
