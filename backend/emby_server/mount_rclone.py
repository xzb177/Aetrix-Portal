"""rclone 挂载：直接复用 rclone 的 remote，把内容接进媒体库

和 `local` 挂载的区别：**不需要把网盘挂到本机**。rclone 支持的后端（Google Drive /
OneDrive / S3 / 115 / 阿里云盘 / 夸克 / WebDAV / SFTP …）都通过同一个挂载类型接进来，
配置也只复用 rclone 自己的 remote 定义，不用在面板里再抄一遍密钥。

两种模式：

``rc``（推荐，默认）
    连到正在运行的 ``rclone rcd --rc-serve``：

    - 列目录 / 测试走 RC API（``POST /operations/list``、``/config/listremotes``）；
    - 播放地址直接用 rc-serve 暴露的 ``http://<rc 地址>/<remote:path>``，
      rclone 自己处理 Range，EA 照旧代理转发，凭据与 rc 地址都不下发客户端。

``cli``（兜底）
    直接调用 rclone 可执行文件：``lsjson`` 列目录、``cat`` 读内容（.strm / 字幕）、
    ``link`` 取公开直链。适合「机器上有 rclone 但不想常驻 rc」的场景；
    后端不支持公开链接时会在测试里明确提示改用 rc 模式或把网盘挂到本机（``local``）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import urllib.parse
from typing import Optional

from backend.emby_server import mounts as mount_lib
from backend.emby_server.mount_cloud import _CloudMount
from backend.emby_server.mounts import (
    MountAuthError,
    MountEntry,
    MountError,
    PlayTarget,
    cached_listing,
)

logger = logging.getLogger(__name__)

MOUNT_RCLONE = "rclone"

MODE_RC = "rc"
MODE_CLI = "cli"

RCLONE_BIN = os.getenv("MOUNT_RCLONE_BIN", "rclone")
RCLONE_CONFIG = os.getenv("MOUNT_RCLONE_CONFIG", "")
RC_URL = os.getenv("MOUNT_RCLONE_RC_URL", "http://127.0.0.1:5572")
# 服务器侧统一配置的 RC 凭据（见 docker-compose.yml 的 .env）：
# 同一台机器上的 rclone RC 属于本机基础设施，挂载表单不必（也不应该）每条都存一份密码。
# 表单留空 → 直接用这里；表单填错 → 先按填的试，失败自动回退到这里并记一条日志。
RC_USER = os.getenv("MOUNT_RCLONE_RC_USER", "").strip()
RC_PASS = os.getenv("MOUNT_RCLONE_RC_PASS", "")

# CLI 输出里这些字样说明是凭据问题而不是网络/路径问题
_AUTH_HINTS = ("unauthorized", "401", "403", "invalid_grant", "token", "credentials",
               "authentication", "not authorized", "permission denied")
_NOT_FOUND_HINTS = ("not found", "doesn't exist", "no such file", "directory not found")

# remote 名漏冒号时 rclone 的输出：
#   NOTICE: "paul_emby" refers to a local folder, use "paul_emby:" to refer to your remote
#   ERROR : error listing: directory not found
# 后半句看起来像「目录不存在」，前半句才是原因，所以这两行要当成**写法问题**翻译。
_LOCAL_FOLDER_HINT = "refers to a local folder"
_REMOTE_SUGGEST_RE = re.compile(r'use\s+"([^"]+)"\s+to refer to your remote', re.I)


def fs_remote_name(value: str) -> str:
    """``gdrive`` ← ``gdrive:Movies``；没有冒号（rclone 当本机路径）时返回空串"""
    head = (value or "").strip().split("/", 1)[0]
    name, sep, _rest = head.partition(":")
    return name if sep and name else ""


def looks_like_local_path(value: str) -> bool:
    """``/media/movies`` / ``./media`` / ``~/media``：rclone 确实支持的本地写法

    这种写法不该被当成「remote 漏冒号」去纠正，也不拦（本机目录应该用「本地 /
    已挂载目录」类型，提示里写明了）。
    """
    return (value or "").strip().startswith(("/", ".", "~", "\\"))


def remote_name_list(remotes: Optional[list[str]]) -> list[str]:
    """remote 列表统一成不带尾冒号的名字（CLI 与 RC 两种返回格式都能对齐）"""
    names: list[str] = []
    for item in remotes or []:
        name = str(item or "").strip().rstrip(":")
        if name and name not in names:
            names.append(name)
    return names


def normalize_fs(value: str, remotes: Optional[list[str]] = None) -> str:
    """把漏冒号的 remote 写法补成 rclone 语法（**只认已配置的 remote 才改写**）

    ``paul_emby`` / ``paul_emby/电影`` 在 rclone 眼里是本机路径，报出来的是
    「refers to a local folder, use "paul_emby:" to refer to your remote」。
    这里在确认首段就是远端已配置的 remote 时补上冒号；其余原样返回——
    是不是写法错误交给 `fs_missing_colon_hint` 判断。
    """
    raw = (value or "").strip()
    if not raw or fs_remote_name(raw) or looks_like_local_path(raw):
        return raw
    head, _sep, tail = raw.partition("/")
    head = head.strip()
    if head not in remote_name_list(remotes):
        return raw
    tail = tail.strip("/")
    return f"{head}:{tail}" if tail else f"{head}:"


def fs_missing_colon_hint(value: str, remotes: Optional[list[str]] = None) -> str:
    """看起来是「remote 漏了冒号」时返回可操作的提示，否则空串

    明确的本地写法（``/media/movies``、``./media``、``~/media``）不拦：rclone 本来就支持
    本机路径，只是 rclone 挂载类型不该这么用（本机目录请用「本地 / 已挂载目录」类型）。
    """
    raw = (value or "").strip()
    if not raw or fs_remote_name(raw) or looks_like_local_path(raw):
        return ""
    head = raw.split("/", 1)[0].strip()
    if not head:
        return ""
    hint = (f"remote 名后面要带冒号：「{head}」会被 rclone 当成本机目录"
            f"（报 refers to a local folder）。正确写法：{head}: 或 {head}:子目录。")
    names = remote_name_list(remotes)
    if names:
        hint += f" 远端已配置的 remote：{', '.join(names)}。"
    return hint


def _missing_colon_error(raw: str) -> MountError:
    """把 rclone 的「refers to a local folder」翻译成可操作的错误"""
    match = _REMOTE_SUGGEST_RE.search(raw or "")
    remote = (match.group(1).strip() if match else "") or "你的 remote 名（如 paul_emby:）"
    return MountError(
        f"rclone: {remote} 是本机目录，不是 remote——remote 名后面必须带冒号。"
        f"正确写法：{remote} 或 {remote}子目录（例如 {remote}Movies）。"
    )


def _cli_error(exc: "subprocess.CalledProcessError") -> MountError:
    """把 rclone 的 stderr 翻译成可读错误（凭据问题单独识别）"""
    raw = (exc.stderr or b"")
    text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
    message = " ".join(line.strip() for line in text.splitlines() if line.strip())[:300]
    message = message or f"rclone 退出码 {exc.returncode}"
    lowered = message.lower()
    if any(hint in lowered for hint in _AUTH_HINTS):
        return MountAuthError(f"rclone: {message}")
    if _LOCAL_FOLDER_HINT in lowered:
        return _missing_colon_error(message)
    if any(hint in lowered for hint in _NOT_FOUND_HINTS):
        return MountError(f"rclone: 路径不存在（{message}）")
    return MountError(f"rclone: {message}")


def run_rclone(args: list[str], *, bin_path: str = "", config: str = "",
               timeout: float = 0) -> bytes:
    """执行一条 rclone 命令，返回 stdout（非零退出码翻译成挂载错误）"""
    binary = (bin_path or RCLONE_BIN or "rclone").strip()
    if not shutil.which(binary) and not os.path.isabs(binary):
        raise MountError(
            f"找不到 rclone 可执行文件：{binary}（在挂载配置里填写绝对路径，"
            f"或用 MOUNT_RCLONE_BIN 指定）"
        )
    command = [binary, *args]
    config_path = (config or RCLONE_CONFIG or "").strip()
    if config_path:
        command.append(f"--config={config_path}")
    try:
        proc = subprocess.run(
            command, capture_output=True,
            timeout=timeout or mount_lib.MOUNT_TIMEOUT * 3,
        )
    except subprocess.TimeoutExpired as exc:
        raise MountError(f"rclone 命令超时: {' '.join(command[:3])} …") from exc
    except OSError as exc:
        raise MountError(f"无法执行 rclone: {exc}") from exc
    if proc.returncode != 0:
        raise _cli_error(proc)
    return proc.stdout or b""


def rc_call(rc_url: str, path: str, payload: Optional[dict] = None, *,
            username: str = "", password: str = "", timeout: float = 0):
    """调用 rclone RC API（未开启 RC 时给出可操作的提示）

    返回 RC 的原始 JSON：多数接口是 dict，``/operations/listfile`` 这类直接返回数组。

    凭据优先级：调用方传入的 → 服务器 .env 里统一配置的。传入的若被 RC 拒绝（401/403），
    自动回退到服务器配置再试一次：挂载表单里填错密码不该让整条挂载永远用不了，
    而这台机器上的 RC 本来就是本站自己管的。回退命中会记一条日志，便于发现表单填错。
    """
    import httpx

    base = (rc_url or RC_URL).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise MountError("RC 地址必须以 http:// 或 https:// 开头（如 http://127.0.0.1:5572）")
    headers = {"Content-Type": "application/json"}

    def _try(user: str, secret: str) -> httpx.Response:
        auth = (user, secret) if user else None
        with httpx.Client(timeout=timeout or mount_lib.MOUNT_TIMEOUT,
                          follow_redirects=True) as client:
            return client.post(f"{base}/{path.lstrip('/')}", json=payload or {},
                               headers=headers, auth=auth)

    username = (username or "").strip()
    password = password or ""
    try:
        resp = _try(username, password)
        if resp.status_code in (401, 403) and RC_USER and (
            username != RC_USER or password != RC_PASS
        ):
            logger.info(
                "rclone RC 拒绝表单里的凭据（%s），回退到服务器统一配置的 RC 账号", username or "空",
            )
            resp = _try(RC_USER, RC_PASS)
    except Exception as exc:  # noqa: BLE001 — 网络层异常统一成可读提示
        raise MountError(
            f"连接 rclone RC 失败: {exc}（确认已启动 rclone rcd --rc-serve，"
            f"地址 {base}）"
        ) from exc
    if resp.status_code in (401, 403):
        raise MountAuthError("rclone RC 拒绝访问（HTTP %s），请检查 RC 用户名 / 密码" % resp.status_code)
    if resp.status_code == 404:
        raise MountError(f"rclone RC 没有这个接口: {path}（该 rclone 版本不提供）")
    if resp.status_code >= 400:
        raise MountError(f"rclone RC 返回 HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise MountError(f"rclone RC 返回了无法解析的响应: {exc}") from exc
    if isinstance(body, dict) and body.get("error"):
        message = str(body.get("error"))
        if any(hint in message.lower() for hint in _AUTH_HINTS):
            raise MountAuthError(f"rclone: {message}")
        raise MountError(f"rclone: {message}")
    return body if isinstance(body, (dict, list)) else {}


def list_remotes(rc_url: str = "", *, username: str = "", password: str = "",
                 bin_path: str = "", config: str = "", mode: str = MODE_RC) -> list[str]:
    """列出 rclone 里已配置的 remote（后台「获取 remote 列表」用）"""
    if (mode or MODE_RC) == MODE_CLI:
        out = run_rclone(["listremotes"], bin_path=bin_path, config=config)
        return [line.strip() for line in out.decode("utf-8", "ignore").splitlines() if line.strip()]
    body = rc_call(rc_url, "/config/listremotes", {}, username=username, password=password)
    remotes = body.get("remotes") if isinstance(body, dict) else None
    return sorted(str(r) for r in (remotes or []))


def _rc_list_items(rc_url: str, fs: str, remote: str, *, username: str = "",
                    password: str = "") -> list[dict]:
    """列目录：同时兼容 rclone 新旧两套 RC 接口。

    - 旧版 rclone：``/operations/list``，返回 ``{"list": [FileInfo, ...]}``；
    - 新版 rclone（≥ 1.65 起逐步替换，1.71 已移除旧接口）：
      ``/operations/listfile``，直接返回 ``[FileInfo, ...]`` 数组。

    先试旧的（老部署零影响），404 再落到新的 —— 否则只把 rclone 升个版本，挂载就全废。
    """
    try:
        body = rc_call(rc_url, "/operations/list", {"fs": fs, "remote": remote},
                       username=username, password=password)
    except MountError as exc:
        if "没有这个接口" not in str(exc):
            raise
        body = rc_call(rc_url, "/operations/listfile", {"fs": fs, "remote": remote},
                       username=username, password=password)
        logger.info("rclone RC 使用新接口 /operations/listfile 列目录 %s", fs)
        return [i for i in (body if isinstance(body, list) else []) if isinstance(i, dict)]
    return [i for i in ((body or {}).get("list") or []) if isinstance(i, dict)]


class RcloneMount(_CloudMount):
    """rclone 挂载（rc 模式 / cli 模式）"""

    mount_type = MOUNT_RCLONE
    what = "rclone"

    def __init__(self, mount, db=None, library=None):
        super().__init__(mount, db, library)
        cfg = self.config
        self.mode = (cfg.get("mode") or MODE_RC).strip().lower()
        if self.mode not in (MODE_RC, MODE_CLI):
            self.mode = MODE_RC
        # fs 就是 rclone 的「remote:路径」，例如 gdrive:Movies
        self.fs = (cfg.get("fs") or cfg.get("remote") or "").strip()
        self.rc_url = (cfg.get("rc_url") or RC_URL).strip().rstrip("/") or RC_URL
        # 留空即用服务器 .env 里统一配置的 RC 账号：挂载记录不存 RC 密码
        self.rc_user = (cfg.get("rc_user") or RC_USER).strip()
        self.rc_pass = cfg.get("rc_pass") or RC_PASS
        self.bin_path = (cfg.get("rclone_bin") or "").strip()
        self.config_path = (cfg.get("rclone_config") or "").strip()
        # remote 名漏冒号时的原始写法（自愈后留在 test 提示里，好让管理员把配置改过来）
        self.healed_from = ""

    # ---- 目标路径 ----

    def _require_fs(self) -> str:
        if not self.fs:
            raise MountError("请填写 remote（例如 gdrive:Movies）")
        return self.fs

    def _heal_fs(self) -> bool:
        """remote 名漏冒号时按远端已配置的 remote 自愈（只在列目录 / 测试这类网络入口做）

        老配置里存成 ``paul_emby``（漏冒号）时 rclone 会把它当本机目录，报
        「refers to a local folder」。这里问一次远端有哪些 remote，首段能对上就补冒号，
        不必先让管理员手改配置、重扫一遍才恢复。
        """
        if not self.fs or fs_remote_name(self.fs) or looks_like_local_path(self.fs):
            return False
        try:
            remotes = list_remotes(
                self.rc_url, username=self.rc_user, password=self.rc_pass,
                bin_path=self.bin_path, config=self.config_path, mode=self.mode,
            )
        except MountError as exc:
            logger.info("rclone remote 列表读取失败（不自动纠正 %s）: %s", self.fs, exc)
            return False
        fixed = normalize_fs(self.fs, remotes)
        if fixed == self.fs:
            return False
        logger.warning("rclone remote 名漏冒号：%s → %s（建议在挂载配置里改成带冒号的写法）",
                       self.fs, fixed)
        self.healed_from, self.fs = self.fs, fixed
        return True

    def _target(self, rel: str) -> str:
        """挂载根 + 相对路径 → rclone 目标（`gdrive:Movies/2024/a.mkv`）"""
        fs = self._require_fs().rstrip("/")
        rel = (rel or "").lstrip("/")
        joined = f"{fs}/{rel}" if rel else fs
        # 经 rclone 解析时反斜杠是转义符，统一成正斜杠
        return joined.replace("\\", "/")

    def _rel_remote(self, rel: str) -> str:
        """rc 模式下 ``remote`` 参数：相对 fs 根的子路径"""
        return (rel or "").lstrip("/")

    # ---- rc 模式 ----

    def _rc_play_url(self, rel: str) -> str:
        """rc-serve 出流地址：``http://<rc>/[remote:]/path``

        rclone 的 rc-serve 用**方括号**把 remote 名和普通目录区分开（它根目录页面上给
        的链接就是 ``./[paul_emby:]/``）。写成 ``/paul_emby:/x.mkv`` 会被当成叫
        ``paul_emby:`` 的本机目录而 404 —— 列目录走 ``/operations/list`` 一切正常，
        只有真正取流时才炸，很容易被误判成「rc-serve 没开」。
        """
        fs = self._require_fs().rstrip("/")
        rel = (rel or "").lstrip("/").replace("\\", "/")
        # 根（remote 自身）与子路径：都要先给 remote 套上 [ ]
        base = f"{self.rc_url}/[{fs}]"
        if not rel:
            return base + "/"
        return base + "/" + "/".join(
            urllib.parse.quote(seg, safe="") for seg in rel.split("/") if seg
        )

    def _rc_headers(self) -> dict:
        headers = {"User-Agent": mount_lib.MOUNT_UA}
        if self.rc_user:
            import base64

            token = base64.b64encode(f"{self.rc_user}:{self.rc_pass}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    # ---- cli 模式 ----

    def _cli(self, args: list[str]) -> bytes:
        self._require_fs()
        return run_rclone(args, bin_path=self.bin_path, config=self.config_path)

    def _cli_lsjson(self, rel: str) -> list[dict]:
        out = self._cli(["lsjson", self._target(rel)])
        try:
            data = json.loads(out.decode("utf-8", "ignore") or "[]")
        except json.JSONDecodeError as exc:
            raise MountError(f"rclone lsjson 返回了无法解析的 JSON: {exc}") from exc
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def _cli_link(self, rel: str) -> str:
        try:
            out = self._cli(["link", self._target(rel)])
        except MountError as exc:
            # 后端不支持公开链接时 link 会失败，这不算挂载不可用
            logger.info("rclone link 不可用（%s），回退失败: %s", self._target(rel), exc)
            return ""
        return out.decode("utf-8", "ignore").strip().splitlines()[0].strip() if out.strip() else ""

    # ---- 接口 ----

    def _raw_listing(self, rel: str) -> list[dict]:
        """列目录并统一成 ``{Path, Name, Size, IsDir}``（rc / cli 两种模式各自的字段都要对齐）"""
        if self.mode == MODE_CLI:
            items = self._cli_lsjson(rel)
        else:
            # 新老 rclone 的 RC 列目录接口差异（/operations/list → /operations/listfile）
            # 统一由 _rc_list_items 兜住，这里只管字段对齐
            items = _rc_list_items(self.rc_url, self._require_fs(), self._rel_remote(rel),
                                   username=self.rc_user, password=self.rc_pass)
        return [
            {"Path": str(i.get("Path") or ""), "Name": str(i.get("Name") or ""),
             "Size": int(i.get("Size") or 0), "IsDir": bool(i.get("IsDir"))}
            for i in items
        ]

    def _explain_colonless(self, exc: MountError) -> MountError:
        """写法可疑时把「目录不存在」补成完整解释

        rc 模式只拿得到一句 ``directory not found``（rclone 的 NOTICE 不会出现在 RC 响应里），
        和 cli 模式一样容易让人去查错方向。
        """
        if fs_remote_name(self.fs) or looks_like_local_path(self.fs):
            return exc
        hint = fs_missing_colon_hint(self.fs)
        if not hint:
            return exc
        return MountError(f"{exc}；{hint}")

    @cached_listing
    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        self._heal_fs()
        base_rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        try:
            raw = self._raw_listing(rel)
        except MountError as exc:
            raise self._explain_colonless(exc) from exc
        entries: list[MountEntry] = []
        for item in raw:
            name = item["Name"] or os.path.basename(item["Path"])
            if not name:
                continue
            child_rel = f"{base_rel}/{name}" if base_rel != "/" else f"/{name}"
            entries.append(MountEntry(
                name=name, rel=child_rel, is_dir=item["IsDir"],
                size=item["Size"], entry_id=item["Path"] if item["IsDir"] else "",
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def test(self) -> dict:
        self._heal_fs()
        if self.mode == MODE_CLI:
            items = self._cli_lsjson("/")
            how = "rclone 命令"
        else:
            items = _rc_list_items(self.rc_url, self._require_fs(), "",
                                   username=self.rc_user, password=self.rc_pass)
            how = f"rclone RC（{self.rc_url}）"
        hint = ""
        if self.healed_from:
            # 自愈只是让访问先恢复：存进库的仍是漏冒号的写法，得提醒改
            hint += (f"；配置里写的是 {self.healed_from}（漏冒号，rclone 会当成本机目录），"
                     f"已按 {self.fs} 访问，建议把配置改成 {self.fs}")
        if self.mode == MODE_RC:
            # 探测 rc-serve 出流面：取 remote 根的目录页（rclone 会给 HTML 列表）。
            # 之前这里拿「旧写法的播放 URL」去探，那个 URL 本来就是错的（没套 []），
            # 于是无论 rc-serve 开没开都 404，提示成了误报。
            try:
                resp = self._request("GET", self._rc_play_url("/"), headers=self._rc_headers())
                if resp.status_code == 404:
                    hint += "；注意：rc-serve 可能未开启（rclone rcd 需带 --rc-serve），播放会 404"
            except MountError:
                pass
        return {
            "ok": True,
            "message": f"{how} 可访问（{self.fs} 下 {len(items)} 项）{hint}",
            "mode": self.mode,
        }

    def resolve(self, rel: str) -> PlayTarget:
        if self.mode == MODE_CLI:
            url = self._cli_link(rel)
            if not url:
                raise MountError(
                    f"rclone 未返回公开直链: {self._target(rel)}"
                    "（该后端不支持 link 时，请改用 rc 模式，或把网盘挂到本机后用 local 挂载）"
                )
            return PlayTarget("url", url, {"User-Agent": mount_lib.MOUNT_UA})
        return PlayTarget("url", self._rc_play_url(rel), self._rc_headers())

    def read_text(self, rel: str) -> str:
        if self.mode == MODE_CLI:
            return self._cli(["cat", self._target(rel)]).decode("utf-8", "ignore")
        return super().read_text(rel)


MOUNT_TYPE_ENTRIES = [
    {
        "value": MOUNT_RCLONE,
        "label": "rclone（任意后端）",
        "kind": "remote",
        "group": "gateway",
        "hint": "复用 rclone 的 remote，网盘不用挂到本机。推荐连 rclone rcd --rc-serve；"
                "也可以直接调 rclone 命令。已经 rclone mount 到本机的目录用「本地 / 已挂载目录」更直接。",
        "needs_path": False,
        "browse": True,
        "root_key": "fs",
        "remotes": True,
        "fields": [
            {
                "key": "mode", "label": "模式", "type": "select",
                "options": [{"label": "RC API（推荐，需 rclone rcd --rc-serve）", "value": "rc"},
                            {"label": "直接调用 rclone 命令", "value": "cli"}],
            },
            {"key": "fs", "label": "remote", "placeholder": "gdrive:Movies", "required": True,
             "type": "rclone_fs"},
            {"key": "rc_url", "label": "RC 地址", "placeholder": "http://127.0.0.1:5572"},
            {"key": "rc_user", "label": "RC 用户名（可选）"},
            {"key": "rc_pass", "label": "RC 密码（可选）", "secret": True},
            {"key": "rclone_bin", "label": "rclone 路径（可选）", "placeholder": "默认从 PATH 找 rclone"},
            {"key": "rclone_config", "label": "rclone.conf 路径（可选）",
             "placeholder": "默认 ~/.config/rclone/rclone.conf"},
        ],
    },
]

PROVIDERS = {MOUNT_RCLONE: RcloneMount}


def register() -> None:
    """注册 rclone 挂载类型与提供者（幂等）"""
    mount_lib.register_mount_types(MOUNT_TYPE_ENTRIES)
    mount_lib.register_providers(PROVIDERS)
    logger.debug("已注册 rclone 挂载类型")


# 模块导入即注册：无论谁先被导入（mounts 或本模块），类型表都是齐的
register()
