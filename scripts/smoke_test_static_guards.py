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

`scripts/check_hardcoded_secrets.py`（仓库里不许出现像真的密钥）
    真实发生过：`scripts/check_emby_sync.sh` 在**公开**仓库里写死了 Emby API Key 与
    生产域名。这类「边角文件」不进主流程，代码评审最容易跳过，而一旦提交就等于泄露。
    这条护栏认厂商前缀密钥与「变量名 + 随机值」的赋值，并要求假值必须写行内放行注释。

`scripts/check_branding.py`（仓库里不许再出现旧品牌名）
    项目改名后，一半代码叫新名、一半叫旧名是最难用的状态：类型检查、导入、冒烟测试
    全绿，因为它只是一段字符串——只有漏改的那处默认值会真的改变行为（客户端列表里
    出现两台同名服务器）。所以这里也钉住：**喂它一个还写着旧名的文件，它必须失败**，
    同时占位值 / 行内放行注释不能误报。

护栏最常见的失效方式不是报错，而是**根本不会响**：正则写歪、路径找错、基线比实际大，
于是它永远返回 0，谁也不知道。所以四条都要证明「喂它一个违规样本，它必须失败」。
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
SECRET_GUARD = ROOT / "scripts" / "check_hardcoded_secrets.py"
BRAND_GUARD = ROOT / "scripts" / "check_branding.py"

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

# ==========================================================================
# 三、硬编码密钥护栏
# ==========================================================================

proc = subprocess.run([sys.executable, str(SECRET_GUARD)], capture_output=True, text=True,
                      cwd=str(ROOT))
check("硬编码密钥：真实代码树上退出码为 0", proc.returncode == 0,
      (proc.stdout or proc.stderr).strip().splitlines()[-1][:120])

secret_guard = load(SECRET_GUARD, "_check_hardcoded_secrets")

# 违规样本：一个写死的 Emby API Key（就是事故里那个形状）+ 一个厂商前缀密钥
# 下面两处合成样本自带行内放行注释，否则扫描**本文件**时会先被自己报出来。
bad_tmp = pathlib.Path(tempfile.mkdtemp(prefix="secret-guard-bad-"))
(bad_tmp / "scripts").mkdir(parents=True, exist_ok=True)
(bad_tmp / "scripts" / "check_emby_sync.sh").write_text(
    "EMBY_URL=\"https://emby.example.com\"\n"
    "EMBY_API_KEY=\"9f4c1d7a2b8e3506c1a4d9f2b7e0c358\"\n", encoding="utf-8")  # secret-scan: allow — 合成样本
(bad_tmp / "backend").mkdir(parents=True, exist_ok=True)
(bad_tmp / "backend" / "integration.py").write_text(
    "OPENAI_KEY = \"sk-hz8Kq2Lm4Np6Rt0Vw1Xy3Zb5Cd7Ef9G\"\n", encoding="utf-8")  # secret-scan: allow — 合成样本

secret_guard.ROOT = bad_tmp
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    bad_code = secret_guard.main()
bad_out = buf.getvalue()

check("硬编码密钥：合成代码树上失败（退出码 1）", bad_code == 1,
      (bad_out.strip().splitlines() or ["(无输出)"])[0][:120])
check("硬编码密钥：两处都点了出来",
      bad_out.count("疑似硬编码密钥") + bad_out.count("[OpenAI / Stripe 密钥]") == 3,
      " | ".join(bad_out.strip().splitlines()[1:4])[:200])
check("硬编码密钥：点名了写死密钥的脚本",
      "scripts/check_emby_sync.sh:2" in bad_out, "")
check("硬编码密钥：认得出厂商前缀密钥",
      "backend/integration.py:1" in bad_out and "OpenAI" in bad_out, "")

# 合规样本：占位值 / 行内放行注释 / 纯单词夹具都不该报
good_tmp = pathlib.Path(tempfile.mkdtemp(prefix="secret-guard-good-"))
(good_tmp / "config").mkdir(parents=True, exist_ok=True)
(good_tmp / "config" / "template.py").write_text(
    "API_KEY = \"your-api-key-here\"\n"
    "SECRET_KEY = \"${SECRET_KEY}\"\n"
    "NODE_KEY = os.getenv(\"NODE_KEY\", \"\")\n"
    "EMBY_TOKEN = \"emby-client-token-alice\"\n", encoding="utf-8")
