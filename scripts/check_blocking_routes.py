#!/usr/bin/env python3
"""契约检查：`async def` 路由里不许出现同步数据库访问（只许减少，不许增加）

为什么要有这条
--------------
全项目用的是**同步 SQLAlchemy**。FastAPI 对 `async def` 端点是在事件循环上直接跑的，
对它 `def` 端点才会丢进线程池。所以一个 `async def` 端点里只要出现
`db.query(...) / db.commit()` 这类同步调用，**整个进程**（所有人的播放、所有请求）
就得等这次查询——单机 SQLite 亚毫秒还能忍，跨机 PostgreSQL 每查询一个 RTT 就是全站卡顿，
也与 docs/performance.md 里「扫描不把内存吃满、不让事件循环停摆」的口径相反。

修法有两种，按「这个端点有没有必须 await 的东西」选：

1. 什么都不用 await（绝大多数）→ 把 `async def` 改成 `def`。FastAPI 自动丢线程池，
   业务代码一个字都不用动，改动最小、风险最低。**首选。**
2. 确实要 await（通知推送 / 网络探测等）→ 把同步数据库那段拆成一个同步函数，
   用 `await run_in_threadpool(那个函数, db, ...)` 调用（本仓库已有先例，见
   `backend/emby_server/portal_mount_routes.py`）。

口径
----
* 只认**路由函数体自身**的同步 DB 调用（`ast` 层面），不看嵌套函数定义，
  也不做跨函数调用图分析——所以「路由 -> 同步辅助函数 -> 写库」这条间接路径抓不到。
  宁可少报，也不误报：误报会让人干脆把这条检查关掉。
* 会话对象按名字识别（`db` / `session` / `sess` / `conn` 及 `xxx_db` 这类），
  方法名取 SQLAlchemy 的常见读写口（query / add / commit / execute / flush …）。
* 基线：已经存在的这些先记在下面的集合里（它们是已知欠账，见 docs/performance.md）。
  **把基线里的名字删掉**（因为你把它改好了）随时欢迎；**往基线里加新名字**
  要么说明理由，要么就该改成同步 `def`。

退出码 0 = 通过；1 = 有新增的阻塞路由（或基线里写了不存在的名字）。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
DB_METHODS = {
    "query", "add", "add_all", "commit", "refresh", "delete", "execute",
    "flush", "rollback", "scalar", "scalars", "bulk_save_objects", "merge",
    "expire_all", "get",
}
SESSIONISH = re.compile(r"(?i)^(_?[a-z0-9]*(db|session|sess|conn))$")

# 已知欠账：file::函数名。这些是「async 路由里仍有同步 DB 访问」的存量，
# 按 docs/performance.md「先量、再改、最后固化成门禁」的做法记在这里。
# 已知欠账：`文件::函数名`（v2.21.0 时点 41 条；v2.35.0 把两条热路径改好 → 39 条）。
#
# v2.35.0 删掉的两条：
#   backend/emby_server/compat_routes.py::session_progress —— 每 10 秒 × 每个在播客户端上报一次，
#     是全站最热的写路径（详见 docs/performance.md）；
#   backend/emby_server/api.py::user_views —— 客户端每次打开媒体库都问，改同步 `def`。
#
# 它们**不是**机械改 `def` 就能解决的：函数体里都有必须 await 的东西，而那个「必须 await
# 的东西」（通知推送 backend/notifications.py、网络探测 backend/servers.py）**自己也**
# 在 async 函数里跑同步 SQLAlchemy——也就是说这不是 41 个端点的问题，而是这一层要一起改。
# 按 docs/performance.md 里「先量、再改、最后固化成门禁」的做法记在这里：
# 改好一个就删一行，新增一个就过不了 CI。
BASELINE: set[str] = set(
    """\
backend/api/admin.py::grant_subscription
backend/api/admin.py::extend_subscription
backend/api/admin.py::send_user_message
backend/api/admin.py::broadcast_message
backend/api/admin.py::create_announcement
backend/api/admin.py::update_announcement
backend/api/admin.py::update_ticket
backend/api/admin.py::reply_ticket
backend/api/admin.py::close_ticket
backend/api/admin.py::push_media_seek
backend/api/admin.py::update_media_seek
backend/api/admin.py::economy_mark_order_paid
backend/api/admin_economy.py::economy_adjust_points
backend/api/coupons_admin.py::list_coupon_usages
backend/api/economy.py::do_checkin
backend/api/economy.py::redeem_exchange_code
backend/api/emby_servers.py::save_server
backend/api/emby_servers.py::refresh_server_mounts
backend/api/emby_servers.py::test_server
backend/api/orders_admin.py::refund_order
backend/api/realms.py::sync_realm_nodes
backend/api/reminders_admin.py::run_expiry_reminders
backend/api/servers.py::emby_overview
backend/api/servers.py::create_server
backend/api/servers.py::update_server
backend/api/servers.py::activate_server
backend/api/servers.py::refresh_mount_health_now
backend/api/user.py::mark_all_read
backend/api/user.py::create_ticket
backend/api/user.py::reply_ticket
backend/api/user.py::create_media_seek
backend/emby_server/api.py::rate_item
backend/emby_server/portal.py::stop_my_session
backend/emby_server/portal.py::scan_library_endpoint
backend/emby_server/portal.py::admin_stop_session
backend/emby_server/portal.py::verify_pan115_account
backend/emby_server/portal_mount_routes.py::check_all_mounts
backend/emby_server/portal_mount_routes.py::test_saved_mount
backend/emby_server/portal_mount_routes.py::browse_mount
""".split()
)


def router_names(tree: ast.Module) -> set[str]:
    """本文件里的路由对象名

    路由对象不一定在本文件里创建：``admin.py`` 就是从 ``admin_core`` **导入**
    ``admin_router`` 的；``emby_server`` 那几个 install_xxx 模块拿到的是**函数参数**。
    所以这里不只认 ``X = APIRouter(...)``，而是把所有「被当成路由用」的名字都收进来
    ——判定标准就是「它是某个 ``@obj.<http 方法>(...)`` 装饰器的对象」。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    obj = dec.func.value
                    if isinstance(obj, ast.Name) and dec.func.attr in HTTP_METHODS:
                        names.add(obj.id)
    return names


