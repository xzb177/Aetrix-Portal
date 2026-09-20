"""115 网盘下载与转存

对标成熟媒体站的运营做法，给 EM 补上「分享链接 → 转存/下载 → 整理入库」这条链路。
实现按 **Cookie 型 115 Web API**（不依赖 115 OpenAPI）：

- **账号配置档**：可以配置多个命名账号（`pan115_accounts`），其中一个为默认账号；
  媒体库可单独绑定账号（`Library.account_115_id`），未绑定时回退「默认账号 → 服务器级
  `PAN115_COOKIE`」，因此历史部署里只在 .env 放一个 Cookie 的写法继续可用。
- **分享链接解析**：`https://115.com/s/xxxx?password=abcd`、`...#abcd`、
  「链接 + 提取码：abcd」等口令文本都能解析。
- **按任务原子持久化**：分享快照条目、已完成文件键、下载地址同时写数据库与
  `PAN115_STATE_DIR` 下的 JSON 文件；写文件走「临时文件 + os.replace」，
  EA 重启、自更新或优雅关停都不会读到半截 JSON。
- **可续跑、不重复**：启动时把 `running` 拉回 `pending` 重新入队，已完成文件靠
  `payload.done_keys` 跳过；Cookie 暂时失效时任务置 `waiting_auth` 并**保留**，
  修好账号后重试即可继续。
- **完成后进入统一整理、扫描与入库流程**：任务绑定了媒体库就触发一次该库扫描。

对外序列化永远返回 `items` / `urls` 列表（旧实现把 `items/urls` 为 null 的响应直接丢给
前端，导致转存记录页崩溃）。
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import tempfile
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.emby_server import models as em

logger = logging.getLogger(__name__)

# ==================== 配置 ====================

PAN115_COOKIE_ENV = "PAN115_COOKIE"
# 端点可用环境变量覆盖：115 的 Web API 域名偶有调整，也便于测试指向本地假服务
PAN115_WEBAPI_BASE = os.getenv("PAN115_WEBAPI_BASE", "https://webapi.115.com").rstrip("/")
PAN115_SHARE_BASE = os.getenv("PAN115_SHARE_BASE", PAN115_WEBAPI_BASE).rstrip("/")
PAN115_TIMEOUT = float(os.getenv("PAN115_TIMEOUT", "20"))
PAN115_UA = os.getenv(
    "PAN115_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
)

# ==================== 状态 ====================

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_WAITING_AUTH = "waiting_auth"
STATUS_CANCELED = "canceled"

# 未结束的状态：重启后需要恢复、也会参与「重复提交」判定
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_RUNNING)
# 终态
TERMINAL_STATUSES = (STATUS_DONE, STATUS_FAILED, STATUS_CANCELED)

STATUS_LABELS = {
    STATUS_PENDING: "排队中",
    STATUS_RUNNING: "进行中",
    STATUS_DONE: "已完成",
    STATUS_FAILED: "失败",
    STATUS_WAITING_AUTH: "等待 Cookie",
    STATUS_CANCELED: "已取消",
}

MODE_RECEIVE = "receive"    # 转存到自己的 115 网盘
MODE_DOWNLOAD = "download"  # 仅解析下载地址（交给外部下载器 / 直链）
MODE_LABELS = {MODE_RECEIVE: "转存", MODE_DOWNLOAD: "下载地址"}


# ==================== 分享链接解析 ====================

_SHARE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:115\.com|115cdn\.com|anxia\.com)/(?:s|web/share)/([A-Za-z0-9_\-]{6,})",
    re.IGNORECASE,
)
_SHARE_CODE_RE = re.compile(r"^(?:s/)?([A-Za-z0-9]{8,})$")
_RECEIVE_CODE_RE = re.compile(
    r"(?:password|passcode|pwd|receive_?code|提取码|口令|密码)\s*[=:：]?\s*([A-Za-z0-9]{4,8})",
    re.IGNORECASE,
)


class ShareLinkError(ValueError):
    """分享链接无法解析"""


def parse_share_link(text: str) -> dict:
    """从链接 / 口令文本里解析出分享码与提取码

    支持：

    - ``https://115.com/s/abcdefg?password=1234``
    - ``https://115.com/s/abcdefg#1234``
    - ``点此查看 https://115.com/s/abcdefg 提取码：1234``
    - 纯分享码 ``abcdefg``（可选 ``#1234`` / ``:1234``）
    """
    raw = (text or "").strip()
    if not raw:
        raise ShareLinkError("请填写 115 分享链接或分享码")

    share_code = ""
    receive_code = ""
    url = ""

    match = _SHARE_URL_RE.search(raw)
    if match:
        share_code = match.group(1)
        url = match.group(0)
        if not url.lower().startswith("http"):
            url = "https://" + url
    else:
        # 纯分享码（可能带 #提取码 或 空格分隔的提取码）
        candidate = raw.split("提取码")[0].split("密码")[0].strip()
        candidate = re.sub(r"^https?://\S+", "", candidate).strip()
        for token in re.split(r"[\s#:：,，]+", candidate):
            token = token.strip()
            if not token:
                continue
            hit = _SHARE_CODE_RE.match(token)
            if hit:
                share_code = hit.group(1)
                break

    if not share_code:
        raise ShareLinkError("未能识别 115 分享码，请检查链接格式")

    # 提取码：优先 ?password= / #code 形式，其次中文「提取码：xxxx」
    qs = re.search(r"[?&#](?:password|pwd|code)=([A-Za-z0-9]{4,8})", raw, re.IGNORECASE)
    if qs:
        receive_code = qs.group(1)
    else:
        frag = re.search(rf"{re.escape(share_code)}[#\s:：]+([A-Za-z0-9]{{4,8}})", raw)
        if frag:
            receive_code = frag.group(1)
    if not receive_code:
        tail = _RECEIVE_CODE_RE.search(raw)
        if tail:
            receive_code = tail.group(1)

    return {
        "share_code": share_code,
        "receive_code": receive_code,
        "url": url or f"https://115.com/s/{share_code}",
    }


# ==================== Cookie 解析 ====================


def normalize_cookie(raw: Optional[str]) -> str:
    """规范化 Cookie：去掉换行与首尾空白，便于整体粘贴"""
    return re.sub(r"\s+", " ", (raw or "").strip())


def resolve_cookie(
    db: Session,
    *,
    library=None,
    account_id: Optional[int] = None,
    explicit_cookie: Optional[str] = None,
) -> tuple[str, str]:
    """解析要使用的 115 Cookie，返回 ``(cookie, 来源说明)``

    优先级：显式账号 > 显式 Cookie > 媒体库绑定账号 > 默认账号 > 服务器级环境变量。
    每次解析前都会刷新一次，因此**配置档更新后无需重启**。

    媒体库绑定账号被删除或停用时，回退到默认账号并给出可读来源，避免任务直接卡死。
    """
    if account_id is not None:
        account = db.query(em.Pan115Account).filter(em.Pan115Account.id == account_id).first()
        if not account:
            raise ShareLinkError(f"115 账号配置档 #{account_id} 不存在")
        return normalize_cookie(account.cookie), f"账号配置档「{account.name}」"

    if explicit_cookie and explicit_cookie.strip():
        return normalize_cookie(explicit_cookie), "表单 Cookie"

    bound_id = getattr(library, "account_115_id", None)
    if bound_id:
        account = db.query(em.Pan115Account).filter(em.Pan115Account.id == bound_id).first()
        if account and account.is_enabled:
            return normalize_cookie(account.cookie), f"媒体库绑定账号「{account.name}」"
        logger.warning(
            "媒体库 #%s 绑定的 115 账号 #%s 不可用，回退到默认账号",
            getattr(library, "id", None), bound_id,
        )

    default = (
        db.query(em.Pan115Account)
        .filter(em.Pan115Account.is_default == True, em.Pan115Account.is_enabled == True)  # noqa: E712
        .first()
    )
    if default:
        return normalize_cookie(default.cookie), f"默认账号「{default.name}」"

    env_cookie = os.getenv(PAN115_COOKIE_ENV, "").strip()
    if env_cookie:
        return normalize_cookie(env_cookie), f"服务器级 {PAN115_COOKIE_ENV}"

    return "", "未配置"


def ensure_single_default(db: Session, keep_id: int) -> None:
    """保证同一时间只有一个默认账号（否则配置档更新后行为不确定）"""
    for other in db.query(em.Pan115Account).filter(em.Pan115Account.id != keep_id).all():
        if other.is_default:
            other.is_default = False


# ==================== HTTP 客户端 ====================

# 115 用 state/errno 表达失败；这几个 errno 说明是登录态问题（而不是业务错误）
_AUTH_ERRNOS = {"401", "403", "40101017", "40101002", "990002", "990009"}


class Pan115Error(RuntimeError):
    """115 调用失败（业务错误）"""


class Pan115AuthError(Pan115Error):
    """115 登录态失效（Cookie 过期 / 被踢）——调用方应把任务置 waiting_auth"""


def _http_json(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    cookie: str = "",
    timeout: Optional[float] = None,
) -> dict:
    """薄 HTTP 封装（测试可替换本函数，其余逻辑全部与网络解耦）"""
    import httpx

    headers = {
        "User-Agent": PAN115_UA,
        "Referer": "https://115.com/",
        "Accept": "application/json, text/plain, */*",
    }
    if cookie:
        headers["Cookie"] = cookie
    with httpx.Client(timeout=timeout or PAN115_TIMEOUT, follow_redirects=True) as client:
        resp = client.request(method, url, params=params, data=data, headers=headers)
    if resp.status_code in (401, 403):
        raise Pan115AuthError(f"115 返回 HTTP {resp.status_code}，Cookie 可能已失效")
    if resp.status_code >= 400:
        raise Pan115Error(f"115 返回 HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — 115 偶发返回 HTML 登录页
        raise Pan115AuthError("115 返回了非 JSON 响应，通常是登录态失效")
    if not isinstance(body, dict):
        return {"state": True, "data": body}
    return body


def _raise_for_state(body: dict) -> dict:
    """把 115 的 state/errno 表达统一成异常或成功返回"""
    if body.get("state") in (True, 1, "1"):
        return body
    errno = str(body.get("errno") or body.get("errNo") or "")
    message = str(body.get("error") or body.get("message") or "115 接口返回失败")
    if errno in _AUTH_ERRNOS or "登录" in message or "cookie" in message.lower():
        raise Pan115AuthError(message)
    raise Pan115Error(message)


class Pan115Client:
    """Cookie 型 115 客户端（只覆盖本功能用到的几个端点）"""

    def __init__(self, cookie: str):
        self.cookie = normalize_cookie(cookie)
        if not self.cookie:
            raise Pan115AuthError("未配置 115 Cookie")

    # ---- 账号 ----

    def check(self) -> dict:
        """校验 Cookie 是否有效，返回 ``{ok, uid, vip}``"""
        body = self._call(
            "GET", f"{PAN115_WEBAPI_BASE}/files",
            params={"aid": 1, "cid": 0, "limit": 1, "offset": 0, "show_dir": 1},
        )
        _raise_for_state(body)
        info = body.get("data") or {}
        if isinstance(info, list):
            info = {}
        return {"ok": True, "uid": str(info.get("uid") or "") or None,
                "vip": bool(info.get("vip") or info.get("is_vip"))}

    # ---- 目录 ----

    def list_dir(self, cid: str = "0") -> list[dict]:
        """列目录（用于目标路径浏览）"""
        body = self._call(
            "GET", f"{PAN115_WEBAPI_BASE}/files",
            params={
                "aid": 1, "cid": cid or "0", "o": "user_ptime", "asc": 1,
                "show_dir": 1, "limit": 200, "offset": 0,
            },
        )
        _raise_for_state(body)
        data = body.get("data") or []
        if not isinstance(data, list):
            return []
        return [
            {
                "fid": str(entry.get("fid") or entry.get("cid") or ""),
                "cid": str(entry.get("cid") or entry.get("fid") or ""),
                "name": entry.get("n") or entry.get("name") or "",
                "is_dir": _is_dir(entry),
                "size": int(entry.get("s") or 0),
                "pickcode": entry.get("pc") or "",
            }
            for entry in data
        ]

    # ---- 分享 ----

    def share_snapshot(self, share_code: str, receive_code: str = "",
                       cid: str = "0") -> dict:
        """读取分享快照：返回 ``{share_code, receive_code, items, total}``"""
        params = {
            "share_code": share_code,
            "receive_code": receive_code or "",
            "offset": 0,
            "limit": 200,
            "cid": cid or "0",
        }
        body = self._call("GET", f"{PAN115_SHARE_BASE}/share/snap", params=params)
        _raise_for_state(body)
        data = body.get("data") or {}
        if isinstance(data, list):
            data = {"list": data}
        raw_items = data.get("list") or data.get("items") or []
        if not isinstance(raw_items, list):
            raw_items = []
        items = [
            {
                "fid": str(entry.get("fid") or entry.get("file_id") or entry.get("cid") or ""),
                "name": entry.get("n") or entry.get("name") or "",
                "is_dir": _is_dir(entry),
                "size": int(entry.get("s") or entry.get("size") or 0),
                "pickcode": entry.get("pc") or entry.get("pick_code") or "",
            }
            for entry in raw_items
        ]
        return {
            "share_code": share_code,
            "receive_code": receive_code or "",
            "cid": cid or "0",
            "items": items,
            "total": int(data.get("count") or len(items)),
        }

    def receive(self, share_code: str, receive_code: str, file_ids: list[str],
                target_cid: str = "0") -> dict:
        """转存到自己的 115 网盘（秒存）"""
        body = self._call(
            "POST", f"{PAN115_SHARE_BASE}/share/receive",
            data={
                "share_code": share_code,
                "receive_code": receive_code or "",
                "file_id": ",".join(file_ids),
                "cid": target_cid or "0",
                "app": "web",
            },
        )
        return _raise_for_state(body)

    # ---- 下载 ----

    def download_url(self, pickcode: str) -> str:
        """取单个文件下载地址（供外部下载器 / 直链使用）"""
        body = self._call(
            "GET", f"{PAN115_WEBAPI_BASE}/files/download", params={"pickcode": pickcode},
        )
        _raise_for_state(body)
        url = body.get("file_url") or body.get("url")
        if not url:
            raise Pan115Error("115 未返回下载地址")
        return str(url)

    # ---- 内部 ----

    def _call(self, method: str, url: str, *, params: Optional[dict] = None,
              data: Optional[dict] = None) -> dict:
        return _http_json(method, url, params=params, data=data, cookie=self.cookie)


def _is_dir(entry: dict) -> bool:
    """115 目录项判定：优先显式字段，其次 fc == "0"（115 的目录分类码）"""
    if "is_dir" in entry:
        return bool(entry["is_dir"])
    for key in ("isdir", "is_dir"):
        if key in entry:
            return bool(entry[key])
    fc = entry.get("fc")
    if fc is not None:
        return str(fc) == "0"
    # 目录没有大小、没有 pickcode 是常见特征
    return not entry.get("s") and not entry.get("pc")


def verify_account(cookie: str) -> dict:
    """校验一个 Cookie（供后台「测试账号」按钮）"""
    client = Pan115Client(cookie)
    try:
        return client.check()
    except Pan115AuthError as exc:
        return {"ok": False, "message": str(exc), "auth_error": True}
    except Pan115Error as exc:
        return {"ok": False, "message": str(exc), "auth_error": False}


# ==================== 任务持久化 ====================


def _state_dir() -> str:
    configured = os.getenv("PAN115_STATE_DIR", "").strip()
    candidates = [configured] if configured else []
    candidates.append(os.path.join(os.getenv("EMBY_TRANSCODE_DIR", "/tmp/emby_transcode"), "pan115"))
    candidates.append(os.path.join(tempfile.gettempdir(), "pan115_tasks"))
    for path in candidates:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception as exc:  # noqa: BLE001 — 换下一个候选，绝不因为目录不可写让任务失败
            logger.warning("115 任务状态目录不可用 %s: %s", path, exc)
    return tempfile.gettempdir()


def _state_path(uid: str) -> str:
    return os.path.join(_state_dir(), f"{uid}.json")


# 超过这个时长还没被替换掉的临时文件，一定是上次进程被杀时留下的
STALE_TMP_SECONDS = int(os.getenv("PAN115_STALE_TMP_SECONDS", "900"))


def cleanup_stale_tmp() -> int:
    """清掉上次进程被强杀留下的临时文件（原子写入的正常副作用）

    不能删“正在写”的文件：只清超过 ``PAN115_STALE_TMP_SECONDS`` 的，避开并发写。
    """
    removed = 0
    try:
        now = time.time()
        for name in os.listdir(_state_dir()):
            if not name.endswith(".tmp"):
                continue
            full = os.path.join(_state_dir(), name)
            try:
                if now - os.path.getmtime(full) < STALE_TMP_SECONDS:
                    continue
                os.remove(full)
                removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    if removed:
        logger.info("已清理 %s 个残留的 115 任务临时文件", removed)
    return removed


def persist_payload(uid: str, payload: dict) -> None:
    """原子落盘：写临时文件 → fsync → os.replace

    进程在任意时刻被杀，磁盘上要么是旧版本、要么是新版本，不会出现半截 JSON。
    """
    path = _state_path(uid)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        # 顺手清理上次进程被杀留下的临时文件（低频，不拖慢落盘）
        if random.random() < 0.05:
            cleanup_stale_tmp()
    except Exception as exc:  # noqa: BLE001 — 落盘失败不影响数据库里的副本
        logger.warning("115 任务 %s 状态落盘失败: %s", uid, exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def load_payload(uid: str) -> dict:
    """读取任务状态文件（损坏 / 不存在时返回空字典，由数据库副本兜底）"""
    try:
        with open(_state_path(uid), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def task_payload(task: "em.Pan115Task") -> dict:
    """任务状态：优先数据库（权威副本），文件副本用于跨进程续跑兜底"""
    payload: dict = {}
    try:
        raw = json.loads(task.payload or "{}")
        if isinstance(raw, dict):
            payload = raw
    except Exception:  # noqa: BLE001
        payload = {}
    file_copy = load_payload(task.uid)
    for key, value in file_copy.items():
        if key not in payload or payload.get(key) in (None, [], ""):
            payload[key] = value
    return payload


def save_task_payload(db: Session, task: "em.Pan115Task", payload: dict) -> None:
    """数据库 + 状态文件双写（顺序：先文件后库，崩溃后不会出现「库新文件旧」）"""
    persist_payload(task.uid, payload)
    task.payload = json.dumps(payload, ensure_ascii=False)
    db.commit()


# ==================== 任务序列化 ====================


def _safe_list(value: Any) -> list:
    """永远返回列表：旧实现把 None 直接透传给前端，转存记录页会整体崩溃"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value] if value else []
    return []


