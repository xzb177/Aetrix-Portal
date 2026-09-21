"""挂载体检：把「每条挂载在哪台机器上真的能用」变成可查询的事实

## 为什么需要它

同一条 ``StorageMount`` 会被**两个进程各自解析**：

- **EM（面板）**：扫描、目录浏览、后台「测试连接」
- **EA（网关）**：播放出流（``mount_routes`` → 代理 / 读本机文件）

而挂载里有些配置是**主机相对**的：``local`` / ``strm`` 的路径、``rclone`` 的 RC 地址
（默认 ``127.0.0.1:5572`` 指的是各自容器自己）与 rclone 可执行文件。于是 EM/EA 分开
部署时，「后台测试通过」并**不代表 EA 能播**——不一致只在之后以扫描 ``failed_roots``
或播放 502/404 的形式暴露，排查很绕。

本模块提供两件事：

1. ``probe_mounts`` / ``mounts_health``：**在当前进程里**逐条体检（EM 与 EA 共用同一份逻辑，
   复用 ``mounts.test_mount``，所以结论和「测试连接」按钮完全一致）；
2. ``panel_router``：EA 上的受鉴权端点 ``GET /api/admin/mounts/health``，让 EM 能拿到
   **以 EA 视角**的结果并存进 ``SystemConfig``（键见 ``EA_HEALTH_KEY``），
   供「存储挂载」页展示「EM 可达 / EA 可达」两个徽标。

鉴权用两端本来就共享的 ``SECRET_KEY``：EA 校验请求头 ``X-Panel-Key``，缺失或不一致一律 401
（密钥没配置时也拒绝，绝不能因为漏配而变成公开端点）。
"""
from __future__ import annotations

import hmac
import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend import models
from backend.database import get_db
from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib

logger = logging.getLogger(__name__)

# EM 保存 / 手动刷新时，把 EA 视角的体检结果存进这条 SystemConfig（JSON）
EA_HEALTH_KEY = "emby_managed_mounts_health"
# EM → EA 的证明：请求头里带共享密钥
PANEL_KEY_HEADER = "X-Panel-Key"

PLAYBACK_NODE_EA = "ea"
PLAYBACK_NODE_EXTERNAL = "external"
PLAYBACK_NODE_PANEL = "panel"

# EM 向 EA 拉体检的超时：每条挂载最多 MOUNT_TIMEOUT（默认 20s），这里给足余量
EA_FETCH_TIMEOUT = float(os.getenv("MOUNT_HEALTH_FETCH_TIMEOUT", "60"))


# ==================== 面板密钥 ====================

def panel_key() -> str:
    return (os.getenv("SECRET_KEY") or "").strip()


def panel_key_ok(request: Request) -> bool:
    """请求头里的密钥是否等于本机的 SECRET_KEY（常量时间比较）"""
    expected = panel_key()
    provided = (request.headers.get(PANEL_KEY_HEADER) or "").strip()
    return bool(expected) and bool(provided) and hmac.compare_digest(expected, provided)


def require_panel_key(request: Request) -> None:
    if not panel_key_ok(request):
        raise HTTPException(
            status_code=401,
            detail=f"缺少或错误的 {PANEL_KEY_HEADER}（应为 EM 的 SECRET_KEY）",
        )


# ==================== 体检（EM / EA 共用）====================

def _config_value(db: Session, key: str, default: str = "") -> str:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return (row.value if row and row.value is not None else default).strip()


def playback_node(db: Session) -> str:
    """当前真正出流的是谁：EA（分离部署）/ 外部 Emby / 面板自己（一体化）"""
    mode = _config_value(db, "emby_active_mode", "")
    if mode == "managed_ea" and _config_value(db, "emby_managed_enabled", "false").lower() == "true":
        return PLAYBACK_NODE_EA
    if mode == "external" and _config_value(db, "emby_external_enabled", "false").lower() == "true":
        return PLAYBACK_NODE_EXTERNAL
    return PLAYBACK_NODE_PANEL


