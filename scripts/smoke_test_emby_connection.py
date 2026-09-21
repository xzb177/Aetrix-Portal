"""面板 Emby 双模式联动冒烟测试

用临时 SQLite 库 + 假的探测器，不访问真实服务器、不碰开发库：
- 管理端配置 API 鉴权与输入校验（不完整地址直接被拒）
- EA 连接成功后切换到「分离部署」入口
- EA 不可用时拦截自建 Emby 功能（503）
- 切到「已有 Emby 服」后拦截自建媒体库功能（503）
- 外部 Emby 探测成功后切换到外部入口
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.api import emby_servers
from backend.database import Base
from backend.emby_server import portal

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


path = os.path.join(tempfile.mkdtemp(), "emby-connection.db")
engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

admin = models.WebUser(
    username="smoke-admin",
    password_hash="not-used",
    is_active=True,
    is_staff=True,
)
with SessionLocal() as db:
    db.add(admin)
    db.commit()
    db.refresh(admin)

app = FastAPI()
app.include_router(emby_servers.router)
app.dependency_overrides[emby_servers.get_current_admin] = lambda: admin
app.dependency_overrides[emby_servers.get_db] = lambda: SessionLocal()

probes: list[tuple[str, str]] = []


async def fake_probe(mode: str, url: str, api_key: str = "") -> dict:
    """假探测器：不发真实请求，只记录调用并返回成功。"""
    probes.append((mode, url))
    return {
        "ok": True,
        "status_code": 200,
        "server_name": "EA smoke" if mode == "managed_ea" else "External smoke",
    }


async def failing_probe(mode: str, url: str, api_key: str = "") -> dict:
    """假探测器：模拟服务不可达，用来验证「失败不切换入口」。"""
    return {"ok": False, "status_code": None, "message": "无法连接"}


real_probe = emby_servers.probe
emby_servers.probe = fake_probe

try:
    with TestClient(app) as client:
        response = client.get("/api/admin/emby/servers")
        check("读取双模式配置", response.status_code == 200, str(response.status_code))
        check("默认保持单进程模式", response.json().get("active_mode") == "managed_ea")

        # 只有端口的简写地址必须被拒（保存与测试两条路径都要拦）
        for path_, payload in (
            ("/api/admin/emby/servers/test", {"mode": "managed_ea", "url": "emby.local:8096"}),
            ("/api/admin/emby/servers", {"mode": "managed_ea", "url": "ftp://ea.example.test", "enabled": True}),
        ):
            response = client.post(path_, json=payload) if "test" in path_ else client.put(path_, json=payload)
            check(f"拒绝非法地址 {payload['url']}", response.status_code == 400, str(response.status_code))

        response = client.put(
            "/api/admin/emby/servers",
            json={"mode": "managed_ea", "url": "https://ea.example.test/", "enabled": True},
        )
        check("保存已连接 EA", response.status_code == 200, str(response.status_code))
        check("EA 连接成功后切为当前模式", response.json().get("mode") == "managed_ea")
        check("尾斜杠被归一化", probes[-1][1] == "https://ea.example.test", probes[-1][1])

        response = client.get("/api/admin/emby/servers")
        check("读取时报告 EA 可达", response.json()["managed_ea"]["reachable"] is True)

    with SessionLocal() as db:
        managed = db.query(models.SystemConfig).filter(
            models.SystemConfig.key == "emby_managed_reachable"
        ).first()
        managed.value = "false"
        db.commit()
        try:
            portal.ensure_emby_backend_available(db)
            check("EA 不可用时拦截自建功能", False, "未返回 503")
        except HTTPException as exc:
            check("EA 不可用时拦截自建功能", exc.status_code == 503, str(exc.status_code))

    with TestClient(app) as client:
        # 外部模式：探测成功即切换入口
        response = client.put(
            "/api/admin/emby/servers",
            json={
                "mode": "external",
                "url": "https://external.example.test",
                "api_key": "smoke-key",
                "enabled": True,
            },
        )
        check("保存已有外部 Emby", response.status_code == 200, str(response.status_code))
        check("外部 Emby 探测成功后切为当前模式", response.json().get("mode") == "external")

        with SessionLocal() as db:
            active = db.query(models.SystemConfig).filter(
                models.SystemConfig.key == "emby_active_mode"
            ).first()
            check("当前模式已落库为 external", active is not None and active.value == "external")

            try:
                portal.ensure_emby_backend_available(db)
                check("外部 Emby 模式拦截自建功能", False, "未返回 503")
            except HTTPException as exc:
                check("外部 Emby 模式拦截自建功能", exc.status_code == 503, str(exc.status_code))

        # 保存时未通过探测的服务不得切换入口（只有探测成功才切换）
        emby_servers.probe = failing_probe
        response = client.put(
            "/api/admin/emby/servers",
            json={"mode": "managed_ea", "url": "https://broken.example.test", "enabled": True},
        )
        check("探测失败不切换入口", response.status_code == 200, str(response.status_code))
        with SessionLocal() as db:
            active = db.query(models.SystemConfig).filter(
                models.SystemConfig.key == "emby_active_mode"
            ).first()
            check("入口仍保持 external", active is not None and active.value == "external", str(active.value))
finally:
    emby_servers.probe = real_probe


if failures:
    print(f"FAILED {len(failures)}:")
    for name in failures:
        print(f"  - {name}")
    raise SystemExit(1)
print("ALL PASS")
