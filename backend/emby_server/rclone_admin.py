"""管理后台 · rclone remote 配置端点（从 portal.py 拆出）

rclone remote = 访问云盘的方式（个人盘 OAuth / 服务账号 + 团队盘）。
配置存 `rclone_remotes` 表，一键生成 rclone.conf 并应用到 rclone 容器。

拆分约定：路由挂在 portal.py 定义的 ``admin_emby_router`` 上（导入即注册），
调用方（backend/main.py）在 ``include_router`` 之前导入本模块；
``require_staff`` 等共享依赖从 portal 导入，本模块不被 portal 反向引用（无循环导入）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db
from backend.emby_server import models as em
from backend.emby_server import rclone_manager
from backend.emby_server.portal import admin_emby_router, require_staff

logger = logging.getLogger(__name__)


# ---------------- Pydantic ----------------

class RcloneRemoteCreate(BaseModel):
    name: str
    remote_type: str = "drive"
    drive_type: str = "personal"  # personal / service_account
    client_id: str = ""
    client_secret: str = ""
    team_drive_id: str = ""
    is_enabled: bool = True
    remark: str = ""


class RcloneRemoteUpdate(BaseModel):
    name: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    team_drive_id: str | None = None
    is_enabled: bool | None = None
    remark: str | None = None


class OAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: str = ""


# ---------------- 序列化（脱敏） ----------------

def _mask_secret(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    v = value.strip()
    if len(v) <= keep:
        return "*" * len(v)
    return v[:keep] + "*" * (len(v) - keep)


def _serialize_remote(r: em.RcloneRemote, db: Session) -> dict:
    sa_filename = ""
    if r.sa_file_id:
        sa = db.query(em.ServiceAccountFile).filter(
            em.ServiceAccountFile.id == r.sa_file_id).first()
        if sa:
            sa_filename = sa.filename or ""
    return {
        "id": r.id,
        "name": r.name,
        "remote_type": r.remote_type or "drive",
        "drive_type": "service_account" if r.sa_file_id else "personal",
        "client_id": r.client_id or "",
        "client_id_masked": _mask_secret(r.client_id or ""),
        "has_client_secret": bool((r.client_secret or "").strip()),
        "has_token": bool((r.token_json or "").strip()),
        "team_drive_id": r.team_drive or "",
        "service_account_file": sa_filename,
        "has_service_account": bool(r.sa_file_id),
        "is_enabled": bool(r.is_enabled),
        "is_probe_remote": bool(r.is_probe_remote),
        "remark": r.remark or "",
        "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
        "last_check_ok": r.last_check_ok,
        "last_check_message": r.last_check_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写 remote 名称")
    if not re.match(r'^[A-Za-z0-9_-]+$', name):
        raise HTTPException(status_code=400, detail="名称只允许字母、数字、下划线、中划线")
    return name


# ---------------- CRUD ----------------

@admin_emby_router.get("/rclone/remotes")
def list_rclone_remotes(
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    remotes = db.query(em.RcloneRemote).order_by(em.RcloneRemote.id).all()
    return {"remotes": [_serialize_remote(r, db) for r in remotes]}


@admin_emby_router.post("/rclone/remotes")
def create_rclone_remote(
    req: RcloneRemoteCreate,
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    name = _validate_name(req.name)
    if db.query(em.RcloneRemote).filter(em.RcloneRemote.name == name).first():
        raise HTTPException(status_code=400, detail=f"名称「{name}」已存在")
    if req.drive_type not in ("personal", "service_account"):
        raise HTTPException(status_code=400, detail="类型只能是 personal 或 service_account")

    r = em.RcloneRemote(
        name=name,
        remote_type=req.remote_type or "drive",
        client_id=req.client_id.strip(),
        client_secret=req.client_secret.strip(),
        team_drive=req.team_drive_id.strip(),
        is_enabled=req.is_enabled,
        remark=req.remark or "",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    logger.info("新建 rclone remote: %s", name)
    return {"success": True, "remote": _serialize_remote(r, db)}


@admin_emby_router.put("/rclone/remotes/{remote_id}")
def update_rclone_remote(
    remote_id: int,
    req: RcloneRemoteUpdate,
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    r = db.query(em.RcloneRemote).filter(em.RcloneRemote.id == remote_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Remote 不存在")
    if req.name is not None:
        name = _validate_name(req.name)
        if name != r.name and db.query(em.RcloneRemote).filter(
                em.RcloneRemote.name == name).first():
            raise HTTPException(status_code=400, detail=f"名称「{name}」已存在")
        r.name = name
    if req.client_id is not None:
        r.client_id = req.client_id.strip()
    if req.client_secret is not None and req.client_secret.strip():
        # 空字符串 = 不修改（前端不回传密钥）
        r.client_secret = req.client_secret.strip()
    if req.team_drive_id is not None:
        r.team_drive = req.team_drive_id.strip()
    if req.is_enabled is not None:
        r.is_enabled = req.is_enabled
    if req.remark is not None:
        r.remark = req.remark
    db.commit()
    db.refresh(r)
    logger.info("更新 rclone remote: %s", r.name)
    return {"success": True, "remote": _serialize_remote(r, db)}


@admin_emby_router.delete("/rclone/remotes/{remote_id}")
def delete_rclone_remote(
    remote_id: int,
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    r = db.query(em.RcloneRemote).filter(em.RcloneRemote.id == remote_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Remote 不存在")
    if r.is_probe_remote:
        raise HTTPException(status_code=400, detail="该 remote 是探测用 remote，请先切换后再删除")
    name = r.name
    db.delete(r)
    db.commit()
    logger.info("删除 rclone remote: %s", name)
    return {"success": True}


# ---------------- 一键生成 rclone.conf ----------------

def _rclone_conf_path() -> str:
    return os.getenv("RCLONE_CONF_PATH", "/config/rclone/rclone.conf")


def _write_conf_to_target(content: str, conf_path: str) -> dict:
    """写入 rclone.conf：本机路径直接写，否则 docker exec 到 rclone 容器"""
    backup = ""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        conf_dir = os.path.dirname(conf_path)
        if conf_dir and os.path.isdir(conf_dir) and os.access(conf_dir, os.W_OK):
            if os.path.exists(conf_path):
                backup = f"{conf_path}.bak.{ts}"
                shutil.copy2(conf_path, backup)
            with open(conf_path, "w") as f:
                f.write(content)
            os.chmod(conf_path, 0o600)
            return {"success": True, "message": f"已写入 {conf_path}", "backup": backup}

        rclone_container = os.getenv("RCLONE_CONTAINER", "aetrix-rclone")
        backup = f"{conf_path}.bak.{ts}"
        subprocess.run(
            ["docker", "exec", rclone_container, "cp", conf_path, backup],
            capture_output=True, timeout=10,
        )
        proc = subprocess.run(
            ["docker", "exec", "-i", rclone_container, "sh", "-c",
             f"cat > {conf_path} && chmod 600 {conf_path}"],
            input=content.encode("utf-8"),
            capture_output=True, timeout=30,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace")[:200]
            logger.error("写入 rclone.conf 失败: %s", err)
            return {"success": False, "message": f"写入失败: {err}", "backup": backup}
        return {"success": True, "message": f"已写入 rclone 容器 {conf_path}", "backup": backup}
    except Exception as e:
        logger.error("写入 rclone.conf 异常: %s", type(e).__name__)
        return {"success": False, "message": "写入异常", "backup": backup}


def _reload_rclone() -> dict:
    rclone_container = os.getenv("RCLONE_CONTAINER", "aetrix-rclone")
    try:
        proc = subprocess.run(
            ["docker", "restart", rclone_container],
            capture_output=True, timeout=60,
        )
        if proc.returncode == 0:
            return {"success": True, "message": "rclone 容器已重启，配置生效"}
        err = proc.stderr.decode("utf-8", errors="replace")[:200]
        return {"success": False, "message": f"重启失败: {err}"}
    except Exception:
        return {"success": False, "message": "重启异常"}


@admin_emby_router.post("/rclone/remotes/generate-conf")
def generate_and_apply_conf(
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    content = rclone_manager.generate_rclone_conf(db)
    if not content.strip():
        raise HTTPException(status_code=400, detail="没有启用的 remote，无法生成配置")

    conf_path = _rclone_conf_path()
    write_result = _write_conf_to_target(content, conf_path)
    if not write_result["success"]:
        raise HTTPException(status_code=500, detail=write_result["message"])

    reload_result = _reload_rclone()
    logger.info("rclone.conf 已重新生成（%d 字符）", len(content))
    return {
        "success": True,
        "message": write_result["message"],
        "backup": write_result.get("backup", ""),
        "reload": reload_result,
    }


@admin_emby_router.get("/rclone/remotes/conf-preview")
def preview_rclone_conf(
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    content = rclone_manager.generate_rclone_conf(db)

    def _redact(m):
        key, val = m.group(1), m.group(2)
        return f"{key} = {val[:4]}****" if len(val) > 8 else f"{key} = ****"

    preview = re.sub(r'^(token|client_secret)\s*=\s*(.+)$', _redact,
                     content, flags=re.MULTILINE)
    return {"preview": preview}


# ---------------- 探测用 remote ----------------

@admin_emby_router.post("/rclone/remotes/{remote_id}/set-probe")
def set_probe_remote_api(
    remote_id: int,
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    r = db.query(em.RcloneRemote).filter(em.RcloneRemote.id == remote_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Remote 不存在")
    if not r.is_enabled:
        raise HTTPException(status_code=400, detail="请先启用该 remote")
    if not rclone_manager.set_probe_remote(db, remote_id):
        raise HTTPException(status_code=500, detail="设置失败")
    return {"success": True, "probe_remote": r.name}


@admin_emby_router.get("/rclone/probe-remote")
def get_probe_remote_api(
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return {"probe_remote": rclone_manager.get_probe_remote(db)}


# ---------------- OAuth（个人盘） ----------------

GOOGLE_OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_SCOPE = "https://www.googleapis.com/auth/drive"


def _panel_base_url(request: Request) -> str:
    base_url = os.getenv("PANEL_BASE_URL", "").strip()
    if not base_url:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        base_url = f"{scheme}://{host}" if host else ""
    return base_url.rstrip("/")


@admin_emby_router.get("/rclone/remotes/{remote_id}/oauth-url")
def get_oauth_url(
    remote_id: int,
    request: Request,
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    r = db.query(em.RcloneRemote).filter(em.RcloneRemote.id == remote_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Remote 不存在")
    if not (r.client_id or "").strip():
        raise HTTPException(status_code=400, detail="请先填写 Client ID")

    base_url = _panel_base_url(request)
    if not base_url:
        raise HTTPException(status_code=400, detail="无法确定回调地址，请配置 PANEL_BASE_URL")
    redirect_uri = f"{base_url}/admin/rclone/oauth-callback"

    params = {
        "client_id": r.client_id.strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    url = GOOGLE_OAUTH_URL + "?" + urllib.parse.urlencode(params)
    return {"oauth_url": url, "redirect_uri": redirect_uri}


@admin_emby_router.post("/rclone/remotes/{remote_id}/oauth-callback")
def oauth_callback(
    remote_id: int,
    req: OAuthCallbackRequest,
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    r = db.query(em.RcloneRemote).filter(em.RcloneRemote.id == remote_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Remote 不存在")
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="缺少授权码")
    if not (r.client_id or "").strip() or not (r.client_secret or "").strip():
        raise HTTPException(status_code=400, detail="请先填写 Client ID 和 Client Secret")
    if not req.redirect_uri.strip():
        raise HTTPException(status_code=400, detail="缺少 redirect_uri")

    try:
        resp = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": req.code.strip(),
                "client_id": r.client_id.strip(),
                "client_secret": r.client_secret.strip(),
                "redirect_uri": req.redirect_uri.strip(),
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
    except Exception:
        logger.error("OAuth token 请求异常")
        raise HTTPException(status_code=502, detail="连接 Google 失败")

    if resp.status_code != 200:
        logger.warning("OAuth 换 token 失败: HTTP %s", resp.status_code)
        raise HTTPException(status_code=400, detail="授权码无效或已过期，请重新授权")

    data = resp.json()
    token_data = {
        "access_token": data.get("access_token", ""),
        "token_type": data.get("token_type", "Bearer"),
        "refresh_token": data.get("refresh_token", ""),
    }
    if data.get("expires_in"):
        expiry = datetime.now(timezone.utc) + timedelta(seconds=int(data["expires_in"]))
        token_data["expiry"] = expiry.isoformat()
    elif data.get("expiry"):
        token_data["expiry"] = data["expiry"]

    r.token_json = json.dumps(token_data)
    db.commit()
    logger.info("rclone remote %s OAuth 授权成功", r.name)
    return {"success": True, "has_token": True}


# ---------------- 服务账号上传 ----------------

SA_DIR = "/sa-accounts"


@admin_emby_router.post("/rclone/remotes/{remote_id}/upload-sa")
def upload_service_account(
    remote_id: int,
    file: UploadFile = File(...),
    staff: models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    r = db.query(em.RcloneRemote).filter(em.RcloneRemote.id == remote_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Remote 不存在")

    content = file.file.read()
    if len(content) > 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件太大（最大 1MB）")
    try:
        sa_data = json.loads(content.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="不是有效的 JSON 文件")
    if sa_data.get("type") != "service_account":
        raise HTTPException(status_code=400, detail="不是服务账号 JSON 文件")

    client_email = sa_data.get("client_email", "")
    project_id = sa_data.get("project_id", "")
    filename = f"{r.name}.json"
    sa_path = os.path.join(SA_DIR, filename)
    try:
        os.makedirs(SA_DIR, exist_ok=True)
        with open(sa_path, "w") as f:
            f.write(content.decode("utf-8"))
        os.chmod(sa_path, 0o600)
    except Exception:
        logger.error("写入服务账号文件失败")
        raise HTTPException(status_code=500, detail="写入服务账号文件失败")

    sa_file = None
    if r.sa_file_id:
        sa_file = db.query(em.ServiceAccountFile).filter(
            em.ServiceAccountFile.id == r.sa_file_id).first()
    if not sa_file:
        sa_file = em.ServiceAccountFile(filename=filename, stored_path=sa_path)
        db.add(sa_file)
        db.flush()
    sa_file.filename = filename
    sa_file.stored_path = sa_path
    sa_file.client_email = client_email
    sa_file.project_id = project_id
    r.sa_file_id = sa_file.id
    db.commit()

    logger.info("rclone remote %s 已上传服务账号", r.name)
    return {
        "success": True,
        "filename": filename,
        "client_email": client_email,
        "project_id": project_id,
    }
