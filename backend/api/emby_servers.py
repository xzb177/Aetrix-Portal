"""管理员配置：分离部署的 EA，或已有的外部 Emby。"""
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models
from backend.api.admin import get_current_admin
from backend.database import get_db
from backend.api.admin import _audit

router = APIRouter(prefix="/api/admin/emby", tags=["Emby 服务连接"])

class ConnectionRequest(BaseModel):
    mode: str
    url: str = Field(..., min_length=8, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=500)
    enabled: bool = True

def value(db: Session, key: str, default: str = "") -> str:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return (row.value if row and row.value is not None else default).strip()

def save_value(db: Session, key: str, new_value: str, description: str) -> None:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if row:
        row.value = new_value
    else:
        db.add(models.SystemConfig(key=key, value=new_value, description=description))

async def probe(mode: str, url: str, api_key: str = "") -> dict:
    """检查服务是否真的可用，而不是只检查端口是否能打开。"""
    target = url.rstrip("/")
    endpoint = f"{target}/api/health" if mode == "managed_ea" else f"{target}/System/Info/Public"
    headers = {} if mode == "managed_ea" else ({"X-Emby-Token": api_key} if api_key else {})
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(endpoint, headers=headers)
        if response.status_code >= 400:
            return {"ok": False, "status_code": response.status_code, "message": f"服务返回 HTTP {response.status_code}"}
        body = response.json() if response.content else {}
        if mode == "managed_ea" and (body.get("service") != "ea" or body.get("status") != "healthy" or not body.get("paired_with_em")):
            return {"ok": False, "status_code": response.status_code, "message": "EA 已响应，但还没有和面板配对；请确认共享数据库与 SECRET_KEY 一致"}
        return {"ok": True, "status_code": response.status_code,
                "server_name": body.get("emby_server_name") or body.get("ServerName") or body.get("Product") or "Emby 服务",
                "version": body.get("version") or body.get("Version") or ""}
    except (httpx.RequestError, ValueError):
        return {"ok": False, "status_code": None, "message": "无法连接或返回格式不正确"}

@router.get("/servers")
async def get_servers(_: models.WebUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    return {
        "managed_ea": {
            "url": value(db, "emby_managed_url"),
            "enabled": value(db, "emby_managed_enabled", "false") == "true",
            "reachable": value(db, "emby_managed_reachable", "") == "true",
        },
        "external": {
            "url": value(db, "emby_external_url"),
            "enabled": value(db, "emby_external_enabled", "false") == "true",
            "has_api_key": bool(value(db, "emby_external_api_key")),
            "reachable": value(db, "emby_external_reachable", "") == "true",
        },
        "active_mode": value(db, "emby_active_mode", "managed_ea"),
    }

@router.put("/servers")
async def save_server(request: ConnectionRequest, admin: models.WebUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    if request.mode not in ("managed_ea", "external"):
        raise HTTPException(400, "mode 必须是 managed_ea 或 external")
    url = request.url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "地址必须以 http:// 或 https:// 开头")
    prefix = "emby_managed" if request.mode == "managed_ea" else "emby_external"
    save_value(db, f"{prefix}_url", url, "Emby 服务地址")
    save_value(db, f"{prefix}_enabled", "true" if request.enabled else "false", "Emby 服务是否启用")
    if request.mode == "external" and request.api_key:
        save_value(db, "emby_external_api_key", request.api_key.strip(), "外部 Emby API 密钥")
    db.commit()
    result = await probe(request.mode, url, request.api_key or value(db, "emby_external_api_key"))
    save_value(db, f"{prefix}_reachable", "true" if result.get("ok") else "false", "Emby 服务最近一次连接结果")
    # 只有真正探测成功且勾选启用，才切换当前入口；避免保存一个不存在的服务后全站假运行。
    if request.enabled and result.get("ok"):
        save_value(db, "emby_active_mode", request.mode, "当前 Emby 服务模式")
    db.commit()
    _audit(db, admin, "save_emby_server_connection", "system", None, {"mode": request.mode, "ok": result.get("ok")})
    db.commit()
    return {"success": True, "mode": request.mode, "probe": result}

@router.post("/servers/test")
async def test_server(request: ConnectionRequest, _: models.WebUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    if request.mode not in ("managed_ea", "external"):
        raise HTTPException(400, "mode 必须是 managed_ea 或 external")
    result = await probe(request.mode, request.url.strip(), request.api_key or value(db, "emby_external_api_key"))
    prefix = "emby_managed" if request.mode == "managed_ea" else "emby_external"
    save_value(db, f"{prefix}_reachable", "true" if result.get("ok") else "false", "Emby 服务最近一次连接结果")
    db.commit()
    return result
