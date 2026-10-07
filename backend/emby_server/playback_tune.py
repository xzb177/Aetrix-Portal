"""开箱即用的播放优化通用能力。

用户部署 Aetrix、挂载存储后，不用手动调任何参数，播放就好好工作。
本模块收敛四块能力，全项目只此一处实现（横切能力只许一套）：

1. rclone 挂载参数自动优化（``DEFAULT_RCLONE_VFS_ARGS``）
2. SA 自动轮换（``ensure_sa_rotation``）
3. 单文件并发 Range 限流（``RangeConcurrencyLimiter``）
4. 移动端 4K 透明降级（``maybe_downgrade_for_client``）
"""

from __future__ import annotations

import configparser
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. rclone 挂载参数自动优化
# ---------------------------------------------------------------------------
# 实测结论（2026-10-07 压力排查）：
# - vfs-read-chunk-size 默认 128M：起播要先抓满 128MB 才出首字节，手机端
#   体感就是"点了没反应"。32M 让首字节快约 4 倍。
# - vfs-read-ahead 128M：顺序播放时预读隐藏网络延迟，拖动进度条更跟手。
# - chunk-size-limit 256M：长顺序读自动放大分块，吞吐不掉。
# - buffer-size 32M / drive-chunk-size 128M：上传/缓冲配平，避免小水管被打满。
DEFAULT_RCLONE_VFS_ARGS: list[str] = [
    "--vfs-cache-mode", "full",
    "--vfs-read-chunk-size", "32M",
    "--vfs-read-chunk-size-limit", "256M",
    "--vfs-read-ahead", "128M",
    "--buffer-size", "32M",
    "--drive-chunk-size", "128M",
]

# 通用挂载开关（与性能无关，但开箱即用必须有）
DEFAULT_RCLONE_MOUNT_FLAGS: list[str] = [
    "--daemon",
    "--allow-other",
]


def _flag_key(args: list[str], idx: int) -> str:
    return args[idx]


def build_rclone_mount_args(extra: Optional[Iterable[str]] = None) -> list[str]:
    """合并默认优化参数与用户自定义参数，用户显式给的胜出。

    ``extra`` 形如 ``["--vfs-read-chunk-size", "64M", "--daemon"]``。
    返回去重后的完整参数列表（不含 ``rclone mount`` 本体与 remote/挂载点）。
    """
    merged: dict[str, str | None] = {}
    order: list[str] = []

    def _feed(argv: Iterable[str]) -> None:
        argv = list(argv)
        i = 0
        while i < len(argv):
            tok = argv[i]
            if tok.startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                key, val = tok, argv[i + 1]
                i += 2
            else:
                key, val = tok, None
                i += 1
            if key not in merged:
                order.append(key)
            merged[key] = val

    _feed(DEFAULT_RCLONE_VFS_ARGS)
    _feed(DEFAULT_RCLONE_MOUNT_FLAGS)
    if extra:
        _feed(extra)

    out: list[str] = []
    for key in order:
        out.append(key)
        if merged[key] is not None:
            out.append(merged[key])
    return out


def build_rclone_mount_cmd(remote: str, mountpoint: str,
                           extra: Optional[Iterable[str]] = None,
                           bin_path: str = "rclone",
                           config: str = "") -> list[str]:
    """拼出开箱即用的 ``rclone mount`` 完整命令（含优化参数）。"""
    cmd = [bin_path, "mount", remote, mountpoint]
    if config:
        cmd += ["--config", config]
    cmd += build_rclone_mount_args(extra)
    return cmd


# ---------------------------------------------------------------------------
# 2. SA 自动轮换
# ---------------------------------------------------------------------------
# Google Drive 单 SA 有下载配额，热门文件会被 403（downloadQuotaExceeded）。
# rclone >= 1.55 支持 service_account_file_path（目录），自动轮换目录下所有 SA，
# 配额 × N。老版本只能单 SA，本函数降级并给出告警。
SA_ROTATION_MIN_VERSION = (1, 55, 0)


def rclone_version_tuple(bin_path: str = "rclone") -> Optional[tuple[int, int, int]]:
    """解析 ``rclone version``，返回 (major, minor, patch)，失败返回 None。"""
    exe = shutil.which(bin_path) or bin_path
    try:
        out = subprocess.run([exe, "version"], capture_output=True, text=True,
                             timeout=15).stdout or ""
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"rclone v(\d+)\.(\d+)\.(\d+)", out)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _sa_json_files(sa_dir: str | Path) -> list[Path]:
    p = Path(sa_dir)
    if not p.is_dir():
        return []
    return sorted(f for f in p.glob("*.json") if f.is_file())


