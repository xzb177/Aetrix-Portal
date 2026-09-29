"""EA 事件循环回归测试（P0，2026-09-29）。

背景：单 uvicorn worker 下，``async def`` 路由里直接调同步 DB 会阻塞事件循环，
跑久了登录从 0.4s 退化到 15.7s。本测试钉住两件事：

1. **静态护栏**：EA 的 ``async def`` 路由/函数里，不得直接出现 ``db.query`` /
   ``db.commit`` 等同步 DB 调用（必须经 ``async_db.run_db`` 扔线程池）。
   例外：``await run_db(...)`` 包裹的显然不算；``request.json()`` 等真异步不算。
2. **心跳测试**：在事件循环里跑一个 10ms 心跳，同时用慢 DB（sleep 0.5s 模拟
   fsync 阻塞）调被修过的路由逻辑，心跳空洞必须 < 0.3s（修之前会 ≥0.5s）。
"""
import ast
import asyncio
import pathlib
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

# 这些文件是 EA 进程实际装载的 async 路由
EA_ASYNC_FILES = [
    "backend/emby_server/api.py",
    "backend/emby_server/stream_routes.py",
    "backend/emby_server/session_routes.py",
    "backend/emby_server/portal.py",
    "backend/emby_server/portal_mount_routes.py",
]

# 同步 DB 操作的黑名单方法
DB_ATTRS = {"query", "commit", "add", "delete", "execute", "flush", "refresh"}


def _direct_db_calls_in_async(tree: ast.AST) -> list[tuple[str, int, str]]:
    """找出 async 函数体内直接写的 db.<op>。

    允许的写法只有一种：``await run_db(<sync_fn>, db, ...)``——db 只作为参数传给
    run_db，由 run_db 扔到线程池里执行。其他任何在 async 函数体内直接出现的
    ``db.query`` / ``db.commit`` 等都是违规。
    """
    offenders = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue

        # 收集该函数内所有 run_db(...) 调用的 db 参数节点 id
        run_db_db_nodes: set[int] = set()

        class CallCollector(ast.NodeVisitor):
            def visit_Call(self, call_node):
                func = call_node.func
                is_run_db = (
                    (isinstance(func, ast.Name) and func.id == "run_db")
                    or (isinstance(func, ast.Attribute) and func.attr == "run_db")
                )
                if is_run_db:
                    for arg in list(call_node.args) + [kw.value for kw in call_node.keywords]:
                        # db 作为位置/关键字参数传给 run_db
                        if isinstance(arg, ast.Name) and arg.id == "db":
                            run_db_db_nodes.add(id(arg))
                self.generic_visit(call_node)

        CallCollector().visit(node)

        # 再扫一遍：db.<op> 属性访问，排除作为 run_db 参数的那个 db Name 节点本身
        #（注意：db.query 里 db 是 Attribute 的 value，不是 Call 的 arg，所以上面收集的
        # 其实是 run_db(db, ...) 这种写法的 db；db.query(...) 的 db 不会出现在 args 里。
        # 因此逻辑简化为：async 函数体内出现 db.<op> 即违规，除非它在 run_db 调用内部。
        # 更精确的做法：检查 Attribute 节点是否位于 run_db Call 的子树内。）
        class AttrChecker(ast.NodeVisitor):
            def __init__(self):
                self.in_run_db = 0
                self.in_nested_def = 0

            def visit_FunctionDef(self, node):
                # 嵌套的 sync def（如 rate_item 里的 _rate）：它本身跑在线程池，
                # 里面的 db 操作不算阻塞事件循环，跳过
                self.in_nested_def += 1
                self.generic_visit(node)
                self.in_nested_def -= 1

            def visit_Call(self, call_node):
                func = call_node.func
                is_run_db = (
                    (isinstance(func, ast.Name) and func.id == "run_db")
                    or (isinstance(func, ast.Attribute) and func.attr == "run_db")
                )
                if is_run_db:
                    self.in_run_db += 1
                    self.generic_visit(call_node)
                    self.in_run_db -= 1
                else:
                    self.generic_visit(call_node)

            def visit_Attribute(self, attr_node):
                v = attr_node.value
                if (
                    isinstance(v, ast.Name)
                    and v.id == "db"
                    and attr_node.attr in DB_ATTRS
                    and self.in_run_db == 0
                    and self.in_nested_def == 0
                ):
                    offenders.append((node.name, attr_node.lineno, f"db.{attr_node.attr}"))
                self.generic_visit(attr_node)

        AttrChecker().visit(node)

    # 去重（同一函数多处命中保留第一处）
    seen: dict[str, tuple[int, str]] = {}
    for name, lineno, what in offenders:
        if name not in seen:
            seen[name] = (lineno, what)
    return [(n, l, w) for n, (l, w) in seen.items()]


def test_no_direct_db_in_ea_async_routes():
    """静态护栏：EA async 路由里不许直接调同步 DB"""
    offenders = []
    for rel in EA_ASYNC_FILES:
        p = REPO / rel
        if not p.exists():
            continue
        tree = ast.parse(p.read_text())
        for func_name, lineno, what in _direct_db_calls_in_async(tree):
            offenders.append(f"{rel}:{lineno} async {func_name}() 直接调 {what}")
    assert not offenders, (
        "以下 async 函数直接调用了同步 DB，会阻塞单 worker 的事件循环，"
        "请经 backend.emby_server.async_db.run_db 扔线程池：\n" + "\n".join(offenders)
    )


def test_run_db_does_not_block_loop():
    """心跳测试：run_db 包装的慢 DB 操作不卡事件循环"""
    import sys
    sys.path.insert(0, str(REPO))
    from backend.emby_server.async_db import run_db

    async def _run():
        gaps = []
        stop = False

        async def heartbeat():
            last = time.monotonic()
            while not stop:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                gaps.append(now - last - 0.01)
                last = now

        def slow_db():
            # 模拟 SQLite commit 的 fsync 阻塞
            time.sleep(0.5)
            return "ok"

        hb = asyncio.create_task(heartbeat())
        try:
            result = await run_db(slow_db)
            assert result == "ok"
        finally:
            stop = True
            await hb

        max_gap = max(gaps) if gaps else 0
        # 修之前：直接在循环里 sleep(0.5)，心跳空洞 ≥0.5s
        # 修之后：扔线程池，心跳空洞应 < 0.3s
        assert max_gap < 0.3, f"事件循环被阻塞了 {max_gap:.2f}s，run_db 没生效"

    asyncio.run(_run())


def test_loop_monitor_thresholds_sane():
    """监控阈值是合理值（别太敏感刷屏，也别太迟钝漏报）"""
    import sys
    sys.path.insert(0, str(REPO))
    from backend.emby_server import loop_monitor
    assert 0.5 <= loop_monitor.LAG_WARN_SECONDS <= 5.0
    assert loop_monitor.LAG_WARN_CONSECUTIVE >= 2
