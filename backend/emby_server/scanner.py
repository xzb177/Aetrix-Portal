"""自建 Emby 服务器：扫描共享基础（工具函数 + 扫描生命周期）

本模块不再包含扫描主体（2026-10-05 起，唯一的扫描实现是
``fast_scanner.scan_library_sync``，旧扫描体已删除）。保留：

- 文件名解析 / 媒体探测（ffprobe/mediainfo）/ 工具函数：probe_worker 等仍在用
- LibrarySnapshot / ScanFile：扫描配置快照
- 扫描生命周期：begin_scan / finish_scan / fail_scan（ScanRun 流水、trigger）
- 进程内互斥：_acquire_scan / _release_scan / is_scan_active
- 扫描结果载荷：scan_result_payload / scan_runs_payload（管理端展示）
- _purge_items：soft_delete 的物理删除用
"""
from __future__ import annotations

import hashlib
import json  # 扫描结果落库（scan_stats）需要
import logging
import os
import posixpath
import re
import struct
import subprocess
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db_retry import commit_with_retry
from backend.emby_server import models as emby_models
from backend.emby_server import mounts as mount_lib

# TMDB 刮削客户端已拆到 tmdb.py：扫描器只管遍历与写库，网络客户端（密钥轮询 + 短 TTL 缓存）
# 单独成模块。这里重新导出一次，`scanner.tmdb_client` / `scanner.TmdbClient` 等既有引用不变。
from backend.emby_server.tmdb import (  # noqa: F401
    TMDB_API,
    TMDB_IMAGE,
    TMDB_LANG,
    TmdbClient,
    prewarm_images,
    tmdb_client,
)

# 外挂字幕的同名判定与语言识别已拆到 subtitle_match.py（本机与远程挂载共用同一份实现；
# 注意别与负责字幕**投递**的 subtitles.py 搞混）。同样重新导出，
# `scanner.match_subtitle_names` 等既有引用不需改动。
from backend.emby_server.subtitle_match import (  # noqa: F401
    SUBTITLE_EXTS,
    find_external_subtitles_in,
    find_external_subtitles_remote,
    match_subtitle_names,
    subtitle_language,
)

logger = logging.getLogger(__name__)

# ==================== 资源预算（这个后端要能在小机器上跑完整库）（这个后端要能在 1C1G 的小机器上跑完整库）====================
# 老实现每处理一个文件就：2~5 次数据库查询 + 1 次 ffprobe + 1~2 次目录列举 + 1 次 commit，
# 而且清理阶段会把整库 MediaItem 一次性载入内存。大库（十万级）下既慢又吃内存。
# 现在按「批次」处理：
#   SCAN_BATCH  一批多少个文件（批量查库 / 批量提交 / 批后清空会话）
#   SCAN_WORKERS 并行 IO 线程数（ffprobe、目录列举、TMDB 搜索都是“等网络/等磁盘”，不是吃 CPU）
SCAN_BATCH = max(20, int(os.getenv("SCAN_BATCH", "400") or 400))
SCAN_WORKERS = max(1, min(16, int(os.getenv("SCAN_WORKERS", "4") or 4)))
# 两阶段扫描（v2.39.0）：
#   inline（默认）：与旧行为完全一致，扫描时直接 ffprobe；
#   background：Phase 1 只入库结构（路径解析/NFO/TMDB 图），不做 ffprobe，
#     需要探测的条目标 probe_status='pending'，由 probe_worker 后台按优先级探测。
# 回滚：改回 inline 并重启，行为即回到从前。
SCAN_PROBE_MODE = (os.getenv("SCAN_PROBE_MODE", "inline") or "inline").strip().lower()
PROBE_BACKGROUND = SCAN_PROBE_MODE == "background"
# SQLite 的绑定变量上限是 999，IN 查询按这个分片（片内元素个数）
SQL_IN_CHUNK = 200
# 清理阶段每批读多少条：这一步不碰 IO（只读 4 个列），批越大越省往返。
# 实测十万条目：每批 400 条 2.1s → 每批 5000 条 0.6s（稳定库还有更快的快速路径，见下）。
CLEANUP_BATCH = max(20, int(os.getenv("SCAN_CLEANUP_BATCH", "5000") or 5000))

# ==================== 删除保护（v2.46.0）====================
# 事故形状：「挂载断开 → 底层空目录还在 → 本轮扫描看到 0 个文件 → 清理阶段把整库删了」。
# ``failed_roots`` 挡不住这种（目录还在，只是空的），所以再加两道：
# 1) **零结果**：一个文件都没看到，但库里有条目 —— 直接不删。一次判断就能兜住事故主体。
# 2) **数量阈值**：本轮删掉的量超过库内条目数的这个比例（或绝对数），就认为不对劲。
REMOVAL_MIN_SEEN = 1
#: 比例阈值：删掉超过库内文件类条目的这个比例就停手（0.5 = 一半以上全没了）
REMOVAL_MAX_RATIO = float(os.getenv("SCAN_REMOVAL_MAX_RATIO", "0.5") or 0.5)
#: 绝对阈值：小库也要有下限保护（库里总共就 10 条，删 6 条就已经是“全没了”）
REMOVAL_MAX_ABSOLUTE = max(1, int(os.getenv("SCAN_REMOVAL_MAX_ABSOLUTE", "20") or 20))


# 上一次清理阶段的决策（健康检查与测试用：有没有走快速路径、走过多少条、耗时）
_CLEANUP_LAST: dict = {"fast_path": False, "walked": 0, "removed": 0, "elapsed_ms": 0.0,
                       # skipped = 删除保护拦下了本轮清理的原因（空串 = 没拦）
                       # 调用点用 .get("skipped") 读，所以这个键**必须一开始就存在**，
                       # 否则读出来恒为空、“被拦了”这件事就永远传不到接口/前端。
                       "skipped": ""}

# ==================== 扫描限速（播放优先）====================
# 扫描跑在 API 进程的后台线程里，而 POSIX 的 nice 是**进程级**的：直接给本进程降优先级，
# 会连同一进程里正在播放的请求一起降——那是错的。所以这里只降**子进程**：ffprobe 是扫描里
# 唯一的外部进程，既是最吃 CPU 的一步，也最容易和播放抢磁盘 IO。
#   SCAN_IO_NICE  探测子进程的 niceness（0 = 关闭，默认 10；越大越让路）
# 同时若有 ionice 就把 IO 优先级降到 best-effort 最低档（-c2 -n7；只降不升，普通用户即可）。
SCAN_IO_NICE = max(0, min(19, int(os.getenv("SCAN_IO_NICE", "10") or 0)))


def _tool_usable(argv: list) -> bool:
    """先拿一个空命令试跑一次：工具存在但内核/容器不允许时，绝不能拖累真正的探测"""
    try:
        proc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def _io_nice_prefix() -> tuple:
    """给探测子进程加「低优先级」前缀；平台或工具不具备时返回空，不影响功能

    只在**启动时探一次**（结果缓存）：宁可退化成普通优先级，也不能让 wrapper 把 ffprobe 挡掉。
    """
    if SCAN_IO_NICE <= 0:
        return ()
    prefix: list = []
    if os.name == "posix":
        ionice = shutil_which("ionice")
        if ionice and _tool_usable([ionice, "-c", "2", "-n", "7", "sleep", "0"]):
            prefix += [ionice, "-c", "2", "-n", "7"]
    nice = shutil_which("nice")
    if nice:
        prefix += [nice, "-n", str(SCAN_IO_NICE)]
    if prefix:
        logger.info("扫描限速：ffprobe 子进程降优先级 %s（SCAN_IO_NICE=%d）", " ".join(prefix), SCAN_IO_NICE)
    return tuple(prefix)


def _io_nice_command(argv: list) -> list:
    """把命令包成低优先级版本（前缀为空时原样返回）"""
    return list(_io_nice_prefix()) + list(argv)


# `.strm` 不是视频文件，而是「内容为播放直链的文本文件」；是否把 strm 当媒体由调用方决定
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m2ts", ".ts", ".m4v", ".strm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# 集号解析: S01E02 / 1x02 / 第1集 / EP03 / E03
EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})\s?[\s._-]*[Ee](\d{1,3})"),
    re.compile(r"(\d{1,2})x(\d{1,3})"),
    re.compile(r"第\s*(\d{1,3})\s*[集话話]"),
    re.compile(r"\b[Ee][Pp]\.?\s?(\d{1,3})(?!\d)"),
]

# 只有季号（季包 / 中文命名）: S09 / Season 9 / 第九季 / 第9季
# 注意：裸 S09 只在剧集库里启用，否则 "S1m0ne" 这类片名会被误判成第 1 季。
SEASON_PATTERNS_TV = [
    re.compile(r"(?<![A-Za-z0-9])[Ss](\d{1,2})(?![\dEe])"),
]
SEASON_PATTERNS_ANY = [
    re.compile(r"[Ss]eason\s*\.?\s*(\d{1,2})", re.IGNORECASE),
    re.compile(r"第\s*(\d{1,2})\s*季"),
    re.compile(r"第\s*([一二三四五六七八九十]{1,3})\s*季"),
]
# 电影文件名解析: Name (2019) / Name.2019.1080p
YEAR_RE = re.compile(r"[\(\.\s](\d{4})[\)\.\s]")
# 旧写法 `[.\_-_\[\]【】]+'` 在字符类外多了一个引号，导致这个正则几乎永不命中，
# 于是 `Rick.and.Morty` 这类点分隔片名会原样入库（显示成 "Rick.and.Morty"）。
CLEAN_RE = re.compile(r"[\.\_\-\[\]【】]+")

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn_to_int(text: str) -> Optional[int]:
    """中文数字 → 整数（支持 一 ~ 九十九，够用于季数）"""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(text)

