"""服务器管理 API：添加 / 编辑 / 测试 / 删除 / 设为当前使用

面板以前只能填一台 EA 和一台外部 Emby，MoviePilot 与 qBittorrent 更是完全没有入口，
于是「求片」批了以后没有任何办法把片子真的弄进来。这里把「服务器」变成一份可增删改的清单：

- `GET    /api/admin/servers`            清单 + 类型元数据 + 统计（面板顶部与数据概览都用它）
- `GET    /api/admin/servers/summary`    只取统计（数据概览的信息展示用）
- `POST   /api/admin/servers`            新增（保存即体检一次，结果落到列表）
- `PUT    /api/admin/servers/{id}`       修改（密钥留空 = 不改）
- `POST   /api/admin/servers/{id}/test`  重新体检
- `POST   /api/admin/servers/{id}/activate`  设为该类型的「当前使用」
- `POST   /api/admin/servers/{id}/toggle`    启用 / 停用
- `DELETE /api/admin/servers/{id}`       删除
- `POST   /api/admin/servers/test`       测试「还没保存」的配置

EA / Emby 被激活时会同步写回既有的 `emby_managed_*` / `emby_external_*` / `emby_active_mode`，
所以网关闸门、挂载体检、客户端指引、用户端账号卡全部照旧生效（见 ``backend.servers.sync_legacy``）。
所有写操作都落管理审计。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models, realms
from backend import servers as registry
from backend.api.admin import _audit, get_current_admin
from backend.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/servers", tags=["服务器管理"])


class ServerPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    kind: str = Field(..., min_length=1, max_length=20)
    url: str = Field(..., min_length=8, max_length=500)
    config: dict = Field(default_factory=dict)
    is_enabled: bool = True
    remark: str = Field(default="", max_length=300)
    # 属于哪个服（留空 = 新增时归当前服，修改时不改归属）
    realm_id: Optional[int] = None
    # MoviePilot / qBittorrent 专用：声明「全服共用」（realm_id 置空，每个服都看得到）
    shared: bool = False


class ProbePayload(BaseModel):
    """测试「还没保存」的配置：新增对话框里的「测试连接」按钮用"""
    kind: str = Field(..., min_length=1, max_length=20)
    url: str = Field(..., min_length=8, max_length=500)
    config: dict = Field(default_factory=dict)
    server_id: Optional[int] = None  # 编辑时带上：密钥留空则沿用已保存的那份


def _check_kind(kind: str) -> str:
    kind = (kind or "").strip().lower()
    if kind not in registry.KIND_MAP:
        raise HTTPException(400, f"服务器类型必须是：{'、'.join(registry.KINDS)}")
    return kind


def _check_url(url: str) -> str:
    try:
        return registry._validate_url(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _effective_config(kind: str, config: dict, server_id: Optional[int], db: Session) -> dict:
    """体检用的配置：密钥留空且带 server_id 时，沿用已保存的那份（否则「测一下」永远失败）"""
    merged = dict(config or {})
    if server_id:
        saved = registry.get_server(db, server_id)
        if saved and saved.kind == kind:
            for key in registry.secret_keys(kind):
                if not str(merged.get(key) or "").strip():
                    value = registry.parse_config(saved).get(key)
                    if value:
                        merged[key] = value
    return merged


def _name_conflict(db: Session, name: str, exclude_id: Optional[int] = None) -> bool:
    query = db.query(models.RemoteServer).filter(models.RemoteServer.name == name.strip())
    if exclude_id:
        query = query.filter(models.RemoteServer.id != exclude_id)
    return db.query(query.exists()).scalar() is True


def _missing_required(kind: str, url: str, config: dict) -> Optional[str]:
    """类型层面的必填校验（比「地址填了就行」更早给出可读提示）"""
    if kind == "qbittorrent" and not str(config.get("username") or "").strip():
        return "qBittorrent 需要用户名（Web UI 的登录名）"
    if kind == "moviepilot" and not (str(config.get("api_key") or "").strip()
                                     or str(config.get("username") or "").strip()):
        return "MoviePilot 至少填一项凭据：API 密钥（查订阅）或用户名 + 密码（提交订阅）"
    return None


@router.get("")
async def list_servers(_: models.WebUser = Depends(get_current_admin), db: Session = Depends(get_db),
                      realm_id: Optional[int] = None):
    """服务器清单（按服；``realm_id=0`` 看全部服）

    ``ea`` / ``emby`` 这两类属于某个服（一个服一个入口）；MoviePilot / qBittorrent
    是内容自动化，多服可以共用，所以“全部服”视图里它们也一并列出。
    """
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    # EA / Emby 按归属服；MoviePilot / qB 共用的（realm_id 为空）在每个服里都列出
    rows = (registry.realm_scope(db.query(models.RemoteServer), scope_id)
            .order_by(models.RemoteServer.kind, models.RemoteServer.id).all())
    return {
        "servers": [registry.serialize(db, r) for r in rows],
        # 类型元数据由后端下发，前端不再自己维护一份字段表
        "kinds": registry.SERVER_KINDS,
        "summary": registry.summary(db, scope_id),
        "realm_id": scope_id,
        "active_realm_id": realms.active_realm_id(db),
        "realms": [{"id": r.id, "name": r.name, "slug": r.slug} for r in realms.list_realms(db)],
    }


@router.get("/summary")
async def servers_summary(_: models.WebUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    """只有统计结果：给「数据概览」的信息展示卡用"""
    return registry.summary(db)


@router.post("")
async def create_server(
    payload: ServerPayload,
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    kind = _check_kind(payload.kind)
    url = _check_url(payload.url)
    name = payload.name.strip()
    if _name_conflict(db, name):
        raise HTTPException(409, "已经有同名服务器了，换个名字吧")
    required_error = _missing_required(kind, url, payload.config or {})
    if required_error:
        raise HTTPException(400, required_error)

    # 内容自动化（MoviePilot / qB）可以选择「全服共用」：归属服留空，多服一起用一套
    shared = bool(payload.shared) and kind in registry.PUSH_TARGETS
    server = models.RemoteServer(
        name=name, kind=kind, url=url,
        config=registry.json_dumps(registry.only_known(kind, payload.config or {})),
        is_enabled=payload.is_enabled, remark=payload.remark or "",
        realm_id=None if shared else (payload.realm_id or realms.active_realm_id(db)),
    )
    db.add(server)
    db.commit()
    db.refresh(server)

    result = await registry.probe_and_store(db, server)
    _audit(db, admin, "create_server", "server", server.id,
           {"kind": kind, "ok": result.get("ok"), "url": url})
    db.commit()
    return {"success": True, "server": registry.serialize(db, server), "probe": result}


@router.put("/{server_id}")
async def update_server(
    server_id: int,
    payload: ServerPayload,
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    server = registry.get_server(db, server_id)
    if not server:
        raise HTTPException(404, "服务器不存在")
    kind = _check_kind(payload.kind)
    url = _check_url(payload.url)
    name = payload.name.strip()
    if _name_conflict(db, name, exclude_id=server_id):
        raise HTTPException(409, "已经有同名服务器了，换个名字吧")

    kind_changed = kind != server.kind
    server.name = name
    server.kind = kind
    server.url = url
    server.is_enabled = payload.is_enabled
    server.remark = payload.remark or ""
    if payload.shared and kind in registry.PUSH_TARGETS:
        # 内容自动化改成「全服共用」
        server.realm_id = None
    elif payload.realm_id:
        if not realms.get_realm(db, payload.realm_id):
            raise HTTPException(400, f"服不存在: #{payload.realm_id}")
        server.realm_id = payload.realm_id
    # 换类型时旧类型的字段不再适用，直接以新配置为准
    server.config = registry.json_dumps(
        registry.only_known(kind, payload.config or {})
        if kind_changed else registry.merge_config(server, payload.config or {})
    )
    db.commit()

    result = await registry.probe_and_store(db, server)
    # 停用 / 类型变更后，旧配置键要跟着收回，否则会出现「面板说没接入、网关却还在跑」
    if not server.is_enabled and server.is_active and server.kind in registry.LEGACY_PREFIX:
        server.is_active = False
        registry.deactivate_legacy(db, server.kind)
        db.commit()
    elif server.is_active and server.kind in registry.LEGACY_PREFIX:
        registry.sync_legacy(db, server, reachable=bool(result.get("ok")))
        db.commit()

    _audit(db, admin, "update_server", "server", server.id,
           {"kind": kind, "ok": result.get("ok")})
    db.commit()
    return {"success": True, "server": registry.serialize(db, server), "probe": result}


@router.post("/test")
async def test_unsaved(
    payload: ProbePayload,
    _: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    kind = _check_kind(payload.kind)
    url = _check_url(payload.url)
    config = _effective_config(kind, payload.config or {}, payload.server_id, db)
    required_error = _missing_required(kind, url, config)
    if required_error:
        return {"ok": False, "message": required_error}
    return await registry.probe_server(kind, url, config)


@router.post("/{server_id}/test")
async def test_server(
    server_id: int,
    _: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    server = registry.get_server(db, server_id)
    if not server:
        raise HTTPException(404, "服务器不存在")
    return await registry.probe_and_store(db, server)


@router.post("/{server_id}/activate")
async def activate_server(
    server_id: int,
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """设为该类型的「当前使用」

    激活前会**重新体检一次**：面板不能拿一份几小时前的结论去切换全站入口。
    """
    server = registry.get_server(db, server_id)
    if not server:
        raise HTTPException(404, "服务器不存在")
    probe = await registry.probe_and_store(db, server)
    if not probe.get("ok"):
        _audit(db, admin, "activate_server_failed", "server", server.id,
               {"kind": server.kind, "message": str(probe.get("message") or "")[:200]})
        db.commit()
        return {"success": False, "activated": False, "probe": probe,
                "message": str(probe.get("message") or "连接测试未通过")}

    result = registry.activate(db, server, reachable=True)
    if not result.get("ok"):
        return {"success": False, "activated": False, "probe": probe,
                "message": str(result.get("message") or "无法设为当前使用")}

    # EA 一旦成为出流节点，就顺手把「EA 视角的挂载体检」拉一次：
    # 挂载里的本机路径 / rclone 地址是跟着那台机器走的，这里不查就得等播放 502 才发现。
    mounts_health = None
    if server.kind == "ea":
        from backend.api.emby_servers import refresh_mount_health

        mounts_health = await refresh_mount_health(db, server.url, server.realm_id)

    _audit(db, admin, "activate_server", "server", server.id,
           {"kind": server.kind, "mode": result.get("mode"),
            "mount_health_ok": None if mounts_health is None else mounts_health.get("ok")})
    db.commit()
    return {
        "success": True,
        "activated": bool(result.get("activatable")),
        "configurable": bool(result.get("activatable")),
        "mode": result.get("mode"),
        "message": result.get("message"),
        "probe": probe,
        "mounts_health": mounts_health,
        "server": registry.serialize(db, server),
    }


@router.post("/{server_id}/toggle")
async def toggle_server(
    server_id: int,
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    server = registry.get_server(db, server_id)
    if not server:
        raise HTTPException(404, "服务器不存在")
    server.is_enabled = not bool(server.is_enabled)
    if not server.is_enabled:
        was_active = bool(server.is_active)
        server.is_active = False
        if was_active and server.kind in registry.LEGACY_PREFIX:
            registry.deactivate_legacy(db, server.kind)
    db.commit()
    _audit(db, admin, "toggle_server", "server", server.id,
           {"kind": server.kind, "enabled": bool(server.is_enabled)})
    db.commit()
    return {"success": True, "server": registry.serialize(db, server), "summary": registry.summary(db)}


@router.delete("/{server_id}")
async def delete_server(
    server_id: int,
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    server = registry.get_server(db, server_id)
    if not server:
        raise HTTPException(404, "服务器不存在")
    kind = server.kind
    was_active = bool(server.is_active)
    name = server.name
    db.delete(server)
    db.commit()
    # 删掉的正好是「当前使用」时，必须把旧配置键收回，不能让面板继续指着一台不存在的服务
    if was_active and kind in registry.LEGACY_PREFIX:
        registry.deactivate_legacy(db, kind)
        db.commit()
    _audit(db, admin, "delete_server", "server", server_id, {"kind": kind, "name": name})
    db.commit()
    return {"success": True, "summary": registry.summary(db)}


@router.post("/mounts/health")
async def refresh_mount_health_now(
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """手动重拉一次当前服的「EA 视角的挂载体检」（服务器页的「EA 体检」按钮）"""
    realm_id = realms.active_realm_id(db)
    ea = registry.active_config(db, "ea", realm_id)
    if not ea:
        raise HTTPException(400, "当前服还没有可用的后端服（EA）：请先添加并测试连接")
    from backend.api.emby_servers import refresh_mount_health

    health = await refresh_mount_health(db, ea["url"], realm_id)
    _audit(db, admin, "refresh_ea_mounts_health", "server", ea["id"],
           {"ok": health.get("ok")})
    db.commit()
    return {"success": bool(health.get("ok")), "health": health, "server": ea["name"]}


__all__ = ["router"]
