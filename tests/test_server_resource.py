"""服务器资源优化（perf/server-resource）的测试。

覆盖：
1. CacheManager 内存回退有界（条目上限 + TTL 过期 + FIFO 淘汰）
2. 请求体大小限制中间件（超限 413）
3. Emby 登录限流规则存在（15次/分钟）
4. Download/File 端点一律服务端代理（不再对客户端 302）
5. 主列表接口 EnableTotalRecordCount=false 时跳过 COUNT(*)
"""
import importlib
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------- 1. CacheManager 有界 ----------

def _fresh_cache_manager():
    """拿一个 Redis 不可用的 CacheManager（走内存回退路径）。
    只改模块属性并复位，不 reload 整个模块，避免影响其它测试。"""
    import backend.database as dbmod
    dbmod.redis_client = None
    dbmod.CacheManager._memory_cache = {}
    dbmod.CacheManager._memory_cache_order = []
    return dbmod.CacheManager


def test_memory_cache_ttl_expiry():
    CM = _fresh_cache_manager()
    CM.set("k1", "v1", ttl=1)
    assert CM.get("k1") == "v1"
    time.sleep(1.1)
    assert CM.get("k1") is None  # 过期后读不到
    assert CM.exists("k1") is False


def test_memory_cache_bounded():
    CM = _fresh_cache_manager()
    max_n = CM._MEMORY_CACHE_MAX
    for i in range(max_n + 100):
        CM.set(f"k{i}", "x" * 10, ttl=3600)
    assert len(CM._memory_cache) <= max_n
    # 最老的被淘汰，最新的还在
    assert CM.get("k0") is None
    assert CM.get(f"k{max_n + 99}") == "x" * 10


def test_memory_cache_delete_cleans_order():
    CM = _fresh_cache_manager()
    CM.set("a", "1", ttl=60)
    CM.set("b", "2", ttl=60)
    CM.delete("a")
    assert "a" not in CM._memory_cache_order
    assert CM.get("a") is None
    assert CM.get("b") == "2"


# ---------- 2. 请求体限制 ----------

def test_body_limit_middleware_exists():
    """main.py 里有请求体大小限制中间件：读 Content-Length，超限回 413。"""
    import ast
    src = open(REPO_ROOT / "backend/main.py").read()
    tree = ast.parse(src)
    names = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert "request_body_limit_middleware" in names
    # 中间件函数体内要有 413 和 content-length 检查
    for n in ast.walk(tree):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "request_body_limit_middleware":
            body_src = ast.get_source_segment(src, n)
            assert "413" in body_src
            assert "content-length" in body_src
            assert "MAX_REQUEST_BODY_MB" in body_src
            break
    else:
        raise AssertionError("middleware body not found")


# ---------- 3. Emby 登录限流 ----------

def test_emby_login_rate_limit_rule_exists():
    """RATE_LIMITS 里有 /emby/Users/AuthenticateByName 的 15次/分钟规则，
    且中间件覆盖 /emby/ 路径（原来只覆盖 /api/）。
    EM（backend/main.py，单进程模式）和 EA（emby_api/main.py，分离部署生产用）都要有。"""
    import ast
    for path in [
        REPO_ROOT / "backend/main.py",
        REPO_ROOT / "emby_api/main.py",
    ]:
        src = open(path).read()
        assert '"/emby/Users/AuthenticateByName"' in src, path
        tree = ast.parse(src)
        found_rule = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id in ("RATE_LIMITS", "_EA_RATE_LIMITS"):
                        val = ast.literal_eval(n.value)
                        rules = {p: (a, b) for p, a, b in val}
                        anon, auth = rules["/emby/Users/AuthenticateByName"]
                        assert anon <= 15 and auth <= 15, path
                        found_rule = True
        assert found_rule, path
        # 限流中间件的路径判断要包含 /emby/
        mw_names = ("rate_limit_middleware", "ea_rate_limit_middleware")
        for n in ast.walk(tree):
            if isinstance(n, ast.AsyncFunctionDef) and n.name in mw_names:
                body_src = ast.get_source_segment(src, n)
                assert "/emby/" in body_src, path
                break
        else:
            raise AssertionError(f"rate limit middleware not found in {path}")


def test_body_limit_middleware_in_both_apps():
    """EM 和 EA 都有请求体大小限制中间件（413）。"""
    import ast
    for path, mw in [
        (REPO_ROOT / "backend/main.py", "request_body_limit_middleware"),
        (REPO_ROOT / "emby_api/main.py", "ea_body_limit_middleware"),
    ]:
        src = open(path).read()
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.AsyncFunctionDef) and n.name == mw:
                body_src = ast.get_source_segment(src, n)
                assert "413" in body_src, path
                assert "content-length" in body_src, path
                assert "MAX_REQUEST_BODY_MB" in body_src, path
                break
        else:
            raise AssertionError(f"{mw} not found in {path}")


# ---------- 4. Download/File 一律代理（不再 302） ----------

def test_download_paths_never_redirect_the_client():
    """下载 / 拉文件两个端点都不再对客户端 302，只做服务端代理转发。"""
    import ast
    for path in [
        REPO_ROOT / "backend/emby_server/media_routes.py",
        REPO_ROOT / "backend/emby_server/mount_routes.py",
    ]:
        src = open(path).read()
        assert "can_redirect_direct" not in src, path
        assert "status_code=302" not in src, path
        tree = ast.parse(src)
        calls = [
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        assert "serve_remote" in calls, path



# ---------- 5. EnableTotalRecordCount=false ----------

def test_query_items_skips_count_when_disabled():
    """_query_items 里有 EnableTotalRecordCount=false 分支：跳过 query.count()，
    改用有没有下一页的探测（HasMore）。"""
    import ast
    src = open(REPO_ROOT / "backend/emby_server/api.py").read()
    assert "EnableTotalRecordCount" in src
    tree = ast.parse(src)
    found = False
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_query_items":
            body_src = ast.get_source_segment(src, n)
            assert "want_total" in body_src
            # 不查总数时：用 has_more 探测有没有下一页（旧实现是 limit+1 多取一行，
            # PR #343 改为先全量取去重后的 id 再比较 len > start + limit，语义等价且更精确）
            assert "has_more" in body_src
            assert "HasMore" in body_src
            assert "start + limit" in body_src
            found = True
            break
    assert found, "_query_items not found"