# ==================== 发行平台识别（虚拟媒体库的数据来源）====================
# 片名里的发行组标签是最稳定的平台信号：NF / DSNP / ATVP / AMZN / MAX …
# 这里把常见标签映射成“平台 id（展示名）”，供按平台自动生成虚拟媒体库。
PLATFORM_TAGS: dict[str, tuple[str, ...]] = {
    "netflix": ("nf", "netflix", "nfhd", "nfweb"),
    "disney": ("dsnp", "dsny", "disney", "disneyplus"),
    "appletv": ("atvp", "atv", "appletv", "itunes", "atv4k"),
    "prime": ("amzn", "prime", "amazon", "primevideo"),
    "max": ("max", "hmax", "hbo", "hbomax"),
    "hulu": ("hulu",),
    "paramount": ("pmtp", "pmp", "paramount", "paramountplus"),
    "peacock": ("pcok", "peacock"),
    "crunchyroll": ("cr", "crunchyroll", "cr-web", "crweb"),
}
# 展示名（虚拟媒体库名称）
PLATFORM_LABELS: dict[str, str] = {
    "netflix": "Netflix",
    "disney": "Disney+",
    "appletv": "Apple TV+",
    "prime": "Prime Video",
    "max": "Max",
    "hulu": "Hulu",
    "paramount": "Paramount+",
    "peacock": "Peacock",
    "crunchyroll": "Crunchyroll",
}
# 只认“独立成词”的标签，避免 nf / cr / max 这种短标签误命中片名
_PLATFORM_RE = {
    platform: re.compile(
        r"(?<![A-Za-z0-9])(" + "|".join(re.escape(t) for t in sorted(tags, key=len, reverse=True)) + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    for platform, tags in PLATFORM_TAGS.items()
}


# 发布标识（分辨率/来源/编码）：短平台标签（nf / cr / max …）只有出现在真正的发布名里才认，
# 否则一部就叫《Max》或《C.R.》的电影会被打成 HBO Max 库。
_RELEASE_HINT_RE = re.compile(
    r"(?<![A-Za-z0-9])(2160p|1080p|720p|480p|4k|uhd|web-?dl|webrip|bluray|blu-ray|"
    r"bdrip|remux|hdtv|hdrip|dvdrip|x264|x265|h264|h265|hevc|avc)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
SHORT_PLATFORM_TAG_LEN = 4


# ==================== 刮削策略 ====================
# 后台可选的媒体库刮削策略：天数为“到期重刮”窗口，None = 永远只补缺，0 = 每次全量
SCAN_POLICIES: dict[str, Optional[int]] = {
    "missing_only": None,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "all": 0,
}
DEFAULT_SCRAPE_POLICY = "missing_only"

def normalize_scrape_policy(value: Optional[str]) -> str:
    """归一化刮削策略（未知值回退为 missing_only，不会因为脏数据全量重刮）"""
    return value if value in SCAN_POLICIES else DEFAULT_SCRAPE_POLICY


_INT64_MAX = 2 ** 63 - 1


def safe_probe_int(value, default: int = 0) -> int:
    """把探测结果里的数值字段收敛成能落库的整数。

    ffprobe/MediaInfo 在远程流上偶发给出 None、负数或超大码率。任一情况直接
    落库都会抛 ``NumericValueOutOfRange``，把这一条 commit 失败、连带整轮扫描
    或探测白跑，所以写库前一律走这里。
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        # 少数探测源给的是 "1234.9" 这类字符串小数，退一步按浮点解析再截断
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            return default
    if parsed < 0 or parsed > _INT64_MAX:
        return default
    return parsed


def needs_probe(item, path: str, size: Optional[int] = None) -> bool:
    """是否需要重新 ffprobe

    文件信息已经获取过就不再每次扫描重复探测——ffprobe 是扫描里最贵的一步，
    整库重扫时它会吃掉绝大部分时间。仅当文件大小变了（换源/重压）才重探。

    远程挂载（115 / WebDAV / AList）没有本机文件，大小由调用方从目录列表传入。
    """
    # 远程探测失败后的 degraded、以及 ffprobe 跑完但拿不到时长的 probed_no_duration，
    # 都是**明确的终态结果**：同一文件不要每轮扫描无限重试（否则 2.6 万条会把 worker
    # 名额占满，真正能探到的文件排不进来）。用户按需点详情/播放时再 boost_probe，
    # 或文件大小变化时重新排队。
    if (getattr(item, "probe_status", None) in ("degraded", "probed_no_duration")
            and item.last_probed_at is not None):
        if size is None:
            return False
        return bool(item.size) and size != item.size
    if not item.duration_ticks or item.last_probed_at is None:
        return True
    if size is None:
        try:
            size = os.path.getsize(path)
        except OSError:
            # 远程源取不到大小时不重复探测（ffprobe 走网络更贵），保留已有元数据
            return False
    if not size:
        return False
    return bool(item.size) and size != item.size


def item_guid(path: str) -> str:
    """由稳定路径生成 32 位 guid"""
    return hashlib.md5(("rb:item:" + path.lower()).encode("utf-8")).hexdigest()


def _tidy_name(raw: str) -> str:
    """清洗片名；结果只剩分隔符时返回空（供回退到目录名用）"""
    out = clean_name(raw or "")
    return "" if not out.strip(" .-_[]()") else out


# 发行平台标签（NF / DSNP / ATVP …）也属于发布标签，片名里要一起去掉
_PLATFORM_TOKEN_RE = re.compile(
    r"(" + "|".join(
        sorted((t for tags in PLATFORM_TAGS.values() for t in tags), key=len, reverse=True)
    ) + r")",
    re.IGNORECASE,
)


def _strip_platform_tags(name: str) -> str:
    """去掉片名里的发行平台标签

    只删非首个词：一部片名就叫 `Max` / `Hulu` 的电影不会被吃空。
    否则 `Alpha.Target.2024.1080p.NF.WEB-DL` 会入库成 “Alpha Target  NF”。
    """
    parts = [p for p in (name or "").split() if p]
    return " ".join(p for idx, p in enumerate(parts) if idx == 0 or not _PLATFORM_TOKEN_RE.fullmatch(p))


def clean_name(raw: str) -> str:
    name = CLEAN_RE.sub(" ", raw)
    # 去掉质量标签。注意 CLEAN_RE 已经把 `.` `_` `-` 换成了空格，所以这里的分隔符
    # 必须容得下空格：否则 "WEB-DL" 变成 "WEB DL" 后不再被识别。
    name = re.sub(
        r"\b(2160p|1080p|720p|480p|4k|uhd|hdr10\+?|hdr|dolby|dv|hevc|h\.?264|x264|h\.?265|x265|"
        r"aac|ac3|eac3|dts|flac|truehd|atmos|web[\s\-]?dl|webrip|web|remux|blu[\s\-]?ray|bluray|"
        r"bdrip|brrip|hdtv|dvdrip|repack|proper|multi|internal|chs&eng|chs|cht|eng|gb|big5)\b",
        " ",
        name,
        flags=re.IGNORECASE,
    )
    name = _strip_platform_tags(name)
    return re.sub(r"\s+", " ", name).strip(" .-_") or raw


def _episode_display_name(name: str, season_no: Optional[int], ep_no: Optional[int]) -> str:
    """一集的标准展示名：``片名 S01E02``

    **只解析出季号、没有集号**时（``片名 Season 2.mkv``、季包整季文件）不能硬套
    ``E{ep_no:02d}``：``None`` 做 ``:02d`` 会抛
    ``TypeError: unsupported format string passed to NoneType.__format__``，
    整个媒体库的扫描会在这一行崩掉、前面已扫的批次全部白跑。

    这类文件按 ``片名 S02`` 命名，集号留空（后续人工补），不猜、不填 0。
    """
    base = (name or "").strip()
    if ep_no is None:
        return f"{base} S{season_no:02d}" if season_no is not None else base
    if season_no is None:
        return f"{base} E{ep_no:02d}"
    return f"{base} S{season_no:02d}E{ep_no:02d}"


def parse_media_filename(path: str, library_type: str) -> dict:
    """从文件路径解析 基础名称/年份/季/集

    季的识别除 S01E02 / 1x02 / 第1集 外，还覆盖**只有季号**的常见命名：
    `S09`、`Season 9`、`第九季`、`第9季` —— 季包与中文命名场景下，
    旧实现认不出季，整季包会被当成电影。
    """
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    folder = os.path.basename(os.path.dirname(path))
    is_tv = library_type == "tvshows"

    season = episode = None
    matched_in_folder = False
    match_span: Optional[tuple[int, int]] = None

    # 1) 带集号：文件名优先，剧集库再退回目录名
    for pat in EP_PATTERNS:
        m = pat.search(stem)
        if not m and is_tv:
            m = pat.search(folder)
            matched_in_folder = m is not None
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 2:
            season, episode = int(groups[0]), int(groups[1])
        else:
            season, episode = 1, int(groups[0])
        match_span = (m.start(), m.end())
        break

    # 2) 只有季号：中文季与 "Season N" 任意库都认；裸 S09 仅剧集库认
    if season is None:
        season_patterns = SEASON_PATTERNS_ANY + (SEASON_PATTERNS_TV if is_tv else [])
        for pat in season_patterns:
            m = pat.search(stem)
            if not m and is_tv:
                m = pat.search(folder)
                matched_in_folder = m is not None
            if not m:
                continue
            raw = m.group(1)
            season = cn_to_int(raw) if raw and not raw.isdigit() else int(raw)
            if season is None or season < 0 or season > 99:
                season = None
                continue
            match_span = (m.start(), m.end())
            break

    # 片名：把匹配到的季/集标记从名称里**挖掉**其余保留。
    # 只看前缀在 "Rick.and.Morty.Season 9" 这类命名上会把季号留在片名里，
    # 也会在标记在最前面时丢掉片名。
    target = folder if matched_in_folder else stem
    raw_name = target
    if season is not None and match_span:
        raw_name = f"{target[: match_span[0]]} {target[match_span[1]:]}".strip()
    name_part = _tidy_name(raw_name) or _tidy_name(folder) or _tidy_name(stem)

    year = None
    m = YEAR_RE.search(stem) or YEAR_RE.search(folder)
    if m:
        y = int(m.group(1))
        if 1900 <= y <= datetime.now().year + 2:
            year = y
    if year and str(year) in name_part:
        name_part = name_part.replace(str(year), "").strip(" .-_()")

    return {"name": name_part or stem, "year": year, "season": season, "episode": episode}


# 远程 ffprobe 的有限 Range 上限：rclone rc-serve 不接受默认的开放式
# ``Range: bytes=0-``，但媒体头（尤其 Matroska 的 EBML/Info）通常在前段即可拿到。
#
# 窗口不能开太大：ffprobe 会把 206 响应当成**整个文件**，窗口一大就等于喂了半个文件，
# 它读到截断处判定 "File ended prematurely" 反而失败。实测 1 MiB 稳定拿到 mkv 时长，
# 8 MiB 就会触发该错误，所以默认按 1 MiB 走（256 KiB～4 MiB 均可，按需用环境变量调）。
try:
    PROBE_REMOTE_RANGE_BYTES = max(1 << 18, int(os.getenv("PROBE_REMOTE_RANGE_BYTES", "1048576")))
except ValueError:
    PROBE_REMOTE_RANGE_BYTES = 1 << 20


# 第二跳（双 Range）的**尾部**窗口。moov 原子在文件尾的 MP4/MOV，头部窗口读不到时长，
# 这时才并行再取一段尾巴——只对下面这些容器开，其它封装（MKV 的时长在 EBML 头部）
# 第一跳就拿到了，别为它们多花流量。
try:
    PROBE_REMOTE_TAIL_BYTES = max(1 << 18, int(os.getenv("PROBE_REMOTE_TAIL_BYTES", "2097152")))
except ValueError:
    PROBE_REMOTE_TAIL_BYTES = 2 << 20

#: 需要「尾部再读一次」的容器（moov 可能落在文件尾）。
#: 只收 MP4/MOV 系：Matroska / WebM 的时长写在文件头的 Segment Info 里，
#: 第一跳 1 MiB 稳定命中，给它们加尾部请求纯属白烧网盘流量与带宽。
_TAIL_MOOV_CONTAINERS = frozenset({
    "mp4", "m4v", "m4a", "mov", "qt", "3gp", "3g2", "f4v",
})

#: 双 Range 抓字节的超时。rclone rc-serve / 云盘直链首字节慢是常态，
#: 但也别放到和 ffprobe 一样的 90 秒——那是兜底 seek 路径的量级。
PROBE_HTTP_TIMEOUT = 45.0

#: 探测**本机文件**（含 FUSE / rclone 挂载）的超时秒数。
#:
#: 原先本机与远端共用 90 秒，而 ffprobe 失败后还会再跑一次同样 90 秒的 MediaInfo
#: 备用探测——单个文件最坏 180 秒。生产实测（2026-10-05）：4 核机器、``/mnt/mp``
#: 是 fuse.rclone，mediainfo 常驻 D 状态（不可中断 IO），探测吞吐掉到约 1.3 个
#: 文件/分钟，一千多个待探测条目堆着不动，同时把补全 worker 的 IO 一起堵住。
#:
#: 读文件头不需要 90 秒：正常文件秒级返回，读不出来的是挂载本身没响应，等满 90 秒
#: 也等不到——只会白占一个 worker 槽位。
PROBE_FILE_TIMEOUT = max(5.0, float(os.getenv("PROBE_FILE_TIMEOUT_SEC", "30") or 30))
#: 远端 URL 的探测上限不变：网络慢是常态，砍时间会误伤真正在下载的大文件。
PROBE_REMOTE_TIMEOUT = max(10.0, float(os.getenv("PROBE_REMOTE_TIMEOUT_SEC", "90") or 90))

#: 最近一次 ffprobe 是否以超时告终。ffprobe 跑在多个 worker 线程里，所以用线程局部
#: 存；判定只发生在紧接其后的调用点，不跨条目复用。
_ffprobe_timeout_flag = threading.local()


def _mark_ffprobe_timed_out() -> None:
    _ffprobe_timeout_flag.timed_out = True


def _last_ffprobe_timed_out() -> bool:
    """读取「本次 ffprobe 是否超时」并**清零**（供 probe_metadata 决定要不要跑备用探测）

    读完就清，避免上一条标记让后面的判定走偏；``_ffprobe`` 入口也会再清一次——
    两处都清是刻意的：这里防「上一条」，入口防「上一跳」。
    """
    was = bool(getattr(_ffprobe_timeout_flag, "timed_out", False))
    _ffprobe_timeout_flag.timed_out = False
    return was


# ffprobe 错误码翻译：把含糊的底层错误转成可行动的信息
_FFPROBE_HTTP_ERRORS = {
    403: "远端配额/权限受限 (HTTP 403)——可能是 Google Drive 每日下载配额耗尽，24 小时后自动恢复；或检查 rclone 账号权限",
    401: "远端认证失败 (HTTP 401)——检查 rclone 账号/Token 是否过期",
    404: "远端文件不存在 (HTTP 404)——文件可能已被删除或路径变更",
    429: "远端限流 (HTTP 429)——请求过快，稍后重试",
}


def _parse_ffprobe_http_error(stderr: str) -> Optional[int]:
    """从 ffprobe stderr 解析 HTTP 状态码。

    ffprobe 的 http 层对非 200 一律报 404（误导人），实际需从
    "Server returned 403 Forbidden" 这类信息里提取真实状态码。
    """
    import re
    # 匹配 "Server returned 403 Forbidden" 或 "HTTP error 403" 等
    for pat in (r"Server returned (\d{3})", r"HTTP error (\d{3})", r"HTTP (\d{3})"):
        m = re.search(pat, stderr)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def _ffprobe(path: str, headers: Optional[dict] = None, size: int = 0,
             ranged: bool = True, local_path: str = "") -> Optional[dict]:
    """ffprobe 提取媒体信息（无 ffprobe 时优雅降级）。

    远程直链补一个有限 Range，兼容 rclone rc-serve；本机文件不改变行为。
    ``ranged=False`` 时不注入 Range，让 ffprobe 自己按需 seek（慢速回退路径，
    见 ``probe_metadata``：有限窗口读不到 moov 的容器需要它）。
    ``local_path`` 非空时改为探测**这个本地文件**（双 Range 拼出来的「头部 + moov」临时文件），
    完全不碰 Range / ``-headers``——这两项只对 http 协议有效，喂本地文件反而会让
    ffprobe 报 ``Option headers not found`` 直接失败。

    返回的 dict 可能含 `_error` 字段：
    - `_error="quota"`：HTTP 403，远端配额/权限受限
    - `_error="not_found"`：HTTP 404，文件不存在
    - `_error="auth"`：HTTP 401，认证失败
    """
    if not shutil_which("ffprobe"):
        return None
    # -v error：只输出错误（不用 quiet，否则 403/404 的真实原因被吞掉）
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    target = local_path or path
    if not local_path:
        probe_headers = dict(headers or {})
        if ranged and path.startswith(("http://", "https://")) and not any(
            str(k).lower() == "range" for k in probe_headers
        ):
            total = int(size or 0)
            end = min(total - 1, PROBE_REMOTE_RANGE_BYTES - 1) if total > 0 else PROBE_REMOTE_RANGE_BYTES - 1
            probe_headers["Range"] = f"bytes=0-{max(0, end)}"
        if probe_headers:
            joined = "".join(f"{k}: {v}\r\n" for k, v in probe_headers.items())
            cmd += ["-headers", joined]
    cmd.append(target)
    # 扫描探测让路给播放（见文件头「扫描限速」）：只降这一条子命令，不碰本进程
    cmd = _io_nice_command(cmd)
    # 本机文件（含 FUSE）与远端 URL 用不同上限：FUSE 读不出就是读不出，
    # 干等 90 秒只是白占 worker 槽位（见 PROBE_FILE_TIMEOUT 的说明）。
    _is_remote = (not local_path) and path.startswith(("http://", "https://"))
    _timeout = PROBE_REMOTE_TIMEOUT if _is_remote else PROBE_FILE_TIMEOUT
    # 每次调用先清零：上一次 ffprobe 超时不应让这一次的判定跟着走偏。
    _ffprobe_timeout_flag.timed_out = False
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=_timeout)
        import json

        data = json.loads(out.stdout or "{}")
        # 检查 stderr 里的 HTTP 错误（ffprobe 把 403 也报成 404，需提取真实码）
        if not data.get("format"):
            http_code = _parse_ffprobe_http_error(out.stderr or "")
            if http_code:
                data["_http_code"] = http_code
                detail = _FFPROBE_HTTP_ERRORS.get(http_code, f"远端 HTTP 错误 ({http_code})")
                data["_error_detail"] = detail
                if http_code == 403:
                    data["_error"] = "quota"
                    logger.warning("ffprobe 探测 %s: %s", path, detail)
                elif http_code == 404:
                    data["_error"] = "not_found"
                elif http_code == 401:
                    data["_error"] = "auth"
                else:
                    data["_error"] = f"http_{http_code}"
        return data
    except subprocess.TimeoutExpired:
        # 超时 ≠ 数据不对，而是「挂载/端点没响应」。标记给 probe_metadata，
        # 让它跳过同样会超时的 MediaInfo 备用探测。
        # 必须排在下面的宽 except **之前**：TimeoutExpired 继承自 SubprocessError，
        # 被宽分支先吃掉的话这个专用处理永远轮不到（测试就是这么抓出来的）。
        _mark_ffprobe_timed_out()
        logger.warning("ffprobe 超时（%ss）%s: 挂载或端点无响应", _timeout, path)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("ffprobe 失败 %s: %s", path, e)
        return None


def shutil_which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


def _mediainfo(path: str, headers: Optional[dict] = None, size: int = 0) -> Optional[dict]:
    """ffprobe 失败后的 MediaInfo 备用探测。

    MediaInfo 对部分 MP4/MKV 的容错比 ffprobe 好，但它同样可能被远程 Range 限制，
    所以只是 fallback，不把它当万能替代。返回与 _ffprobe 兼容的简化结构。
    """
    if not shutil_which("mediainfo"):
        return None
    cmd = ["mediainfo", "--Output=JSON"]
    # MediaInfo 没有 ffprobe 那样稳定的 header 注入口；本机文件直接用，
    # 远程 URL 失败就交给 degraded，不额外制造一次可能更慢的网络请求。
    if path.startswith(("http://", "https://")):
        return None
    cmd.append(path)
    # 与 ffprobe 用同一个上限：FUSE 上超时意味着挂载没响应，
    # 这时再等一次同样读不出东西。
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_FILE_TIMEOUT)
        import json
        raw = json.loads(out.stdout or "{}")
        tracks = raw.get("media", {}).get("track", [])
        if not tracks:
            return None
        info = {"format": {}, "streams": []}
        for t in tracks:
            kind = str(t.get("@type") or "").lower()
            if kind == "general":
                info["format"] = {
                    "duration": float(t.get("Duration") or 0) / 1000.0,
                    "size": int(float(t.get("FileSize") or size or 0)),
                    "bit_rate": int(float(t.get("OverallBitRate") or 0)),
                }
            elif kind in ("video", "audio", "text"):
                stype = {"video": "video", "audio": "audio", "text": "subtitle"}[kind]
                info["streams"].append({
                    "codec_type": stype,
                    "codec_name": t.get("CodecID") or t.get("Format"),
                    "width": int(float(t.get("Width") or 0)),
                    "height": int(float(t.get("Height") or 0)),
                    "bit_rate": int(float(t.get("BitRate") or 0)),
                    "channels": int(float(t.get("Channel_s_") or t.get("Channels") or 0)),
                    "tags": {"language": t.get("Language") or ""},
                })
        return info if info.get("format", {}).get("duration") else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("MediaInfo 备用探测失败 %s: %s", path, exc)
        return None


# ==================== 第二跳：远程 moov 在尾的双 Range 读取 ====================
#
# 背景：第一跳只注入 ``Range: bytes=0-1MiB``，ffprobe 把 206 当成整个文件。mkv 的时长在
# EBML 头部（第一跳就拿到），但**moov 原子在文件尾**的 mp4/mov 前 1 MiB 里根本没时长，
# 于是 format 为空。旧做法是「去掉 Range 再探一次」让 ffprobe 自己 seek——它会把整个文件
# 从头拉到尾，云盘直链上这是几 GB 的流量，2.6 万条文件撞上它就是场灾难。
#
# 现在改成：**并行**取两段（前 1 MiB + 后 N MiB），从尾段里把 moov 盒子**摘出来**，
# 拼成「头部 + moov」的小文件再喂 ffprobe，并把 mdat 的大小改写成恰好在 moov 前结束。
# 这样 demuxer 读得懂、时长与各轨参数都来自 moov（正确），而落盘只有 1 MiB 出头。
#
# 为什么不是「头尾直接首尾相接」：实测（ffmpeg 7.0.2）那样拼出来会报
# ``moov atom not found`` —— 头部里的 mdat 声明了整个 mdat 的长度，demuxer 跳完它就
# EOF 了，根本走不到后面接的 moov。改写 mdat 长度是让它「指到 moov」的唯一办法。
#
# 为什么不用「按真实偏移回填 + 稀疏文件」：那样 moov 的绝对位置天然正确，但文件逻辑
# 大小等于原文件。ext4 与 Docker 的 overlayfs 在实测里**不会真的挖洞**（8 GiB 的空洞
# 实打实占了 8 GiB），一次探测就能把磁盘吃穿。


def _mp4_boxes(buf: bytes, base: int = 0, allow_overrun: bool = False):
    """按 MP4 box 结构逐层遍历顶层盒子，产出 (类型, 绝对起点, 绝对终点, 头长度, 声明大小)。

    ``allow_overrun=True`` 时不因「盒子声明的长度超出缓冲区」而停下。定位 mdat 头必须用
    这个模式：它的声明长度就是**整个媒体文件的大小**，远大于我们手上的 1 MiB 窗口，
    严格模式下永远走不到它。
    """
    off = 0
    while off + 8 <= len(buf):
        size = int.from_bytes(buf[off:off + 4], "big")
        typ = bytes(buf[off + 4:off + 8])
        hdr = 8
        if size == 1:                      # 64 位长度：大文件常见
            if off + 16 > len(buf):
                return
            size = int.from_bytes(buf[off + 8:off + 16], "big")
            hdr = 16
        if size == 0:                      # 「一直到文件末尾」
            size = len(buf) - off
        if size < hdr:
            return                          # 非法长度，停止遍历
        if off + size > len(buf):
            if not allow_overrun:
                return                      # 被截断了，停止遍历
            # 越界盒（就是 mdat）：位置与头长度仍然可信，交给调用方去改写它
            yield (typ, base + off, base + off + size, hdr, size)
            return
        yield (typ, base + off, base + off + size, hdr, size)
        off += size


def _find_moov(buf: bytes, base: int = 0):
    """在字节里定位 moov 盒子，返回 (绝对起点, 绝对终点)；找不到返回 None。

    不能从 buf[0] 按盒结构往下解析：尾段的起点在 mdat 中间，第一个「盒子」就是乱码，
    解析会立刻停住。改成搜 ``moov`` 四字节码，再校验它前面那个长度字段站得住脚。
    """
    pos = 0
    while True:
        hit = buf.find(b"moov", pos)
        if hit < 0:
            return None
        start = hit - 4
        if start >= 4:
            size = int.from_bytes(buf[start:start + 4], "big")
            hdr = 8
            if size == 1 and start + 16 <= len(buf):
                size = int.from_bytes(buf[start + 8:start + 16], "big")
                hdr = 16
            if size >= hdr and start + size <= len(buf):
                return (base + start, base + start + size)
        pos = hit + 4


def _mp4_probe_bytes(head: bytes, tail: bytes) -> Optional[bytes]:
    """「头部 + moov」拼出 ffprobe 能读的小文件；拼不出来返回 None（交给上层回退）。"""
    span = _find_moov(tail)
    if not span:
        return None
    moov = tail[span[0]:span[1]]
    body = bytearray(head + moov)
    moov_at = len(head)
    for typ, start, _end, hdr, _size in _mp4_boxes(bytes(body), allow_overrun=True):
        if typ != b"mdat":
            continue
        # 把 mdat 的声明长度改成「恰好停在 moov 前」，demuxer 跳过它就能读到 moov
        new_size = moov_at - start
        if new_size < 8:
            return None
        if hdr == 16 or new_size > 0xFFFFFFFF:
            struct.pack_into(">I", body, start, 1)
            struct.pack_into(">Q", body, start + 8, new_size)
        else:
            struct.pack_into(">I", body, start, new_size)
        return bytes(body)
    return None  # 没有顶层 mdat（分片 mp4 / 非标准封装），别硬拼


def _tail_moov_container(path: str, container: str = "") -> bool:
    """这个文件要不要走尾部再读一次（moov 可能落在文件尾的 MP4/MOV 系）。

    优先用调用方从库里带来的 ``container``（``MediaItem.container``，扫描时写死的），
    没给就从 URL 的后缀推——远程直链常带 ``?token=`` 之类的查询串，要先剥掉。
    """
    name = (container or "").strip().lower().lstrip(".")
    if not name:
        bare = path.split("?", 1)[0].split("#", 1)[0]
        name = posixpath.splitext(bare)[1].lstrip(".").lower()
    return name in _TAIL_MOOV_CONTAINERS


def _http_fetch_range(url: str, headers: Optional[dict], start: int, end: int) -> Optional[bytes]:
    """按 ``Range: bytes=start-end`` 取一段字节；失败返回 None（不抛）。

    云盘直链有几种不讲理的行为，这里都当正常情况处理：
    - 206（正常）与 200（**无视 Range 直接回整个文件**）都接受，后者按偏移自己切；
    - 4xx/5xx 抛出去（403 配额、404 文件没了要在上层翻译成 _error）。
    """
    import httpx

    req = {str(k): str(v) for k, v in (headers or {}).items()}
    req["Range"] = f"bytes={start}-{end}"
    with httpx.Client(timeout=PROBE_HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers=req)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}")
    body = resp.content or b""
    if resp.status_code == 206:
        return body
    # 200：服务端没认 Range，按我们请求的偏移自己切一刀（长度不够说明拿不全，弃用）
    return body[start:end + 1] if len(body) >= end + 1 else None


def _dual_range_temp_file(path: str, headers: Optional[dict], size: int) -> Optional[str]:
    """并行取「前 1 MiB + 后 PROBE_REMOTE_TAIL_BYTES」，拼成「头部 + moov」的临时文件。

    返回临时文件路径（调用方负责删），任何一步没成就返回 None。
    **两个请求是并行的**：先全部 submit 到 2 线程的池子，再逐个取结果——
    顺序等待等于串行，等于白优化。
    """
    total = int(size or 0)
    if total <= PROBE_REMOTE_RANGE_BYTES:
        return None  # 文件整个都在头部窗口里，第二跳没意义
    head_end = min(total - 1, PROBE_REMOTE_RANGE_BYTES - 1)
    tail_start = max(0, total - PROBE_REMOTE_TAIL_BYTES)
    if tail_start <= head_end + 1:
        return None  # 两段已经贴上（乃至重叠），拼出来就是整个文件，不如直接慢速回退
    with ThreadPoolExecutor(max_workers=2) as pool:
        # 两个请求都 submit 完再取结果：此刻它们已经在路上，并行。
        # 谁先返回谁先完成无所谓——顺序等待就是串行，等于白优化。
        head_future = pool.submit(_http_fetch_range, path, headers, 0, head_end)
        tail_future = pool.submit(_http_fetch_range, path, headers, tail_start, total - 1)
        try:
            head = head_future.result()
            tail = tail_future.result()
        except Exception as exc:  # noqa: BLE001 — 抓字节失败只是「这次双 Range 没成」
            logger.debug("双 Range 抓取失败 %s: %s", path, exc)
            return None
    if not head or not tail:
        logger.debug("双 Range 缺段 %s：head=%s tail=%s",
                     path, len(head or b""), len(tail or b""))
        return None
    payload = _mp4_probe_bytes(head, tail)
    if not payload:
        logger.debug("双 Range 拼不出可探的 mp4 %s（尾窗口里没有完整的 moov？）", path)
        return None
    suffix = posixpath.splitext(path.split("?", 1)[0])[1][:8] or ".bin"
    fd, tmp = tempfile.mkstemp(prefix="probe-tail-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
    except OSError as exc:
        logger.debug("双 Range 写临时文件失败 %s: %s", path, exc)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None
    return tmp


def _rescale_synthetic_format(data: dict, real_size: int, synth_size: int) -> None:
    """把 ffprobe 从「合成文件」算出来的容器级数值换算回原文件（就地改）。

    时长与各轨参数（分辨率 / 编码 / 帧率 / 声道）都写在 moov 里，不受拼装影响；
    但 ``format.bit_rate`` 与 ``format.size`` 是 demuxer 用「文件大小 ÷ 时长」现算的，
    而我们喂进去的只有 1 MiB 出头。实测差到千分之几（224 MiB 的文件被算成 19 kb/s）。
    漏掉这一步会把一堆离谱的码率写进库、显示在客户端的「媒体信息」页上。
    """
    fmt = data.get("format") or {}
    if not isinstance(fmt, dict):
        return
    if real_size > 0:
        fmt["size"] = str(real_size)
    if real_size <= 0 or synth_size <= 0 or synth_size >= real_size:
        return
    try:
        bit_rate = int(fmt.get("bit_rate") or 0)
    except (TypeError, ValueError):
        return
    if bit_rate > 0:
        fmt["bit_rate"] = int(bit_rate * real_size / synth_size)


def _dual_range_probe(path: str, headers: Optional[dict], size: int,
                      container: str = "") -> Optional[dict]:
    """第二跳：头尾并行抓 → 拼出「头部 + moov」→ ffprobe。

    拿不到 format 就返回 None，让上层回退到旧的自由 seek 路径（行为不倒退）。
    """
    if not _tail_moov_container(path, container):
        return None
    # 调用方自己带了 Range（说明它对这条直链另有安排），别插手
    if any(str(k).lower() == "range" for k in (headers or {})):
        return None
    tmp = _dual_range_temp_file(path, headers, size)
    if not tmp:
        return None
    try:
        data = _ffprobe(path, headers, size=size, local_path=tmp)
        if data and data.get("format"):
            try:
                _rescale_synthetic_format(data, int(size or 0), os.path.getsize(tmp))
            except OSError:
                pass
        return data
    finally:
        try:
            os.unlink(tmp)
        except OSError:  # noqa: BLE001 — 临时文件删不掉也不该让探测崩掉
            logger.debug("双 Range 临时文件删除失败 %s", tmp)


# 逐流字段白名单（与 probe_worker._STREAM_COLS 同口径）
_PROBE_STREAM_COLS = frozenset({
    "stream_index", "stream_type", "codec", "language", "display_title", "title",
    "channels", "bit_rate", "frame_rate", "video_range", "profile", "level",
    "pixel_format", "aspect_ratio", "bit_depth", "sample_rate",
    "channel_layout", "sample_format",
})


def _detect_video_range(stream: dict, tags: dict) -> str:
    """从 ffprobe 字段判断动态范围（客户端「动态范围」那一行）"""
    dovi = (tags.get("DOVI") or tags.get("dovi") or "").lower()
    if "dv" in dovi or "dolby vision" in dovi:
        return "DolbyVision"
    transfer = (stream.get("color_transfer") or "").lower()
    primaries = (stream.get("color_primaries") or "").lower()
    space = (stream.get("color_space") or "").lower()
    if "smpte2084" in transfer or "smpte2084" in primaries or "smpte2084" in space:
        return "HDR10"
    if "arib-std-b67" in transfer:
        return "HLG"
    return "SDR"


def _bit_depth(stream: dict, tags: dict) -> int:
    """位深：优先 raw_sample，其次 bits_per_sample"""
    for value in (tags.get("bits_per_raw_sample"), stream.get("bits_per_raw_sample"),
                  tags.get("bits_per_sample"), stream.get("bits_per_sample")):
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return 0


def probe_metadata(path: str, headers: Optional[dict] = None, size: int = 0,
                   container: str = "") -> dict:
    """返回 duration_ticks/bitrate/尺寸/编码/轨道信息

    ``size`` 是已知的文件大小（远程挂载从目录列表传入），ffprobe 读不到本地文件大小时用它兜底。
    ``container`` 是调用方从库里带来的容器后缀（``MediaItem.container``）；不给就从 URL 后缀推。
    """
    info: dict = {
        "duration_ticks": 0, "bitrate": 0, "width": 0, "height": 0,
        "video_codec": None, "audio_codec": None,
        "audio_languages": "", "subtitle_languages": "", "streams": [],
    }
    remote = path.startswith(("http://", "https://"))
    data = _ffprobe(path, headers, size=size)
    # 有限 Range 只是「少读点」的快速路径（decd396）：它只保证**头部带时长**的封装
    # （Matroska 实测有效）。moov 在文件尾的 MP4/MOV 在前 1 MiB 里根本没有时长，
    # 而我们注入的 Range 又让 ffprobe 把 206 当成整个文件，读到窗口末尾就报
    # "File ended prematurely" → format 为空 → 白白记 degraded（生产 4.3 万条）。
    #
    # 拿不到 format、且不是明确的 HTTP 错误时，按「速度优先」分两级回退：
    #   第二跳（mp4/mov 专有）：并行取「头 1 MiB + 尾 2 MiB」，从尾段摘出 moov 拼成
    #     「头部 + moov」的小文件，时长与各轨参数都来自 moov（正确）。流量固定在
    #     两个窗口，与文件多大无关（8 GB 的片子也只读 3 MiB）。
    #   第三跳（兜底）：去掉 Range 让 ffprobe 自己按需 seek。这条会把整个文件拉下来，
    #     所以放在最后，只在双 Range 也失手时才走。
    # 只对「窗口确实截断了文件」的条目做，避免给本就完整的文件白跑一遍。
    if (remote and (size <= 0 or size > PROBE_REMOTE_RANGE_BYTES)
            and (not data or not data.get("format"))
            and not (data or {}).get("_http_code")):
        tail_first = _dual_range_probe(path, headers, size, container)
        if tail_first and tail_first.get("format"):
            data = tail_first
        else:
            seekable = _ffprobe(path, headers, size=size, ranged=False)
            if seekable and seekable.get("format"):
                data = seekable
    used_mediainfo = False
    if not data or not data.get("format"):
        # ffprobe 是**超时**还是**读完但没数据**，决定还要不要跑 MediaInfo：
        # 超时说明挂载本身没响应（生产上 /mnt/mp 是 fuse.rclone，mediainfo 常驻
        # D 状态），再花一个 PROBE_FILE_TIMEOUT 读同一份字节只是白等——
        # 单文件最坏耗时直接减半。读完没数据才值得换工具再试。
        ffprobe_timed_out = _last_ffprobe_timed_out()
        fallback = None
        if not ffprobe_timed_out:
            # 本机文件再尝试 MediaInfo；远程 URL 不重复发起一次随机读取，
            # 直接由调用方记 degraded（客户端仍可播放，信息不完整）。
            fallback = _mediainfo(path, headers, size=size)
        if fallback:
            data = fallback
            used_mediainfo = True
        else:
            try:
                info["size"] = os.path.getsize(path)
            except OSError:
                info["size"] = size
            if remote:
                # 明确解析出的远端 HTTP 错误照样随结果透出（403 → 熔断器；
                # 404/401 → 重试→failed），别让早返回把它吞成一句「信息不完整」。
                if (data or {}).get("_error"):
                    info["_error"] = data["_error"]
                    info["_http_code"] = data.get("_http_code")
                    info["_error_detail"] = data.get("_error_detail", "")
                info["_degraded"] = True
                if not info.get("_error_detail"):
                    info["_error_detail"] = "远程媒体可访问，但探测未取得完整时长（ffprobe/MediaInfo）"
            return info
    if used_mediainfo:
        info["_probe_backend"] = "mediainfo"
    # 透出 ffprobe 的 HTTP 错误（供熔断器和日志使用）
    if data.get("_error"):
        info["_error"] = data["_error"]
        info["_http_code"] = data.get("_http_code")
        info["_error_detail"] = data.get("_error_detail", "")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0)
    info["duration_ticks"] = int(duration * 10_000_000)
    info["bitrate"] = int(fmt.get("bit_rate") or 0)
    try:
        info["size"] = os.path.getsize(path)
    except OSError:
        info["size"] = int(fmt.get("size") or 0) or size

    audio_langs, sub_langs, streams = [], [], []
    for idx, s in enumerate(data.get("streams", [])):
        stype = s.get("codec_type")
        tags = s.get("tags") or {}
        lang = tags.get("language", "")
        entry = {
            "stream_index": idx, "stream_type": stype, "codec": s.get("codec_name"),
            "language": lang, "channels": s.get("channels"),
            "bit_rate": int(s.get("bit_rate") or 0),
            "display_title": tags.get("title"),
            "title": tags.get("title"),
        }
        if stype == "video":
            entry["stream_type"] = "Video"
            info["width"] = s.get("width", 0)
            info["height"] = s.get("height", 0)
            info["video_codec"] = (s.get("codec_name") or "").upper()
            # 客户端「媒体信息」页逐行显示这些，缺了详情页只剩编码/码率两行
            fps = s.get("avg_frame_rate") or s.get("r_frame_rate") or ""
            if fps and fps not in ("0/0", "N/A"):
                entry["frame_rate"] = fps
            entry["video_range"] = _detect_video_range(s, tags)
            if s.get("profile"):
                entry["profile"] = str(s.get("profile"))
            if s.get("level") not in (None, -99, ""):
                entry["level"] = str(s.get("level"))
            if s.get("pix_fmt"):
                entry["pixel_format"] = s.get("pix_fmt")
            sar = s.get("sample_aspect_ratio") or ""
            if sar not in ("", "N/A", "0:1", "1:1"):
                entry["aspect_ratio"] = sar
            depth = _bit_depth(s, tags)
            if depth:
                entry["bit_depth"] = depth
        elif stype == "audio":
            entry["stream_type"] = "Audio"
            info["audio_codec"] = (s.get("codec_name") or "").upper()
            if s.get("sample_rate"):
                try:
                    entry["sample_rate"] = int(s.get("sample_rate"))
                except (TypeError, ValueError):
                    pass
            if s.get("sample_fmt"):
                entry["sample_format"] = s.get("sample_fmt")
            layout = s.get("channel_layout")
            if layout:
                entry["channel_layout"] = layout
            else:
                ch = int(s.get("channels") or 0)
                entry["channel_layout"] = {
                    1: "mono", 2: "stereo", 6: "5.1", 8: "7.1",
                }.get(ch, "")
            depth = _bit_depth(s, tags)
            if depth:
                entry["bit_depth"] = depth
            if lang:
                audio_langs.append(lang)
        elif stype == "subtitle":
            entry["stream_type"] = "Subtitle"
            if lang:
                sub_langs.append(lang)
        streams.append(entry)
    info["streams"] = streams
    info["audio_languages"] = ",".join(dict.fromkeys(audio_langs))
    info["subtitle_languages"] = ",".join(dict.fromkeys(sub_langs))
    return info


# ==================== 本机目录列表缓存 ====================
# 扫描一个目录下十几个文件时，旧实现每个文件都会 os.listdir 两次（找图 + 找字幕），
# 大目录（整季集数）下这就是几千次多余的目录读。缓存在每次扫描开始时清空。
_DIR_LIST_CACHE: dict = {}
_DIR_LIST_MAX = 20000
_DIR_LIST_LOCK = threading.Lock()


def clear_dir_cache() -> None:
    """开始一次扫描前调用：保证不拿上一次扫描的目录列表

    同时清掉**挂载层的共用缓存**（见 mounts.cached_listing）：那份缓存是扫描与播放
    共用的，扫描必须看到当下的目录——否则刚上传的文件会被播放刚踩过的缓存挡住，
    要等下一轮扫描才入库。
    """
    with _DIR_LIST_LOCK:
        _DIR_LIST_CACHE.clear()
    mount_lib.invalidate_list_cache()


@dataclass(frozen=True)
class LibrarySnapshot:
    """一次扫描固定使用的媒体库配置

    扫描可能跑很久，期间管理员可能改路径/策略。任务只认自己这份快照：

    - 运行中的任务不会被“改到一半”，不会出现“旧根目录扫一半、新根目录扫一半”；
    - 保存新配置后重新触发，用的就是新路径，**旧路径不会被继续扫描**。
    """

    library_id: int
    name: str
    collection_type: str
    paths: tuple[str, ...]
    scrape_policy: str
    # 绑定的存储挂载（storage_mounts.id）；扫描时与 paths 一起遍历
    mount_ids: tuple[int, ...] = ()
    # 本轮是否走增量秒跳：全局开关 SCAN_INCREMENTAL 与本库的开关都要开（v2.44.0）
    incremental_scan: bool = True
    # 这一轮强制全量（管理员手动点「全量扫描」）：无视所有指纹，处理一遍全部文件。
    # 快照字段而不是全局开关 —— 别的库、别的轮次都不能被这次手动操作带跑。
    force_full: bool = False

    @classmethod
    def of(cls, library) -> "LibrarySnapshot":
        paths = tuple(p.strip() for p in (library.paths or "").split(",") if p.strip())
        # 挂载互斥（scan_queue._MOUNT_OWNER）要看「实际用了哪些挂载」：
        # 除了 mount_ids 字段，paths 里的 mount://<id>/... 也算。
        # 否则 mount_ids 为空的库会绕过串行化，与同挂载的库并发扫描——
        # 2026-09-29 生产事故：动漫/国产剧/欧美剧同用 mount 3 并发扫描，
        # 触发 SQLAlchemy Session 并发崩溃（provisioning a new connection）。
        mount_ids = set(mount_lib.parse_mount_ids(library))
        for p in paths:
            parsed = mount_lib.parse_mount_path(p)
            if parsed is not None:
                mount_ids.add(parsed[0])
        return cls(
            library_id=library.id,
            name=library.name,
            collection_type=library.collection_type or "movies",
            paths=paths,
            scrape_policy=normalize_scrape_policy(getattr(library, "scrape_policy", None)),
            mount_ids=tuple(sorted(mount_ids)),
            # 老库没有这两列时 getattr 默认 True = 保持升级前的行为（本来就有增量）
            incremental_scan=getattr(library, "incremental_scan", True) is not False,
        )


@dataclass
class ScanFile:
    """扫描器看到的一个待处理媒体文件

    ``stored_path`` 是入库的 ``file_path``：本机可读的来源（媒体库路径 / local 挂载 /
    strm 挂载）存真实文件路径，远程挂载（115 / WebDAV / AList）存 ``mount://<id>/<rel>``。
    播放/探测输入懒解析——没装 ffprobe 或不需要重探时不会白白发 API 请求。
    """

    stored_path: str
    name: str
    local_dir: Optional[str]      # 本机目录（找本地图片 / 外挂字幕）；远程挂载为 None
    dir_rel: str = "/"            # 远程挂载里的目录（相对挂载根）
    size: int = 0
    container: str = ""           # 已知容器（strm 取直链里的真实容器）
    mount_id: Optional[int] = None
    rel: str = ""
    mtime_ns: Optional[int] = None  # 本机文件=st_mtime_ns；远程挂载无mtime，记None""
    provider: Any = None
    local_target: Any = None      # 本机可读来源的播放目标（strm 的直链在这里）
    _target: Any = None

    def play_target(self):
        if self._target is None:
            # 远程挂载走 resolve_final：.strm 条目先取文件内容再当直链播
            # （否则客户端会收到一个文本文件）
            self._target = (self.local_target if self.local_target is not None
                            else self.provider.resolve_final(self.rel))
        return self._target

    def probe_input(self) -> tuple[str, dict]:
        target = self.play_target()
        return target.value, target.headers


# 同一媒体库同时只允许一个扫描任务（进程内互斥；EM/EA 都是单进程部署）
_ACTIVE_SCANS: dict[int, datetime] = {}  # 库 id → 开始时间（本进程内）
_ACTIVE_SCANS_LOCK = threading.Lock()


class ScanInProgress(RuntimeError):
    """同一媒体库已有扫描任务在运行"""


def is_scan_active(library_id: int) -> bool:  # noqa: D401
    """是否有扫描任务正在跑（比数据库里的 is_scanning 标志可靠：进程崩溃不会卡死）"""
    with _ACTIVE_SCANS_LOCK:
        return library_id in _ACTIVE_SCANS


def _acquire_scan(library_id: int) -> None:
    with _ACTIVE_SCANS_LOCK:
        if library_id in _ACTIVE_SCANS:
            raise ScanInProgress(f"媒体库 {library_id} 正在扫描中")
        _ACTIVE_SCANS[library_id] = datetime.now()


def _release_scan(library_id: int) -> None:
    with _ACTIVE_SCANS_LOCK:
        _ACTIVE_SCANS.pop(library_id, None)


def count_virtual_items(db: Session, library) -> int:
    """虚拟媒体库的条目数

    虚拟媒体库没有自己的文件与库归属，它是跨库的“发行平台视图”（Netflix / Disney+ …），
    因此计数按 `MediaItem.platforms` 里的平台标签聚合。
    """
    platform = (getattr(library, "platform", "") or "").strip()
    if not platform:
        return 0
    return (
        db.query(emby_models.MediaItem)
        .filter(
            emby_models.MediaItem.is_hidden == False,  # noqa: E712
            emby_models.MediaItem.item_type.in_(["movie", "series"]),
            emby_models.MediaItem.platforms.ilike(f"%{platform}%"),
        )
        .count()
    )


    # 本批条目的外挂字幕：item_id → {external_path}（秒跳时比对用，一批只查一次 DB，
    # 不能每个文件查一次，否则 202 个文件就是 202 条 SQL，直接撑爆 SQL 预算）


# ==================== 增量扫描：目录指纹 ====================
# 重扫一个库时，绝大多数目录里的文件一个都没动过，但旧实现照样把每个文件走一遍完整流程
# （建/查条目、找本地图片、找外挂字幕、重建外挂字幕轨、每文件一次提交）。实测 2000 个
# 文件的重扫 ≈ 冷扫的 95%，约 4 条 SQL + 1 次 commit / 文件。
#
# 现在按**目录**记指纹：
#   指纹没变 → 该目录的文件不再逐条处理，只做两件必须做的事：
#              ① guid 记进 seen_guids（否则清理阶段会把这些文件当成已删除）；
#              ② 确认库里存在这一行且不需要重探 / 重刮 / 补详情。
#              任一条不满足（新文件、大小变了、库里没这一行、要补图）→ 照常完整处理。
#   指纹变了 → 整个目录照常完整处理，处理完把新指纹写回。
#
# 安全性：跳过**永远**以「库里那一行存在且不过期」为前提，指纹只决定「图片 / 字幕 /
# 轨道这些逐文件的重活要不要重做」。因此指纹写早了、随后进程崩了也不会漏文件——
# 下次扫描会因为「查不到那一行」而重新处理。指纹含目录项数，增删改名都会动它；
# 替换同名文件不一定动 mtime，所以跳过的前提里还要求「文件大小与库里的记录一致」。
#
# 远程挂载同样参与：目录列举本来就要做（图片/字幕判定用同一份列表），指纹只是复用
# 那份列表，不额外增加任何网络往返。SCAN_INCREMENTAL=0 可整体关掉（回到每次全量处理）。
#
# v2.44.0 多了**每库**开关（``Library.incremental_scan``，默认开）：扫描循环里一律问
# ``_incremental_on(ctx)``，而不是直接读这个模块级常量——否则全局开着时无法只给某一个
# 关掉。手动「全量扫描」通过快照上的 ``force_full`` 只让**那一轮**变成全量。
SCAN_INCREMENTAL = (os.getenv("SCAN_INCREMENTAL", "1") or "1").strip().lower() \
    not in {"0", "false", "no", "off"}


# 分层扫描 L1/L2 总开关（v2.40.0）：1=开（默认）。
# 开：Phase 1 只做文件发现+指纹+极简入库（秒级可见），side/NFO/TMDB 全部
#     交给后台 enrich_worker 补全；关：回到旧行为（Phase 1 内联做完所有事）。
# 探测：background 模式走 probe_worker（不变）；inline 模式在分层下也推迟到
#     enrich_worker 排队（避免远程直链拖慢秒级入库），关分层则恢复当场探测。
SCAN_LAYERED = (os.getenv("SCAN_LAYERED", "1") or "1").strip().lower() \
    not in {"0", "false", "no", "off"}

# 强制远程模式（2026-10-05）：FUSE 挂载（如 /mnt/mp）有本地路径但 IO 并不快，
# 按"本地"处理会走 side/NFO 的逐文件慢操作。设为 1 后，所有文件都按远程处理，
# 跳过逐文件的 FUSE 慢操作，只做极简入库。简洁/高效/稳定：默认关闭，按需开启。
SCAN_FORCE_REMOTE = (os.getenv("SCAN_FORCE_REMOTE", "0") or "0").strip().lower() \
    not in {"0", "false", "no", "off"}


# 季目录名（远端挂载的剧集分组用）：Season 01 / S01 / 第1季 / 第一季
_SEASON_DIR_RE = re.compile(
    r"^(?:season\s*\.?\s*\d{1,2}|s\d{1,2}|第\s*(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*季)$",
    re.IGNORECASE,
)


# 扫描用的进程级线程池：同一进程里可能连续扫多个媒体库（多来源、多库批量扫描），
# 反复建池/销池反而更贵。池子只在第一次真正提交任务时才会创建线程，空闲时几乎不吃资源，
# 进程退出时由解释器统一回收。
_SCAN_POOL: Optional[ThreadPoolExecutor] = None
_SCAN_POOL_LOCK = threading.Lock()


        # 线程池是进程级的（_scan_pool）：扫描结束不销毁，也不影响后面的扫描


def _purge_items(db: Session, item_ids: list) -> None:
    """批量删条目与从属数据（用批量语句：不逐条加载 ORM 对象，也不触发级联查询）

    `MediaStream` 在 ORM 上有级联会被一起带走，但 `UserMediaData`
    （播放进度 / 收藏）**没有级联**——只 `db.delete(item)` 会留下永远指向不存在条目的
    孤儿行；这类行只增不减，追新久了就是几十万条垃圾，也是「跑久了变慢」的来源之一。
    """
    ids = list(item_ids)
    db.query(emby_models.UserMediaData).filter(
        emby_models.UserMediaData.item_id.in_(ids)
    ).delete(synchronize_session=False)
    db.query(emby_models.MediaStream).filter(
        emby_models.MediaStream.item_id.in_(ids)
    ).delete(synchronize_session=False)
    db.query(emby_models.ItemFacet).filter(
        emby_models.ItemFacet.item_id.in_(ids)
    ).delete(synchronize_session=False)
    db.query(emby_models.MediaItem).filter(
        emby_models.MediaItem.id.in_(ids)
    ).delete(synchronize_session=False)


# ==================== 扫描结果与流水（落库 + 对外可查）====================
# 扫描统计以前只在返回值与日志里：管理端刷新一下就没了，「上一轮到底扫到什么」只能去
# 服务器日志翻。这里做两层：
#
# - **最近一次**写回 Library（scan_status / scan_stats / scan_error），由
#   /api/admin/emby/libraries 一并带回（见 scan_result_payload）——刷新页面就能看；
# - **最近若干轮**记进 ScanRun 流水（状态 / 触发方 / 耗时 / 同一份统计 / 失败原因），
#   由 /api/admin/emby/libraries/{id}/scans 提供（见 scan_runs_payload）——
#   「这个库每轮都失败」和「只是最近一轮失败」是两件事，只看最后一次分不出来。
SCAN_STATUS_RUNNING = "running"
SCAN_STATUS_SUCCESS = "success"
SCAN_STATUS_PARTIAL = "partial"   # 有来源读不到：本轮已跳过清理
SCAN_STATUS_FAILED = "failed"

# 谁触发的扫描（写进流水：回答「半夜三点是谁在扫」）：
# manual = 面板按钮 · client = Emby 客户端刷新 · node = 归属节点 · repair = 面板修复队列
SCAN_TRIGGERS = ("manual", "client", "node", "repair")

# 每个媒体库保留多少轮扫描流水（0 = 不记流水）。一轮一行，超过就按库回收最旧的行——
# 量很小，但没人清就会随「建库→删库」和长期运行一直涨。
SCAN_RUN_KEEP = int(os.getenv("EMBY_SCAN_HISTORY", "20"))

# 需要长期保留的统计键：其余键本来只是内部状态，不进库
SCAN_STATS_KEYS = ("added", "updated", "removed", "probed", "probe_queued", "scraped",
                   "repaired", "unchanged", "resurrected", "removal_skipped",
                   "failed_roots", "duplicate_files", "duration_ms", "sources")


def normalize_scan_trigger(trigger: Optional[str]) -> str:
    """把触发方收敛到枚举内（未知值当作 manual，不因为调用方写错就丢记录）"""
    value = (trigger or "").strip().lower()
    return value if value in SCAN_TRIGGERS else "manual"


# 需要跟着一轮扫描一起落库的来源计数器
SCAN_SOURCE_COUNTERS = ("files", "added", "updated", "probed", "scraped", "repaired", "unchanged")
SCAN_SOURCES_MAX = 50              # 一个库的来源（路径 + 挂载）远小于这个量级；超了只留前 N 条
SCAN_SOURCE_LABEL_MAX = 200
SCAN_SOURCE_TEXT_MAX = 300


def _encode_scan_sources(entries) -> list:
    """来源明细 → 可落库结构（条数、标签与原因都封顶：库里的 JSON 不该无限长）

    单条坏数据只丢它自己，不影响整轮统计（统计里带着扫描结论，不能因为一条来源烂掉全没）。
    """
    out = []
    for entry in list(entries or [])[:SCAN_SOURCES_MAX]:
        if not isinstance(entry, dict):
            continue
        try:
            label = str(entry.get("label") or "").strip()[:SCAN_SOURCE_LABEL_MAX]
            if not label:
                continue  # 连来源都说不清的明细没有意义，别让它在面板上占一行
            item = {"label": label}
            for key in ("kind", "error"):
                if entry.get(key):
                    item[key] = str(entry[key])[:SCAN_SOURCE_TEXT_MAX]
            for key in SCAN_SOURCE_COUNTERS:
                item[key] = max(0, int(entry.get(key) or 0))
        except Exception:  # noqa: BLE001 — 一条坏来源不该带走整轮统计
            continue
        out.append(item)
    return out


def encode_scan_stats(stats: Optional[dict]) -> Optional[str]:
    """统计字典 → JSON 文本（序列化失败一律当作没有，不影响扫描本身）"""
    if not stats:
        return None
    try:
        out = {k: stats.get(k, 0) for k in SCAN_STATS_KEYS if k in stats}
        if "failed_roots" in out:
            out["failed_roots"] = [str(r)[:SCAN_SOURCE_TEXT_MAX]
                                   for r in (out.get("failed_roots") or [])][:20]
        if "sources" in out:
            out["sources"] = _encode_scan_sources(out.get("sources"))
        return json.dumps(out, ensure_ascii=False, sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("序列化扫描统计失败: %s", exc)
        return None


def decode_scan_stats(raw: Optional[str]) -> dict:
    """JSON 文本 → 统计字典（坏数据回空字典，不向外抛）"""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return value if isinstance(value, dict) else {}


def _scan_metrics(stats: dict) -> dict:
    """统计字典 → 对外字段（「最近一次」与「扫描流水」共用同一份口径）"""
    return {
        "added": int(stats.get("added") or 0),
        "updated": int(stats.get("updated") or 0),
        "removed": int(stats.get("removed") or 0),
        "probed": int(stats.get("probed") or 0),
        "scraped": int(stats.get("scraped") or 0),
        "repaired": int(stats.get("repaired") or 0),
        "unchanged": int(stats.get("unchanged") or 0),
        # 软删除（v2.48.0）：文件重新出现、被放回可见的原条目数
        "resurrected": int(stats.get("resurrected") or 0),
        "removal_skipped": bool(stats.get("removal_skipped")),
        "failed_roots": list(stats.get("failed_roots") or []),
        # 按来源拆分的明细：只记失败来源的话，「挂载在、但一条文件都没有」这种
        # （挂载点被清空 / 账号范围变了 / 路径写错了但目录存在）根本看不出来
        "sources": [s for s in (stats.get("sources") or []) if isinstance(s, dict)],
    }


def scan_result_payload(library) -> Optional[dict]:
    """媒体库最近一次扫描结果的对外结构（管理端列表与客户端接口共用一份口径）

    从没扫过（既没有状态也没有时间）时返回 None，前端据此显示「尚未扫描」——
    「没扫过」和「扫了但都是 0」是两件事，不能混成一个空结构。
    """
    status = getattr(library, "scan_status", None)
    if not status and not getattr(library, "last_scan_at", None):
        return None
    stats = decode_scan_stats(getattr(library, "scan_stats", None))
    return {
        "status": status or SCAN_STATUS_SUCCESS,
        "finished_at": library.last_scan_at.isoformat() if library.last_scan_at else None,
        "duration_ms": stats.get("duration_ms"),
        **_scan_metrics(stats),
        "error": getattr(library, "scan_error", None),
    }


def _scan_run_payload(run) -> dict:
    """一条扫描流水的对外结构（与 scan_result_payload 同一套字段口径）"""
    stats = decode_scan_stats(getattr(run, "stats", None))
    duration = run.duration_ms if run.duration_ms is not None else stats.get("duration_ms")
    return {
        "id": run.id,
        "status": run.status,
        "trigger": run.trigger,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": duration,
        **_scan_metrics(stats),
        "error": run.error,
    }


def scan_runs_payload(db: Session, library_id: int, limit: int = 20) -> list:
    """某个媒体库最近的扫描流水（新的在前；上限钳到 200，避免有人拉全表）"""
    hits = max(0, min(int(limit or 0), 200))
    if not hits:
        return []
    rows = (
        db.query(emby_models.ScanRun)
        .filter(emby_models.ScanRun.library_id == library_id)
        .order_by(emby_models.ScanRun.id.desc())
        .limit(hits)
        .all()
    )
    return [_scan_run_payload(run) for run in rows]


def recent_scan_runs(db: Session, library_ids, limit: int = 40) -> list:
    """跨库取最近若干轮扫描流水（服务器维度视图用；新的在前）

    「整服视角的扫描历史」问的是「这台节点负责的那批库，最近扫得怎么样」——
    按库各查一遍再拼接既慢又排不出时间顺序，所以这里一次查完再排。
    每条带上 ``library_id``，面板才能把流水写回库名。
    """
    ids = [int(i) for i in (library_ids or [])]
    if not ids:
        return []
    hits = max(0, min(int(limit or 0), 200))
    if not hits:
        return []
    rows = (
        db.query(emby_models.ScanRun)
        .filter(emby_models.ScanRun.library_id.in_(ids))
        .order_by(emby_models.ScanRun.id.desc())
        .limit(hits)
        .all()
    )
    return [{**_scan_run_payload(run), "library_id": run.library_id} for run in rows]


def prune_library_scan_runs(db: Session, library_id: int,
                            keep: Optional[int] = None) -> int:
    """只留某个媒体库最近 ``keep`` 轮流水（不提交：由调用方与本次写入一起提交）"""
    limit = SCAN_RUN_KEEP if keep is None else max(0, int(keep))
    if limit <= 0:
        return 0
    stale_ids = [
        row[0] for row in db.query(emby_models.ScanRun.id)
        .filter(emby_models.ScanRun.library_id == library_id)
        .order_by(emby_models.ScanRun.id.desc())
        .offset(limit)
        .all()
    ]
    if not stale_ids:
        return 0
    deleted = db.query(emby_models.ScanRun).filter(
        emby_models.ScanRun.id.in_(stale_ids)
    ).delete(synchronize_session=False)
    return int(deleted or 0)


def _finish_scan_run(db: Session, run_id: Optional[int], status: str,
                     stats: Optional[dict], error: Optional[str]) -> None:
    """收尾这一轮的扫描流水，并就地回收过旧的行（写失败只记日志，不影响扫描本身）"""
    if not run_id:
        return
    try:
        run = db.query(emby_models.ScanRun).filter(emby_models.ScanRun.id == run_id).first()
        if run is None:
            return
        run.status = status
        run.finished_at = datetime.now()
        duration = (stats or {}).get("duration_ms")
        if duration is None and run.started_at is not None:
            # 调用方没给耗时（直接调 begin/finish 的路径）也能量出来：
            # 收尾过的流水必须有耗时，否则「扫了多久」这条信息就丢了
            duration = int((run.finished_at - run.started_at).total_seconds() * 1000)
        run.duration_ms = duration
        run.stats = encode_scan_stats(stats)
        run.error = (error or "")[:500] or None
        prune_library_scan_runs(db, run.library_id)
        commit_with_retry(db, label="扫描流水收尾")
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入扫描流水失败: %s", exc, exc_info=True)
        db.rollback()


def _write_scan_state(db: Session, library: emby_models.Library, status: str,
                      stats: Optional[dict], error: Optional[str]) -> None:
    """状态 / 统计 / 原因写回媒体库并提交（落盘失败只记日志，不覆盖真实异常）"""
    library.is_scanning = False
    library.last_scan_at = datetime.now()
    library.scan_started_at = None   # 本轮已收尾，不再参与复位判定
    library.scan_status = status
    library.scan_stats = encode_scan_stats(stats)
    library.scan_error = (error or "")[:500] or None
    try:
        commit_with_retry(db, label="扫描结果写回")
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入扫描结果失败: %s", exc, exc_info=True)
        db.rollback()


def begin_scan(db: Session, library: emby_models.Library,
               trigger: str = "manual") -> Optional[int]:
    """标记扫描开始，并开一条扫描流水，返回它 id

    独立提交一次：扫描过程中进程被杀，库里也能看出「上一轮在跑」以及是谁触发的。
    状态写不进去不影响扫描本身（只是这次没有流水）。
    """
    library.is_scanning = True
    library.scan_status = SCAN_STATUS_RUNNING
    library.scan_error = None
    # 单独记本轮起始时刻：复位判定只能看它（见 models.Library.scan_started_at）
    library.scan_started_at = datetime.now()
    run = None
    if SCAN_RUN_KEEP > 0:
        run = emby_models.ScanRun(library_id=library.id, status=SCAN_STATUS_RUNNING,
                                  trigger=normalize_scan_trigger(trigger),
                                  started_at=datetime.now())
        db.add(run)
    try:
        commit_with_retry(db, label="扫描开始状态")
    except Exception as exc:  # noqa: BLE001 — 状态写不进去也要照常扫描
        logger.warning("写入扫描开始状态失败: %s", exc)
        db.rollback()
        return None
    return int(run.id) if run is not None and run.id is not None else None


def _cover_autogen_after_scan(db: Session, library, stats: dict) -> None:
    """新片入库后自动重生成封面（``Library.cover_auto_regen`` 开了才做）

    三个提前返回都是刻意的：

    - 没开开关 → 什么都不做（这是绝大多数库）；
    - 没选样式 → 没有可复用的配置，重生成必然失败，不如什么都不做；
    - **本轮没新增** → 封面就是最新的，重画一遍只会白白花渲染时间 + 让缓存失效。
      “自动更新”该跟“新片”绑定，而不是跟“又扫了一次”绑定。

    延迟导入：封面模块住在 ``backend.api`` 且反过来依赖本包，直接 import 会成环
    （与 ``probe_worker`` 里的延迟导入同理）。**只入队**、不渲染：渲染交给后台
    线程按库合并执行（见 ``library_cover.enqueue_cover_regeneration``），封面慢、
    失败或根本没有海报，都不会把一轮扫描的结果拖下水。
    """
    if not getattr(library, "cover_auto_regen", False):
        return
    if not getattr(library, "cover_template", ""):
        return
    if not int((stats or {}).get("added") or 0):
        return
    library_id = getattr(library, "id", None)
    try:
        # 只入队，不渲染（v2.48.0）：渲染慢会把整轮扫描拖住，而且转场一批新片时
        # 同一轮里会反复触发。队列按库合并，扫描与封面完全解耦。
        from backend.api.library_cover import enqueue_cover_regeneration

        created = enqueue_cover_regeneration(library_id)
        logger.info("封面已排队（%s）library_id=%s 新增=%s",
                    "新建任务" if created else "已有任务在跑，合并", library_id,
                    (stats or {}).get("added"))
    except Exception:  # noqa: BLE001 — 封面失败绝不能影响扫描结果落库
        logger.warning("封面任务入队失败 library_id=%s", library_id, exc_info=True)


def finish_scan(db: Session, library: emby_models.Library, stats: Optional[dict],
                run_id: Optional[int] = None) -> str:
    """写入一轮扫描的结果，返回归类后的状态

    只有「来源全部可用且正常跑完」才算 success；任何来源读不到就记 partial——
    那种情况下清理阶段被跳过，结果本身并不完整，不能对外报「一切正常」。
    """
    stats = stats or {}
    status = SCAN_STATUS_PARTIAL if stats.get("removal_skipped") else SCAN_STATUS_SUCCESS
    error = None
    if status == SCAN_STATUS_PARTIAL:
        error = "；".join(str(r) for r in (stats.get("failed_roots") or []))[:500] \
            or "媒体库没有可用来源，本轮已跳过清理"
    _write_scan_state(db, library, status, stats, error)
    # 与媒体库状态分开两次提交：流水写不进去不该影响「上一轮扫得怎么样」这条主状态
    _finish_scan_run(db, run_id, status, stats, error)
    # 结果已经落库了，封面重生成即使失败也不影响上面那两条状态
    _cover_autogen_after_scan(db, library, stats)
    return status


def fail_scan(db: Session, library: emby_models.Library, exc: Exception,
              run_id: Optional[int] = None,
              duration_ms: Optional[int] = None) -> None:
    """扫描抛异常时把原因落库（管理端要能看到「为什么没扫成」）"""
    # 诊断日志：定位 Session 跨线程等问题时直接抓现行（只记日志，不改落库逻辑）。
    # 调用方保证在 except 块内调用，因此 traceback.format_exc() 一定有内容。
    logger.error(
        "扫描失败诊断 library_id=%s trigger=fail_scan thread=%s session_id=%s\n%s",
        getattr(library, "id", "?"),
        threading.current_thread().name,
        id(db),
        traceback.format_exc(),
    )
    error = f"{type(exc).__name__}: {exc}"
    _write_scan_state(db, library, SCAN_STATUS_FAILED, None, error)
    # 失败也要记耗时：扫了四十分钟才炸和刚开就炸不是一回事
    stats = {"duration_ms": duration_ms} if duration_ms is not None else None
    _finish_scan_run(db, run_id, SCAN_STATUS_FAILED, stats, error)