def is_route(node: ast.AST, routers: set[str]) -> bool:
    for dec in getattr(node, "decorator_list", []):
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            obj = dec.func.value
            if isinstance(obj, ast.Name) and obj.id in routers and dec.func.attr in HTTP_METHODS:
                return True
    return False


OFFLOAD_CALLS = {"run_in_threadpool", "to_thread", "run_in_executor", "run_sync"}


def _offloaded_names(node: ast.AST) -> set[str]:
    """被丢进线程池执行的函数名

    路由里常见的写法是：外层 ``async def`` 只负责等，真正的同步活儿放在体内定义的
    嵌套函数里，用 ``await run_in_threadpool(work)`` 调用（见
    ``backend/emby_server/portal_mount_routes.py``）。这种**不算**阻塞，
    所以只对「确实被下放了」的嵌套函数放行——不能一刀切把所有嵌套函数都跳过，
    否则「路由里定义一个同步 helper 然后直接调用」这条真·阻塞路径就成了盲区。
    """
    names: set[str] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if fname not in OFFLOAD_CALLS:
            continue
        for arg in list(sub.args) + [kw.value for kw in sub.keywords]:
            if isinstance(arg, ast.Name):
                names.add(arg.id)
    return names


def sync_db_calls(node: ast.AST) -> list[str]:
    """函数体里会**在事件循环上跑**的同步 DB 调用

    计入：路由函数自己的语句，以及「体内定义、并且被直接同步调用」的嵌套函数。
    不计入：被 ``run_in_threadpool`` / ``to_thread`` 下放的嵌套函数。
    """
    offloaded = _offloaded_names(node)
    skipped: list[tuple[int, int]] = []
    for sub in ast.walk(node):
        if sub is node or not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if sub.name not in offloaded:
            continue
        start = getattr(sub, "lineno", None)
        if start is not None:
            skipped.append((start, getattr(sub, "end_lineno", start) or start))

    def is_offloaded(line: int) -> bool:
        return any(lo <= line <= hi for lo, hi in skipped)

    hits: list[str] = []
    for sub in ast.walk(node):
        if sub is node or not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if not isinstance(func, ast.Attribute) or func.attr not in DB_METHODS:
            continue
        root = func.value
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or not SESSIONISH.match(root.id):
            continue
        if is_offloaded(func.lineno):
            continue
        label = f"{func.attr}() @L{func.lineno}"
        if label not in hits:
            hits.append(label)
    return hits


def main() -> int:
    if not BACKEND.is_dir():
        print(f"找不到 {BACKEND}，请在项目根目录运行")
        return 1

    found: dict[str, list[str]] = {}
    for path in sorted(BACKEND.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"❌ 解析失败 {path.relative_to(ROOT)}: {exc}")
            return 1
        routers = router_names(tree)
        if not routers:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or not is_route(node, routers):
                continue
            hits = sync_db_calls(node)
            if hits:
                found[f"{path.relative_to(ROOT)}::{node.name}"] = hits

    new_keys = sorted(set(found) - BASELINE)
    stale_keys = sorted(BASELINE - set(found))

    print(f"扫描到阻塞型 async 路由 {len(found)} 个（基线 {len(BASELINE)} 个）")

    if new_keys:
        print(f"\n❌ 新增了 {len(new_keys)} 个「async 路由里做同步 DB」的端点：")
        for key in new_keys:
            print(f"    {key}  ->  {', '.join(found[key])}")
        print()
        print("修法：优先把它改成同步 `def`（FastAPI 自动丢线程池，业务代码不用动）。")
        print("      确实要 await 就拆出同步核心 + `await run_in_threadpool(...)`。")
        print("      两者都做不到，才把它加进本脚本的 BASELINE，并在 PR 里说明理由。")

    if stale_keys:
        # 不判失败：改名 / 合并也会让基线里出现“查无此人”，不该为此把人拦在门外。
        print(f"\nℹ️  基线里有 {len(stale_keys)} 个名字已不存在（改好了或者改名了），"
              f"可以把它们从 BASELINE 删掉：")
        for key in stale_keys:
            print(f"    {key}")

    if new_keys:
        return 1
    print("✅ 没有新增的阻塞型 async 路由")
    return 0


if __name__ == "__main__":
    sys.exit(main())
