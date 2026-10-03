"""Google Drive 原生挂载：直接走 Drive REST v3，不经过 rclone

为什么要有这个类型（2026-10 rclone CPU 事故的根治）：

- rclone ``rcd`` 在持续 RC 调用下堆会累积到 GB 级并触发 GC 空转，历史上实测
  ``rclone 83% CPU`` 把整台机器拖垮（见提交 ``8e5ce0c`` 的事故记录）；
- 追新 ``change_watcher._rc_list()`` 直调 RC，每轮可能打上千次 ``operations/list``；
- 播放直链的 file ID 也来自 ``operations/stat``。

Google Drive 本身有完整的 REST API，``direct_url.ServiceAccountPool`` 里已经现成
做好了「服务账号轮换 + token 缓存 + 限流冷却」。所以这里直接把这两块拼起来：

    扫描列目录 → Drive files.list
    播放       → 服务器代理转发（凭据不下发；Google 的 302 真直链不可行）
    ffprobe    → 与播放同一套 resolve（走 Drive 的 alt=media）

rclone 仍然保留给 SFTP / FTP / WebDAV 等其它后端，**不在本类型的链路上**。

配置（全部落在 ``storage_mounts.config`` 这段 JSON 里，无表结构变更）：

- ``auth_mode``：``sa``（服务账号轮换池，默认）/ ``oauth``（refresh_token 换票）
- ``root_id``：Drive 文件夹 ID，留空 = My Drive 根目录（共享盘建议显式填）
- ``drive_id``：共享云端硬盘 ID；填了则按团队盘寻址
- ``api_base``：接口地址，测试或自建代理可改

> 曾经有过一个 ``direct_link`` 配置（打开则播放 302 到 Drive），已删除：重定向带不
> 过 Authorization 头，token 放 URL 会被限流（Alist / RClone / Cloudreve 也均为服务
> 端代理）。**库里已存的配置值不受影响**（不再读取，也不会报错）。

条目带 ``modTime``，所以后台「追新」对本类型同样生效（走公共通道，吃缓存与限流）。
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse
from typing import Iterator, Optional

from backend.emby_server import disc_filter
from backend.emby_server import direct_url
from backend.emby_server import file_id_cache
from backend.emby_server import mounts as mount_lib
from backend.emby_server.mount_cloud import _CloudMount
from backend.emby_server.mounts import (
    REMOTE_MEDIA_EXTS,
    MountAuthError,
    MountEntry,
    MountError,
    MountFile,
    PlayTarget,
    _is_strm_name,
    cached_listing,
)

logger = logging.getLogger(__name__)

MOUNT_GDRIVE = "gdrive"

GOOGLE_DRIVE_API = os.getenv(
    "MOUNT_GOOGLE_API", "https://www.googleapis.com/drive/v3"
).rstrip("/")

# Google Drive 的文件夹 mimeType；其余 application/vnd.google-apps.* 是原生文档
# （Docs / Sheets / Slides…），它们没有可播放的字节，必须跳过而不是当成 0 字节文件。
_DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
_DRIVE_GOOGLE_DOCS_PREFIX = "application/vnd.google-apps."

# 遍历并发：Drive 是 per-user 配额（100s/10000 次查询），不能用全局的 16。
try:
    _GDRIVE_WALK_WORKERS = max(1, min(8, int(os.getenv("GDRIVE_WALK_WORKERS", "4") or 4)))
except (TypeError, ValueError):
    _GDRIVE_WALK_WORKERS = 4

# 单次 files.list 的页大小（Drive 允许到 1000）与翻页防御上限
_PAGE_SIZE = 1000
_MAX_PAGES = 200


class GoogleDriveMount(_CloudMount):
    """Google Drive（REST v3，原生，不依赖 rclone）"""

    mount_type = MOUNT_GDRIVE
    what = "Google Drive"

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        cfg = self.config
        self.api_base = (cfg.get("api_base") or GOOGLE_DRIVE_API).strip().rstrip("/")
        self.auth_mode = (cfg.get("auth_mode") or "sa").strip().lower()
        self.root_id = (cfg.get("root_id") or "").strip()
        self.drive_id = (cfg.get("drive_id") or "").strip()
        self.sa_file = (cfg.get("sa_file") or "").strip()
        self.client_id = (cfg.get("client_id") or "").strip()
        self.client_secret = (cfg.get("client_secret") or "").strip()
        self.refresh_token = (cfg.get("refresh_token") or "").strip()
        # token 缓存（每个挂载实例一份；resolve 会被并发调用）
        self._token_value = ""
        self._token_exp = 0.0
        self._drive_root = self.root_id

    # ---------------- 令牌 ----------------

    def walk_workers(self) -> int:
        return _GDRIVE_WALK_WORKERS

    def _token(self) -> str:
        """拿一个可用的 access token（提前 5 分钟视为过期）。

        取票顺序：``oauth`` 模式用自己的 refresh_token；``sa`` 模式优先用配置里
        指定的单个服务账号，否则走 ``ServiceAccountPool`` 轮换池（多账号分摊配额，
        撞 429/403 自动冷却换号——这正是根治「跑一段时间 CPU/配额一起爆」的关键）。
        """
        now = time.time()
        if self._token_value and now < self._token_exp - 300:
            return self._token_value
        token, expiry = self._fetch_token()
        if not token:
            raise MountAuthError("拿不到 Google access_token，请检查授权方式与服务账号配置")
        self._token_value, self._token_exp = token, expiry
        return token

    def _fetch_token(self) -> tuple[str, float]:
        if self.auth_mode == "oauth":
            if not (self.client_id and self.client_secret and self.refresh_token):
                raise MountAuthError(
                    "OAuth 模式需要 client_id / client_secret / refresh_token 三项"
                )
            got = direct_url.refresh_access_token_sync(
                self.client_id, self.client_secret, self.refresh_token,
            )
            return got or ("", 0.0)
        if self.sa_file:
            try:
                got = direct_url._sa_access_token_sync(self.sa_file, self._sa_label())
            except direct_url.SARateLimited:
                raise MountAuthError("服务账号被限流，请稍后重试或改用轮换池（清空服务账号路径）")
            return got or ("", 0.0)
        got = direct_url.get_sa_pool().get_token_sync()
        return got or ("", 0.0)

    def _sa_label(self) -> str:
        return os.path.basename(self.sa_file) or "sa"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token()}",
            "User-Agent": mount_lib.MOUNT_UA,
        }

    # ---------------- 错误翻译 ----------------

    def _drive_error(self, resp, what: str) -> Optional[Exception]:
        """把 Drive 的响应翻译成挂载异常；成功返回 None。

        Drive 的 403 有好几种，处置完全不同，笼统当「权限问题」会让人查错方向：

        - ``rateLimitExceeded`` / ``userRateLimitExceeded``：配额打满，等一会儿就好；
        - ``insufficientPermissions``：账号没被共享盘接纳，改配置也没用；
        - ``storageQuotaExceeded``：用户额度满。
        """
        if resp.status_code < 400:
            return None
        reason, message = "", ""
        try:
            body = resp.json()
            err = (body or {}).get("error") or {}
            if isinstance(err, dict):
                reason = str(err.get("reason") or "")
                message = str(((err.get("errors") or [{}])[0]).get("message") or "")
        except Exception:  # noqa: BLE001 — 错误体读不出来就按状态码走
            pass
        detail = message or reason or f"HTTP {resp.status_code}"
        if resp.status_code == 401:
            return MountAuthError(f"Google Drive 拒绝了凭据（{detail}），请重新授权")
        if resp.status_code == 403:
            if reason in ("rateLimitExceeded", "userRateLimitExceeded"):
                return MountError(
                    f"Google Drive 配额已打满（{detail}）：请等配额窗口恢复，"
                    f"或在同一共享盘里加入更多服务账号分摊（填多个账号文件会让轮换池接手）"
                )
            if reason == "storageQuotaExceeded":
                return MountAuthError(f"Google Drive 账号额度已满（{detail}）")
            return MountAuthError(
                f"Google Drive 拒绝访问（{detail}）：服务账号需要被加入共享云端硬盘，"
                f"并授予「内容管理员」及以上角色"
            )
        if resp.status_code == 404:
            return MountError(f"Google Drive 上找不到{what}（{detail}），请检查目录 ID 是否正确")
        return MountError(f"Google Drive {what}失败：{detail}")

    def _api(self, path: str, params: Optional[dict] = None, *, what: str = "请求") -> dict:
        """调一次 Drive API 并把错误翻译成挂载异常。"""
        url = f"{self.api_base}{path}"
        resp = self._request("GET", url, headers=self._headers(), params=params)
        err = self._drive_error(resp, what)
        if err:
            raise err
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"Google Drive 返回了无法解析的响应: {exc}") from exc
        return body if isinstance(body, dict) else {}

    # ---------------- 目录 ----------------

    def _root_id(self) -> str:
        """挂载根的 Drive 文件夹 ID（``root`` 是 My Drive 根目录的固定别名）。"""
        if self._drive_root:
            return self._drive_root
        if self.drive_id:
            body = self._api(f"/drives/{urllib.parse.quote(self.drive_id, safe='')}",
                             {"fields": "id,name,root"}, what="读取共享云端硬盘")
            self._drive_root = str(body.get("root") or "")
            if not self._drive_root:
                raise MountError(
                    "读取共享云端硬盘根目录失败：请确认 drive_id 正确，且账号有该盘的访问权"
                )
            return self._drive_root
        self._drive_root = "root"
        return self._drive_root

    def _files_of(self, parent_id: str) -> list[dict]:
        """列一个文件夹的直属子项（翻页追完）。

        只按 **父目录 ID** 查询，不按文件名：Drive 的 ``q`` 用单引号包字符串，
        文件名里的单引号必须转义，错一个字符就是 400 或「目录不存在」——按 ID 查彻底绕开。

        ``modTime`` 一起取：追新（``change_watcher``）靠条目的 ``mod_ts`` 做
        「新增」窗口过滤，不取就等于这一类挂载永远检不出新文件（静默漏检）。
        """
        items: list[dict] = []
        page = ""
        for _ in range(_MAX_PAGES):
            params = {
                "q": f"'{parent_id}' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,size,mimeType,modifiedTime)",
                "pageSize": str(_PAGE_SIZE),
                # 共享云端硬盘必需：缺了这两个参数会「能列目录但打不开文件」
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if self.drive_id:
                params["corpora"] = "drive"
                params["driveId"] = self.drive_id
            if page:
                params["pageToken"] = page
            body = self._api("/files", params, what="列目录")
            for item in body.get("files") or []:
                if isinstance(item, dict) and item.get("id"):
                    items.append(item)
            page = str(body.get("nextPageToken") or "")
            if not page:
                break
        return items

    def _parent_id(self, rel: str) -> str:
        """相对挂载根的目录 → Drive 文件夹 ID。

        **逐级下钻**，不走「一次 files.list 把整棵树拉回来」：Drive 不支持按路径查，
        而逐级下钻正好命中 ``cached_listing`` 的目录缓存——扫描时同一个目录只查一次。
        """
        node = self._root_id()
        for seg in [s for s in (rel or "").strip("/").split("/") if s]:
            hit = next(
                (it for it in self._files_of(node)
                 if not self._is_doc(it) and str(it.get("name") or "") == seg
                 and str(it.get("mimeType") or "") == _DRIVE_FOLDER_MIME),
                None,
            )
            if hit is None:
                raise MountError(f"Google Drive 上找不到目录: /{seg}")
            node = str(hit["id"])
        return node

    @staticmethod
    def _is_doc(item: dict) -> bool:
        """Google 原生文档（Docs/Sheets…）不可播放，也不该出现在浏览列表里。

        **文件夹必须先排除**：Drive 的文件夹 mimeType 恰好就是
        ``application/vnd.google-apps.folder``，它是原生文档命名空间的前缀——
        用 ``startswith`` 判一次会把**所有文件夹**当成文档，扫描立刻扫不出任何东西。
        """
        mime = str(item.get("mimeType") or "")
        if mime == _DRIVE_FOLDER_MIME:
            return False
        return mime.startswith(_DRIVE_GOOGLE_DOCS_PREFIX)

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        base_rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        parent_id = self._parent_id(base_rel)
        entries: list[MountEntry] = []
        for item in self._files_of(parent_id):
            if self._is_doc(item):
                continue
            name = str(item.get("name") or "")
            if not name:
                continue
            is_dir = str(item.get("mimeType") or "") == _DRIVE_FOLDER_MIME
            entries.append(MountEntry(
                name=name,
                rel=f"{base_rel}/{name}" if base_rel != "/" else f"/{name}",
                is_dir=is_dir,
                size=0 if is_dir else int(item.get("size") or 0),
                # file id 放进 entry_id：解析播放目标时靠它在父目录里定位文件，
                # 于是播放不需要再问 Drive「这个路径对应哪个文件」。
                entry_id=str(item.get("id") or ""),
                # modifiedTime 走公共通道的 parse_mod_ts（Drive 给的是 RFC3339，
                # 精度写法与 rclone 不同，统一由那一个函数处理）
                mod_ts=mount_lib.parse_mod_ts(item.get("modifiedTime")),
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def _locate(self, rel: str) -> dict:
        """按相对路径找到文件项（复用目录缓存，通常零请求）"""
        clean = "/" + (rel or "").lstrip("/")
        parent, _, name = clean.rpartition("/")
        for entry in self.list_dir(parent or "/"):
            if entry.name == name and not entry.is_dir:
                return {"id": entry.entry_id, "name": entry.name, "size": entry.size}
        raise MountError(f"Google Drive 上找不到文件: {clean}")

    # ---------------- 播放 ----------------

    def _file_url(self, file_id: str) -> str:
        """文件字节地址（不带凭据）。

        凭据走 ``_headers()`` 的 Authorization 头，由本服务代理转发时带上。
        """
        params = {"alt": "media", "supportsAllDrives": "true"}
        return f"{self.api_base}/files/{urllib.parse.quote(file_id, safe='')}?" + \
            urllib.parse.urlencode(params)

    def resolve(self, rel: str) -> PlayTarget:
        """解析成播放目标。

        始终返回带 Bearer 头的服务器代理形态（凭据不下发，播放层也没有 302 分支）。

        **秒开靠的是 file id 持久化缓存**：``_locate`` 在目录缓存冷了之后要走
        ``_parent_id`` 逐级下钻，4 层目录就是 4~5 次 Drive 请求（1~2 秒）。这里先问
        ``file_id_cache``（库里的「挂载 + 相对路径 → file id」），命中就**一次 API 都
        不调**直接拼地址；没命中才走原来的逐级下钻，并把结果写回缓存。

        取 token 的路径**一字未改**（``self._token()`` 每次现取）——缓存里只有 file id，
        没有凭据。
        """
        clean = "/" + (rel or "").lstrip("/")
        mount_id = getattr(self.mount, "id", 0) or 0
        file_id = file_id_cache.lookup(self.db, mount_id, clean) if mount_id else ""
        from_cache = bool(file_id)
        if file_id:
            entry = {"id": file_id, "size": 0}
        else:
            entry = self._locate(clean)
            if mount_id:
                file_id_cache.store(self.db, mount_id, clean, entry["id"], entry.get("size", 0))
        target = PlayTarget("url", self._file_url(entry["id"]), self._headers())
        target.from_file_id_cache = from_cache
        return target

    def walk_media(self, max_depth: int = 32, root: str = "/") -> Iterator[MountFile]:
        """遍历媒体文件（并发由 ``walk_workers`` 限到 Drive 配额的舒适区）。

        结构与 ``_CloudMount.walk_media`` 一致（原盘目录剪枝 / 文件去重 / 子目录失败不中断），
        这里只多一件事：**跳过 Google 原生文档**——它们 mimeType 以
        ``application/vnd.google-apps.`` 开头、没有可播放字节，扩展名也没有意义。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        self.list_dir(root)
        seen: set[str] = {root}
        current = [(root, 0)]
        seen_files: set[str] = set()
        workers = self.walk_workers() if hasattr(self, "walk_workers") else _GDRIVE_WALK_WORKERS
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="walk-gdrive") as pool:
            while current:
                fut_to_dir = {
                    pool.submit(self._entries, rel): (rel, depth)
                    for rel, depth in current
                }
                current = []
                for fut in as_completed(fut_to_dir):
                    rel, depth = fut_to_dir[fut]
                    try:
                        entries = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Google Drive 并行列目录失败 %s: %s", rel, exc)
                        continue
                    for entry in entries:
                        if entry.is_dir:
                            if disc_filter.is_disc_subtree_dir(entry.name):
                                continue
                            if depth < max_depth and entry.rel not in seen:
                                seen.add(entry.rel)
                                current.append((entry.rel, depth + 1))
                            continue
                        if os.path.splitext(entry.name)[1].lower() not in REMOTE_MEDIA_EXTS:
                            continue
                        if entry.rel in seen_files:
                            logger.debug("Google Drive 遍历跳过重复文件条目：%s", entry.rel)
                            continue
                        seen_files.add(entry.rel)
                        yield MountFile(rel=entry.rel, name=entry.name, size=entry.size,
                                        is_strm=_is_strm_name(entry.name))

    # ---------------- 连通性 ----------------

    def test(self) -> dict:
        root_id = self._root_id()
        entries = self.list_dir("/")
        body = self._api(f"/files/{urllib.parse.quote(root_id, safe='')}",
                         {"fields": "id,name,mimeType", "supportsAllDrives": "true"},
                         what="读取根目录")
        where = body.get("name") or ("My Drive 根目录" if root_id == "root" else root_id)
        auth = "服务账号轮换池" if self.auth_mode != "oauth" else "OAuth refresh_token"
        return {
            "ok": True,
            "message": f"Google Drive 可访问（{where} 下 {len(entries)} 项，授权：{auth}）",
            "root_id": root_id,
            "drive_id": self.drive_id,
        }


