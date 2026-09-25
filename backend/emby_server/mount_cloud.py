"""云端挂载类型：S3 / 阿里云盘 / 夸克网盘 / OneDrive

这些类型和 ``mounts.py`` 里的 ``115`` / ``webdav`` / ``alist`` 是同一种东西——
**把内容直接挂到媒体库上的方式**。区别只在「怎么列目录」和「怎么把文件换成直链」：

- 条目路径仍然是 ``mount://<挂载 id>/<相对路径>``，凭据只留在服务器；
- 播放时由 EA 按 Range 代理转发，客户端看到的始终是本服务器地址；
- 扫描探测（ffprobe）与播放走同一套 ``resolve``，不会出现「扫得到、播不了」。

本模块只负责「提供者」，不碰数据库与路由：类型元数据与提供者通过
``register_mount_types`` / ``register_providers`` 注册进 ``mounts`` 注册表，
后台下拉、表单字段、必填校验、密钥脱敏、目录浏览都会自动认这些新类型。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Iterator, Optional

from backend.emby_server import mounts as mount_lib
from backend.emby_server.mounts import (
    REMOTE_MEDIA_EXTS,
    MountAuthError,
    MountEntry,
    MountError,
    MountFile,
    MountProvider,
    PlayTarget,
    _is_strm_name,
    cached_listing,
)

logger = logging.getLogger(__name__)

MOUNT_S3 = "s3"
MOUNT_ALIYUN = "aliyun"
MOUNT_QUARK = "quark"
MOUNT_ONEDRIVE = "onedrive"

# 各云端的默认入口（可在挂载配置里覆盖，方便自建/换线路）
S3_REGION_DEFAULT = os.getenv("MOUNT_S3_REGION", "us-east-1")
ALIYUN_ENDPOINT = os.getenv("MOUNT_ALIYUN_ENDPOINT", "https://openapi.alipan.com")
ALIYUN_AUTH_URL = os.getenv("MOUNT_ALIYUN_AUTH_URL", "https://auth.aliyundrive.com/v2/account/token")
QUARK_BASE = os.getenv("MOUNT_QUARK_BASE", "https://drive-pc.quark.cn/1/clouddrive")
GRAPH_BASE = os.getenv("MOUNT_GRAPH_BASE", "https://graph.microsoft.com/v1.0")
GRAPH_TOKEN_URL = os.getenv(
    "MOUNT_GRAPH_TOKEN_URL", "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
)

# 夸克 PC 端的 UA；网盘对 UA 有要求，带上更稳
QUARK_UA = os.getenv(
    "MOUNT_QUARK_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
)

# 网盘接口里「需要重新配置凭据」的错误码（夸克）
QUARK_AUTH_CODES = {31001, 31023, 31024, 31066}


def _join(*parts: str) -> str:
    """把若干路径片段拼成 ``a/b/c``（去空、去重斜杠）"""
    out: list[str] = []
    for part in parts:
        for piece in str(part or "").split("/"):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return "/".join(out)


# ==================== S3 签名（SigV4，纯标准库）====================

def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def s3_presign(
    url: str,
    params: Optional[dict] = None,
    access_key: str = "",
    secret_key: str = "",
    region: str = S3_REGION_DEFAULT,
    session_token: str = "",
    expires: int = 900,
    now: Optional[datetime] = None,
) -> str:
    """S3 兼容存储的 SigV4 预签名 URL

    只签 ``host``，载荷哈希用 ``UNSIGNED-PAYLOAD``——列目录和取对象都能用同一个函数，
    不需要引入 boto3，也不需要在请求头里放签名（代理转发时更好处理）。
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    canonical_uri = parsed.path or "/"
    moment = now or datetime.now(timezone.utc)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    datestamp = moment.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/s3/aws4_request"

    query = {k: str(v) for k, v in (params or {}).items()}
    query.update({
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(int(expires)),
        "X-Amz-SignedHeaders": "host",
    })
    if session_token:
        query["X-Amz-Security-Token"] = session_token

    pairs = sorted(
        (urllib.parse.quote(k, safe="-_.~"), urllib.parse.quote(v, safe="-_.~"))
        for k, v in query.items()
    )
    canonical_query = "&".join(f"{k}={v}" for k, v in pairs)
    canonical_request = "\n".join([
        "GET", canonical_uri, canonical_query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD",
    ])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signing_key = _hmac(
        _hmac(_hmac(_hmac(f"AWS4{secret_key}".encode("utf-8"), datestamp), region), "s3"),
        "aws4_request",
    )
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{url}?{canonical_query}&X-Amz-Signature={signature}"