def _mount_library_map(db: Session) -> dict[int, list[int]]:
    """挂载 id → 引用它的媒体库 id 列表（用于「被库引用却不可用」的告警）"""
    usage: dict[int, list[int]] = {}
    for lib in db.query(em.Library).all():
        for mount_id in mount_lib.parse_mount_ids(lib):
            usage.setdefault(mount_id, []).append(lib.id)
    return usage


def redact(message: str, mount) -> str:
    """把告警文案里的密钥值洗掉

    探测失败时很多实现会把异常原样拼进 ``message``（如 ``连接失败: <exc>``），而异常
    里可能带着配置中的凭据。体检结果会被 EM 拉走并在后台展示，所以这里按挂载类型元
    数据里的 ``secret`` 字段收集明文，凡是出现在文案里的一律换成 ``***``。
    """
    text = message or ""
    try:
        config = mount_lib.parse_config(mount)
    except Exception:  # noqa: BLE001 — 配置坏了就退化为只做长度截断
        config = {}
    secret_keys = mount_lib.secret_config_keys()
    for key, value in (config or {}).items():
        if key in secret_keys and isinstance(value, str) and len(value) >= 4 and value in text:
            text = text.replace(value, "***")
    return text[:300]


def probe_one_mount(db: Session, mount, usage: Optional[dict[int, list[int]]] = None) -> dict:
    """单条挂载体检：跑一次与「测试连接」相同的探测（resolve / 目录可读）"""
    meta = mount_lib.MOUNT_TYPE_MAP.get(mount.mount_type, {})
    kind = meta.get("kind", "local")
    path = (mount.path or "").strip()

    item: dict = {
        "id": mount.id,
        "name": mount.name,
        "mount_type": mount.mount_type,
        "mount_type_label": mount_lib.MOUNT_TYPE_LABELS.get(mount.mount_type, mount.mount_type),
        "kind": kind,
        "path": path,
        "is_enabled": bool(mount.is_enabled),
        # local / strm 的路径是本机相对资源，单独报出来（远程类型为 None）
        "path_exists": os.path.isdir(path) if kind == "local" and path else None,
        "library_ids": (usage if usage is not None else _mount_library_map(db)).get(mount.id, []),
    }
    item["used_by_library"] = bool(item["library_ids"])

    if not mount.is_enabled:
        item.update({"ok": None, "message": "已停用（未体检）", "skipped": True})
        return item

    result = mount_lib.test_mount(mount, db)
    item.update({
        "ok": bool(result.get("ok")),
        "message": redact(str(result.get("message") or ""), mount),
        "auth_error": bool(result.get("auth_error")),
    })
    return item


def probe_mounts(db: Session, include_disabled: bool = True) -> list[dict]:
    """逐条体检（停用的挂载标记 skipped，不发请求）"""
    usage = _mount_library_map(db)
    mounts = db.query(em.StorageMount).order_by(em.StorageMount.id).all()
    if not include_disabled:
        mounts = [m for m in mounts if m.is_enabled]
    return [probe_one_mount(db, m, usage) for m in mounts]


def mounts_health(db: Session, service: str) -> dict:
    """体检汇总：[挂载] + 统计 + 当前播放节点"""
    mounts = probe_mounts(db)
    probed = [m for m in mounts if m.get("ok") is not None]
    failed = [m for m in probed if not m["ok"]]
    node = playback_node(db)
    return {
        "service": service,
        "checked_at": datetime.now().isoformat(),
        "mounts": mounts,
        "total": len(mounts),
        "probed": len(probed),
        "ok_count": len(probed) - len(failed),
        "failed_count": len(failed),
        # 面板最需要知道的两件事：谁在出流、哪些挂载过不去
        "playback_node": node,
        "unreachable": [
            m["id"] for m in failed if node == PLAYBACK_NODE_EA and m["used_by_library"]
        ],
    }


