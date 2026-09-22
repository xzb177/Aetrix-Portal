"""管理员配置：分离部署的 EA，或已有的外部 Emby。

保存 / 启用 EA 时会顺带拉一次**EA 视角的挂载体检**并落库（见
``backend/emby_server/mount_health``）：挂载里的本机路径、rclone RC 地址这类配置是
主机相对的，「面板测试通过」不代表那台 EA 能播，必须在添加服务入口时就把它查出来。
"""
import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models, realms
from backend import servers as registry
from backend.api.admin_core import _audit, get_current_admin
from backend.database import get_db
from backend.emby_server import mount_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/emby", tags=["Emby 服务连接"])


class ConnectionRequest(BaseModel):
    mode: str
    url: str = Field(..., min_length=8, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=500)
    enabled: bool = True


def _validate_url(raw_url: str) -> str:
    """地址必须是完整的 http(s) 地址：只有端口的 "emby.local" 之类会在这里被拒。

    probe() 也要经过这里，否则「测试连接」可以绕过保存时的校验。
    """
    url = raw_url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "地址必须是完整的 http:// 或 https:// 地址")
    return url


def value(db: Session, key: str, default: str = "", realm_id: Optional[int] = None) -> str:
    """读配置：Emby 入口那几个键是**一个服一个**的（默认服沿用历史键名）"""
    if key in realms.REALM_CONFIG_BASES:
        return realms.realm_config(db, key, realm_id, default)
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return (row.value if row and row.value is not None else default).strip()


def save_value(db: Session, key: str, new_value: str, description: str,
               realm_id: Optional[int] = None) -> None:
    if key in realms.REALM_CONFIG_BASES:
        realms.set_realm_config(db, key, new_value, realm_id, description)
        return
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if row:
        row.value = new_value
    else:
        db.add(models.SystemConfig(key=key, value=new_value, description=description))


async def refresh_mount_health(db: Session, url: str, realm_id: Optional[int] = None) -> dict:
    """拉一次 EA 视角的挂载体检并落库（按服保存：挂载跟着服走）

    失败时**保留上一次的逐条结果**（只标记快照失效），避免一次网络抖动就把面板上的
    「EA 可达」全部抹成未知。
    """
    if realm_id is None:
        realm_id = realms.active_realm_id(db)
    previous = mount_health.read_ea_health(db, realm_id)
    result = await mount_health.fetch_ea_health(url)

    if result.get("ok"):
        data = result.get("data") or {}
        mount_health.write_ea_health(db, {
            "ok": True,
            "checked_at": data.get("checked_at"),
            "error": "",
            "playback_node": data.get("playback_node"),
            "mounts": data.get("mounts") or [],
        }, realm_id)
        db.commit()
        return {
            "ok": True,
            "checked_at": data.get("checked_at"),
            "total": data.get("total"),
            "failed_count": data.get("failed_count"),
            "unreachable": data.get("unreachable") or [],
        }

    error = str(result.get("error") or "EA 体检失败")[:300]
    mount_health.write_ea_health(db, {
        "ok": False,
        "checked_at": previous.get("checked_at"),
        "error": error,
        "playback_node": previous.get("playback_node"),
        "mounts": previous.get("mounts") or [],
    }, realm_id)
    db.commit()
    return {"ok": False, "error": error, "checked_at": previous.get("checked_at")}


async def probe(mode: str, url: str, api_key: str = "") -> dict:
    """检查服务是否真的可用，而不是只检查端口是否能打开。

    实现落在 ``backend.servers``（``probe_ea`` / ``probe_emby``）：服务器清单页与这里
    用的是同一套探测，避免两处对「连得上」的口径出现分岐。
    """
    target = _validate_url(url)
    if mode == "managed_ea":
        return await registry.probe_ea(target)
    return await registry.probe_emby(target, api_key)


@router.get("/servers")
async def get_servers(_: models.WebUser = Depends(get_current_admin), db: Session = Depends(get_db),
                      realm_id: Optional[int] = None):
    """当前服的 Emby 服务入口（两个格子：自建 EA / 已有 Emby）

    入口是**一个服一个**的：多服部署下每个服各自填自己的地址，默认服沿用历史配置键。
    """
    scope_id = realm_id or realms.active_realm_id(db)
    realm = realms.get_realm(db, scope_id)
    health = mount_health.read_ea_health(db, scope_id)
    mounts = health.get("mounts") or []
    return {
        "realm_id": scope_id,
        "realm_name": realm.name if realm else "",
        "managed_ea": {
            "url": value(db, "emby_managed_url", realm_id=scope_id),
            "enabled": value(db, "emby_managed_enabled", "false", scope_id).lower() == "true",
            "reachable": value(db, "emby_managed_reachable", "", scope_id).lower() == "true",
        },
        "external": {
            "url": value(db, "emby_external_url", realm_id=scope_id),
            "enabled": value(db, "emby_external_enabled", "false", scope_id).lower() == "true",
            "has_api_key": bool(value(db, "emby_external_api_key", realm_id=scope_id)),
            "reachable": value(db, "emby_external_reachable", "", scope_id).lower() == "true",
        },
        "active_mode": value(db, "emby_active_mode", "managed_ea", scope_id),
        # EA 视角的挂载体检快照（汇总；逐条结果在「存储挂载」页）
        "mounts_health": {
            "ok": bool(health.get("ok")),
            "checked_at": health.get("checked_at"),
            "error": health.get("error") or "",
            "total": len(mounts),
            "failed_count": len([m for m in mounts if isinstance(m, dict) and m.get("ok") is False]),
            "unreachable": health.get("unreachable") or [],
        },
    }


