"""流节点（分离架构）：高宽带大盘机器独立出流，主服务只改播放 URL。

## 架构

单机部署（默认）：``stream_nodes`` 无配置 → 所有行为与升级前逐字节一致，
播放 URL 指向本机，零影响。

分离部署：管理员在主服务后台（或一键脚本）注册一台/多台流节点
``https://stream.example.com``（高宽带 + 大盘 + CF 橙云隐藏 IP），
PlaybackInfo 生成的 ``DirectStreamUrl`` / ``TranscodingUrl`` 自动改写为
流节点地址。URL 上的短期签名（``uid/exp/sign``）原样保留——流节点与主服务
共享 ``SECRET_KEY``，验签不需要额外对接。

## 与现有机制的关系（横切能力只许一套）

- 节点列表、健康检查、加权选择：复用 ``node_health``（``stream_nodes`` 键），
  本模块不另起一套；
- CDN 域名改写（``cdn`` 模块）是另一套：流节点命中时跳过 CDN 改写——
  节点域名本身就是边缘入口（CF 在前），再套一层没有意义；
- 鉴权：签名验签只依赖 ``SECRET_KEY``（``play_sign``），流节点读主库做
  用户/订阅校验（只读），无状态，可横向扩展。

## 安全

- 永远不把播放 URL 改写到内网/回环地址（``is_public_node_url`` 守卫）：
  ``node_health`` 的默认本机条目（``http://127.0.0.1:8000``）只在无配置时
  兜底，改写层直接忽略它；
- 管理接口（``admin_router``）用面板密钥（``X-Panel-Key`` = SECRET_KEY）
  鉴权，与节点间既有机制一致（``mount_health.require_panel_key``）。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.emby_server import node_health
from backend.emby_server.mount_health import require_panel_key

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL 改写
# ---------------------------------------------------------------------------

def _is_public_node_url(url: str) -> bool:
    """节点地址必须是公网可达的：拒绝回环/内网/空地址。"""
    try:
        host = (urlsplit(url).hostname or "").strip().lower()
    except Exception:
        return False
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
        return not (addr.is_loopback or addr.is_private or addr.is_reserved)
    except ValueError:
        # 非 IP 即域名：拒绝 localhost 这类
        return host not in ("localhost",)


def _same_origin(a: str, b: str) -> bool:
    """两个基址是否同一源（scheme+host+port 一致）。"""
    try:
        pa, pb = urlsplit(a.rstrip("/")), urlsplit(b.rstrip("/"))
    except Exception:
        return False
    def _port(p):
        try:
            return p.port
        except ValueError:
            return None
    return (
        (pa.scheme or "http") == (pb.scheme or "http")
        and (pa.hostname or "").lower() == (pb.hostname or "").lower()
        and _port(pa) == _port(pb)
    )


def pick_stream_node(db: Session) -> Optional[dict]:
    """选一个可用的远端流节点；无远端节点时返回 None（= 本机出流）。"""
    node = node_health.pick_node(db)
    if not node:
        return None
    url = (node.get("url") or "").rstrip("/")
    if not url or not _is_public_node_url(url):
        return None
    return node


def rewrite_playback_urls(
    db: Session, stream_url: str, transcoding_url: str, base: str,
) -> tuple[str, str, bool]:
    """有远端健康流节点时，把播放 URL 基址换成流节点。

    返回 ``(stream_url, transcoding_url, hit)``。未命中时原样返回，
    调用方行为与升级前逐字节一致。
    """
    node = pick_stream_node(db)
    if node is None:
        return stream_url, transcoding_url, False
    node_base = (node.get("url") or "").rstrip("/")
    base = (base or "").rstrip("/")
    if not base or _same_origin(node_base, base):
        return stream_url, transcoding_url, False
    new_stream = stream_url.replace(base, node_base, 1) if stream_url.startswith(base) else stream_url
    new_trans = transcoding_url.replace(base, node_base, 1) if transcoding_url.startswith(base) else transcoding_url
    # 两个都没换上说明 base 对不上：宁可不改写，也不能给客户端一个坏 URL
    if new_stream == stream_url and new_trans == transcoding_url:
        return stream_url, transcoding_url, False
    logger.debug("播放 URL 改写到流节点 %s", node_base)
    return new_stream, new_trans, True


# ---------------------------------------------------------------------------
# 注册 / 管理
# ---------------------------------------------------------------------------

def _raw_nodes(db: Session) -> list:
    """读原始配置（不带 node_health 的默认本机兜底）。"""
    from backend.models import SystemConfig
    row = db.query(SystemConfig).filter(
        SystemConfig.key == node_health.CONFIG_KEY).first()
    if row and row.value:
        try:
            nodes = json.loads(row.value)
            if isinstance(nodes, list):
                return nodes
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def register_node(db: Session, url: str, name: str = "", weight: int = 100) -> dict:
    """注册/更新一个流节点（按 URL 去重）。返回注册后的节点。"""
    url = (url or "").strip().rstrip("/")
    if not url:
        raise ValueError("节点 URL 不能为空")
    if not _is_public_node_url(url):
        raise ValueError("节点 URL 必须是公网地址（不能是内网/回环）")
    try:
        weight = max(1, int(weight))
    except (TypeError, ValueError):
        weight = 100
    nodes = _raw_nodes(db)
    node = {"url": url, "name": name or url, "weight": weight}
    for i, n in enumerate(nodes):
        if isinstance(n, dict) and (n.get("url") or "").rstrip("/") == url:
            nodes[i] = node
            break
    else:
        nodes.append(node)
    node_health.set_nodes(db, nodes)
    logger.info("注册流节点: %s（%s，权重 %s）", url, node["name"], weight)
    return node


def unregister_node(db: Session, url: str) -> bool:
    """按 URL 移除流节点；返回是否真的删掉了。"""
    url = (url or "").strip().rstrip("/")
    nodes = _raw_nodes(db)
    kept = [n for n in nodes
            if not (isinstance(n, dict) and (n.get("url") or "").rstrip("/") == url)]
    if len(kept) == len(nodes):
        return False
    node_health.set_nodes(db, kept)
    logger.info("移除流节点: %s", url)
    return True


# ---------------------------------------------------------------------------
# 管理接口（一键部署脚本调用）
# ---------------------------------------------------------------------------

admin_router = APIRouter(prefix="/api/admin/stream-nodes", tags=["stream-nodes"])


def _panel_auth(request: Request) -> None:
    try:
        require_panel_key(request)
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@admin_router.get("")
def list_nodes(request: Request, db: Session = Depends(get_db)):
    _panel_auth(request)
    return {"nodes": _raw_nodes(db), "healthy": [
        n.get("url") for n in node_health.healthy_nodes(db)
    ], "tokens": list_join_tokens(db)}


@admin_router.post("/register")
def api_register(request: Request, payload: dict, db: Session = Depends(get_db)):
    _panel_auth(request)
    try:
        node = register_node(
            db,
            payload.get("url", ""),
            payload.get("name", ""),
            payload.get("weight", 100),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "node": node, "nodes": _raw_nodes(db)}


@admin_router.delete("")
def api_unregister(request: Request, url: str, db: Session = Depends(get_db)):
    _panel_auth(request)
    return {"ok": unregister_node(db, url), "nodes": _raw_nodes(db)}


def _build_bundle() -> dict:
    """构建流节点配置包（SECRET_KEY/rclone.conf/SA 文件等）。

    被 /bundle（面板密钥鉴权）和 /join（join token 鉴权）复用，
    信任级别相同：调用方拿到后即拥有验签密钥与主库只读连接串。
    """
    from backend.security import SECRET_KEY

    bundle: dict = {
        "secret_key": SECRET_KEY,
        "database_url": os.environ.get("DATABASE_URL", ""),
        "database_type": os.environ.get("DATABASE_TYPE", "postgresql"),
    }

    # rclone.conf
    conf_path = os.environ.get("MOUNT_RCLONE_CONF", "/config/rclone/rclone.conf")
    try:
        with open(conf_path, "r", encoding="utf-8") as f:
            bundle["rclone_conf"] = f.read()
    except OSError:
        bundle["rclone_conf"] = ""
    # 远端列表（供节点给挂载点做默认建议）
    bundle["rclone_remotes"] = _parse_remotes(bundle["rclone_conf"])

    # SA 文件
    sa_dir = os.environ.get("RCLONE_SA_DIR", "/sa-accounts")
    sa_files: dict[str, str] = {}
    try:
        import pathlib
        for p in sorted(pathlib.Path(sa_dir).glob("*.json"))[:200]:
            try:
                sa_files[p.name] = p.read_text(encoding="utf-8")
            except OSError:
                continue
    except OSError:
        pass
    bundle["sa_files"] = sa_files
    bundle["sa_count"] = len(sa_files)
    return bundle


@admin_router.post("/token")
def api_create_token(request: Request, payload: dict,
                     db: Session = Depends(get_db)):
    """生成一次性 join token（管理后台"添加节点"用）。

    Body: {name, node_url（可空，join 时可上报）, weight, ttl_minutes（默认 30）}
    """
    _panel_auth(request)
    try:
        ttl = int(payload.get("ttl_minutes", 30) or 30)
    except (TypeError, ValueError):
        ttl = 30
    ttl = max(1, min(ttl, 24 * 60))
    try:
        info = create_join_token(
            db,
            payload.get("name", ""),
            payload.get("node_url", ""),
            payload.get("weight", 100),
            ttl * 60,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **info}


@admin_router.get("/tokens")
def api_list_tokens(request: Request, db: Session = Depends(get_db)):
    """列出 join token（含 pending/used/expired 状态）。"""
    _panel_auth(request)
    return {"tokens": list_join_tokens(db)}


@admin_router.delete("/tokens/{token}")
def api_revoke_token(request: Request, token: str,
                     db: Session = Depends(get_db)):
    """作废一个未使用的 join token。"""
    _panel_auth(request)
    return {"ok": revoke_join_token(db, token)}


@admin_router.post("/join")
def api_join(request: Request, payload: dict,
             db: Session = Depends(get_db)):
    """流节点自注册（免脚本）：容器启动时带 JOIN_TOKEN 调此接口。

    鉴权：token 本身（一次性，30 分钟有效，用后即焚），不走面板密钥。
    Body: {token, node_url（建 token 时未预填则必填）, disk_gb, version}
    成功：注册节点 + 返回配置包（SECRET_KEY/rclone.conf/SA 文件）。
    """
    token = (payload.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="缺少 token")
    try:
        info = consume_join_token(db, token, payload.get("node_url", ""))
    except ValueError as e:
        logger.warning("流节点 join 失败：%s", e)
        raise HTTPException(status_code=403, detail=str(e))
    try:
        node = register_node(db, info["node_url"], info["name"], info["weight"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("流节点自注册成功：%s（%s）", info["node_url"], info["name"])
    return {"ok": True, "node": node, "bundle": _build_bundle()}


@admin_router.get("/bundle")
def api_bundle(request: Request, db: Session = Depends(get_db)):
    """一键部署包：流节点建自身所需的主服务侧配置。

    包含：SECRET_KEY（验签）、DATABASE_URL（只读主库）、rclone.conf 内容、
    SA 文件（{文件名: 内容}）、rclone 远端列表。走 HTTPS + 面板密钥，
    与既有节点间机制同等信任级别。
    """
    _panel_auth(request)
    return _build_bundle()




# ---------------------------------------------------------------------------
# Join Token（免脚本自助接入）
#
# 流程：管理后台"添加节点" → 生成一次性 token（30 分钟有效）→
# 新机器 `docker run -e JOIN_TOKEN=xxx` → 容器调 /join 自注册 →
# token 即焚，节点拿到配置包（SECRET_KEY/rclone.conf/SA）完成接入。
#
# 安全：token 256 位随机，不可猜；单次有效；过期自动失效；
# /join 不走面板密钥（节点还没有），token 本身即凭证。
# ---------------------------------------------------------------------------

JOIN_TOKEN_CONFIG_KEY = "stream_node_join_tokens"
JOIN_TOKEN_TTL_SECONDS = 30 * 60


def _raw_tokens(db: Session) -> dict:
    """读 token 表（dict: token -> info）。"""
    from backend.models import SystemConfig
    row = db.query(SystemConfig).filter(
        SystemConfig.key == JOIN_TOKEN_CONFIG_KEY).first()
    if row and row.value:
        try:
            data = json.loads(row.value)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _save_tokens(db: Session, tokens: dict) -> None:
    from backend.models import SystemConfig
    row = db.query(SystemConfig).filter(
        SystemConfig.key == JOIN_TOKEN_CONFIG_KEY).first()
    value = json.dumps(tokens, ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(SystemConfig(key=JOIN_TOKEN_CONFIG_KEY, value=value,
                            description="流节点 join token（一次性，30 分钟有效）"))
    db.commit()


def _token_status(info: dict, now: float | None = None) -> str:
    now = now if now is not None else time.time()
    if info.get("used"):
        return "used"
    if now > float(info.get("expires_at", 0)):
        return "expired"
    return "pending"


def create_join_token(db: Session, name: str = "", node_url: str = "",
                      weight: int = 100,
                      ttl_seconds: int = JOIN_TOKEN_TTL_SECONDS) -> dict:
    """生成一次性 join token。node_url 可空（节点可在 join 时上报）。"""
    node_url = (node_url or "").strip().rstrip("/")
    if node_url and not _is_public_node_url(node_url):
        raise ValueError("节点 URL 必须是公网地址（不能是内网/回环）")
    try:
        weight = max(1, int(weight))
    except (TypeError, ValueError):
        weight = 100
    # 顺手清掉已过期/已用的旧 token，保持表小
    now = time.time()
    tokens = {t: i for t, i in _raw_tokens(db).items()
              if _token_status(i, now) == "pending"}
    token = secrets.token_urlsafe(32)
    info = {
        "name": name or "流节点",
        "node_url": node_url,
        "weight": weight,
        "created_at": now,
        "expires_at": now + max(60, int(ttl_seconds)),
        "used": False,
        "used_at": None,
    }
    tokens[token] = info
    _save_tokens(db, tokens)
    logger.info("生成流节点 join token（%s），%s 秒后过期",
                info["name"], int(info["expires_at"] - now))
    return {"token": token, **info}


def list_join_tokens(db: Session) -> list:
    """列出 token（含状态），不返回已过期超过 1 天的。"""
    now = time.time()
    out = []
    for token, info in _raw_tokens(db).items():
        if now - float(info.get("expires_at", 0)) > 86400:
            continue
        out.append({"token": token, "status": _token_status(info, now), **info})
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


def revoke_join_token(db: Session, token: str) -> bool:
    """作废一个 token（pending 才有效）。"""
    tokens = _raw_tokens(db)
    info = tokens.get(token)
    if not info or _token_status(info) != "pending":
        return False
    del tokens[token]
    _save_tokens(db, tokens)
    logger.info("作废流节点 join token（%s）", info.get("name"))
    return True


def consume_join_token(db: Session, token: str,
                       reported_url: str = "") -> dict:
    """核销 token：校验 → 标记已用 → 返回 token 信息。

    node_url 优先级：建 token 时预填 > 节点 join 时上报。
    失败抛 ValueError（调用方转 4xx）。
    """
    tokens = _raw_tokens(db)
    info = tokens.get(token)
    if not info:
        raise ValueError("token 不存在或已作废")
    st = _token_status(info)
    if st == "used":
        raise ValueError("token 已使用（一次性）")
    if st == "expired":
        raise ValueError("token 已过期，请重新生成")
    node_url = (info.get("node_url") or "").strip().rstrip("/") or \
        (reported_url or "").strip().rstrip("/")
    if not node_url:
        raise ValueError("缺少节点公网 URL（建 token 时填写或 join 时上报）")
    if not _is_public_node_url(node_url):
        raise ValueError("节点 URL 必须是公网地址（不能是内网/回环）")
    info["used"] = True
    info["used_at"] = time.time()
    info["node_url"] = node_url
    tokens[token] = info
    _save_tokens(db, tokens)
    logger.info("流节点 join token 已核销（%s → %s）",
                info.get("name"), node_url)
    return {"node_url": node_url, "name": info.get("name", ""),
            "weight": info.get("weight", 100)}


def _parse_remotes(conf_text: str) -> list[str]:
    """从 rclone.conf 文本提取远端名（[xxx] 节）。"""
    remotes: list[str] = []
    for line in (conf_text or "").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]") and len(line) > 2:
            remotes.append(line[1:-1])
    return remotes