(good_tmp / "scripts").mkdir(parents=True, exist_ok=True)
(good_tmp / "scripts" / "allow.py").write_text(
    "FAKE = \"0123456789abcdef0123456789abcdef\"  # secret-scan: allow — 自检用的假值\n",
    encoding="utf-8")  # secret-scan: allow — 合成样本

secret_guard.ROOT = good_tmp
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    good_code = secret_guard.main()
check("硬编码密钥：占位值与放行注释不误报", good_code == 0,
      buf.getvalue().strip().splitlines()[-1][:120] if buf.getvalue().strip() else "(无输出)")

# ==========================================================================
# 四、品牌契约护栏
# ==========================================================================

proc = subprocess.run([sys.executable, str(BRAND_GUARD)], capture_output=True, text=True,
                      cwd=str(ROOT))
check("品牌契约：真实代码树上退出码为 0", proc.returncode == 0,
      (proc.stdout or proc.stderr).strip().splitlines()[-1][:120])

brand_guard = load(BRAND_GUARD, "_check_branding")

# 违规样本：一处旧名（一行代码、一行文档）
bad_tmp = pathlib.Path(tempfile.mkdtemp(prefix="brand-guard-bad-"))
(bad_tmp / "backend").mkdir(parents=True, exist_ok=True)
# 下面两行是「违规内容」的合成样本（自带放行注释，否则护栏会先报出本文件自己）。
(bad_tmp / "backend" / "api.py").write_text(
    "SERVER_NAME = os.getenv(\"EMBY_SERVER_NAME\", \"RoyalBot Media Server\")\n",  # brand-scan: allow — 合成样本
    encoding="utf-8")
(bad_tmp / "docs").mkdir(parents=True, exist_ok=True)
(bad_tmp / "docs" / "operations.md").write_text(
    "# 运维\n\n备份目录是 /root/RoyalBot-Portal/backups\n",  # brand-scan: allow — 合成样本
    encoding="utf-8")

brand_guard.ROOT = bad_tmp
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    brand_bad_code = brand_guard.main()
brand_bad_out = buf.getvalue()

check("品牌契约：合成代码树上失败（退出码 1）", brand_bad_code == 1,
      (brand_bad_out.strip().splitlines() or ["(无输出)"])[0][:120])
check("品牌契约：两处旧名都点了出来", "发现 2 处" in brand_bad_out,
      brand_bad_out.strip().splitlines()[0][:120])
check("品牌契约：点名了残留文件与行号",
      "backend/api.py:1" in brand_bad_out and "docs/operations.md:3" in brand_bad_out, "")

# 合规样本：新名 / 行内放行注释 / 发布说明豁免都不该报
good_tmp = pathlib.Path(tempfile.mkdtemp(prefix="brand-guard-good-"))
(good_tmp / "backend").mkdir(parents=True, exist_ok=True)
(good_tmp / "backend" / "api.py").write_text(
    "SERVER_NAME = os.getenv(\"EMBY_SERVER_NAME\", \"Aetrix Media Server\")\n", encoding="utf-8")
(good_tmp / "backend" / "compat.py").write_text(
    "LEGACY_DB = \"RoyalBot_unified.db\"  # brand-scan: allow — 老部署的库文件名，只用于兼容\n",
    encoding="utf-8")
(good_tmp / "CHANGELOG.md").write_text(
    "## v2.30 - 改名 RoyalBot → Aetrix\n",  # brand-scan: allow — 合成样本（发布说明本就该写着旧名）
    encoding="utf-8")

brand_guard.ROOT = good_tmp
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    brand_good_code = brand_guard.main()
check("品牌契约：新名 / 放行注释 / 发布说明不误报", brand_good_code == 0,
      buf.getvalue().strip().splitlines()[-1][:120] if buf.getvalue().strip() else "(无输出)")

# ==================== 汇总 ====================

print()
if failures:
    print(f"❌ {len(failures)}/{TOTAL} 项失败：{failures}")
    sys.exit(1)
print(f"✅ 全部通过（{TOTAL} 项）")