@router.put("/servers")
async def save_server(
    request: ConnectionRequest,
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if request.mode not in ("managed_ea", "external"):
        raise HTTPException(400, "mode 必须是 managed_ea 或 external")
    scope_id = realms.active_realm_id(db)
    url = _validate_url(request.url)
    prefix = "emby_managed" if request.mode == "managed_ea" else "emby_external"
    save_value(db, f"{prefix}_url", url, "Emby 服务地址", scope_id)
    save_value(db, f"{prefix}_enabled", "true" if request.enabled else "false",
               "Emby 服务是否启用", scope_id)
    if request.mode == "external" and request.api_key and request.api_key.strip():
        save_value(db, "emby_external_api_key", request.api_key.strip(),
                   "外部 Emby API 密钥", scope_id)
    db.commit()

    result = await probe(request.mode, url,
                         request.api_key or value(db, "emby_external_api_key", realm_id=scope_id))
    save_value(db, f"{prefix}_reachable", "true" if result.get("ok") else "false",
               "Emby 服务最近一次连接结果", scope_id)
    # 只有真正探测成功且勾选启用，才切换当前入口；避免保存一个不存在的服务后全站假运行。
    if request.enabled and result.get("ok"):
        save_value(db, "emby_active_mode", request.mode, "当前 Emby 服务模式", scope_id)
    db.commit()

    # 同步进「服务器」清单：两个页面（旧的两个格子 / 新的清单）操作的是同一件事，
    # 收敛到一条真相，旧页保存后新页面就能看到它是「当前使用」。
    registry.upsert_legacy(
        db, "ea" if request.mode == "managed_ea" else "emby", url,
        api_key=(request.api_key or "") if request.mode == "external" else "",
        enabled=request.enabled, reachable=bool(result.get("ok")), realm_id=scope_id,
    )

    # 挂载是主机相对的：EA 能连通不等于它能碰到面板里配的存储。
    # 所以保存 EA 服务入口时顺带做一次 EA 视角的挂载体检，把结果落到面板上。
    health: dict | None = None
    if request.mode == "managed_ea" and result.get("ok"):
        health = await refresh_mount_health(db, url, scope_id)

    _audit(db, admin, "save_emby_server_connection", "system", None,
           {"mode": request.mode, "ok": result.get("ok"), "realm_id": scope_id,
            "mount_health_ok": None if health is None else health.get("ok")})
    db.commit()
    return {"success": True, "mode": request.mode, "probe": result,
            "mounts_health": health, "realm_id": scope_id}


@router.post("/servers/mounts/refresh")
async def refresh_server_mounts(
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重新拉一次 EA 视角的挂载体检（「存储挂载」页的「EA 体检」按钮）

    只对 managed EA 有意义：一体化（EM 自己出流）与外部 Emby 都不存在这台 EA。
    """
    scope_id = realms.active_realm_id(db)
    url = value(db, "emby_managed_url", realm_id=scope_id)
    if not url:
        raise HTTPException(400, "这个服还没有配置 EA 服务地址：请先在「服务器」页添加一台后端服（EA）并设为当前使用")
    mode = value(db, "emby_active_mode", "managed_ea", scope_id)
    if mode != "managed_ea":
        # 不阻断：切回 EA 之前也想先把那台机器的存储情况看清楚
        logger.info("当前模式是 %s，仍按 EA 地址体检挂载", mode)
    health = await refresh_mount_health(db, url, scope_id)
    _audit(db, admin, "refresh_ea_mounts_health", "system", None,
           {"ok": health.get("ok")})
    db.commit()
    return {"success": bool(health.get("ok")), "health": health}


@router.post("/servers/test")
async def test_server(
    request: ConnectionRequest,
    _: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if request.mode not in ("managed_ea", "external"):
        raise HTTPException(400, "mode 必须是 managed_ea 或 external")
    # 先校验地址再探测：校验不能只挂在 probe 里，否则替换探测器时就绕过了
    scope_id = realms.active_realm_id(db)
    url = _validate_url(request.url)
    result = await probe(request.mode, url,
                         request.api_key or value(db, "emby_external_api_key", realm_id=scope_id))
    prefix = "emby_managed" if request.mode == "managed_ea" else "emby_external"
    save_value(db, f"{prefix}_reachable", "true" if result.get("ok") else "false",
               "Emby 服务最近一次连接结果", scope_id)
    db.commit()
    return result
