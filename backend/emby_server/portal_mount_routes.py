"""管理后台 · 存储挂载端点（从 portal.py 拆出）

挂载 = 媒体库的内容来源：local / strm 是本机目录，115 / webdav / alist / s3 / aliyun /
quark / onedrive 是远程来源（远程挂载的条目入库为 mount://<id>/<rel>，播放时由 EA 按
Range 代理转发，凭据不下发）。

类型、配置字段、必填与脱敏规则都来自类型元数据：backend/emby_server/mounts.py（基础类型）
与 backend/emby_server/mount_cloud.py（云端类型）。

拆分约定：路由仍挂在 portal.py 定义的 ``admin_emby_router`` 上（导入即注册），
调用方（backend/main.py）在 ``include_router`` 之前导入本模块；
``require_staff`` 等共享依赖从 portal 导入，本模块不被 portal 反向引用（无循环导入）。
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend import models, realms
from backend.database import get_db
from backend.emby_server import models as em
from backend.emby_server import mount_health
from backend.emby_server import mount_rclone
from backend.emby_server import mounts as mount_lib
from backend.emby_server.portal import admin_emby_router, require_staff


def _mask_mount_config(config: dict) -> tuple[dict, list[str]]:
    """脱敏：密钥类字段只报是否已配置，不回明文

    密钥集合由挂载类型元数据算出（见 ``mounts.secret_config_keys``），所以新增
    挂载类型时把字段标成 ``secret`` 就够了，不用动这里。
    """
    secret_keys = mount_lib.secret_config_keys()
    public: dict = {}
    secrets: list[str] = []
    for key, value in (config or {}).items():
        if key in secret_keys and value:
            secrets.append(key)
            continue
        public[key] = value
    return public, secrets


def _merge_mount_config(old: dict, new: dict) -> dict:
    """合并配置：密钥类字段留空 = 不修改（避免前端拿不到明文就被抹掉）"""
    secret_keys = mount_lib.secret_config_keys()
    merged = dict(old or {})
    for key, value in (new or {}).items():
        if key in secret_keys and value in ("", None):
            continue
        merged[key] = value
    return merged


def _validate_mount_fields(mount_type: str, path: str, config: dict) -> None:
    """按类型元数据校验：本机路径 + 必填字段 + 地址格式

    必填字段来自 ``MOUNT_TYPES[*].fields[*].required``，所以新类型的校验也是自动的。
    """
    meta = mount_lib.MOUNT_TYPE_MAP.get(mount_type)
    if meta is None:
        raise HTTPException(status_code=400, detail=f"不支持的挂载类型: {mount_type or '(空)'}")
    if meta["needs_path"]:
        if not (path or "").strip():
            raise HTTPException(status_code=400, detail="请填写目录路径")
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"目录不存在: {path}")
    for field in mount_lib.required_fields(mount_type):
        if not str(config.get(field["key"]) or "").strip():
            raise HTTPException(status_code=400, detail=f"请填写{field.get('label') or field['key']}")
    for field in mount_lib.type_meta(mount_type).get("fields", []):
        if field["key"] not in ("url", "endpoint"):
            continue
        value = str(config.get(field["key"]) or "").strip()
        if value and not value.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail=f"{field.get('label') or field['key']} 必须以 http:// 或 https:// 开头")


def _fix_rclone_root(mount_type: str, config: dict) -> None:
    """rclone 的 remote 名必须带冒号（漏了会被 rclone 当成本机目录）

    只在**首段没有冒号**时介入，正常写法（``gdrive:Movies``）不受影响：

    - 首段就是远端已配置的 remote → 直接补上冒号（``paul_emby/电影`` → ``paul_emby:电影``）；
    - 查得到 remote 列表却没有这个名字 → 400，给出正确写法与可用的 remote；
    - 查不到（EM 这台机器没 rclone / RC 连不上）→ 按文本规则兜底。

    不拦明确的本地写法（``/media``、``./media``）：rclone 本来就支持本机路径，
    只是本机目录应该用「本地 / 已挂载目录」类型，提示里也这么写。
    """
    if mount_type != mount_rclone.MOUNT_RCLONE:
        return
    fs = str(config.get("fs") or config.get("remote") or "").strip()
    if not fs or mount_rclone.fs_remote_name(fs) or mount_rclone.looks_like_local_path(fs):
        return
    remotes: list[str] | None = None
    try:
        remotes = mount_rclone.list_remotes(
            str(config.get("rc_url") or ""), username=str(config.get("rc_user") or ""),
            password=config.get("rc_pass") or "",
            bin_path=str(config.get("rclone_bin") or ""),
            config=str(config.get("rclone_config") or ""),
            mode=str(config.get("mode") or mount_rclone.MODE_RC),
        )
    except mount_lib.MountError:
        remotes = None  # EM 侧查不到不影响保存：退回文本规则
    fixed = mount_rclone.normalize_fs(fs, remotes)
    if fixed != fs:
        config["fs"] = fixed
        return
    hint = mount_rclone.fs_missing_colon_hint(fs, remotes)
    if hint:
        raise HTTPException(status_code=400, detail=hint)


def _serialize_mount(db: Session, mount: em.StorageMount, ea_map: dict | None = None) -> dict:
    config, secrets = _mask_mount_config(mount_lib.parse_config(mount))
    meta = mount_lib.MOUNT_TYPE_MAP.get(mount.mount_type, {})
    kind = meta.get("kind", "local")
    path = (mount.path or "").strip()
    # EM 视角 = 后台「测试连接」的结果（跑在 EM 进程里）
    em_result = {
        "ok": mount.last_check_ok,
        "message": mount.last_check_message or "",
        "checked_at": mount.last_checked_at.isoformat() if mount.last_checked_at else None,
    }
    # EA 视角 = 保存 EA 服务入口 / 手动刷新时拉到的那份快照
    if ea_map is None:
        ea_map = mount_health.ea_mount_map(db)
    ea_item = ea_map.get(mount.id) or {}
    return {
        "id": mount.id,
        "name": mount.name,
        "realm_id": mount.realm_id,
        "mount_type": mount.mount_type,
        "mount_type_label": mount_lib.MOUNT_TYPE_LABELS.get(mount.mount_type, mount.mount_type),
        "kind": kind,
        "path": path,
        "config": config,
        "secret_keys": secrets,
        "is_enabled": bool(mount.is_enabled),
        "remark": mount.remark or "",
        "last_checked_at": mount.last_checked_at.isoformat() if mount.last_checked_at else None,
        "last_check_ok": mount.last_check_ok,
        "last_check_message": mount.last_check_message,
        # local / strm 的路径是本机相对资源（远程类型为 None）
        "path_exists": os.path.isdir(path) if kind == "local" and path else None,
        # 两个播放节点各自能不能用它（EA 缺失快照时为 None，表示「未体检」）
        "em_reachable": em_result["ok"],
        "em_message": em_result["message"],
        "em_checked_at": em_result["checked_at"],
        "ea_reachable": ea_item.get("ok"),
        "ea_message": ea_item.get("message") or "",
        "library_ids": [
            lib.id for lib in db.query(em.Library).all()
            if mount.id in mount_lib.parse_mount_ids(lib)
        ],
    }


class MountCreate(BaseModel):
    name: str
    mount_type: str
    path: str = ""
    config: dict = {}
    is_enabled: bool = True
    remark: str = ""
    # 归属哪个服（留空 = 当前服）：存储是主机相对资源，跟着服走
    realm_id: int | None = None


class MountUpdate(BaseModel):
    name: str | None = None
    path: str | None = None
    config: dict | None = None
    is_enabled: bool | None = None
    remark: str | None = None
    realm_id: int | None = None


class MountTestRequest(BaseModel):
    """测试尚未保存的配置（先测再存）"""
    mount_type: str
    path: str = ""
    config: dict = {}


class MountBrowseParams(BaseModel):
    rel: str = "/"


@admin_emby_router.get("/mounts")
def list_mounts(staff: models.WebUser = Depends(require_staff), db: Session = Depends(get_db),
                     realm_id: int | None = None):
    """存储挂载清单（按服；realm_id=0 表示全部服）"""
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope_inclusive(db.query(em.StorageMount), em.StorageMount.realm_id, scope_id)
    mounts = query.order_by(em.StorageMount.id).all()
    ea_map = mount_health.ea_mount_map(db, scope_id)
    snapshot = mount_health.read_ea_health(db, scope_id)
    realm_names = {r.id: r.name for r in realms.list_realms(db)}
    return {
        "mounts": [_serialize_mount(db, m, ea_map) for m in mounts],
        # 类型元数据（标签 / 说明 / 需要哪些字段）由后端下发，前端不再自己维护一份
        "mount_types": [dict(t) for t in mount_lib.MOUNT_TYPES],
        # 当前谁在出流：EA 分离部署 / 外部 Emby / 面板自己。
        # 「被媒体库引用却 EA 不可达」只有 EA 才是阻断性问题，前端据此决定要不要报红。
        "playback_node": mount_health.playback_node(db, scope_id),
        "realm_id": scope_id,
        "realm_names": realm_names,
        "ea_health": {
            "ok": bool(snapshot.get("ok")),
            "checked_at": snapshot.get("checked_at"),
            "error": snapshot.get("error") or "",
        },
    }


@admin_emby_router.post("/mounts/health")
async def check_all_mounts(staff: models.WebUser = Depends(require_staff),
                          db: Session = Depends(get_db)):
    """一键体检（EM 视角）：逐条跑与「测试连接」相同的探测并落库

    只解决「这台面板自己能不能碰到存储」；EA 那一侧要看 ``/mounts`` 响应里的
    ``ea_reachable``（由 EA 服务入口拉取）。"""
    health = await run_in_threadpool(mount_health.mounts_health, db, "panel",
                                     realms.active_realm_id(db))
    checked_at = datetime.now()
    for item in health.get("mounts", []):
        if item.get("ok") is None:
            continue  # 停用的挂载不写测试结果
        mount = db.query(em.StorageMount).filter(em.StorageMount.id == item["id"]).first()
        if not mount:
            continue
        mount.last_checked_at = checked_at
        mount.last_check_ok = bool(item.get("ok"))
        mount.last_check_message = str(item.get("message") or "")[:300]
    db.commit()
    return health


@admin_emby_router.get("/mounts/rclone/remotes")
async def list_rclone_remotes(mode: str = "rc", rc_url: str = "", rc_user: str = "",
                              rc_pass: str = "", rclone_bin: str = "",
                              rclone_config: str = "",
                              staff: models.WebUser = Depends(require_staff)):
    """列出 rclone 已配置的 remote（给 rclone 挂载的「remote」选择器用）

    即使用表单里还没保存的 RC 地址 / 密码也能查，方便先连上再看有哪些 remote。
    """
    try:
        remotes = await run_in_threadpool(
            mount_rclone.list_remotes, rc_url,
            username=rc_user, password=rc_pass,
            bin_path=rclone_bin, config=rclone_config, mode=mode,
        )
    except mount_lib.MountAuthError as exc:
        # 这是「RC 地址/账号密码不对」，属于挂载表单的填写错误，不是后台会话过期。
        # 回 401 会让前端 401 拦截器整页重载，用户刚填的表单全丢，所以这里回 400。
        raise HTTPException(status_code=400, detail=str(exc))
    except mount_lib.MountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"remotes": remotes, "total": len(remotes)}


@admin_emby_router.post("/mounts")
def create_mount(req: MountCreate, staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写挂载名称")
    if db.query(em.StorageMount).filter(em.StorageMount.name == name).first():
        raise HTTPException(status_code=400, detail=f"挂载名称已存在: {name}")
    config = _merge_mount_config({}, req.config)
    _validate_mount_fields(req.mount_type, req.path, config)
    _fix_rclone_root(req.mount_type, config)
    realm_id = req.realm_id or realms.active_realm_id(db)
    if not realms.get_realm(db, realm_id):
        raise HTTPException(status_code=400, detail=f"服不存在: #{realm_id}")
    mount = em.StorageMount(
        name=name, mount_type=req.mount_type, path=(req.path or "").strip(),
        config=mount_lib.dump_config(config), is_enabled=req.is_enabled,
        remark=(req.remark or "")[:300], realm_id=realm_id,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)
    return {"success": True, "mount": _serialize_mount(db, mount)}


@admin_emby_router.put("/mounts/{mount_id}")
def update_mount(mount_id: int, req: MountUpdate,
                       staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写挂载名称")
        exists = db.query(em.StorageMount).filter(
            em.StorageMount.name == name, em.StorageMount.id != mount_id,
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail=f"挂载名称已存在: {name}")
        mount.name = name
    config = _merge_mount_config(mount_lib.parse_config(mount), req.config or {})
    path = (req.path if req.path is not None else mount.path or "").strip()
    # 换类型不允许（条目路径按挂载 id + 类型解析），只允许改配置与路径
    _validate_mount_fields(mount.mount_type, path, config)
    _fix_rclone_root(mount.mount_type, config)
    mount.path = path
    mount.config = mount_lib.dump_config(config)
    if req.is_enabled is not None:
        mount.is_enabled = req.is_enabled
    if req.remark is not None:
        mount.remark = req.remark[:300]
    if "realm_id" in req.model_fields_set and req.realm_id is not None:
        if not realms.get_realm(db, req.realm_id):
            raise HTTPException(status_code=400, detail=f"服不存在: #{req.realm_id}")
        mount.realm_id = req.realm_id
        # 引用本挂载的媒体库跟着走，否则库会跨服引用存储
        for lib in db.query(em.Library).filter(
                em.Library.mount_ids.ilike(f"%{mount.id}%")).all():
            if str(mount.id) in [x.strip() for x in (lib.mount_ids or "").split(",") if x.strip()]:
                lib.realm_id = req.realm_id
    db.commit()
    db.refresh(mount)
    # 路径/配置变更后需要重新扫描才生效（扫描任务使用固定配置快照）
    return {"success": True, "mount": _serialize_mount(db, mount), "rescan_required": True}


@admin_emby_router.delete("/mounts/{mount_id}")
def delete_mount(mount_id: int, staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    # 解除媒体库绑定，不留悬空引用（条目会在下一次扫描时清理）
    unbound = 0
    for lib in db.query(em.Library).all():
        ids = mount_lib.parse_mount_ids(lib)
        if mount_id in ids:
            lib.mount_ids = ",".join(str(i) for i in ids if i != mount_id)
            unbound += 1
    db.delete(mount)
    db.commit()
    return {"success": True, "unbound_libraries": unbound}


@admin_emby_router.post("/mounts/{mount_id}/test")
async def test_saved_mount(mount_id: int, staff: models.WebUser = Depends(require_staff),
                           db: Session = Depends(get_db)):
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    result = await run_in_threadpool(mount_lib.test_mount, mount, db)
    # 测试结果只作展示，不影响扫描（扫描自己会报错）
    mount.last_checked_at = datetime.now()
    mount.last_check_ok = bool(result.get("ok"))
    mount.last_check_message = str(result.get("message") or "")[:300]
    db.commit()
    db.refresh(mount)
    return {"success": bool(result.get("ok")), "result": result,
            "mount": _serialize_mount(db, mount)}


@admin_emby_router.post("/mounts/test")
async def test_unsaved_mount(req: MountTestRequest,
                             staff: models.WebUser = Depends(require_staff)):
    """测试表单里还没保存的配置（Cookie / 令牌不用先存再测）"""
    probe = em.StorageMount(
        name="(未保存)", mount_type=req.mount_type, path=(req.path or "").strip(),
        config=mount_lib.dump_config(_merge_mount_config({}, req.config)), is_enabled=True,
    )
    result = await run_in_threadpool(mount_lib.test_mount, probe, None)
    return {"success": bool(result.get("ok")), "result": result}


@admin_emby_router.get("/mounts/{mount_id}/browse")
async def browse_mount(mount_id: int, rel: str = "/",
                       staff: models.WebUser = Depends(require_staff),
                       db: Session = Depends(get_db)):
    """浏览挂载目录（给「目标目录 / 目录 ID」选择器用）"""
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if not mount:
        raise HTTPException(status_code=404, detail="挂载不存在")
    try:
        provider = mount_lib.build_provider(mount, db)
        entries = await run_in_threadpool(provider.list_dir, rel)
    except mount_lib.MountAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except mount_lib.MountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "rel": rel or "/",
        "entries": [
            {"name": e.name, "rel": e.rel, "is_dir": e.is_dir, "size": e.size,
             "entry_id": e.entry_id}
            for e in entries
        ],
        "total": len(entries),
    }