def ensure_sa_rotation(conf_path: str | Path,
                       sa_dir: str | Path,
                       bin_path: str = "rclone") -> dict:
    """让 rclone 配置自动用上 SA 轮换（幂等，可重复调）。

    - rclone >= 1.55 且 SA 目录里有 >=2 个 json：写
      ``service_account_file_path = <sa_dir>``（删掉旧的单文件配置）。
    - 只有 1 个 json：用 ``service_account_file`` 指向它。
    - 版本太老：不动配置，返回 warning 提示升级。
    - SA 目录为空/不存在：不动，返回 warning。

    返回 ``{"changed": bool, "mode": "dir"|"single"|"none", "warning": str|None}``。
    只改 [remote] 里原来就配了 service_account_* 的节，不碰 OAuth 的节。
    """
    result: dict = {"changed": False, "mode": "none", "warning": None}
    conf = Path(conf_path)
    if not conf.is_file():
        result["warning"] = f"rclone 配置不存在：{conf}"
        return result

    sa_files = _sa_json_files(sa_dir)
    if not sa_files:
        result["warning"] = f"SA 目录为空或不存在：{sa_dir}，未启用轮换"
        return result

    ver = rclone_version_tuple(bin_path)
    if ver is None:
        result["warning"] = "检测不到 rclone 版本，未改动 SA 配置"
        return result

    parser = configparser.ConfigParser()
    parser.read(conf, encoding="utf-8")

    changed = False
    for section in parser.sections():
        has_single = parser.has_option(section, "service_account_file")
        has_dir = parser.has_option(section, "service_account_file_path")
        if not (has_single or has_dir):
            continue
        if len(sa_files) >= 2 and ver >= SA_ROTATION_MIN_VERSION:
            # 目录轮换
            want = str(Path(sa_dir).resolve()) + "/"
            if has_single:
                parser.remove_option(section, "service_account_file")
                changed = True
            if (not has_dir) or parser.get(section, "service_account_file_path") != want:
                parser.set(section, "service_account_file_path", want)
                changed = True
            result["mode"] = "dir"
        else:
            # 单 SA（版本太老或只有一个 json）
            want = str(sa_files[0].resolve())
            if has_dir:
                parser.remove_option(section, "service_account_file_path")
                changed = True
            if (not has_single) or parser.get(section, "service_account_file") != want:
                parser.set(section, "service_account_file", want)
                changed = True
            result["mode"] = "single"
            if ver < SA_ROTATION_MIN_VERSION:
                result["warning"] = (
                    f"rclone {'.'.join(map(str, ver))} < 1.55，不支持 SA 目录轮换，"
                    "已用单 SA；建议升级 rclone 后重跑以启用轮换"
                )

    if changed:
        with open(conf, "w", encoding="utf-8") as fh:
            parser.write(fh)
    result["changed"] = changed
    return result


# ---------------------------------------------------------------------------
# 3. 单文件并发 Range 限流
# ---------------------------------------------------------------------------
# 播放器（尤其手机端）对一个大文件会开 5~7 个并发 Range 请求，7 路同时回源
# Drive 直接把带宽打满，谁都播不动。这里按文件限流：同一文件最多
# ``MAX_CONCURRENT_RANGES_PER_FILE`` 路并发，超出的直接 503（播放器会重试，
# 效果等同排队）。注意：事件循环里必须用非阻塞的 try_acquire。
MAX_CONCURRENT_RANGES_PER_FILE = 3
RANGE_ACQUIRE_TIMEOUT_SEC = 60.0


