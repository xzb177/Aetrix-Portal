#!/usr/bin/env python3
"""契约检查：``await`` 的目标必须是协程函数

为什么要有这条
--------------
性能整改里最常见的一步是把 ``async def`` 端点改成同步 ``def``（FastAPI 会把 ``def``
端点丢进线程池，不再把同步 SQLAlchemy 查询压在事件循环上）。**但同一个函数可能被
别的 ``async`` 端点 ``await`` 着复用**——写这条门禁时真实存在两处：
``coupons_admin.list_coupon_usages_by_code`` 复用 ``list_coupon_usages``、
``compat_routes.library_media_folders`` 复用 ``api.user_views``（两边后来都改成了
同步 ``def``：v2.35.0 改 ``user_views``，v2.39.0 把核销记录两个端点一起同步化、
查询抽成 ``coupon_usages_payload``——这条门禁就是为那次（以及以后的）改造守着的）。
这时把它改成 ``def``，编译、类型检查、导入统统看不出来，
只有真打到那个请求才会：

    TypeError: object dict can't be used in 'await' expression

这套代码库用的就是同步 SQLAlchemy，这类改造还会继续做，所以把它固化成门禁：
``await f(...)`` 里的 ``f`` 只要在 ``backend/`` 里有模块级定义，就必须至少有一个
``async def`` 的定义。

口径
----
* 只看裸名字调用（``await f(...)``），不看 ``await obj.f(...)``——后者无法靠文本
  可靠地解析到定义，容易误报；不误报比多抓更重要。
* 同一个名字在多个模块里既有 ``async def`` 又有 ``def`` 时，视为「有协程版本」放行
  （宁可不报，也不要把正确代码判红）。

退出码 0 = 通过；1 = 有违规。
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def main() -> int:
    if not BACKEND.is_dir():
        print(f"找不到 {BACKEND}，请在项目根目录运行")
        return 1

    definitions: dict[str, list[tuple[bool, str, int]]] = defaultdict(list)
    trees: list[tuple[Path, ast.Module]] = []

    for path in sorted(BACKEND.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"❌ 解析失败 {path.relative_to(ROOT)}: {exc}")
            return 1
        trees.append((path, tree))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions[node.name].append(
                    (isinstance(node, ast.AsyncFunctionDef), str(path.relative_to(ROOT)), node.lineno)
                )

    violations: list[str] = []
    for path, tree in trees:
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Await):
                continue
            call = node.value
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            name = call.func.id
            if name not in definitions:
                continue
            if any(is_async for is_async, _, _ in definitions[name]):
                continue
            where = ", ".join(f"{f}:{ln}" for _, f, ln in definitions[name])
            violations.append(
                f"{rel}:{node.lineno} await {name}(...) —— {name} 只在 {where} 定义为同步 def"
            )

    if violations:
        print("❌ await 目标不是协程函数：")
        for v in violations:
            print("   ", v)
        print()
        print("修法：要么把这个函数改回 async def，要么把 await 去掉（调用点同步执行）。")
        return 1

    print(f"✅ await 契约检查通过（扫描 {len(trees)} 个文件，{len(definitions)} 个模块级函数定义）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