def _xml_child(node, name: str):
    for child in list(node):
        if child.tag.split("}")[-1] == name:
            return child
    return None


def _xml_children(node, name: str) -> list:
    return [c for c in list(node) if c.tag.split("}")[-1] == name]


def _xml_text(node, name: str, default: str = "") -> str:
    child = _xml_child(node, name)
    return (child.text or "").strip() if child is not None else default


# ==================== 公共基类 ====================

class _CloudMount(MountProvider):
    """云端挂载基类：统一 HTTP 调用、错误翻译与递归扫描"""

    kind = "remote"
    #: 出错提示里用的名字（如「阿里云盘」）
    what = "云端存储"

    def _client(self, follow_redirects: bool = True):
        import httpx

        return httpx.Client(timeout=mount_lib.MOUNT_TIMEOUT, follow_redirects=follow_redirects)

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        data: Optional[dict] = None,
        follow_redirects: bool = True,
    ):
        try:
            with self._client(follow_redirects) as client:
                return client.request(
                    method, url, headers=headers or {}, params=params,
                    json=json_body, data=data,
                )
        except Exception as exc:  # noqa: BLE001 — 网络层异常统一成可读提示
            raise MountError(f"连接{self.what}失败: {exc}") from exc

    def _request_json(self, method: str, url: str, **kwargs) -> dict:
        resp = self._request(method, url, **kwargs)
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"{self.what}返回了无法解析的响应: {exc}") from exc
        return body if isinstance(body, dict) else {}

    def _entries(self, rel: str) -> list[MountEntry]:
        """列目录；**子目录**读不到时只记日志不中断整库扫描

        根目录失败仍然抛错（扫描据此判定来源不可用并跳过清理），但一个没权限的子目录
        不应该让整个媒体库扫不完。
        """
        try:
            return self.list_dir(rel)
        except MountError as exc:
            if rel in ("", "/"):
                raise
            logger.warning("%s 子目录读取失败，跳过: %s (%s)", self.what, rel, exc)
            return []

    def walk_media(self, max_depth: int = 32, root: str = "/") -> Iterator[MountFile]:
        """远程挂载的通用遍历：靠 ``list_dir`` 递归，自动跳过过深目录

        ``root`` 为挂载内的起始子目录（"/" = 整个挂载）；产出的 ``rel`` 始终是
        挂载根相对路径，与 ``root`` 无关。

        起始目录读不到时直接抛错（不吞掉）：上层按「来源不可用」处理并跳过清理，
        避免把「读不到」当成「文件已删除」而误删条目。
        """
        self.list_dir(root)
        stack: list[tuple[str, int]] = [(root, 0)]
        seen: set[str] = set()
        # 文件级去重：rclone lsjson 偶发在单次列举里返回同一文件两次（网盘侧重复
        # 条目 / 分页异常；2026-09-25 生产事故：同一 mkv 被产出两次，扫描器在同一
        # 事务内两次 INSERT 撞 emby_items.guid 唯一键、整库扫描 abort）。扫描器在
        # _prepare_and_prefetch 按 guid 去重兜底，这里在源头先拦一道，也省掉重复
        # 的 ffprobe 与 TMDB 预取。rel 全局唯一，误杀不了正常文件。
        seen_files: set[str] = set()
        while stack:
            rel, depth = stack.pop()
            if rel in seen:
                continue
            seen.add(rel)
            for entry in self._entries(rel):
                if entry.is_dir:
                    if depth < max_depth:
                        stack.append((entry.rel, depth + 1))
                    continue
                if os.path.splitext(entry.name)[1].lower() not in REMOTE_MEDIA_EXTS:
                    continue
                if entry.rel in seen_files:
                    logger.debug("%s 遍历跳过重复文件条目：%s", self.what, entry.rel)
                    continue
                seen_files.add(entry.rel)
                yield MountFile(rel=entry.rel, name=entry.name, size=entry.size,
                                is_strm=_is_strm_name(entry.name))

    def read_text(self, rel: str) -> str:
        """默认实现：解析成直链后把内容当文本读（用于 .strm 与字幕）"""
        target = self.resolve(rel)
        resp = self._request("GET", target.value, headers=target.headers)
        return resp.content.decode("utf-8", errors="ignore")


# ==================== S3 兼容对象存储 ====================