class RangeConcurrencyLimiter:
    """按文件路径限流的线程信号量池（streaming 的同步 generator 跑在线程池，
    这里必须用 threading 而非 asyncio）。"""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_RANGES_PER_FILE,
                 acquire_timeout: float = RANGE_ACQUIRE_TIMEOUT_SEC):
        self._max = max_concurrent
        self._timeout = acquire_timeout
        self._lock = threading.Lock()
        self._sems: dict[str, threading.Semaphore] = {}
        self._last_used: dict[str, float] = {}

    def _get(self, path: str) -> threading.Semaphore:
        now = time.monotonic()
        with self._lock:
            sem = self._sems.get(path)
            if sem is None:
                sem = threading.Semaphore(self._max)
                self._sems[path] = sem
            self._last_used[path] = now
            # 惰性清理：条目太多时清掉 1 小时没用过的，避免无限增长
            if len(self._sems) > 2000:
                cutoff = now - 3600
                stale = [k for k, ts in self._last_used.items() if ts < cutoff]
                for k in stale:
                    self._sems.pop(k, None)
                    self._last_used.pop(k, None)
            return sem

    def acquire(self, path: str) -> bool:
        """阻塞最多 ``acquire_timeout`` 秒拿一个名额，拿到返回 True。"""
        return self._get(path).acquire(timeout=self._timeout)

    def try_acquire(self, path: str) -> bool:
        """非阻塞拿名额，拿到返回 True，拿不到立即返回 False。

        在 async 事件循环里必须用这个（blocking 的 acquire 会卡住整个循环）。
        拿不到时调用方直接 503，播放器会重试，效果等同排队。"""
        return self._get(path).acquire(blocking=False)

    def release(self, path: str) -> None:
        sem = self._sems.get(path)
        if sem is not None:
            try:
                sem.release()
            except ValueError:
                pass  # 重复释放时忽略


# 全站单例：所有 worker 线程共享同一份限流状态
RANGE_LIMITER = RangeConcurrencyLimiter()


# ---------------------------------------------------------------------------
# 4. 移动端 4K 透明降级
# ---------------------------------------------------------------------------
# 手机屏看 4K 是浪费：22GB 的 2160p 在手机上和 3.8GB 的 1080p 肉眼无差，
# 但带宽差 6 倍。PlaybackInfo 里如果同部片有更低分辨率版本，移动端直接
# 给低版本（客户端无感，不用转码、不用用户手动切）。
MOBILE_UA_PATTERNS = (
    "iphone", "ipad", "ipod", "android", "mobile",
    "senplayer",  # iOS 第三方播放器常见 UA 关键字
    "vidhub",
)


def is_mobile_client(user_agent: Optional[str]) -> bool:
    """UA 是否像手机/平板（含常见第三方播放器）。"""
    if not user_agent:
        return False
    ua = user_agent.lower()
    return any(p in ua for p in MOBILE_UA_PATTERNS)


def maybe_downgrade_for_client(item: Any, user_agent: Optional[str],
                              db: Any) -> Any:
    """移动端 4K 透明降级：有同部 ≤1080p 版本时返回那个，否则原样返回。

    ``item`` 是 MediaItem ORM 对象；``db`` 是 Session。只读不写库。
    判定"同部"：优先 tmdb_id + library_id + item_type，无 tmdb_id 时回退
    归一化标题（复用 dedup.normalize_name）+ 年份。
    """
    try:
        height = int(getattr(item, "height", 0) or 0)
    except (TypeError, ValueError):
        return item
    if height <= 1080 or not is_mobile_client(user_agent):
        return item

    try:
        from backend.emby_server import dedup  # 延迟导入，避免循环
        from backend.emby_server import models as em
    except Exception:  # noqa: BLE001
        return item

    try:
        q = db.query(em.MediaItem).filter(
            em.MediaItem.library_id == item.library_id,
            em.MediaItem.item_type == item.item_type,
            em.MediaItem.height.isnot(None),
            em.MediaItem.height <= 1080,
            em.MediaItem.height > 0,
            em.MediaItem.id != item.id,
        )
        tmdb_id = getattr(item, "tmdb_id", None)
        if tmdb_id:
            q = q.filter(em.MediaItem.tmdb_id == tmdb_id)
        else:
            norm = dedup.normalize_name(getattr(item, "name", ""))
            if not norm:
                return item
            # 归一化标题相等且年份一致才算同部，避免张冠李戴
            q = q.filter(em.MediaItem.name.isnot(None))
            candidates = q.limit(50).all()
            same = [c for c in candidates
                    if dedup.normalize_name(c.name) == norm
                    and getattr(c, "production_year", None) == getattr(item, "production_year", None)]
            if not same:
                return item
            # 取分辨率最高的那个 ≤1080p 版本
            same.sort(key=lambda c: int(c.height or 0), reverse=True)
            chosen = same[0]
            logger.info("移动端 4K 透明降级：%s (%sp) → %s (%sp)",
                        item.name, height, chosen.name, chosen.height)
            return chosen
        chosen = q.order_by(em.MediaItem.height.desc()).first()
        if chosen is None:
            return item
        logger.info("移动端 4K 透明降级：%s (%sp) → %s (%sp)",
                    item.name, height, chosen.name, chosen.height)
        return chosen
    except Exception:  # noqa: BLE001
        logger.exception("透明降级查询失败，回退原片")
        return item
