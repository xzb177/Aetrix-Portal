"""EM / EA 分离部署冒烟测试（v2.6.3）

覆盖：
- EA 不能脱离 EM 单独运行：缺 SECRET_KEY、或共享库还没有 EM 的表时，启动即被拒绝
- EA 在共享库上能启动，并提供完整 Emby 协议面：/emby/* 与裸根路径（/System/Info、/Users/...）
- EA 健康检查如实上报与 EM 的配对状态
- EM 默认（单进程模式）行为不变：/emby/* 仍可用
- EM 分离模式（ENABLE_EMBY_GATEWAY=false）：不再提供协议面，而是给客户端明确的 EA 指引
"""
import importlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("DATABASE_URL", "sqlite:///./royalbot_unified.db")
# 冒烟测试需要一个确定存在的密钥（真实部署请复用 EM 的 .env）
os.environ.setdefault("SECRET_KEY", "smoke-test-only-secret-key-not-for-production")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from emby_api import main as ea
from backend.database import init_db
from backend.emby_server.portal import configured_emby_url

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


init_db()  # EM 的初始化动作，EA 依赖它建出的表


# ==================== 1. EA 的硬依赖闸门 ====================

def _expect_refusal(name: str, engine_override=None, **env_patches) -> None:
    """临时制造不满足配对条件的环境，确认 EA 拒绝启动"""
    saved_env = {k: os.environ.get(k) for k in env_patches}
    saved_engine = ea.engine
    for key, value in env_patches.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    if engine_override is not None:
        ea.engine = engine_override
    try:
        ea.ensure_paired_with_em()
        check(name, False, "未能拦截")
    except ea.PanelDependencyError as exc:
        check(name, True, str(exc)[:48] + "…")
    finally:
        ea.engine = saved_engine
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


print("--- EA 拒绝脱离 EM 单独运行 ---")
_expect_refusal("缺 SECRET_KEY 时拒绝启动", SECRET_KEY=None)

# 用一个空库模拟"EM 还没初始化过"
_tmp_db = os.path.join(tempfile.mkdtemp(), "empty.db")
_empty_engine = create_engine(f"sqlite:///{_tmp_db}")
_expect_refusal("共享库没有 EM 的表时拒绝启动", engine_override=_empty_engine)

# 合法的配对环境下应放行
try:
    ea.ensure_paired_with_em()
    check("配对条件满足时放行", True)
except ea.PanelDependencyError as exc:
    check("配对条件满足时放行", False, str(exc)[:60])


# ==================== 2. EA 提供完整 Emby 协议面 ====================

print("\n--- EA 协议面 ---")
with TestClient(ea.app) as client:
    r = client.get("/emby/system/info/public")
    check("GET /emby/system/info/public", r.status_code == 200, f"HTTP {r.status_code}")

    # 客户端"服务器地址"就是 EA 根地址，协议会走裸路径
    r = client.get("/System/Info/Public")
    check("GET /System/Info/Public（裸根路径）", r.status_code == 200, f"HTTP {r.status_code}")

    # Emby 官方文档里的规范地址是带 /emby 前缀且首字母大写（客户端发现服务第一条请求）
    r = client.get("/emby/System/Info/Public")
    check("GET /emby/System/Info/Public（规范地址）",
          r.status_code == 200 and bool((r.json() if r.status_code == 200 else {}).get("ServerName")),
          f"HTTP {r.status_code}")
    r = client.get("/emby/System/Ping")
    check("GET /emby/System/Ping", r.status_code == 200, f"HTTP {r.status_code}")
    r = client.get("/emby/Branding/Configuration")
    check("GET /emby/Branding/Configuration", r.status_code == 200, f"HTTP {r.status_code}")

    r = client.get("/api/health")
    body = r.json() if r.status_code == 200 else {}
    check(
        "GET /api/health 如实上报配对状态",
        r.status_code == 200 and body.get("service") == "ea" and body.get("paired_with_em") is True,
        f"HTTP {r.status_code} paired={body.get('paired_with_em')}",
    )

    # 两套路径族都要真的可服务：/emby/* 与裸根。
    # 注意：不能用 app.routes 枚举来判断——当前 FastAPI 版本会把 include_router 的路由
    # 保存成嵌套的 _IncludedRouter，app.routes 里看不到子路由，只有发请求才准确。
    r = client.post("/emby/Users/AuthenticateByName", json={})
    check("POST /emby/Users/AuthenticateByName 命中协议路由", r.status_code != 404, f"HTTP {r.status_code}")

    r = client.post("/Users/AuthenticateByName", json={})
    check("POST /Users/AuthenticateByName 命中裸根协议路由", r.status_code != 404, f"HTTP {r.status_code}")


# ==================== 3. EM 默认模式行为不变 ====================

print("\n--- EM 单进程模式（默认）---")
os.environ.pop("ENABLE_EMBY_GATEWAY", None)
import backend.main as em

importlib.reload(em)
with TestClient(em.app) as client:
    r = client.get("/emby/system/info/public")
    check("EM 默认仍提供 /emby/*（现有部署不受影响）", r.status_code == 200, f"HTTP {r.status_code}")


# ==================== 4. EM 分离模式：不再提供协议面，给出 EA 指引 ====================

print("\n--- EM 分离模式（ENABLE_EMBY_GATEWAY=false）---")
os.environ["ENABLE_EMBY_GATEWAY"] = "false"
os.environ["EMBY_API_PUBLIC_URL"] = "https://emby.example.com"
importlib.reload(em)

with TestClient(em.app) as client:
    r = client.get("/emby/system/info/public")
    detail = ""
    try:
        detail = str(r.json().get("detail", ""))
    except Exception:  # noqa: BLE001
        detail = r.text[:60]
    check("EM 不再提供 /emby/*", r.status_code == 404, f"HTTP {r.status_code}")
    # 指引地址的口径是「面板里配置的 Emby 服务入口」优先于环境变量，
    # 所以断言接受两者之一（沙箱库往往已经配过地址，旧断言假定库是干净的）。
    _hint_candidates = (configured_emby_url(), "https://emby.example.com")
    check(
        "并指引客户端去 EA",
        "EA" in detail and any(h and h in detail for h in _hint_candidates),
        detail[:60],
    )

    r = client.get("/System/Info/Public")
    check("裸根协议路径也给出指引", r.status_code == 404, f"HTTP {r.status_code}")

    r = client.get("/api/health")
    check("EM 面板自身的健康检查不受影响", r.status_code == 200, f"HTTP {r.status_code}")

    # 指引路由不能把面板自己的 SPA 吃掉（这是分离模式最容易踩的回归）
    r = client.get("/")
    is_html = r.status_code == 200 and "text/html" in r.headers.get("content-type", "")
    check("门户首页仍正常返回", is_html, f"HTTP {r.status_code} {r.headers.get('content-type', '')}")

    r = client.get("/wallet")
    check("门户子路由仍走 SPA 兜底", r.status_code == 200, f"HTTP {r.status_code}")

os.environ.pop("ENABLE_EMBY_GATEWAY", None)


# ==================== 结果 ====================

print()
if failures:
    print(f"FAILED {len(failures)}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("ALL PASS")