class S3Mount(_CloudMount):
    """S3 兼容对象存储（AWS S3 / MinIO / Cloudflare R2 / Backblaze B2）"""

    mount_type = MOUNT_S3
    what = "对象存储"

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        cfg = self.config
        self.endpoint = (cfg.get("endpoint") or "").strip().rstrip("/")
        self.bucket = (cfg.get("bucket") or "").strip().strip("/")
        self.region = (cfg.get("region") or S3_REGION_DEFAULT).strip() or S3_REGION_DEFAULT
        self.prefix = (cfg.get("prefix") or "").strip().strip("/")
        self.access_key = (cfg.get("access_key") or "").strip()
        self.secret_key = (cfg.get("secret_key") or "").strip()
        self.session_token = (cfg.get("session_token") or "").strip()
        self.path_style = str(cfg.get("path_style") or "true").strip().lower() not in ("false", "0", "no")

    # ---- 基础 ----

    def _require(self) -> str:
        if not self.endpoint.startswith(("http://", "https://")):
            raise MountError("Endpoint 必须以 http:// 或 https:// 开头")
        if not self.bucket:
            raise MountError("请填写存储桶（Bucket）")
        if not self.access_key or not self.secret_key:
            raise MountAuthError("请填写 Access Key / Secret Key")
        if not self.region:
            raise MountError("请填写区域（Region），自建服务填 us-east-1 即可")
        return self.endpoint

    def _base_url(self) -> str:
        parsed = urllib.parse.urlsplit(self._require())
        if self.path_style:
            return f"{parsed.scheme}://{parsed.netloc}/{self.bucket}"
        return f"{parsed.scheme}://{self.bucket}.{parsed.netloc}"

    def _sign(self, url: str, params: Optional[dict] = None, expires: int = 900) -> str:
        return s3_presign(
            url, params, self.access_key, self.secret_key, self.region,
            self.session_token, expires,
        )

    def _key(self, rel: str) -> str:
        """相对路径 → 对象键（挂载根对应配置里的 prefix）"""
        return _join(self.prefix, (rel or "").lstrip("/"))

    def _object_url(self, rel: str) -> str:
        key = self._key(rel)
        if not key:
            raise MountError("无法解析对象键（挂载根不是文件）")
        return f"{self._base_url()}/{urllib.parse.quote(key, safe='/-_.~')}"

    # ---- 列目录 ----

    def _list_prefix(self, prefix: str) -> tuple[list[tuple[str, int]], list[str]]:
        files: list[tuple[str, int]] = []
        dirs: list[str] = []
        token = ""
        for _ in range(100):  # 防御性上限：异常响应不会把扫描拖死
            params = {"list-type": "2", "max-keys": "1000", "delimiter": "/"}
            if prefix:
                params["prefix"] = prefix
            if token:
                params["continuation-token"] = token
            resp = self._request("GET", self._sign(self._base_url() + "/", params, 300),
                                 headers={"User-Agent": mount_lib.MOUNT_UA})
            if resp.status_code in (401, 403):
                raise MountAuthError(f"对象存储拒绝访问（HTTP {resp.status_code}），请检查密钥与桶权限")
            if resp.status_code == 404:
                raise MountError("存储桶不存在（HTTP 404），请检查 Bucket 与 Endpoint")
            if resp.status_code >= 400:
                raise MountError(f"对象存储返回 HTTP {resp.status_code}")
            try:
                root = ET.fromstring(resp.content or b"<ListBucketResult/>")
            except ET.ParseError as exc:
                raise MountError(f"对象存储返回了无法解析的响应: {exc}") from exc
            for node in _xml_children(root, "Contents"):
                key = _xml_text(node, "Key")
                if key and not key.endswith("/"):
                    try:
                        size = int(_xml_text(node, "Size", "0") or 0)
                    except ValueError:
                        size = 0
                    files.append((key, size))
            for node in _xml_children(root, "CommonPrefixes"):
                child = _xml_text(node, "Prefix")
                if child:
                    dirs.append(child)
            if _xml_text(root, "IsTruncated").lower() != "true":
                break
            token = _xml_text(root, "NextContinuationToken")
            if not token:
                break
        return files, dirs

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        base_rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        prefix = self._key(base_rel)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        files, dirs = self._list_prefix(prefix)
        entries: list[MountEntry] = []
        for item in dirs:
            name = item[len(prefix):].rstrip("/")
            if not name or "/" in name:
                continue
            entries.append(MountEntry(
                name=name, rel=f"{base_rel}/{name}" if base_rel != "/" else f"/{name}",
                is_dir=True, entry_id=item,
            ))
        for key, size in files:
            name = key[len(prefix):]
            if not name or "/" in name:
                continue
            entries.append(MountEntry(
                name=name, rel=f"{base_rel}/{name}" if base_rel != "/" else f"/{name}",
                is_dir=False, size=size,
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def test(self) -> dict:
        prefix = f"{self.prefix}/" if self.prefix else ""
        files, dirs = self._list_prefix(prefix)
        where = f"{self.bucket}/{self.prefix}" if self.prefix else self.bucket
        return {"ok": True, "message": f"对象存储可访问（{where} 下 {len(files) + len(dirs)} 项）", "bucket": self.bucket}

    def resolve(self, rel: str) -> PlayTarget:
        return PlayTarget("url", self._sign(self._object_url(rel), None, 3600),
                          {"User-Agent": mount_lib.MOUNT_UA})


# ==================== 阿里云盘 ====================

class AliyunMount(_CloudMount):
    """阿里云盘（Open API）

    两种凭据都支持：
    - ``refresh_token``：启动/需要时用官方接口换 ``access_token``（自动续期，推荐）；
    - ``access_token``：直接给一个短期令牌（会被动失效，适合临时用）。
    填了 ``client_id`` / ``client_secret`` 时走开放平台换票，否则走网页版换票接口。
    """

    mount_type = MOUNT_ALIYUN
    what = "阿里云盘"

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        cfg = self.config
        self.endpoint = (cfg.get("endpoint") or ALIYUN_ENDPOINT).strip().rstrip("/") or ALIYUN_ENDPOINT
        self.refresh_token = (cfg.get("refresh_token") or "").strip()
        self.access_token = (cfg.get("access_token") or "").strip()
        self.client_id = (cfg.get("client_id") or "").strip()
        self.client_secret = (cfg.get("client_secret") or "").strip()
        self.drive_id = str(cfg.get("drive_id") or "").strip()
        self.root_fid = str(cfg.get("file_id") or "").strip() or "root"
        self._expires_at = 0.0
        self._fid_cache: dict[str, str] = {"": self.root_fid, "/": self.root_fid}

    # ---- 令牌 ----

    def _refresh(self) -> str:
        if not self.refresh_token:
            raise MountAuthError("请填写 refresh_token（或未过期的 access_token）")
        payload = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        url = ALIYUN_AUTH_URL
        if self.client_id and self.client_secret:
            url = f"{self.endpoint}/oauth/access_token"
            payload.update({"client_id": self.client_id, "client_secret": self.client_secret})
        resp = self._request("POST", url, json_body=payload,
                             headers={"Content-Type": "application/json", "User-Agent": mount_lib.MOUNT_UA})
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"阿里云盘换票返回了无法解析的响应: {exc}") from exc
        if resp.status_code >= 400 or not isinstance(body, dict) or not body.get("access_token"):
            message = str((body or {}).get("message") or (body or {}).get("error_description") or f"HTTP {resp.status_code}")
            raise MountAuthError(f"阿里云盘换票失败: {message}")
        self.access_token = str(body.get("access_token") or "")
        self._expires_at = time.time() + float(body.get("expires_in") or 7200)
        if not self.drive_id:
            self.drive_id = str(body.get("default_drive_id") or body.get("drive_id") or "")
        return self.access_token

    def _token(self) -> str:
        if self.access_token and not self.refresh_token:
            return self.access_token
        if self.access_token and time.time() < self._expires_at - 60:
            return self.access_token
        return self._refresh()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
            "User-Agent": mount_lib.MOUNT_UA,
            # 开放平台对客户端标识有校验，带上更稳（缺了部分接口会 400）
            "X-Canary": "client=web,app=adrive,version=v4.9.0",
        }

    def _drive(self) -> str:
        if not self.drive_id:
            self._token()
        if not self.drive_id:
            raise MountError("未解析到 drive_id，请在挂载配置里填写")
        return self.drive_id

    def _api(self, path: str, payload: dict) -> dict:
        resp = self._request("POST", f"{self.endpoint}{path}", headers=self._headers(), json_body=payload)
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"阿里云盘返回了无法解析的响应: {exc}") from exc
        if resp.status_code in (401, 403):
            raise MountAuthError(f"阿里云盘拒绝访问（HTTP {resp.status_code}），请重新获取 refresh_token")
        if resp.status_code >= 400 or not isinstance(body, dict):
            message = str((body or {}).get("message") or f"HTTP {resp.status_code}") if isinstance(body, dict) else f"HTTP {resp.status_code}"
            code = str((body or {}).get("code") or "") if isinstance(body, dict) else ""
            if "token" in code.lower() or "token" in message.lower() or "登录" in message:
                raise MountAuthError(f"阿里云盘凭据失效: {message}")
            raise MountError(f"阿里云盘: {message}")
        return body

    # ---- 目录 ----

    def _children(self, file_id: str) -> list[dict]:
        items: list[dict] = []
        marker = ""
        for _ in range(200):
            payload = {
                "drive_id": self._drive(), "parent_file_id": file_id or self.root_fid,
                "limit": 100, "marker": marker, "order_by": "name", "order_direction": "ASC",
                "url_expire_sec": 14400,
            }
            body = self._api("/adrive/v1.0/openFile/list", payload)
            batch = body.get("items")
            items.extend([i for i in (batch or []) if isinstance(i, dict)])
            marker = str(body.get("next_marker") or "")
            if not marker:
                break
        return items

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        fid = self._fid_of(rel)
        base_rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        entries: list[MountEntry] = []
        for item in self._children(fid):
            name = str(item.get("name") or "")
            if not name:
                continue
            is_dir = str(item.get("type") or "") == "folder"
            child_rel = f"{base_rel}/{name}" if base_rel != "/" else f"/{name}"
            if is_dir:
                self._fid_cache[child_rel] = str(item.get("file_id") or "")
            entries.append(MountEntry(
                name=name, rel=child_rel, is_dir=is_dir,
                size=int(item.get("size") or 0), entry_id=str(item.get("file_id") or ""),
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def _fid_of(self, rel: str) -> str:
        rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        if self._fid_cache.get(rel):
            return self._fid_cache[rel]
        fid = self.root_fid
        for part in [p for p in rel.split("/") if p]:
            child = next(
                (i for i in self._children(fid)
                 if str(i.get("name") or "") == part and str(i.get("type") or "") == "folder"),
                None,
            )
            if child is None:
                raise MountError(f"阿里云盘上找不到目录: {rel}")
            fid = str(child.get("file_id") or "")
        self._fid_cache[rel] = fid
        return fid

    def _file_id_of(self, rel: str) -> str:
        parent, _, name = ("/" + (rel or "").lstrip("/")).rpartition("/")
        for item in self._children(self._fid_of(parent or "/")):
            if str(item.get("name") or "") == name:
                return str(item.get("file_id") or "")
        raise MountError(f"阿里云盘上找不到文件: {rel}")

    def test(self) -> dict:
        children = self._children(self.root_fid)
        where = "根目录" if self.root_fid == "root" else f"目录 {self.root_fid}"
        return {"ok": True, "message": f"阿里云盘可访问（{where} 下 {len(children)} 项）, drive={self._drive()}"}

    def resolve(self, rel: str) -> PlayTarget:
        body = self._api("/adrive/v1.0/openFile/getDownloadUrl", {
            "drive_id": self._drive(), "file_id": self._file_id_of(rel), "expire_sec": 900,
        })
        url = str(body.get("url") or "")
        if not url:
            raise MountError(f"阿里云盘未返回直链: {rel}")
        return PlayTarget("url", url, {
            "User-Agent": mount_lib.MOUNT_UA,
            "Referer": "https://www.aliyundrive.com/",
        })


# ==================== 夸克网盘 ====================

class QuarkMount(_CloudMount):
    """夸克网盘（Cookie 型 API，不需要把网盘挂到本机）"""

    mount_type = MOUNT_QUARK
    what = "夸克网盘"

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        cfg = self.config
        self.base = (cfg.get("endpoint") or QUARK_BASE).strip().rstrip("/") or QUARK_BASE
        self.cookie = (cfg.get("cookie") or "").strip()
        self.root_fid = str(cfg.get("pdir_fid") or "").strip() or "0"
        self._fid_cache: dict[str, str] = {"": self.root_fid, "/": self.root_fid}

    def _headers(self) -> dict:
        if not self.cookie:
            raise MountAuthError("请填写夸克 Cookie（浏览器登录 pan.quark.cn 后复制）")
        return {
            "Cookie": self.cookie,
            "User-Agent": QUARK_UA,
            "Referer": "https://pan.quark.cn/",
            "Accept": "application/json, text/plain, */*",
        }

    def _params(self, **extra) -> dict:
        params = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}
        params.update({k: v for k, v in extra.items() if v not in (None, "")})
        return params

    def _get(self, path: str, **params) -> dict:
        body = self._request_json("GET", f"{self.base}{path}", headers=self._headers(),
                                  params=self._params(**params))
        return self._check(body)

    def _post(self, path: str, payload: dict) -> dict:
        body = self._request_json("POST", f"{self.base}{path}", headers=self._headers(),
                                  params=self._params(), json_body=payload)
        return self._check(body)

    def _check(self, body: dict) -> dict:
        code = body.get("code")
        status = body.get("status")
        if code in QUARK_AUTH_CODES or status == 401:
            raise MountAuthError(f"夸克 Cookie 失效或权限不足（code={code}）")
        if code not in (0, None) or (status not in (200, None)):
            message = str(body.get("message") or f"code={code}")
            if "登录" in message or "cookie" in message.lower():
                raise MountAuthError(f"夸克网盘: {message}")
            raise MountError(f"夸克网盘: {message}")
        return body

    def _items(self, fid: str) -> list[dict]:
        out: list[dict] = []
        page = 1
        while page <= 200:
            body = self._get("/file/sort", pdir_fid=fid or self.root_fid, _page=page,
                             _size=200, _fetch_total=1, _sort="file_type:asc,file_name:asc")
            data = body.get("data") or {}
            batch = data.get("list") if isinstance(data, dict) else None
            out.extend([i for i in (batch or []) if isinstance(i, dict)])
            total = 0
            meta = data.get("metadata") if isinstance(data, dict) else {}
            if isinstance(meta, dict):
                total = int(meta.get("_total") or 0)
            if not batch or len(out) >= total:
                break
            page += 1
        return out

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        fid = self._fid_of(rel)
        base_rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        entries: list[MountEntry] = []
        for item in self._items(fid):
            name = str(item.get("file_name") or "")
            if not name:
                continue
            is_dir = bool(item.get("dir"))
            child_rel = f"{base_rel}/{name}" if base_rel != "/" else f"/{name}"
            if is_dir:
                self._fid_cache[child_rel] = str(item.get("fid") or "")
            entries.append(MountEntry(
                name=name, rel=child_rel, is_dir=is_dir,
                size=int(item.get("size") or 0), entry_id=str(item.get("fid") or ""),
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def _fid_of(self, rel: str) -> str:
        rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        if self._fid_cache.get(rel):
            return self._fid_cache[rel]
        fid = self.root_fid
        for part in [p for p in rel.split("/") if p]:
            child = next(
                (i for i in self._items(fid)
                 if str(i.get("file_name") or "") == part and bool(i.get("dir"))),
                None,
            )
            if child is None:
                raise MountError(f"夸克网盘上找不到目录: {rel}")
            fid = str(child.get("fid") or "")
        self._fid_cache[rel] = fid
        return fid

    def _fid_of_file(self, rel: str) -> str:
        parent, _, name = ("/" + (rel or "").lstrip("/")).rpartition("/")
        for item in self._items(self._fid_of(parent or "/")):
            if str(item.get("file_name") or "") == name:
                return str(item.get("fid") or "")
        raise MountError(f"夸克网盘上找不到文件: {rel}")

    def test(self) -> dict:
        items = self._items(self.root_fid)
        where = "根目录" if self.root_fid == "0" else f"目录 {self.root_fid}"
        return {"ok": True, "message": f"夸克 Cookie 有效（{where} 下 {len(items)} 项）"}

    def resolve(self, rel: str) -> PlayTarget:
        body = self._post("/file/download", {"fids": [self._fid_of_file(rel)]})
        data = body.get("data")
        first = data[0] if isinstance(data, list) and data else {}
        url = str((first or {}).get("download_url") or "")
        if not url:
            raise MountError(f"夸克未返回直链: {rel}")
        return PlayTarget("url", url, {
            "User-Agent": QUARK_UA, "Referer": "https://pan.quark.cn/", "Cookie": self.cookie,
        })


# ==================== OneDrive（Microsoft Graph）====================

class OneDriveMount(_CloudMount):
    """OneDrive / SharePoint（Microsoft Graph）

    用 ``refresh_token`` + 应用 ``client_id`` 换 access_token；目录用 Graph 的路径寻址
    （``/root:/目录/子目录:/children``），所以不需要缓存 file id。
    """

    mount_type = MOUNT_ONEDRIVE
    what = "OneDrive"

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        cfg = self.config
        self.refresh_token = (cfg.get("refresh_token") or "").strip()
        self.client_id = (cfg.get("client_id") or "").strip()
        self.tenant = (cfg.get("tenant") or "common").strip() or "common"
        self.root_path = (cfg.get("path") or "").strip().strip("/")
        self.access_token = ""
        self._expires_at = 0.0

    def _token(self) -> str:
        if self.access_token and time.time() < self._expires_at - 60:
            return self.access_token
        if not self.refresh_token or not self.client_id:
            raise MountAuthError("请填写 OneDrive 应用 client_id 与 refresh_token")
        resp = self._request(
            "POST", GRAPH_TOKEN_URL.format(tenant=self.tenant),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": self.client_id, "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "scope": "https://graph.microsoft.com/.default offline_access",
            },
        )
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"OneDrive 换票返回了无法解析的响应: {exc}") from exc
        if resp.status_code >= 400 or not isinstance(body, dict) or not body.get("access_token"):
            message = str((body or {}).get("error_description") or (body or {}).get("error") or f"HTTP {resp.status_code}")
            raise MountAuthError(f"OneDrive 换票失败: {message}")
        self.access_token = str(body.get("access_token") or "")
        self._expires_at = time.time() + float(body.get("expires_in") or 3600)
        return self.access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "User-Agent": mount_lib.MOUNT_UA}

    def _graph(self, suffix: str, params: Optional[dict] = None, absolute: str = "") -> dict:
        url = absolute or f"{GRAPH_BASE}{suffix}"
        resp = self._request("GET", url, headers=self._headers(), params=params)
        if resp.status_code in (401, 403):
            raise MountAuthError(f"OneDrive 拒绝访问（HTTP {resp.status_code}），请重新获取 refresh_token")
        if resp.status_code == 404:
            raise MountError("OneDrive 找不到该目录（HTTP 404），请检查配置的目录路径")
        if resp.status_code >= 400:
            raise MountError(f"OneDrive 返回 HTTP {resp.status_code}")
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MountError(f"OneDrive 返回了无法解析的响应: {exc}") from exc
        return body if isinstance(body, dict) else {}

    def _abs_path(self, rel: str) -> str:
        return _join(self.root_path, (rel or "").lstrip("/"))

    def _children(self, rel: str) -> list[dict]:
        path = self._abs_path(rel)
        url = (f"{GRAPH_BASE}/me/drive/root:/{urllib.parse.quote(path, safe='/')}:/children"
               if path else f"{GRAPH_BASE}/me/drive/root/children")
        out: list[dict] = []
        params: Optional[dict] = {"$top": "200", "$select": "id,name,size,folder,file"}
        for _ in range(200):
            body = self._graph("", params=params, absolute=url)
            batch = body.get("value")
            out.extend([i for i in (batch or []) if isinstance(i, dict)])
            nxt = str(body.get("@odata.nextLink") or "")
            if not nxt:
                break
            url, params = nxt, None  # 后续页直接用 nextLink，不再带参数
        return out

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        base_rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        entries: list[MountEntry] = []
        for item in self._children(rel):
            name = str(item.get("name") or "")
            if not name:
                continue
            is_dir = item.get("folder") is not None
            child_rel = f"{base_rel}/{name}" if base_rel != "/" else f"/{name}"
            entries.append(MountEntry(
                name=name, rel=child_rel, is_dir=is_dir,
                size=int(item.get("size") or 0), entry_id=str(item.get("id") or ""),
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def test(self) -> dict:
        root = self._graph("/me/drive/root", params={"$select": "id,name"})
        children = self._children("/")
        where = self.root_path or "根目录"
        return {"ok": True, "message": f"OneDrive 可访问（{where} 下 {len(children)} 项）", "drive": root.get("name")}

    def resolve(self, rel: str) -> PlayTarget:
        path = self._abs_path(rel)
        if not path:
            raise MountError(f"无法解析 OneDrive 路径: {rel}")
        content_url = f"{GRAPH_BASE}/me/drive/root:/{urllib.parse.quote(path, safe='/')}:/content"
        # Graph 的 /content 会 302 到一个自带授权的临时地址：拿到它就等于拿到了直链
        resp = self._request("GET", content_url, headers=self._headers(), follow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location") or resp.headers.get("location") or ""
            if location:
                return PlayTarget("url", location, {"User-Agent": mount_lib.MOUNT_UA})
        if resp.status_code in (401, 403):
            raise MountAuthError(f"OneDrive 拒绝访问（HTTP {resp.status_code}）")
        if resp.status_code >= 400:
            raise MountError(f"OneDrive 返回 HTTP {resp.status_code}")
        # 没有跳转（部分代理会直接吐流）：仍把地址交给调用方，用 Bearer 头代理转发
        return PlayTarget("url", content_url, {**self._headers(), "Accept": "*/*"})


# ==================== 注册 ====================

MOUNT_TYPE_ENTRIES: list[dict] = [
    {
        "value": MOUNT_S3,
        "label": "S3 / 对象存储",
        "kind": "remote",
        "group": "cloud",
        "hint": "S3 兼容存储（AWS S3 / MinIO / Cloudflare R2 / Backblaze）。填 Endpoint、桶名与密钥。",
        "needs_path": False,
        "browse": True,
        "root_key": "prefix",
        "fields": [
            {"key": "endpoint", "label": "Endpoint", "placeholder": "https://s3.example.com", "required": True},
            {"key": "bucket", "label": "存储桶", "placeholder": "media", "required": True},
            {"key": "prefix", "label": "前缀（可选）", "placeholder": "movies"},
            {"key": "region", "label": "区域", "placeholder": "us-east-1"},
            {"key": "access_key", "label": "Access Key", "secret": True, "required": True},
            {"key": "secret_key", "label": "Secret Key", "secret": True, "required": True},
            {"key": "session_token", "label": "Session Token（可选）", "secret": True},
            {
                "key": "path_style", "label": "寻址方式", "type": "select",
                "options": [{"label": "Path-style（自建/MiniIO）", "value": "true"},
                            {"label": "Virtual-hosted（AWS）", "value": "false"}],
            },
        ],
    },
    {
        "value": MOUNT_ALIYUN,
        "label": "阿里云盘",
        "kind": "remote",
        "group": "cloud",
        "hint": "Open API 直读网盘。填 refresh_token（会自动换 access_token）；开放平台应用另填 client_id / secret。",
        "needs_path": False,
        "browse": True,
        "root_key": "file_id",
        "fields": [
            {"key": "refresh_token", "label": "refresh_token", "secret": True, "required": True},
            {"key": "drive_id", "label": "drive_id（可选）", "placeholder": "留空用默认网盘"},
            {"key": "file_id", "label": "根目录 ID", "placeholder": "root"},
            {"key": "client_id", "label": "client_id（可选）"},
            {"key": "client_secret", "label": "client_secret（可选）", "secret": True},
            {"key": "endpoint", "label": "接口地址（可选）", "placeholder": "https://openapi.alipan.com"},
        ],
    },
    {
        "value": MOUNT_QUARK,
        "label": "夸克网盘",
        "kind": "remote",
        "group": "cloud",
        "hint": "Cookie 型 API 直读网盘，无需把夸克挂到本机。Cookie 在浏览器登录 pan.quark.cn 后复制。",
        "needs_path": False,
        "browse": True,
        "root_key": "pdir_fid",
        "fields": [
            {"key": "cookie", "label": "Cookie", "secret": True, "required": True},
            {"key": "pdir_fid", "label": "根目录 ID", "placeholder": "0 = 根目录"},
            {"key": "endpoint", "label": "接口地址（可选）", "placeholder": "https://drive-pc.quark.cn/1/clouddrive"},
        ],
    },
    {
        "value": MOUNT_ONEDRIVE,
        "label": "OneDrive / SharePoint",
        "kind": "remote",
        "group": "cloud",
        "hint": "Microsoft Graph。需要一个应用 client_id 与 refresh_token（Files.Read.All + offline_access）。",
        "needs_path": False,
        "browse": True,
        "root_key": "path",
        "fields": [
            {"key": "client_id", "label": "client_id", "required": True},
            {"key": "refresh_token", "label": "refresh_token", "secret": True, "required": True},
            {"key": "tenant", "label": "租户", "placeholder": "common"},
            {"key": "path", "label": "目录路径（可选）", "placeholder": "Media/电影"},
        ],
    },
]

PROVIDERS = {
    MOUNT_S3: S3Mount,
    MOUNT_ALIYUN: AliyunMount,
    MOUNT_QUARK: QuarkMount,
    MOUNT_ONEDRIVE: OneDriveMount,
}


def register() -> None:
    """把本模块的挂载类型与提供者注册进 mounts 注册表（幂等）"""
    mount_lib.register_mount_types(MOUNT_TYPE_ENTRIES)
    mount_lib.register_providers(PROVIDERS)
    logger.debug("已注册云端挂载类型: %s", ", ".join(PROVIDERS))


# 模块导入即注册：无论谁先被导入（mounts 或本模块），类型表都是齐的
register()
