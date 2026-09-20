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
import shutil
import subprocess
import urllib.parse
from typing import Optional

from backend.emby_server import mounts as mount_lib
from backend.emby_server.mount_cloud import _CloudMount
from backend.emby_server.mounts import MountAuthError, MountEntry, MountError, PlayTarget

logger = logging.getLogger(__name__)

MOUNT_RCLONE = "rclone"

MODE_RC = "rc"
MODE_CLI = "cli"

RCLONE_BIN = os.getenv("MOUNT_RCLONE_BIN", "rclone")
RCLONE_CONFIG = os.getenv("MOUNT_RCLONE_CONFIG", "")
RC_URL = os.getenv("MOUNT_RCLONE_RC_URL", "http://127.0.0.1:5572")

# CLI 输出里这些字样说明是凭据问题而不是网络/路径问题
_AUTH_HINTS = ("unauthorized", "401", "403", "invalid_grant", "token", "credentials",
               "authentication", "not authorized", "permission denied")
_NOT_FOUND_HINTS = ("not found", "doesn't exist", "no such file", "directory not found")


def _cli_error(exc: "subprocess.CalledProcessError") -> MountError:
    """把 rclone 的 stderr 翻译成可读错误（凭据问题单独识别）"""
    raw = (exc.stderr or b"")
    text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
    message = " ".join(line.strip() for line in text.splitlines() if line.strip())[:300]
    message = message or f"rclone 退出码 {exc.returncode}"
    lowered = message.lower()
    if any(hint in lowered for hint in _AUTH_HINTS):
        return MountAuthError(f"rclone: {message}")
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
            username: str = "", password: str = "", timeout: float = 0) -> dict:
    """调用 rclone RC API（未开启 RC 时给出可操作的提示）"""
    import httpx

    base = (rc_url or RC_URL).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise MountError("RC 地址必须以 http:// 或 https:// 开头（如 http://127.0.0.1:5572）")
    headers = {"Content-Type": "application/json"}
    auth = (username, password) if username else None
    try:
        with httpx.Client(timeout=timeout or mount_lib.MOUNT_TIMEOUT,
                          follow_redirects=True) as client:
            resp = client.post(f"{base}/{path.lstrip('/')}", json=payload or {},
                               headers=headers, auth=auth)
    except Exception as exc:  # noqa: BLE001 — 网络层异常统一成可读提示
        raise MountError(
            f"连接 rclone RC 失败: {exc}（确认已启动 rclone rcd --rc-serve，"
            f"地址 {base}）"
        ) from exc
    if resp.status_code in (401, 403):
        raise MountAuthError("rclone RC 拒绝访问（HTTP %s），请检查 RC 用户名 / 密码" % resp.status_code)
    if resp.status_code == 404:
        raise MountError(f"rclone RC 没有这个接口: {path}（rclone 版本过旧？）")
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
    return body if isinstance(body, dict) else {}


def list_remotes(rc_url: str = "", *, username: str = "", password: str = "",
                 bin_path: str = "", config: str = "", mode: str = MODE_RC) -> list[str]:
    """列出 rclone 里已配置的 remote（后台「获取 remote 列表」用）"""
    if (mode or MODE_RC) == MODE_CLI:
        out = run_rclone(["listremotes"], bin_path=bin_path, config=config)
        return [line.strip() for line in out.decode("utf-8", "ignore").splitlines() if line.strip()]
    body = rc_call(rc_url, "/config/listremotes", {}, username=username, password=password)
    remotes = body.get("remotes")
    return sorted(str(r) for r in (remotes or []))


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
        self.rc_user = (cfg.get("rc_user") or "").strip()
        self.rc_pass = cfg.get("rc_pass") or ""
        self.bin_path = (cfg.get("rclone_bin") or "").strip()
        self.config_path = (cfg.get("rclone_config") or "").strip()

    # ---- 目标路径 ----

    def _require_fs(self) -> str:
        if not self.fs:
            raise MountError("请填写 remote（例如 gdrive:Movies）")
        return self.fs

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
        """rc-serve 暴露的地址：``http://<rc>/<remote:path>``"""
        target = self._target(rel)
        return f"{self.rc_url}/{urllib.parse.quote(target, safe='/:')}"

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

    def list_dir(self, rel: str = "/") -> list[MountEntry]:
        base_rel = ("/" + (rel or "").lstrip("/")).rstrip("/") or "/"
        if self.mode == MODE_CLI:
            raw = [
                {"Path": str(i.get("Path") or ""), "Name": str(i.get("Name") or ""),
                 "Size": int(i.get("Size") or 0), "IsDir": bool(i.get("IsDir"))}
                for i in self._cli_lsjson(rel)
            ]
        else:
            body = rc_call(self.rc_url, "/operations/list",
                           {"fs": self._require_fs(), "remote": self._rel_remote(rel)},
                           username=self.rc_user, password=self.rc_pass)
            raw = [
                {"Path": str(i.get("Path") or ""), "Name": str(i.get("Name") or ""),
                 "Size": int(i.get("Size") or 0), "IsDir": bool(i.get("IsDir"))}
                for i in (body.get("list") or []) if isinstance(i, dict)
            ]
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
        if self.mode == MODE_CLI:
            items = self._cli_lsjson("/")
            how = "rclone 命令"
        else:
            body = rc_call(self.rc_url, "/operations/list",
                           {"fs": self._require_fs(), "remote": ""},
                           username=self.rc_user, password=self.rc_pass)
            items = [i for i in (body.get("list") or []) if isinstance(i, dict)]
            how = f"rclone RC（{self.rc_url}）"
        hint = ""
        if self.mode == MODE_RC:
            # rc-serve 没开时列目录正常但播放会 404，提前给出提示
            try:
                resp = self._request("GET", self._rc_play_url("/"), headers=self._rc_headers())
                if resp.status_code == 404:
                    hint = "；注意：rc-serve 似乎未开启（--rc-serve），播放可能不可用"
            except MountError:
                hint = ""
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