# ==================== EA 侧：受鉴权端点 ====================

panel_router = APIRouter(prefix="/api/admin/mounts", tags=["挂载体检"])


@panel_router.get("/health", dependencies=[Depends(require_panel_key)])
async def mounts_health_endpoint(db: Session = Depends(get_db)):
    """EA 视角的挂载体检（EM 保存服务入口 / 手动刷新时调用）

    鉴权走 ``X-Panel-Key``（= 共享的 SECRET_KEY），不是管理员 JWT：
    EA 上不存在后台会话，而这条端点只该由 EM 调用。
    """
    return await run_in_threadpool(mounts_health, db, "ea")


# ==================== EM 侧：拉取与落库 ====================

async def fetch_ea_health(base_url: str, timeout: float = EA_FETCH_TIMEOUT) -> dict:
    """以 EM 的身份向 EA 拉一次挂载体检

    任何失败都返回 ``{ok: False, error}``，不抛异常：保存服务入口不应该因为
    EA 暂时不可达而整个失败（探测结果本身已经另外报告了）。
    """
    import httpx

    url = f"{(base_url or '').rstrip('/')}/api/admin/mounts/health"
    key = panel_key()
    if not key:
        return {"ok": False, "error": "EM 未配置 SECRET_KEY，无法向 EA 证明身份"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={PANEL_KEY_HEADER: key})
    except Exception as exc:  # noqa: BLE001 — 网络问题只报告，不影响保存
        return {"ok": False, "error": f"无法连接 EA: {exc}"}

    if resp.status_code == 401:
        return {"ok": False, "error": "EA 拒绝了面板密钥（两端 SECRET_KEY 必须一致）"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"EA 返回 HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "error": "EA 返回的不是 JSON（地址可能指向别的服务）"}
    if data.get("service") != "ea":
        return {"ok": False, "error": "该地址不是 EA（缺少 service=ea 标识）"}
    return {"ok": True, "data": data}


def write_ea_health(db: Session, payload: dict) -> None:
    """把拉取结果存进 SystemConfig（EM 侧，供挂载页展示）"""
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == EA_HEALTH_KEY).first()
    text = json.dumps(payload, ensure_ascii=False)
    if row:
        row.value = text
    else:
        db.add(models.SystemConfig(key=EA_HEALTH_KEY, value=text,
                                   description="EA 视角的挂载体检结果"))


def read_ea_health(db: Session) -> dict:
    """读回 EA 体检快照；没有记录时返回空结构（不是错误）"""
    raw = _config_value(db, EA_HEALTH_KEY)
    if not raw:
        return {"ok": False, "checked_at": None, "error": "", "mounts": []}
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("EA 挂载体检快照无法解析，已忽略")
        return {"ok": False, "checked_at": None, "error": "快照无法解析", "mounts": []}
    if not isinstance(data, dict):
        return {"ok": False, "checked_at": None, "error": "快照格式不对", "mounts": []}
    data.setdefault("mounts", [])
    return data


def ea_mount_map(db: Session) -> dict[int, dict]:
    """EA 体检快照按挂载 id 索引，供挂载列表逐条附加 ``ea_reachable``"""
    snapshot = read_ea_health(db)
    out: dict[int, dict] = {}
    for item in snapshot.get("mounts") or []:
        if not isinstance(item, dict):
            continue
        try:
            mount_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        out[mount_id] = item
    return out


__all__ = [
    "EA_HEALTH_KEY",
    "PANEL_KEY_HEADER",
    "PLAYBACK_NODE_EA",
    "PLAYBACK_NODE_EXTERNAL",
    "PLAYBACK_NODE_PANEL",
    "ea_mount_map",
    "fetch_ea_health",
    "mounts_health",
    "panel_key_ok",
    "panel_router",
    "playback_node",
    "probe_mounts",
    "probe_one_mount",
    "redact",
    "read_ea_health",
    "require_panel_key",
    "write_ea_health",
]
