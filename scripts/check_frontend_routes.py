#!/usr/bin/env python3
"""前端路由契约检查：禁止跳转到本前端并不存在的路由。

起因：管理后台认证 store 与用户端 401 兜底曾两次被换成「别的项目」的实现，
其中一次把会话过期后的跳转目标写成 `/m/login`——而用户端根本没有这套 `/m/*` 路由，
结果用户会被送到 catch-all 的 404 页。这类错误类型检查看不出来（字符串就是字符串），
只能在构建期用契约检查兜住。

检查两条规则：
  1. `window.location.href|replace = '<路径>'` 是**浏览器 URL**，必须等于
     `vite base + 路由 path`（管理后台 base 是 /admin/，用户端是 /）。
  2. `router.push|replace('<路径>')` 是**路由内路径**，必须在 router 里声明过。

动态值（变量、模板串、外部 http 链接）自动跳过。

用法：python3 scripts/check_frontend_routes.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FRONTENDS = ("user_frontend", "admin_frontend")

ROUTE_RE = re.compile(r"""\bpath\s*:\s*['"]([^'"]*)['"]""")
VITE_BASE_RE = re.compile(r"""\bbase\s*:\s*['"]([^'"]+)['"]""")

# window.location.href = '/x'   /   window.location.replace('/x')
BROWSER_NAV_RE = re.compile(
    r"""location\s*\.\s*(?:href\s*=\s*|replace\s*\(\s*)['"]([^'"]+)['"]"""
)
# router.push('/x')  /  router.replace('/x')
ROUTER_NAV_RE = re.compile(
    r"""\brouter\s*\.\s*(?:push|replace)\s*\(\s*['"]([^'"]+)['"]"""
)

failures: list[str] = []
checks = 0


def declared_paths(frontend: str) -> list[str]:
    paths: list[str] = []
    for router_file in sorted((ROOT / frontend / "src" / "router").glob("*.ts")):
        paths.extend(ROUTE_RE.findall(router_file.read_text(encoding="utf-8")))
    return paths


def vite_base(frontend: str) -> str:
    cfg = ROOT / frontend / "vite.config.ts"
    if cfg.exists():
        m = VITE_BASE_RE.search(cfg.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return "/"


def to_browser_url(base: str, route_path: str) -> str:
    """路由 path（可能是 '' / '/' / '/login' / 'users'）→ 浏览器 URL。"""
    base_dir = base.rstrip("/")  # /admin/ -> /admin, / -> ''
    if route_path in ("", "/"):
        return base_dir or "/"
    suffix = route_path if route_path.startswith("/") else f"/{route_path}"
    return f"{base_dir}{suffix}"


def is_pattern(route_path: str) -> bool:
    """含参数或通配的路由（'/media/:id'、'/:pathMatch(.*)*'）：不能精确匹配。"""
    return ":" in route_path or "*" in route_path


def param_prefix(route_path: str) -> str | None:
    """'/media/:id' -> '/media'；'/ :pathMatch(.*)*' 这类无静态前缀的返回 None。"""
    if not is_pattern(route_path):
        return None
    return re.split(r"/[:*]", route_path)[0] or None


def matches(candidate: str, allowed: set[str], prefixes: set[str]) -> bool:
    if candidate in allowed:
        return True
    return any(
        prefix and (candidate == prefix or candidate.startswith(f"{prefix}/"))
        for prefix in prefixes
    )


def scan(frontend: str) -> None:
    global checks
    base = vite_base(frontend)
    paths = declared_paths(frontend)
    if not paths:
        failures.append(f"{frontend}: 没有解析到任何路由声明（router/index.ts 结构可能变了）")
        return

    browser_allowed = {to_browser_url(base, p) for p in paths if not is_pattern(p)}
    # 带 base 的前端（/admin/）根路径也允许写成 '/admin/'
    browser_allowed |= {
        to_browser_url(base, p) + "/" for p in paths if p in ("", "/") and base.rstrip("/")
    }
    browser_prefixes = {param_prefix(p) for p in paths} - {None}

    router_allowed = {p for p in paths if not is_pattern(p)}
    router_prefixes = {param_prefix(p) for p in paths} - {None}

    for src in sorted((ROOT / frontend / "src").rglob("*")):
        if src.suffix not in (".ts", ".vue"):
            continue
        rel = src.relative_to(ROOT)

        for target in BROWSER_NAV_RE.findall(src.read_text(encoding="utf-8")):
            checks += 1
            if target.startswith(("http://", "https://", "//")):
                continue
            if not target.startswith("/"):
                continue  # 相对路径/动态值：不在本检查范围
            if not matches(target, browser_allowed, browser_prefixes):
                failures.append(
                    f"{rel}: window.location 跳到 '{target}'，但 {frontend} 没有这个 URL"
                    f"（base={base}，可用示例：{sorted(browser_allowed)[:4]}）"
                )

        for target in ROUTER_NAV_RE.findall(src.read_text(encoding="utf-8")):
            checks += 1
            clean = target.split("?")[0].split("#")[0]
            if not clean.startswith("/"):
                continue
            if not matches(clean, router_allowed, router_prefixes):
                failures.append(
                    f"{rel}: router.push 跳到 '{clean}'，但 {frontend} 的 router 里没有声明该 path"
                )


def main() -> int:
    for frontend in FRONTENDS:
        if not (ROOT / frontend / "src" / "router").is_dir():
            failures.append(f"{frontend}: 找不到 src/router 目录")
            continue
        scan(frontend)

    print("=" * 60)
    if failures:
        print(f"❌ 前端路由契约检查失败（检查了 {checks} 个跳转点）")
        for item in failures:
            print(f"   - {item}")
        return 1

    print(f"✅ 前端路由契约检查通过（{checks} 个跳转点全部指向已声明的路由）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
