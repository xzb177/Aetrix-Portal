#!/usr/bin/env python3
"""管理后台 API 契约检查：前端调用的每个端点都必须真实存在。

## 为什么要有这道门禁

管理后台有 30 个页面、上百个 API 封装，全靠人肉点按钮验证「点了有没有反应」
是不现实的——30 页 × 三遍点检要花掉一个人天，而且**下次改完又得重来一遍**。

真正会出事的两类错误都能静态抓出来：

1. **前端调了不存在的端点** → 运行时 404，用户看到「按钮点了没反应」或一句看不出
   所以然的报错。类型检查抓不到（路径就是字符串），构建也不会失败。
2. **路径写得不规范**（例如 ``/../health`` 这种靠 URL 归一化才碰巧生效的写法）
   → 今天能用，换个反代或改 baseURL 就断。属于「今天没坏、明天会坏」。

检查方法：
- 后端侧**运行时 introspect** ``backend.main:app`` 的路由表（不是正则扫源码）：
  拿到的是真正 include_router 上去的 path + method，避免「源码里写了但没挂载」
  的幽灵端点被算成存在。
- 前端侧扫 ``admin_frontend/src/api/*.ts`` 的 HTTP 调用：
  - 相对路径按 axios 实例的 baseURL（``/api/admin``）补全；
  - 绝对路径（``/api/site/branding``、裸 ``axios.get``）直接比对全量路由；
  - 模板串拼出来的动态路径不判定，只计数。

用法：python3 scripts/check_admin_api_contract.py
"""

from __future__ import annotations

import logging
import os
import posixpath
import re
import sys
from pathlib import Path

#: 以脚本方式运行时 sys.path[0] 是 scripts/，仓库根不在路径上
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

#: 管理后台 axios 实例的 baseURL（见 admin_frontend/src/utils/request.ts）
BASE_URL = "/api/admin"

#: 前端 HTTP 调用：get('/x') / post(`/x`, ...) / delete("/x/y") / getPublic('/api/health')
#:
#: 用命名分组而不是位置分组——位置分组一旦调整就会静默取错值（踩过一次：方法名被
#: 当成了路径，输出全是 ``POST /users`` 这种胡说）。
#: ``(?<!\w)`` 保证匹配的是独立标识符，不会命中 ``budget`` / ``target`` 这种尾巴。
#:
#: ``getPublic`` 必须**显式列出**：``get`` 后面紧跟 ``Public``（非空白），既不会被
#: 现有的 ``\s*`` 接上，命中不了它——服务健康页那次 ``/api/admin/api/health`` 的
#: 404 就是这么溜过门禁的（端点计数从 184 掉到 183 才暴露出来）。
#: 交替里 ``getPublic`` 必须排在 ``get`` 前面：正则择先匹配，不是最长匹配。
#:
#: ``bare`` 不做成正则分组：``(?<!\w)`` 正是为了避开 ``budget.get`` 这种尾巴，
#: 而它会连带阻止可选的 ``(?P<bare>\.)?`` 在点号位置匹配（点号前一个字符是 \w）。
#: 所以改成匹配后回看源码里紧邻的前一个字符——``axios.get(...)`` 的 ``g`` 前面
#: 是 ``.`` → 裸 axios / publicRequest 实例（无 baseURL），导入的 ``get(...)``
#: 前面是换行或标识符 → 走 baseURL。两者拼接行为相反，不区分就会把 site.ts 里
#: 正确的裸 axios 调用误报成拼接错误。
CALL_RE = re.compile(
    r"""(?<!\w)(?P<verb>getPublic|get|post|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*"""
    r"""(?P<q>['"`])(?P<path>[^'"`]+)(?P=q)""",
    re.S,
)
PARAM_RE = re.compile(r"\{[^}/]+\}")
#: 模板串里的插值：``/orders/${id}`` → ``/orders/{}``
TEMPLATE_RE = re.compile(r"\$\{[^}]*\}")
#: 文件内常量：``const R = '/realms'`` → {"R": "/realms"}
CONST_RE = re.compile(r"""^\s*(?:export\s+)?const\s+([A-Z_][A-Z0-9_]*)\s*=\s*['"]([^'"]+)['"]""",
                      re.MULTILINE)


def backend_routes() -> set[tuple[str, str]]:
    """运行时枚举真正挂载的路由 → {(METHOD, path)}

    必须**递归**：当前 FastAPI 版本的 ``include_router`` 不再把子路由扚平到
    ``app.routes``，而是塞一个 ``_IncludedRouter`` 包装对象（真正的路由在它的
    ``original_router.routes`` 里，带自己的 prefix）。只遍历一层的话只能看到
    40 来条默认路由，后台端点会被整片漏掉——「什么都没查出来」比报错更危险。
    """
    os.environ.setdefault("DATABASE_TYPE", "sqlite")
    os.environ.setdefault("REDIS_ENABLED", "false")
    logging.disable(logging.CRITICAL)  # 导入 main 会打一堆挂载日志，淹没检查结果

    from backend.main import app  # noqa: PLC0415 — 必须先设好环境变量

    out: set[tuple[str, str]] = set()

    def walk(routes, prefix: str) -> None:
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                sub = getattr(inner, "routes", [])
                walk(sub, prefix + str(getattr(inner, "prefix", "") or ""))
                continue
            path = str(getattr(route, "path", "") or "")
            # 有些 FastAPI 版本子路由的 path 已经含了 prefix（``/api/admin/users``），
            # 有些没有（``/users``）。先判再拼，否则会得到
            # ``/api/admin/api/admin/users`` 这种双前缀，把真端点全判成不存在。
            if prefix and not path.startswith(prefix):
                path = prefix + path
            if not path.startswith("/"):
                continue
            for method in getattr(route, "methods", None) or set():
                if method in {"HEAD", "OPTIONS"}:
                    continue
                out.add((method.upper(), _norm(path)))

    walk(app.routes, "")
    return out


