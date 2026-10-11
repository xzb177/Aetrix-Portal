"""scanner.tmdb_client 必须是活引用（PEP 562 __getattr__），不能是 import 时快照。

回归：`from backend.emby_server.tmdb import tmdb_client` 会在 scanner 首次导入时
把对象快照进 scanner 命名空间。若首次导入恰好落在
`mock.patch("backend.emby_server.tmdb.tmdb_client")` 窗口内，scanner 会永远拿着
泄漏的 mock——曾导致 `test_genuine_miss_still_terminal_none` 在全量跑时 flaky
（`assert 'retry' == 'done'`，预热 URL 里出现 `tmdb_client.search().get()` 的 MagicMock）。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import sys
from unittest import mock
from unittest.mock import MagicMock

import backend.emby_server.scanner as scanner
import backend.emby_server.tmdb as tmdb_mod


def test_tmdb_client_is_live_reference(monkeypatch):
    """scanner.tmdb_client 必须是活引用，而不是 import 时的快照。"""
    sentinel = object()

    monkeypatch.setattr(tmdb_mod, "tmdb_client", sentinel)
    # 替换 tmdb 模块属性后，scanner 侧立即可见（旧代码下这里是快照，断言必失败）
    assert scanner.tmdb_client is sentinel

    monkeypatch.undo()
    # 正常状态下与 tmdb 模块保持一致，且不是残留的 mock
    assert scanner.tmdb_client is tmdb_mod.tmdb_client
    assert not isinstance(scanner.tmdb_client, MagicMock)


def test_first_import_inside_patch_window_not_poisoned():
    """复现真实场景：scanner 首次导入恰好落在 patch 窗口内，退出后不得残留 mock。"""
    mod_name = "backend.emby_server.scanner"
    pkg_name = "backend.emby_server"
    original = sys.modules.get(mod_name)
    assert original is not None

    try:
        with mock.patch("backend.emby_server.tmdb.tmdb_client") as m:
            # 逐出已导入的 scanner，让下面的 import 走一次真正的首次导入
            sys.modules.pop(mod_name, None)
            import backend.emby_server.scanner as sc2

            # 窗口内看到 mock 是正确的（活引用）
            assert sc2.tmdb_client is m

        # 退出 patch 窗口：scanner 必须跟随 tmdb 模块恢复，不能永久拿着泄漏的 mock
        assert sc2.tmdb_client is tmdb_mod.tmdb_client
        assert not isinstance(sc2.tmdb_client, MagicMock)
    finally:
        # 恢复现场，避免影响其他测试：sys.modules 与父包属性都还原
        pkg = sys.modules.get(pkg_name)
        if original is not None:
            sys.modules[mod_name] = original
            if pkg is not None:
                setattr(pkg, "scanner", original)
        else:
            sys.modules.pop(mod_name, None)
            if pkg is not None and getattr(pkg, "scanner", None) is not None:
                delattr(pkg, "scanner")
