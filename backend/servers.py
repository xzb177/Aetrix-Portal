"""服务器清单：面板可以添加多台服务器，并按类型各自挑一台「当前使用」

以前面板**只能填一台** EA 地址和一台外部 Emby 地址（两个 `SystemConfig` 键），
而且除了 Emby，别的服务（MoviePilot、qBittorrent）根本没有入口——所以「求片」
批了之后没有任何办法真的把片子弄进来。

这份模块提供：

1. **类型元数据**（``SERVER_KINDS``）：字段、是否密钥、需要哪些凭据，前端不再自己维护一份；
2. **连接体检**（``probe_server``）：每类都真的发一次请求，而不是只看端口通不通；
3. **激活时的旧配置同步**（``activate`` / ``sync_legacy``）：EA / Emby 被设为「当前使用」时，
   写回 ``emby_active_mode``、``emby_managed_*``、``emby_external_*`` 等既有键，
   于是网关闸门、挂载体检、客户端指引、用户端账号卡**全部照旧生效**，不需要改它们；
4. **按类型取当前可用配置**（``active_config``）：给求片推送这类功能用。

密钥类字段一律不出接口（见 ``mask_config``），错误文案里的凭据也会被洗掉（``redact``）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from sqlalchemy import and_, or_

from backend import models
from backend import moviepilot, qbittorrent, realms

logger = logging.getLogger(__name__)

# 类型顺序即前端展示顺序：先「出流的服务器」，再「内容自动化」
SERVER_KINDS: list[dict] = [
    {
        "value": "ea",
        "label": "后端服（EA）",
        "short": "后端服",
        "desc": "本项目自带的 Emby API（分离部署）。必须与面板共用数据库与 SECRET_KEY。",
        "group": "播放",
        "activatable": True,
        "writes_active_mode": "managed_ea",
        "fields": [],
    },
    {
        "value": "emby",
        "label": "已有 Emby 服",
        "short": "Emby 服",
        "desc": "你自己已经部署好的 Emby / Jellyfin。接入后本项目的自建媒体库功能会停用。",
        "group": "播放",
        "activatable": True,
        "writes_active_mode": "external",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password", "secret": True,
             "placeholder": "从 Emby 控制台生成，可不填"},
        ],
    },
    {
        "value": "moviepilot",
        "label": "MoviePilot",
        "short": "MoviePilot",
        "desc": "自动搜索下载与整理入库。求片批准后可一键提交成它的订阅。",
        "group": "内容自动化",
        "activatable": False,
        "fields": [
            {"key": "api_key", "label": "API 密钥（API_TOKEN）", "type": "password", "secret": True,
             "placeholder": "MoviePilot「设定 → 系统」里的 API_TOKEN，用来查订阅"},
            {"key": "username", "label": "用户名", "type": "text", "placeholder": "MoviePilot 登录用户名（提交订阅必需）"},
            {"key": "password", "label": "密码", "type": "password", "secret": True,
             "placeholder": "MoviePilot 登录密码（提交订阅必需）"},
            {"key": "save_path", "label": "订阅保存路径", "type": "text",
             "placeholder": "可选，如 /media/movies"},
        ],
    },
    {
        "value": "qbittorrent",
        "label": "qBittorrent",
        "short": "qB 下载器",
        "desc": "下载器。拿到磁力 / 种子链接后可以直接交给它下载。",
        "group": "内容自动化",
        "activatable": False,
        "fields": [
            {"key": "username", "label": "用户名", "type": "text", "placeholder": "qB Web UI 用户名"},
            {"key": "password", "label": "密码", "type": "password", "secret": True,
             "placeholder": "qB Web UI 密码"},
            {"key": "savepath", "label": "默认保存目录", "type": "text",
             "placeholder": "可选，如 /downloads"},
            {"key": "category", "label": "默认分类", "type": "text", "placeholder": "可选"},
        ],
    },
]

KIND_MAP: dict[str, dict] = {k["value"]: k for k in SERVER_KINDS}
KINDS: tuple[str, ...] = tuple(k["value"] for k in SERVER_KINDS)
# 能接收求片推送的类型（前端据此决定显示哪些按钮）
PUSH_TARGETS: tuple[str, ...] = ("moviepilot", "qbittorrent")


def kind_meta(kind: str) -> dict:
    return KIND_MAP.get((kind or "").strip().lower(), {})


def kind_label(kind: str) -> str:
    return kind_meta(kind).get("label") or kind


def secret_keys(kind: str) -> set[str]:
    return {f["key"] for f in kind_meta(kind).get("fields", []) if f.get("secret")}


def known_keys(kind: str) -> set[str]:
    return {f["key"] for f in kind_meta(kind).get("fields", [])}


def parse_config(server) -> dict:
    """读配置 JSON（坏了就当空配置，不要让一条脏数据把整页打崩）"""
    raw = getattr(server, "config", None) or "{}"
    if isinstance(raw, dict):
        return dict(raw)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("服务器 %s 的配置无法解析，已当作空配置", getattr(server, "id", "?"))
        return {}
    return data if isinstance(data, dict) else {}


def mask_config(server) -> tuple[dict, list[str]]:
    """脱敏：密钥类字段只回「是否已配置」，绝不回明文"""
    config = parse_config(server)
    secrets = secret_keys(getattr(server, "kind", ""))
    public: dict = {}
    present: list[str] = []
    for key, value in config.items():
        if key in secrets and value:
            present.append(key)
            continue
        public[key] = value
    return public, present


def redact(message: str, server) -> str:
    """把错误文案里的凭据洗掉（异常里常带着 URL 内嵌的 user:pass）"""
    text = message or ""
    for value in parse_config(server).values():
        if isinstance(value, str) and len(value) >= 4 and value in text:
            text = text.replace(value, "***")
    return text[:300]


def json_dumps(config: dict) -> str:
    return json.dumps(config or {}, ensure_ascii=False)


def only_known(kind: str, config: dict) -> dict:
    """只保留该类型声明过的字段，避免前端塞进任意键污染配置"""
    allowed = known_keys(kind)
    out: dict = {}
    for key, value in (config or {}).items():
        if allowed and key not in allowed:
            continue
        out[key] = value if value is None else str(value).strip()
    return out


def merge_config(server, new_config: dict) -> dict:
    """合并配置：密钥字段留空 = 保持原值（前端拿不到明文，不能因此把密钥抹掉）

    只接受该类型声明过的字段，避免前端塞进任意键污染配置。
    """
    old = parse_config(server)
    allowed = known_keys(getattr(server, "kind", ""))
    merged = dict(old)
    for key, value in (new_config or {}).items():
        if allowed and key not in allowed:
            continue
        if key in secret_keys(getattr(server, "kind", "")) and (value is None or str(value).strip() == ""):
            continue
        merged[key] = value if value is None else str(value).strip()
    return merged


# ==================== 连接体检 ====================

def _validate_url(raw_url: str) -> str:
    from urllib.parse import urlparse

    url = (raw_url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("地址必须是完整的 http:// 或 https:// 地址")
    return url


async def probe_ea(url: str) -> dict:
    """探测 EA（本项目自带的后端服）：必须自报身份且已与面板配对"""
    target = _validate_url(url)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(f"{target}/api/health")
    except (httpx.RequestError, ValueError):
        return {"ok": False, "status_code": None, "message": "无法连接或返回格式不正确"}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code,
                "message": f"服务返回 HTTP {response.status_code}"}
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {}
    if body.get("service") != "ea" or body.get("status") != "healthy" or not body.get("paired_with_em"):
        return {"ok": False, "status_code": response.status_code,
                "message": "EA 已响应，但还没有和面板配对；请确认共享数据库与 SECRET_KEY 一致"}
    # 挂载体检端点是「求片之外的播放链」要用的：顺手确认它也在（老版本 EA 没有）
    return {
        "ok": True,
        "status_code": response.status_code,
        "server_name": body.get("emby_server_name") or body.get("ServerName") or body.get("Product") or "Emby 服务",
        "version": body.get("version") or body.get("Version") or "",
    }


async def probe_emby(url: str, api_key: str = "") -> dict:
    """探测已有的外部 Emby / Jellyfin"""
    target = _validate_url(url)
    headers = {"X-Emby-Token": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(f"{target}/System/Info/Public", headers=headers)
    except (httpx.RequestError, ValueError):
        return {"ok": False, "status_code": None, "message": "无法连接或返回格式不正确"}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code,
                "message": f"服务返回 HTTP {response.status_code}"}
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {}
    return {
        "ok": True,
        "status_code": response.status_code,
        "server_name": body.get("ServerName") or body.get("Product") or "Emby 服务",
        "version": body.get("Version") or "",
    }


async def probe_server(kind: str, url: str, config: Optional[dict] = None) -> dict:
    """按类型体检（统一返回 {ok, message, ...}）"""
    kind = (kind or "").strip().lower()
    config = config or {}
    if kind not in KIND_MAP:
        return {"ok": False, "message": f"未知的服务器类型：{kind or '（空）'}"}
    try:
        if kind == "ea":
            return await probe_ea(url)
        if kind == "emby":
            return await probe_emby(url, str(config.get("api_key") or ""))
        if kind == "moviepilot":
            return await moviepilot.probe(
                url,
                api_key=str(config.get("api_key") or ""),
                username=str(config.get("username") or ""),
                password=str(config.get("password") or ""),
            )
        if kind == "qbittorrent":
            return await qbittorrent.probe(
                url,
                username=str(config.get("username") or ""),
                password=str(config.get("password") or ""),
            )
    except ValueError as exc:  # _validate_url 抛出的地址格式问题
        return {"ok": False, "message": str(exc)}
    except httpx.HTTPError as exc:  # noqa: BLE001 — 网络异常一律转成可读原因
        return {"ok": False, "message": f"连接失败：{exc}"}
    return {"ok": False, "message": "该类型暂不支持体检"}


async def probe_and_store(db: Session, server) -> dict:
    """体检并落库最近一次结果（供列表展示）

    对 EA 额外做一件事：拉一次 ``/api/admin/nodes/me``，把「这台 EA 认领的是哪个服、
    负责哪些库」当场查出来。多服 / 多节点部署下，配错 REALM 或 NODE_KEY 就会表现成
    「客户端看不到任何库」——放在添加服务器这一步报出来，比之后猜要省事得多。
    """
    result = await probe_server(server.kind, server.url, parse_config(server))
    server.last_checked_at = datetime.now()
    server.last_check_ok = bool(result.get("ok"))
    server.last_check_message = redact(str(result.get("message") or ""), server)
    if server.kind == "ea" and result.get("ok"):
        from backend.emby_server import nodes as node_lib

        identity = await node_lib.fetch_node_identity(server.url)
        result["node"] = identity
        if identity.get("ok"):
            node_key = str((identity.get("data") or {}).get("node_key") or "").strip()
            if node_key and not (server.node_key or "").strip():
                server.node_key = node_key
            realm_slug = str((identity.get("data") or {}).get("realm_slug") or "").strip()
            if realm_slug and not server.realm_id:
                realm = realms.realm_by_slug(db, realm_slug)
                if realm:
                    server.realm_id = realm.id
    db.commit()
    return result


# ==================== 旧配置同步（EA / Emby）====================

LEGACY_PREFIX = {"ea": "emby_managed", "emby": "emby_external"}


def realm_scope(query, realm_id: Optional[int]):
    """按服过滤服务器清单

    - ``ea`` / ``emby``：**一个服一个**——只有归属这个服的那几台算数；
    - ``moviepilot`` / ``qbittorrent``：内容自动化，多服共用一套下载与整理即可，
      所以归属服留空（``realm_id IS NULL``）的那几台在**每个服**里都算数；
    - ``realm_id is None``：不过滤（跨服汇总 / 数据概览的「全部服」视图）。
    """
    if realm_id is None:
        return query
    return query.filter(or_(
        models.RemoteServer.realm_id == int(realm_id),
        and_(models.RemoteServer.realm_id.is_(None),
             models.RemoteServer.kind.in_(PUSH_TARGETS)),
    ))


def _config_row(db: Session, key: str):
    return db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()


def config_value(db: Session, key: str, default: str = "", realm_id: Optional[int] = None) -> str:
    """读配置；Emby 入口那几个键是**一个服一个**的（默认服沿用历史键名）"""
    if key in realms.REALM_CONFIG_BASES:
        return realms.realm_config(db, key, realm_id, default)
    row = _config_row(db, key)
    return ((row.value if row and row.value is not None else default) or "").strip()


def set_config(db: Session, key: str, new_value: str, description: str = "",
               realm_id: Optional[int] = None) -> None:
    if key in realms.REALM_CONFIG_BASES:
        realms.set_realm_config(db, key, new_value, realm_id, description)
        return
    row = _config_row(db, key)
    if row:
        row.value = new_value
    else:
        db.add(models.SystemConfig(key=key, value=new_value, description=description))


def sync_legacy(db: Session, server, *, reachable: Optional[bool] = None,
                activate_mode: bool = True) -> None:
    """把激活结果写回既有的 Emby 配置键（**按服写入**）

    这些键是网关闸门、客户端指引、用户端账号卡**唯一**读取的地方
    （``emby_active_mode`` / ``emby_managed_*`` / ``emby_external_*``），
    所以「多服务器」是叠在它们之上的一层管理面，而不是另起一套真相。
    多服部署下每个服各有一套：默认服沿用历史键名，其它服用 ``<键>__r<服 id>``。
    """
    prefix = LEGACY_PREFIX.get(server.kind)
    if not prefix:
        return
    realm_id = server.realm_id or realms.active_realm_id(db)
    config = parse_config(server)
    set_config(db, f"{prefix}_url", server.url, "Emby 服务地址", realm_id)
    set_config(db, f"{prefix}_enabled", "true" if server.is_enabled else "false", "Emby 服务是否启用", realm_id)
    if reachable is None:
        reachable = bool(server.last_check_ok)
    set_config(db, f"{prefix}_reachable", "true" if reachable else "false", "Emby 服务最近一次连接结果", realm_id)
    if server.kind == "emby" and config.get("api_key"):
        set_config(db, "emby_external_api_key", str(config["api_key"]), "外部 Emby API 密钥", realm_id)
    if activate_mode and server.is_enabled and reachable:
        set_config(db, "emby_active_mode", KIND_MAP[server.kind]["writes_active_mode"],
                   "当前 Emby 服务模式", realm_id)


def deactivate_legacy(db: Session, kind: str, realm_id: Optional[int] = None) -> None:
    """某类在某个服已经没有激活的服务器了：把那个服的键收回，回到「面板自己出流」或「未接入」"""
    prefix = LEGACY_PREFIX.get(kind)
    if not prefix:
        return
    if realm_id is None:
        realm_id = realms.active_realm_id(db)
    set_config(db, f"{prefix}_enabled", "false", "Emby 服务是否启用", realm_id)
    set_config(db, f"{prefix}_reachable", "false", "Emby 服务最近一次连接结果", realm_id)
    # 另一类在**同一个服**还有激活的服务器就交给它（比如删了 EA 但还接着外部 Emby），
    # 否则这个服回到「面板自己出流」
    other_kind = "emby" if kind == "ea" else "ea"
    still_active = (db.query(models.RemoteServer)
                    .filter(models.RemoteServer.kind == other_kind,
                            models.RemoteServer.realm_id == realm_id,
                            models.RemoteServer.is_active.is_(True),
                            models.RemoteServer.is_enabled.is_(True))
                    .first())
    set_config(db, "emby_active_mode",
               KIND_MAP[other_kind]["writes_active_mode"] if still_active else "panel",
               "当前 Emby 服务模式", realm_id)


# ==================== 激活 ====================

def get_server(db: Session, server_id: int) -> Optional[models.RemoteServer]:
    return db.query(models.RemoteServer).filter(models.RemoteServer.id == server_id).first()


def active_server(db: Session, kind: str, realm_id: Optional[int] = None) -> Optional[models.RemoteServer]:
    query = (db.query(models.RemoteServer)
             .filter(models.RemoteServer.kind == kind,
                     models.RemoteServer.is_active.is_(True),
                     models.RemoteServer.is_enabled.is_(True)))
    query = realm_scope(query, realm_id)
    return query.order_by(models.RemoteServer.id).first()


def activate(db: Session, server, *, reachable: Optional[bool] = None) -> dict:
    """把某台服务器设为**它那个服**里这一类的「当前使用」

    只有通过连接体检的服务器才能被激活（避免出现「后台指着一台连不上的服务跑」）。
    切换只影响同一个服：甲服换成外部 Emby 不会动到乙服的 EA 入口。
    """
    meta = kind_meta(server.kind)
    if not meta:
        return {"ok": False, "message": f"未知的服务器类型：{server.kind}"}
    if reachable is None:
        reachable = bool(server.last_check_ok)
    if not reachable:
        return {"ok": False, "message": "连接测试未通过，不能设为当前使用；请先修好这台服务器再试"}
    if not meta.get("activatable"):
        # MoviePilot / qBittorrent 没有「当前入口」的概念：多台一起用是正常的
        return {"ok": True, "message": f"{meta['label']} 无需设为当前使用（多台可以同时用于求片）",
                "activatable": False}
    if not server.realm_id:
        server.realm_id = realms.active_realm_id(db)

    same_kind = (db.query(models.RemoteServer)
                 .filter(models.RemoteServer.kind == server.kind,
                         models.RemoteServer.realm_id == server.realm_id,
                         models.RemoteServer.id != server.id)
                 .all())
    for other in same_kind:
        other.is_active = False
    server.is_active = True
    server.is_enabled = True
    sync_legacy(db, server, reachable=True)
    db.commit()
    return {
        "ok": True,
        "message": f"已切换到 {server.name}",
        "activatable": True,
        "mode": meta["writes_active_mode"],
    }


def unique_name(db: Session, base: str, exclude_id: Optional[int] = None) -> str:
    """给自动创建/改名的服务器一个不冲突的名字（如「后端服（EA） 2」）"""
    base = (base or "服务器").strip()[:60] or "服务器"
    taken = {row.name for row in db.query(models.RemoteServer).all()
             if row.id != exclude_id}
    if base not in taken:
        return base
    for i in range(2, 100):
        candidate = f"{base} {i}"
        if candidate not in taken:
            return candidate
    return f"{base} {datetime.now().strftime('%H%M%S')}"


def upsert_legacy(db: Session, kind: str, url: str, *, api_key: str = "",
                  enabled: bool = True, reachable: Optional[bool] = None,
                  name: str = "", realm_id: Optional[int] = None) -> models.RemoteServer:
    """旧「Emby 服务入口」页保存时，把结果同步进服务器清单

    两张入口（旧页面的两个格子 / 新页面的清单）操作的是同一件事，必须收敛到一条真相：
    同一类型只保留一台「当前使用」，旧页保存后就把它标为激活，新页面自然显示为当前入口。
    """
    kind = (kind or "").strip().lower()
    meta = kind_meta(kind)
    if not meta:
        raise ValueError(f"未知的服务器类型：{kind}")
    url = _validate_url(url)

    if realm_id is None:
        realm_id = realms.active_realm_id(db)
    row = (db.query(models.RemoteServer)
           .filter(models.RemoteServer.kind == kind,
                   models.RemoteServer.realm_id == realm_id)
           .order_by(models.RemoteServer.is_active.desc(), models.RemoteServer.id)
           .first())
    if row is None:
        row = models.RemoteServer(name=unique_name(db, name or meta["label"]), kind=kind,
                                  url=url, realm_id=realm_id)
        db.add(row)
        db.flush()

    row.url = url
    row.is_enabled = bool(enabled)
    if api_key:
        config = parse_config(row)
        config["api_key"] = api_key
        row.config = json_dumps(config)
    if reachable is not None:
        row.last_checked_at = datetime.now()
        row.last_check_ok = bool(reachable)

    # 只有真的连上才把它标为「当前使用」：旧页面本来就是这个规则
    # （探测不过时不切换入口），清单不能自己把一台连不上的服务标成当前。
    if reachable is True:
        for other in (db.query(models.RemoteServer)
                      .filter(models.RemoteServer.kind == kind,
                              models.RemoteServer.realm_id == realm_id,
                              models.RemoteServer.id != row.id)
                      .all()):
            other.is_active = False
        row.is_active = True
    db.commit()
    db.refresh(row)
    return row


def summary(db: Session, realm_id: Optional[int] = None) -> dict:
    """按类型统计：加了几台、几台可用、当前用的是哪台（面板顶部与数据概览都用它）

    ``realm_id=None`` 表示跨服汇总（数据概览的「全部服」视图）。
    """
    rows = realm_scope(db.query(models.RemoteServer), realm_id).order_by(models.RemoteServer.id).all()
    by_kind: dict[str, dict] = {}
    for kind in KINDS:
        meta = KIND_MAP[kind]
        items = [r for r in rows if r.kind == kind]
        current = next((r for r in items if r.is_active and r.is_enabled), None)
        by_kind[kind] = {
            "kind": kind,
            "label": meta["label"],
            "short": meta["short"],
            "group": meta["group"],
            "activatable": bool(meta.get("activatable")),
            "total": len(items),
            "enabled": len([r for r in items if r.is_enabled]),
            "reachable": len([r for r in items if r.last_check_ok is True]),
            "active_id": current.id if current else None,
            "active_name": current.name if current else "",
            "active_url": current.url if current else "",
        }
    return {
        "kinds": by_kind,
        "total": len(rows),
        "reachable": len([r for r in rows if r.last_check_ok is True]),
        "unchecked": len([r for r in rows if r.last_check_ok is None]),
        "realm_id": realm_id,
        # 求片能用的目标：给「求片管理」与数据概览用
        "push_ready": [k for k in PUSH_TARGETS
                       if any(r.kind == k and r.is_enabled and r.last_check_ok is True for r in rows)],
    }


def serialize(db: Session, server) -> dict:
    config, secrets = mask_config(server)
    realm = realms.get_realm(db, server.realm_id)
    return {
        "id": server.id,
        "name": server.name,
        "kind": server.kind,
        "kind_label": kind_label(server.kind),
        "realm_id": server.realm_id,
        "realm_name": realm.name if realm else "",
        # 内容自动化（MoviePilot / qB）可以「全服共用」：归属服留空，每个服都能用它求片
        "shared": server.realm_id is None and server.kind in PUSH_TARGETS,
        "node_key": server.node_key or "",
        "kind_group": kind_meta(server.kind).get("group", ""),
        "url": server.url,
        "config": config,
        "secret_keys": secrets,
        "is_enabled": bool(server.is_enabled),
        "is_active": bool(server.is_active),
        "remark": server.remark or "",
        "last_checked_at": server.last_checked_at.isoformat() if server.last_checked_at else None,
        "last_check_ok": server.last_check_ok,
        "last_check_message": server.last_check_message or "",
        # 由类型元数据推出来的能力提示，前端不用自己猜
        "activatable": bool(kind_meta(server.kind).get("activatable")),
        "can_push_media_seek": server.kind in PUSH_TARGETS,
    }


def active_config(db: Session, kind: str, realm_id: Optional[int] = None) -> Optional[dict]:
    """取某类当前可用的服务器配置（含明文密钥，仅供服务端内部调用）

    - ``ea`` / ``emby``：优先取「当前使用」的那台，没标就取最近一台已启用的；
    - ``moviepilot`` / ``qbittorrent``：取第一台已启用且体检通过的（多台一起用没问题）。

    ``realm_id=None`` 表示跨服挑一台（求片推送这类没有服概念的场景用）；传服 id 时
    只在那个服里挑（EA / Emby 的入口一定属于某个服）。
    """
    query = db.query(models.RemoteServer).filter(models.RemoteServer.kind == kind)
    query = realm_scope(query, realm_id)
    if kind in LEGACY_PREFIX:
        row = (query.filter(models.RemoteServer.is_active.is_(True))
               .order_by(models.RemoteServer.id).first())
        if not row:
            row = query.order_by(models.RemoteServer.id).first()
    else:
        row = (query.filter(models.RemoteServer.is_enabled.is_(True),
                            models.RemoteServer.last_check_ok.is_(True))
               .order_by(models.RemoteServer.id).first())
    if not row:
        return None
    return {"id": row.id, "name": row.name, "url": row.url, "realm_id": row.realm_id,
            "config": parse_config(row)}


async def push_media_seek(db: Session, request, target: str, link: str = "",
                          realm_id: Optional[int] = None) -> dict:
    """把一条求片转交给外部服务

    - ``moviepilot``：用它的订阅接口（需要用户名 / 密码换 JWT）；
    - ``qbittorrent``：加种（需要磁力 / 种子链接，因为 qB 自己不会去找片子）。

    MoviePilot / qB 这类「内容自动化」服务是全局共享的（多服共用一套下载与整理即可），
    所以默认跨服挑选；但求片本身记的是**哪个服**要这部片（``MovieRequest.realm_id``）。
    """
    target = (target or "").strip().lower()
    if target == "auto":
        # 挑哪台是同步查库：这个函数是 async（要 await 外部订阅/加种接口），
        # 查询绝不能留在事件循环上（跨机 PostgreSQL 每个查询一个 RTT）。
        has_moviepilot = await run_in_threadpool(active_config, db, "moviepilot", realm_id)
        target = "moviepilot" if has_moviepilot else "qbittorrent"
    if target not in PUSH_TARGETS:
        return {"ok": False, "target": target,
                "message": "只能推送到 MoviePilot 或 qBittorrent；请先在「服务器」里添加并测试连接"}

    server = await run_in_threadpool(active_config, db, target, realm_id)
    if not server:
        label = kind_label(target)
        return {"ok": False, "target": target,
                "message": f"还没有可用的 {label}：请先在「服务器」页添加并测试连接"}

    config = server["config"]
    if target == "moviepilot":
        result = await moviepilot.subscribe(
            server["url"],
            username=str(config.get("username") or ""),
            password=str(config.get("password") or ""),
            name=request.movie_name,
            year=request.year,
            mtype=moviepilot.media_type(request.type),
            save_path=str(config.get("save_path") or ""),
        )
    else:
        result = await qbittorrent.add_torrent(
            server["url"],
            username=str(config.get("username") or ""),
            password=str(config.get("password") or ""),
            link=link or "",
            save_path=str(config.get("save_path") or config.get("savepath") or ""),
            category=str(config.get("category") or ""),
        )
    return {"ok": bool(result.get("ok")), "target": target, "server": server["name"],
            "message": str(result.get("message") or "")[:300], "id": result.get("id")}


__all__ = [
    "KINDS",
    "KIND_MAP",
    "PUSH_TARGETS",
    "SERVER_KINDS",
    "activate",
    "active_config",
    "active_server",
    "config_value",
    "deactivate_legacy",
    "get_server",
    "kind_label",
    "kind_meta",
    "known_keys",
    "json_dumps",
    "mask_config",
    "merge_config",
    "only_known",
    "parse_config",
    "probe_and_store",
    "probe_ea",
    "probe_emby",
    "probe_server",
    "push_media_seek",
    "realm_scope",
    "redact",
    "secret_keys",
    "serialize",
    "set_config",
    "summary",
    "sync_legacy",
    "unique_name",
    "upsert_legacy",
]