def serialize_task(task: "em.Pan115Task", *, with_items: bool = True) -> dict:
    """序列化任务：items / urls 保证是列表，绝不为 null"""
    payload = task_payload(task)
    done_keys = _safe_list(payload.get("done_keys"))
    items = _safe_list(payload.get("items"))
    urls = _safe_list(payload.get("urls"))
    total = task.total_files or len(items)
    return {
        "id": task.id,
        "uid": task.uid,
        "share_url": task.share_url or "",
        "share_code": task.share_code or "",
        "mode": task.mode or MODE_RECEIVE,
        "mode_label": MODE_LABELS.get(task.mode or MODE_RECEIVE, task.mode or ""),
        "target_cid": task.target_cid or "0",
        "target_path": task.target_path or "",
        "account_id": task.account_id,
        "library_id": task.library_id,
        "status": task.status or STATUS_PENDING,
        "status_label": STATUS_LABELS.get(task.status or STATUS_PENDING, task.status or ""),
        "total_files": total,
        "done_files": task.done_files or len(done_keys),
        "failed_files": task.failed_files or 0,
        "progress": task.progress if task.progress is not None else 0,
        "error": task.error,
        "items": items if with_items else [],
        "urls": urls if with_items else [],
        "failed_keys": _safe_list(payload.get("failed_keys")),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


# ==================== 任务执行 ====================

# 进程内运行中的任务（避免同一任务被重复拉起）
_RUNNING: set[int] = set()
_RUNNING_LOCK = threading.Lock()


def spawn_task(task_id: int) -> None:
    """在后台线程运行任务（EM/EA 都是单进程部署，线程即可）"""
    threading.Thread(target=run_task, args=(task_id,), daemon=True,
                     name=f"pan115-task-{task_id}").start()


def create_task(
    db: Session,
    *,
    share_url: str,
    target_cid: str = "0",
    target_path: str = "",
    account_id: Optional[int] = None,
    library_id: Optional[int] = None,
    mode: str = MODE_RECEIVE,
    cookie: Optional[str] = None,
    created_by: Optional[int] = None,
    run_now: bool = True,
) -> "em.Pan115Task":
    """创建转存 / 下载任务

    - 解析分享链接（拿分享码与提取码）
    - **重复提交拒绝**：同一分享码仍有未结束任务时直接返回既有任务，不重复排队
    - 创建后按需在后台线程立即开跑
    """
    if mode not in MODE_LABELS:
        raise ShareLinkError(f"未知模式: {mode}")
    parsed = parse_share_link(share_url)

    existing = (
        db.query(em.Pan115Task)
        .filter(
            em.Pan115Task.share_code == parsed["share_code"],
            em.Pan115Task.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    if existing:
        existing.error = "同一分享链接已有未完成任务，已合并到该任务"
        db.commit()
        if run_now:
            spawn_task(existing.id)
        return existing

    # 有显式 Cookie 时先校验账号可用性，避免任务建好才发现没配账号
    if account_id is not None:
        resolve_cookie(db, account_id=account_id, explicit_cookie=cookie)

    task = em.Pan115Task(
        uid=uuid.uuid4().hex,
        share_url=parsed["url"],
        share_code=parsed["share_code"],
        receive_code=parsed["receive_code"],
        mode=mode,
        target_cid=target_cid or "0",
        target_path=target_path or "",
        account_id=account_id,
        library_id=library_id,
        status=STATUS_PENDING,
        created_by=created_by,
        payload=json.dumps({"items": [], "urls": [], "done_keys": [], "failed_keys": [],
                            "receive_code": parsed["receive_code"]}, ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    persist_payload(task.uid, json.loads(task.payload))

    if run_now:
        spawn_task(task.id)
    return task


def run_task(task_id: int) -> None:
    """执行单个任务（后台线程入口）

    每次都用独立 Session：请求级 Session 在请求结束后即关闭，复用会报
    \"transaction is closed\"，也会与扫描线程抢 SQLite 写锁。
    """
    with _RUNNING_LOCK:
        if task_id in _RUNNING:
            return
        _RUNNING.add(task_id)
    db = SessionLocal()
    try:
        task = db.query(em.Pan115Task).filter(em.Pan115Task.id == task_id).first()
        if not task or task.status in TERMINAL_STATUSES:
            return
        _process(db, task)
    except Exception as exc:  # noqa: BLE001 — 任务失败必须落库，不能静默
        logger.exception("115 任务 #%s 执行异常", task_id)
        try:
            task = db.query(em.Pan115Task).filter(em.Pan115Task.id == task_id).first()
            if task:
                task.status = STATUS_FAILED
                task.error = str(exc)[:1000]
                task.finished_at = datetime.now()
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
        with _RUNNING_LOCK:
            _RUNNING.discard(task_id)


def _process(db: Session, task: "em.Pan115Task") -> None:
    """任务主体：解析 Cookie → 读分享快照 → 逐个文件转存/取链 → 整理入库"""
    library = None
    if task.library_id:
        library = db.query(em.Library).filter(em.Library.id == task.library_id).first()

    cookie, source = resolve_cookie(
        db, library=library, account_id=task.account_id,
        explicit_cookie=(task_payload(task).get("cookie") or None),
    )
    if not cookie:
        # Cookie 缺失与 Cookie 失效一样：保留任务，等配置好再重试
        _mark_waiting_auth(db, task, "未配置 115 Cookie（账号配置档 / 媒体库绑定 / PAN115_COOKIE）")
        return

    payload = task_payload(task)
    payload["cookie_source"] = source

    task.status = STATUS_RUNNING
    task.error = None
    db.commit()

    client = Pan115Client(cookie)

    # 1) 分享快照（结果落库 + 落盘，重启后不必重取）
    items = _safe_list(payload.get("items"))
    if not items:
        try:
            snapshot = client.share_snapshot(task.share_code or "", task.receive_code or "")
        except Pan115AuthError as exc:
            _mark_waiting_auth(db, task, str(exc))
            return
        except Pan115Error as exc:
            _fail(db, task, f"读取分享快照失败：{exc}")
            return
        items = snapshot.get("items") or []
        payload["items"] = items
        payload["share_total"] = snapshot.get("total") or len(items)
        payload.setdefault("urls", [])
        payload.setdefault("done_keys", [])
        payload.setdefault("failed_keys", [])
        task.total_files = len(items)
        save_task_payload(db, task, payload)

    if not items:
        _fail(db, task, "分享里没有可转存的文件")
        return

    done_keys = set(_safe_list(payload.get("done_keys")))
    urls = list(_safe_list(payload.get("urls")))
    failed = 0

    # 2) 逐个文件（已完成文件跳过 —— 重启/自更新后不会重复转存）
    for entry in items:
        key = _entry_key(entry)
        if key in done_keys:
            continue
        try:
            if task.mode == MODE_DOWNLOAD:
                url = client.download_url(str(entry.get("pickcode") or ""))
                if url and url not in urls:
                    urls.append(url)
            else:
                client.receive(task.share_code or "", task.receive_code or "",
                               [str(entry.get("fid") or "")], task.target_cid or "0")
            done_keys.add(key)
            payload["done_keys"] = sorted(done_keys)
            payload["urls"] = urls
            task.done_files = len(done_keys)
            task.progress = int(len(done_keys) / max(1, len(items)) * 100)
            save_task_payload(db, task, payload)
        except Pan115AuthError as exc:
            # Cookie 中途失效：保留已完成进度，任务置等待，不丢
            payload["done_keys"] = sorted(done_keys)
            payload["urls"] = urls
            save_task_payload(db, task, payload)
            _mark_waiting_auth(db, task, str(exc))
            return
        except Pan115Error as exc:
            failed += 1
            payload.setdefault("failed_keys", [])
            payload["failed_keys"] = sorted(set(_safe_list(payload.get("failed_keys"))) | {key})
            task.failed_files = failed
            task.error = str(exc)[:1000]
            save_task_payload(db, task, payload)
            logger.warning("115 任务 #%s 文件 %s 处理失败: %s", task.id, key, exc)

    # 3) 收尾
    task.done_files = len(done_keys)
    task.failed_files = failed
    task.progress = 100 if not failed else int(len(done_keys) / max(1, len(items)) * 100)
    if failed and not done_keys:
        task.status = STATUS_FAILED
    else:
        task.status = STATUS_DONE
    task.finished_at = datetime.now()
    if failed:
        task.error = f"{failed} 个文件处理失败，可重试"
    save_task_payload(db, task, payload)

    if task.status == STATUS_DONE:
        _post_process(db, task, library)


def _entry_key(entry: dict) -> str:
    """文件稳定键：优先 fid 再 pickcode（两者都缺时退回名字 + 大小）"""
    fid = str(entry.get("fid") or "")
    if fid:
        return fid
    pickcode = str(entry.get("pickcode") or "")
    if pickcode:
        return pickcode
    return f"{entry.get('name') or ''}:{entry.get('size') or 0}"


def _mark_waiting_auth(db: Session, task: "em.Pan115Task", message: str) -> None:
    """Cookie 失效：任务保留为 waiting_auth，修好账号后重试即可继续"""
    task.status = STATUS_WAITING_AUTH
    task.error = message[:1000]
    db.commit()
    logger.warning("115 任务 #%s 等待 Cookie：%s", task.id, message)


def _fail(db: Session, task: "em.Pan115Task", message: str) -> None:
    task.status = STATUS_FAILED
    task.error = message[:1000]
    task.finished_at = datetime.now()
    db.commit()


def _post_process(db: Session, task: "em.Pan115Task", library) -> None:
    """完成后进入统一整理、扫描与入库流程（绑定媒体库时触发一次扫描）"""
    if library is None and task.library_id:
        library = db.query(em.Library).filter(em.Library.id == task.library_id).first()
    if library is None:
        return
    try:
        from backend.emby_server.scanner import LibrarySnapshot, ScanInProgress, scan_library_sync
    except Exception as exc:  # noqa: BLE001
        logger.warning("115 任务完成后无法加载扫描器: %s", exc)
        return
    snapshot = LibrarySnapshot.of(library)
    try:
        scan_library_sync(db, library, snapshot)
        logger.info("115 任务 #%s 完成后已触发媒体库「%s」扫描", task.id, library.name)
    except ScanInProgress:
        logger.info("115 任务 #%s 完成，但媒体库「%s」正在扫描中，下一轮扫描会收录", task.id, library.name)
    except Exception as exc:  # noqa: BLE001 — 触发扫描失败不影响任务本身已完成
        logger.warning("115 任务 #%s 触发扫描失败: %s", task.id, exc)


def cancel_task(db: Session, task_id: int) -> Optional["em.Pan115Task"]:
    """取消任务（终态任务不可取消）"""
    task = db.query(em.Pan115Task).filter(em.Pan115Task.id == task_id).first()
    if not task or task.status in TERMINAL_STATUSES:
        return None
    task.status = STATUS_CANCELED
    task.finished_at = datetime.now()
    db.commit()
    return task


def resume_pending_tasks() -> int:
    """启动时恢复未完成任务

    `running` 说明上次进程被强杀，拉回 `pending` 重新排队；已完成文件靠
    `payload.done_keys` 跳过，所以不会重复转存。
    """
    db = SessionLocal()
    try:
        tasks = (
            db.query(em.Pan115Task)
            .filter(em.Pan115Task.status.in_(ACTIVE_STATUSES))
            .order_by(em.Pan115Task.id)
            .all()
        )
        ids: list[int] = []
        for task in tasks:
            if task.status == STATUS_RUNNING:
                task.status = STATUS_PENDING
                task.error = "进程重启，任务已自动续跑"
            ids.append(task.id)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 表不存在时（首次升级）不应该阻塞启动
        logger.warning("恢复 115 任务失败（可忽略，若为首次升级）: %s", exc)
        return 0
    finally:
        db.close()

    for task_id in ids:
        spawn_task(task_id)
    if ids:
        logger.info("已恢复 %s 个未完成的 115 任务", len(ids))
    return len(ids)


__all__ = [
    "ACTIVE_STATUSES",
    "MODE_DOWNLOAD",
    "MODE_LABELS",
    "MODE_RECEIVE",
    "Pan115AuthError",
    "Pan115Client",
    "Pan115Error",
    "STATUS_CANCELED",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_LABELS",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_WAITING_AUTH",
    "ShareLinkError",
    "cancel_task",
    "create_task",
    "ensure_single_default",
    "normalize_cookie",
    "parse_share_link",
    "resolve_cookie",
    "resume_pending_tasks",
    "run_task",
    "serialize_task",
    "spawn_task",
    "task_payload",
    "verify_account",
]
