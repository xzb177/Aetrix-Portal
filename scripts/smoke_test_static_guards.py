"""两条静态契约护栏：先证明「它们会失败」（v2.21.0）

性能整改里反复出现的两类改动，编译、导入、类型检查**都看不出来**，只有真打到那个请求
才炸。所以项目里加了两条静态护栏，这套测试钉的是「护栏本身可用」：

`scripts/check_await_consistency.py`（`await` 的目标必须是协程函数）
    把 ``async def`` 端点改成同步 ``def`` 时，同一个函数可能被**别的 ``async`` 端点**
    ``await`` 着复用（例如 ``coupons_admin.list_coupon_usages`` 被
    ``list_coupon_usages_by_code`` 复用、``api.user_views`` 被 ``compat_routes`` 复用），
    于是那一边会 ``TypeError: object dict can't be used in 'await' expression``。

`scripts/check_blocking_routes.py`（`async` 路由里不许做同步 DB）
    FastAPI 对 ``async def`` 端点是在事件循环上直接跑的，而本项目用的是同步 SQLAlchemy，
    一个查询就能把全站按住。存量 41 条记在脚本的 `BASELINE` 里，只减不增。

护栏最常见的失效方式不是报错，而是**根本不会响**：正则写歪、路径找错、基线比实际大，
于是它永远返回 0，谁也不知道。所以两条都要证明「喂它一个违规样本，它必须失败」。
"""
import ast
import contextlib
import importlib.util
import io
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent
AWAIT_GUARD = ROOT / "scripts" / "check_await_consistency.py"
BLOCKING_GUARD = ROOT / "scripts" / "check_blocking_routes.py"

failures: list[str] = []
TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# 一、await 契约护栏
# ==========================================================================

proc = subprocess.run([sys.executable, str(AWAIT_GUARD)], capture_output=True, text=True,
                      cwd=str(ROOT))
check("await 契约：真实代码树上退出码为 0", proc.returncode == 0,
      (proc.stdout or proc.stderr).strip().splitlines()[-1][:120])

# 合成一棵代码树：async 端点在 await 一个纯同步函数 —— 必须报
await_tmp = pathlib.Path(tempfile.mkdtemp(prefix="await-guard-")) / "backend"
await_tmp.mkdir(parents=True)

(await_tmp / "helper.py").write_text(
    "def do_work(x):\n    return x\n", encoding="utf-8")
(await_tmp / "route.py").write_text(
    "from backend import helper\n"
    "\n"
    "async def endpoint():\n"
    "    return await helper.do_work(1)\n"
    "\n"
    "async def bare_endpoint():\n"
    "    return await do_work(1)\n"
    "\n"
    "def do_work(x):\n"
    "    return x\n",
    encoding="utf-8")

guard = load(AWAIT_GUARD, "_check_await_consistency")
guard.BACKEND = await_tmp
guard.ROOT = await_tmp.parent
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    await_code = guard.main()
await_out = buf.getvalue()

check("await 契约：合成代码树上失败（退出码 1）", await_code == 1,
      (await_out.strip().splitlines() or ["(无输出)"])[0][:120])
check("await 契约：点名了被 await 的那个同步函数",
      "await do_work(" in await_out and "route.py" in await_out,
      " | ".join(l.strip() for l in await_out.strip().splitlines()[1:4])[:160])
check("await 契约：没有误报「点号调用」（口径上只看裸名，不误报优先）",
      "helper.do_work" not in await_out,
      "")

# ==========================================================================
# 二、阻塞路由护栏
# ==========================================================================

guard = load(BLOCKING_GUARD, "_check_blocking_routes")


def scan_all() -> set[str]:
    found: set[str] = set()
    for path in sorted(guard.BACKEND.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        routers = guard.router_names(tree)
        if not routers:
            continue
        rel = str(path.relative_to(guard.ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or not guard.is_route(node, routers):
                continue
            if guard.sync_db_calls(node):
                found.add(f"{rel}::{node.name}")
    return found


real = scan_all()
baseline = set(guard.BASELINE)
check("阻塞路由：基线里的每一条都真实存在（没有死条目）",
      not (baseline - real), f"死条目：{sorted(baseline - real)[:5]}")
check("阻塞路由：真实存在的每一条都在基线里（没有漏网）",
      not (real - baseline), f"漏网：{sorted(real - baseline)[:5]}")
check("阻塞路由：基线非空（不是把基线清空来骗过检查）", len(baseline) > 0,
      f"{len(baseline)} 条")

proc = subprocess.run([sys.executable, str(BLOCKING_GUARD)], capture_output=True, text=True,
                      cwd=str(ROOT))
check("阻塞路由：真实代码树上退出码为 0", proc.returncode == 0,
      (proc.stdout or proc.stderr).strip().splitlines()[-1][:120])

PREAMBLE = (
    "from fastapi import APIRouter, Depends\n"
    "from fastapi.concurrency import run_in_threadpool\n"
    "from sqlalchemy.orm import Session\n"
    "\n"
    "router = APIRouter()\n"
)
blocking_tmp = pathlib.Path(tempfile.mkdtemp(prefix="blocking-guard-"))
(blocking_tmp / "api").mkdir(parents=True, exist_ok=True)
(blocking_tmp / "api" / "blocking.py").write_text(PREAMBLE + """
@router.post("/blocking")
async def blocking(db: Session = Depends(lambda: None)):
    db.commit()
    return {}


@router.get("/clean-sync")
def clean_sync(db: Session = Depends(lambda: None)):
    db.commit()
    return {}


@router.get("/clean-async")
async def clean_async():
    return {}


@router.post("/nested-called")
async def nested_called(db: Session = Depends(lambda: None)):
    def work():
        db.commit()

    work()
    return {}


@router.post("/nested-offloaded")
async def nested_offloaded(db: Session = Depends(lambda: None)):
    def work():
        db.commit()

    await run_in_threadpool(work)
    return {}
""", encoding="utf-8")

guard.BACKEND = blocking_tmp
guard.ROOT = blocking_tmp.parent
guard.BASELINE = set()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    blocking_code = guard.main()
blocking_out = buf.getvalue()
summary = blocking_out.strip().splitlines()[0] if blocking_out.strip() else "(无输出)"

check("阻塞路由：合成代码树上失败（退出码 1）", blocking_code == 1, f"exit={blocking_code}")
check("阻塞路由：报出来的条数正好是 2", "新增了 2 个" in blocking_out, summary)
for expected in ("api/blocking.py::blocking", "api/blocking.py::nested_called"):
    check(f"阻塞路由：点名了 {expected}", expected in blocking_out, summary)
for unexpected in ("api/blocking.py::clean_sync",
                   "api/blocking.py::clean_async",
                   "api/blocking.py::nested_offloaded"):
    check(f"阻塞路由：没有误报 {unexpected}", unexpected not in blocking_out, summary)

# ==================== 汇总 ====================

print()
if failures:
    print(f"❌ {len(failures)}/{TOTAL} 项失败：{failures}")
    sys.exit(1)
print(f"✅ 全部通过（{TOTAL} 项）")
