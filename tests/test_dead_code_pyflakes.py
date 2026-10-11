"""死代码回归测试（死 global 声明 / 无用局部变量赋值）。

只用标准库 ast 做静态分析，不导入被测模块，避免引入运行时副作用。
覆盖本轮清理过的 8 个文件：
  1. 函数内声明了 global 但该函数（含嵌套）从未对其赋值 —— 死 global 声明；
  2. 简单赋值（ast.Assign 且 targets 恰为 1 个 Name）后从未被读取 —— 无用局部变量。

注意：import 遮蔽类问题（如被同名形参遮蔽的无用 import）不在本测试范围内，
由 pyflakes 的 F811 在 CI 日志中覆盖。
"""

from __future__ import annotations

import ast
from pathlib import Path

# 被测文件，相对仓库根目录
FILES = [
    "backend/worker.py",
    "backend/emby_server/fs_watcher.py",
    "backend/emby_server/tmdb_cache.py",
    "backend/emby_server/api.py",
    "backend/api/servers.py",
    "backend/emby_server/enrich_worker.py",
    "backend/emby_server/tmdb.py",
    "backend/emby_server/scanner.py",
]

ROOT = Path(__file__).resolve().parent.parent


def _parse(rel_path: str) -> ast.Module:
    """把被测文件解析成 AST（只读文本，不导入）。"""
    path = ROOT / rel_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _iter_functions(tree: ast.AST):
    """遍历所有函数定义，含 async 函数与嵌套函数。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def test_no_dead_global_declarations() -> None:
    """每个函数内 global 声明的名字，必须在同一函数（含嵌套）里出现过赋值。"""
    for rel_path in FILES:
        tree = _parse(rel_path)
        for func in _iter_functions(tree):
            # 只取该函数体顶层的 global 语句；嵌套函数的 global 由嵌套函数自己负责
            declared = {
                name
                for stmt in func.body
                if isinstance(stmt, ast.Global)
                for name in stmt.names
            }
            if not declared:
                continue

            # 收集该函数（含嵌套函数）内所有 Store 目标；宽松口径，避免误报
            stored: set[str] = set()
            for node in ast.walk(func):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    stored.add(node.id)
                elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                    # x += 1 是复合赋值，语义上算一次 Store
                    stored.add(node.target.id)

            dead = sorted(declared - stored)
            assert not dead, (
                f"{rel_path}:{func.lineno} {func.name}() 存在死 global 声明: {dead}"
            )


def test_no_dead_simple_assignments() -> None:
    """简单赋值的目标名，必须在同一函数（含嵌套）里被读取过。"""
    for rel_path in FILES:
        tree = _parse(rel_path)
        for func in _iter_functions(tree):
            # global / nonlocal 声明的名字指向外层作用域，赋值是刻意写给别处读的，
            # 不算无用局部变量（pyflakes F841 同样跳过这类名字）。
            # 宽松口径：嵌套函数体内的声明也一并收集。
            declared_outer: set[str] = set()
            for node in ast.walk(func):
                if isinstance(node, (ast.Global, ast.Nonlocal)):
                    declared_outer.update(node.names)

            # 只认 ast.Assign 且 targets 恰为 1 个 ast.Name：
            # 排除元组解包、属性/下标赋值；
            # AnnAssign / For 循环变量 / with as / except as / 海象运算符都不是 ast.Assign，天然不算
            targets: list[str] = []
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    targets.append(node.targets[0].id)
            # 排除 global / nonlocal 声明的名字
            targets = [name for name in targets if name not in declared_outer]
            if not targets:
                continue

            # 收集该函数（含嵌套函数）内所有 Load 上下文的名字
            loaded = {
                node.id
                for node in ast.walk(func)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            }

            dead = sorted({name for name in targets if name not in loaded})
            assert not dead, (
                f"{rel_path}:{func.lineno} {func.name}() 存在无用赋值: {dead}"
            )
