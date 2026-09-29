"""管理后台的接口路径必须与后端实际注册的一致。

`utils/request.ts` 的 `baseURL` 已经是 `/api/admin`，而这几条又拼了
``${E}/...``（``E = '/emby'``），于是变成 `/api/admin/emby/services/status`。

后端 `services_router` 的 prefix 是 `/api/admin`，真实路径没有 `emby` 这一段：

    backend/api/admin_services.py:@services_router.get("/services/status")

结果：仪表盘一进来就报 `Not Found`（`{"detail":"Not Found"}`）。

这条测试**只读源码文本**，不 import 后端任何模块——否则它会抢在同批次的其它
测试建库之前初始化 engine，污染它们（这一类问题本仓库已经吃过好几次）。
"""
import re
from pathlib import Path

ADMIN_TS = Path(__file__).resolve().parents[1] / "admin_frontend" / "src" / "api" / "admin.ts"

# 必须是「直接挂在 /api/admin 下」的路径（services_router 的 prefix 就是它）
FLAT_PREFIXES = ("/services/", "/quota-breaker/")


def _registered_admin_routes() -> set[str]:
    """从后端源码里把 services_router / admin_emby_router 注册的路径抽出来。

    只看这两个 router：其它模块的 prefix 规则不同，混进来会误判。
    """
    backend = Path(__file__).resolve().parents[1] / "backend"
    found: set[str] = set()
    for py in backend.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "services_router" not in text:
            continue
        for m in re.finditer(
            r'@services_router\.(?:get|post|put|delete)\("([^"]+)"\)', text
        ):
            found.add("/api/admin" + m.group(1))
    return found


def test_admin_ts_uses_paths_that_backend_actually_registers():
    routes = _registered_admin_routes()
    assert routes, "没能从后端解析出 services_router 的路由（源码结构变了？）"
    assert "/api/admin/services/status" in routes, sorted(routes)
    assert "/api/admin/quota-breaker/status" in routes, sorted(routes)
    assert "/api/admin/quota-breaker/reset" in routes, sorted(routes)


def test_no_double_emby_prefix_in_flat_endpoints():
    """flat 端点不能再拼 ${E}（E='/emby'），否则多一层 emby/"""
    src = ADMIN_TS.read_text(encoding="utf-8")
    bad = [
        line.strip()
        for line in src.splitlines()
        if any(p in line for p in FLAT_PREFIXES) and "${E}" in line
    ]
    assert not bad, "这些路径多了 emby/ 段，后端会 404：\n" + "\n".join(bad)