def _norm(path: str) -> str:
    """归一成可比形式：去查询串、解析 ``.`` / ``..``、去尾斜杠、占位符统一成 ``{}``

    查询串要去：后端路由表里只有 path，``/x?limit=10`` 与 ``/x`` 是同一个端点
    （axios 会把 URL 里的 ``?a=b`` 正常传过去，不是 bug）。
    """
    path = path.split("?", 1)[0]
    path = posixpath.normpath(path)
    return PARAM_RE.sub("{}", path.rstrip("/") or "/")


def frontend_calls() -> tuple[
    dict[tuple[str, str], tuple[str, str]], int, list[tuple[str, str, str]]
]:
    """扫后台前端 API 封装

    返回 ``({(METHOD, 实际请求路径): (原始路径, 文件:行号)}, 无法判定条数, 拼接错误列表)``

    模板串拼出来的路径（``/economy/orders/${id}``）也**参与判定**：把 ``${...}``
    归一成 ``{}`` 后与后端占位符对齐。早先版本直接跳过它们，结果 186 个调用里只
    验了 76 个，剩下七成正是「点了没反应」最容易藏的地方。
    """
    calls: dict[tuple[str, str], tuple[str, str]] = {}
    misjoined: list[tuple[str, str, str]] = []
    unresolved = 0
    api_dir = ROOT / "admin_frontend" / "src" / "api"
    for file in sorted(api_dir.glob("*.ts")):
        src = file.read_text(encoding="utf-8")
        # ``const R = '/realms'`` 这类路径常量：拼出来的整段路径也能参与判定
        consts = {m.group(1): m.group(2) for m in CONST_RE.finditer(src)}
        for match in CALL_RE.finditer(src):
            verb = match.group("verb")
            # 调用紧前面那个字符是 ``.`` → 裸 axios / publicRequest 实例，无 baseURL
            bare = verb == "getPublic" or (
                match.start() > 0 and src[match.start() - 1] == "."
            )
            # ``getPublic`` 是个包装函数名，不是 HTTP 动词，归一成 GET
            method = "GET" if verb == "getPublic" else verb.upper()
            raw = match.group("path")
            line = src.count("\n", 0, match.start()) + 1
            where = f"{file.relative_to(ROOT)}:{line}"
            path = raw
            for name, value in consts.items():
                path = path.replace("${" + name + "}", value)
            path = TEMPLATE_RE.sub("{}", path)
            # 开头不是 / 的：说明首段也来自不可知的变量，判不了
            if not path.startswith("/"):
                unresolved += 1
                continue

            if bare:
                # 裸 axios / publicRequest（无 baseURL）：路径原样发出，所以必须
                # 自带 /api/ 前缀，否则会被当同源静态资源（走 index.html）或直接 404
                if not path.startswith("/api/"):
                    misjoined.append((raw, where, "裸 axios 实例的路径必须以 /api/ 开头"))
                    continue
                full = path
            elif path.startswith("/api/"):
                # 走带 baseURL 的封装却又写了 /api/ 开头的绝对路径 →
                # axios 的 baseURL 是**字符串拼接**不是 URL 解析，结果是
                # ``/api/admin/api/health``。#295 的服务健康页 404 就是这么来的，
                # 而且它能骗过「端点存在性」检查：``/api/health`` 确实存在，
                # 只是没人会请求它。所以必须拿真实 baseURL 拼一遍再查。
                misjoined.append((
                    raw,
                    where,
                    f"经 baseURL {BASE_URL} 拼接后会变成 {BASE_URL}{path}；"
                    f"要打绝对路径请用 getPublic",
                ))
                full = path
            else:
                full = f"{BASE_URL}{path}"
            calls.setdefault((method, _norm(full)), (raw, where))
    return calls, unresolved, misjoined


def main() -> int:
    if not (ROOT / "admin_frontend" / "src" / "api").is_dir():
        print("找不到 admin_frontend/src/api，跳过")
        return 0

    routes = backend_routes()
    calls, unresolved, misjoined = frontend_calls()

    missing = sorted(
        (m, raw, where) for (m, p), (raw, where) in calls.items() if (m, p) not in routes
    )
    # 靠 URL 归一化才碰巧生效的写法：今天能用，换个 baseURL / 反代就断
    fragile = sorted(
        (raw, where) for (m, p), (raw, where) in calls.items() if ".." in raw
    )

    print("=" * 60)
    if missing:
        print(f"❌ 前端调了不存在的端点（{len(missing)} 处，运行时会 404）：")
        for method, raw, where in missing:
            print(f"   - {method} {raw}  ({where})")
    else:
        print(f"✅ 前端调用的 {len(calls)} 个端点全部存在")

    if misjoined:
        print(f"\n❌ baseURL 拼接错误（{len(misjoined)} 处，运行时必然 404）：")
        for raw, where, why in misjoined:
            print(f"   - {raw}  ({where})\n       {why}")

    if fragile:
        print(f"\n⚠️  {len(fragile)} 处路径含 '..'，靠 URL 归一化才生效（脆弱写法）：")
        for raw, where in fragile:
            print(f"   - {raw}  ({where})")

    if unresolved:
        print(f"\nℹ️ 另有 {unresolved} 处路径整段由变量拼成，不在判定范围内")

    return 1 if (missing or misjoined) else 0


if __name__ == "__main__":
    sys.exit(main())