MOUNT_TYPE_ENTRIES: list[dict] = [
    {
        "value": MOUNT_GDRIVE,
        "label": "Google Drive（原生）",
        "kind": "remote",
        "group": "cloud",
        "hint": "直接走 Google Drive 接口，不需要 rclone / rclone-serve 容器。"
                "支持服务账号轮换池（多个账号分摊配额，撞限流自动换号）与 OAuth "
                "refresh_token 两种授权；共享云端硬盘需填 drive_id。",
        "needs_path": False,
        "browse": True,
        "root_key": "root_id",
        "fields": [
            {"key": "auth_mode", "label": "授权方式", "type": "select",
             "options": [
                 {"label": "服务账号轮换池（推荐）", "value": "sa"},
                 {"label": "OAuth refresh_token", "value": "oauth"},
             ],
             "required": True},
            {"key": "root_id", "label": "根目录 ID", "placeholder": "留空 = My Drive 根目录",
             "hint": "填 Drive 文件夹 ID；可用后面的「浏览」选目录自动回填。"},
            {"key": "drive_id", "label": "共享云端硬盘 ID（可选）",
             "hint": "填了按团队盘寻址（corpora=drive）；共享盘务必填写。"},
            {"key": "sa_file", "label": "单个服务账号 JSON 路径（可选）",
             "placeholder": "/sa-accounts/sa-1.json",
             "hint": "留空 = 用整个服务账号目录做轮换池（配额分散，限流自动换号）。"
                     "这是路径不是密钥，不会被脱敏。"},
            {"key": "client_id", "label": "client_id（OAuth 模式）"},
            {"key": "client_secret", "label": "client_secret（OAuth 模式）", "secret": True},
            {"key": "refresh_token", "label": "refresh_token（OAuth 模式）", "secret": True},
            {"key": "api_base", "label": "接口地址（可选）",
             "placeholder": "https://www.googleapis.com/drive/v3"},
        ],
    },
]

PROVIDERS = {MOUNT_GDRIVE: GoogleDriveMount}


def register() -> None:
    """注册挂载类型与提供者（幂等）"""
    mount_lib.register_mount_types(MOUNT_TYPE_ENTRIES)
    mount_lib.register_providers(PROVIDERS)
    logger.debug("已注册 Google Drive 原生挂载类型")


register()