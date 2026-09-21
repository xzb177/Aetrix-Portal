"""管理员配置：分离部署的 EA，或已有的外部 Emby。

保存 / 启用 EA 时会顺带拉一次**EA 视角的挂载体检**并落库（见
``backend/emby_server/mount_health``）：挂载里的本机路径、rclone RC 地址这类配置是
主机相对的，「面板测试通过」不代表那台 EA 能播，必须在添加服务入口时就把它查出来。
"""
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.api.admin import _audit, get_current_admin
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


def value(db: Session, key: str, default: str = "") -> str:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return (row.value if row and row.value is not None else default).strip()


def save_value(db: Session, key: str, new_value: str, description: str) -> None:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if row:
        row.value = new_value
    else:
        db.add(models.SystemConfig(key=key, value=new_value, description=description))


async def refresh_mount_health(db: Session, url: str) -> dict:
    """拉一次 EA 视角的挂载体检并落库

    失败时**保留上一次的逐条结果**（只标记快照失效），避免一次网络抖动就把面板上的
    「EA 可达」全部抹成未知。
    """
    previous = mount_health.read_ea_health(db)
    result = await mount_health.fetch_ea_health(url)

    if result.get("ok"):
        data = result.get("data") or {}
        mount_health.write_ea_health(db, {
            "ok": True,
            "checked_at": data.get("checked_at"),
            "error": "",
            "playback_node": data.get("playback_node"),
            "mounts": data.get("mounts") or [],
        })
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
    })
    db.commit()
    return {"ok": False, "error": error, "checked_at": previous.get("checked_at")}


async def probe(mode: str, url: str, api_key: str = "") -> dict:
    """检查服务是否真的可用，而不是只检查端口是否能打开。"""
    target = _validate_url(url)
    endpoint = f"{target}/api/health" if mode == "managed_ea" else f"{target}/System/Info/Public"
    headers = {} if mode == "managed_ea" else ({"X-Emby-Token": api_key} if api_key else {})
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(endpoint, headers=headers)
        if response.status_code >= 400:
            return {"ok": False, "status_code": response.status_code, "message": f"服务返回 HTTP {response.status_code}"}
        body = response.json() if response.content else {}
        if mode == "managed_ea" and (
            body.get("service") != "ea"
            or body.get("status") != "healthy"
            or not body.get("paired_with_em")
        ):
            return {"ok": False, "status_code": response.status_code, "message": "EA 已响应，但还没有和面板配对；请确认共享数据库与 SECRET_KEY 一致"}
        return {
            "ok": True,
            "status_code": response.status_code,
            "server_name": body.get("emby_server_name") or body.get("ServerName") or body.get("Product") or "Emby 服务",
            "version": body.get("version") or body.get("Version") or "",
        }
    except (httpx.RequestError, ValueError):
        return {"ok": False, "status_code": None, "message": "无法连接或返回格式不正确"}


@router.get("/servers")
async def get_servers(_: models.WebUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    health = mount_health.read_ea_health(db)
    mounts = health.get("mounts") or []
    return {
        "managed_ea": {
            "url": value(db, "emby_managed_url"),
            "enabled": value(db, "emby_managed_enabled", "false").lower() == "true",
            "reachable": value(db, "emby_managed_reachable", "").lower() == "true",
        },
        "external": {
            "url": value(db, "emby_external_url"),
            "enabled": value(db, "emby_external_enabled", "false").lower() == "true",
            "has_api_key": bool(value(db, "emby_external_api_key")),
            "reachable": value(db, "emby_external_reachable", "").lower() == "true",
        },
        "active_mode": value(db, "emby_active_mode", "managed_ea"),
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
    url = _validate_url(request.url)
    prefix = "emby_managed" if request.mode == "managed_ea" else "emby_external"
    save_value(db, f"{prefix}_url", url, "Emby 服务地址")
    save_value(db, f"{prefix}_enabled", "true" if request.enabled else "false", "Emby 服务是否启用")
    if request.mode == "external" and request.api_key and request.api_key.strip():
        save_value(db, "emby_external_api_key", request.api_key.strip(), "外部 Emby API 密钥")
    db.commit()

    result = await probe(request.mode, url, request.api_key or value(db, "emby_external_api_key"))
    save_value(db, f"{prefix}_reachable", "true" if result.get("ok") else "false", "Emby 服务最近一次连接结果")
    # 只有真正探测成功且勾选启用，才切换当前入口；避免保存一个不存在的服务后全站假运行。
    if request.enabled and result.get("ok"):
        save_value(db, "emby_active_mode", request.mode, "当前 Emby 服务模式")
    db.commit()

    # 挂载是主机相对的：EA 能连通不等于它能碰到面板里配的存储。
    # 所以保存 EA 服务入口时顺带做一次 EA 视角的挂载体检，把结果落到面板上。
    health: dict | None = None
    if request.mode == "managed_ea" and result.get("ok"):
        health = await refresh_mount_health(db, url)

    _audit(db, admin, "save_emby_server_connection", "system", None,
           {"mode": request.mode, "ok": result.get("ok"),
            "mount_health_ok": None if health is None else health.get("ok")})
    db.commit()
    return {"success": True, "mode": request.mode, "probe": result, "mounts_health": health}


@router.post("/servers/mounts/refresh")
async def refresh_server_mounts(
    admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重新拉一次 EA 视角的挂载体检（「存储挂载」页的「EA 体检」按钮）

    只对 managed EA 有意义：一体化（EM 自己出流）与外部 Emby 都不存在这台 EA。
    """
    url = value(db, "emby_managed_url")
    if not url:
        raise HTTPException(400, "还没有配置 EA 服务地址：请先在「Emby 服务入口」里保存一次")
    mode = value(db, "emby_active_mode", "managed_ea")
    if mode != "managed_ea":
        # 不阻断：切回 EA 之前也想先把那台机器的存储情况看清楚
        logger.info("当前模式是 %s，仍按 EA 地址体检挂载", mode)
    health = await refresh_mount_health(db, url)
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
    url = _validate_url(request.url)
    result = await probe(request.mode, url, request.api_key or value(db, "emby_external_api_key"))
    prefix = "emby_managed" if request.mode == "managed_ea" else "emby_external"
    save_value(db, f"{prefix}_reachable", "true" if result.get("ok") else "false", "Emby 服务最近一次连接结果")
    db.commit()
    return result
