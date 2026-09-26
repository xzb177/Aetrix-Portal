"""自建 Emby 服务器：媒体库扫描 + 元数据刮削"""
from __future__ import annotations

import hashlib
import json  # 扫描结果落库（scan_stats）需要
import logging
import os
import posixpath
import re
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timedelta
from typing import Any, Iterator, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.db_retry import commit_with_retry, retry_write
from backend.emby_server import models as emby_models
from backend.emby_server import mounts as mount_lib
from backend.emby_server import nfo as nfo_lib
# 实时进度与远程 IO 计数（v2.27.0）：只依赖标准库，不会与 scanner / mounts 形成循环
from backend.emby_server import scan_progress as progress

# TMDB 刮削客户端已拆到 tmdb.py：扫描器只管遍历与写库，网络客户端（密钥轮询 + 短 TTL 缓存）
# 单独成模块。这里重新导出一次，`scanner.tmdb_client` / `scanner.TmdbClient` 等既有引用不变。
from backend.emby_server.tmdb import (  # noqa: F401
    TMDB_API,
    TMDB_IMAGE,
    TMDB_LANG,
    TmdbClient,
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

# 上一次清理阶段的决策（健康检查与测试用：有没有走快速路径、走过多少条、耗时）
_CLEANUP_LAST: dict = {"fast_path": False, "walked": 0, "removed": 0, "elapsed_ms": 0.0}

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


def _chunks(seq, size: int):
    """把序列切成固定大小的块（避免一次性构造巨大的 IN 查询 / 巨大的列表）"""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

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


def detect_platforms(path: str) -> list[str]:
    """从文件名/目录识别发行平台（返回平台 id 列表，稳定有序）

    片名与最近几层父目录一起作为依据（整季常把发行平台写在目录名上）。
    """
    text = os.path.basename(path or "")
    parents = (path or "").replace("\\", "/").split("/")[-4:-1]
    haystack = " ".join([text, *parents])
    if not haystack.strip():
        return []
    release_like = bool(_RELEASE_HINT_RE.search(haystack))
    found = [
        platform
        for platform, pat in _PLATFORM_RE.items()
        if pat.search(haystack)
        and (release_like or all(len(t) > SHORT_PLATFORM_TAG_LEN for t in PLATFORM_TAGS[platform]))
    ]
    return sorted(found)


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


def should_scrape(item, policy: str, now: Optional[datetime] = None) -> bool:
    """按策略判断某个条目是否需要（重新）刮削

    - `missing_only`：只补缺（没 TMDB 命中就刮，已有就不再建请求——省配额）
    - `3m` / `6m` / `1y`：到期重刮；**缺元数据的总是补**，不受窗口限制
    - `all`：每次全量重刮（仅在管理员显式选择时生效）
    """
    policy = normalize_scrape_policy(policy)
    if not item.tmdb_id:  # 缺元数据：任何策略下都要刮
        return True
    if policy == "missing_only":
        return False
    if policy == "all":
        return True
    window = SCAN_POLICIES.get(policy)
    if not window:
        return False
    last = item.last_scraped_at or item.date_added
    if not last:
        return True
    return (now or datetime.now()) - last >= timedelta(days=window)


def needs_probe(item, path: str, size: Optional[int] = None) -> bool:
    """是否需要重新 ffprobe

    文件信息已经获取过就不再每次扫描重复探测——ffprobe 是扫描里最贵的一步，
    整库重扫时它会吃掉绝大部分时间。仅当文件大小变了（换源/重压）才重探。

    远程挂载（115 / WebDAV / AList）没有本机文件，大小由调用方从目录列表传入。
    """
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


def _file_fingerprint(scan_file: "ScanFile") -> str:
    """文件指纹：秒跳未变更文件的唯一依据。

    本机文件用 path|size|mtime_ns（一次 os.stat，多一个系统调用）；
    远程挂载拿不到 mtime（多一次 API 太贵），用 path|size。
    大小变了一定命中不了；同名替换但大小时间都一样是玄学，接受。
    """
    if scan_file.mtime_ns is not None:
        raw = "|".join((scan_file.stored_path, str(scan_file.size),
                        str(scan_file.mtime_ns)))
    else:
        raw = "|".join((scan_file.stored_path, str(scan_file.size)))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


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


def _ffprobe(path: str, headers: Optional[dict] = None) -> Optional[dict]:
    """ffprobe 提取媒体信息（无 ffprobe 时优雅降级）

    ``path`` 可以是本机文件，也可以是远程直链（挂载）：ffprobe 本身支持 http(s) 输入，
    鉴权头通过 ``-headers`` 传入（Cookie / Authorization 只在本机使用）。
    """
    if not shutil_which("ffprobe"):
        return None
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams"]
    if headers:
        joined = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        cmd += ["-headers", joined]
    cmd.append(path)
    # 扫描探测让路给播放（见文件头「扫描限速」）：只降这一条子命令，不碰本进程
    cmd = _io_nice_command(cmd)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        import json

        return json.loads(out.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        logger.warning("ffprobe 失败 %s: %s", path, e)
        return None


def shutil_which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


def probe_metadata(path: str, headers: Optional[dict] = None, size: int = 0) -> dict:
    """返回 duration_ticks/bitrate/尺寸/编码/轨道信息

    ``size`` 是已知的文件大小（远程挂载从目录列表传入），ffprobe 读不到本地文件大小时用它兜底。
    """
    info: dict = {
        "duration_ticks": 0, "bitrate": 0, "width": 0, "height": 0,
        "video_codec": None, "audio_codec": None,
        "audio_languages": "", "subtitle_languages": "", "streams": [],
    }
    data = _ffprobe(path, headers)
    if not data:
        try:
            info["size"] = os.path.getsize(path)
        except OSError:
            info["size"] = size
        return info

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
        lang = (s.get("tags") or {}).get("language", "")
        entry = {
            "stream_index": idx, "stream_type": stype, "codec": s.get("codec_name"),
            "language": lang, "channels": s.get("channels"),
            "bit_rate": int(s.get("bit_rate") or 0),
            "display_title": (s.get("tags") or {}).get("title"),
            "title": (s.get("tags") or {}).get("title"),
        }
        if stype == "video":
            entry["stream_type"] = "Video"
            info["width"] = s.get("width", 0)
            info["height"] = s.get("height", 0)
            info["video_codec"] = (s.get("codec_name") or "").upper()
        elif stype == "audio":
            entry["stream_type"] = "Audio"
            info["audio_codec"] = (s.get("codec_name") or "").upper()
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


def _list_dir_cached(dir_path: str) -> list:
    """本机目录列表（同一次扫描里同一目录只读一次；缓存有上限，不会无限长大）

    「查缓存 → 列目录 → 写缓存」必须整体在锁里完成：同一个目录下的多个文件会被分发到
    不同工作线程，分成两段的实现在线程同时要同一目录时会各自真列一次（CI 上表现为
    3 个目录列了 6 次）。列目录本身很快，串行化它换来的是「目录读次数只跟目录数有关」。
    """
    with _DIR_LIST_LOCK:
        hit = _DIR_LIST_CACHE.get(dir_path)
        if hit is not None:
            return hit
        try:
            entries = os.listdir(dir_path)
        except OSError:
            entries = []
        if len(_DIR_LIST_CACHE) >= _DIR_LIST_MAX:
            _DIR_LIST_CACHE.clear()
        _DIR_LIST_CACHE[dir_path] = entries
        return entries


def find_local_images_in(entries, dir_path: str, base_name: str) -> tuple[Optional[str], Optional[str]]:
    """在已经拿到的目录列表里查 poster/fanart

    扫描时同一目录下的文件很多，目录只需列一次（老实现每个文件列两次），因此把
    “取列表”和“在列表里找”拆开：找的部分是纯计算，可以复用同一份列表。
    """
    poster = fanart = None
    for f in entries:
        low = f.lower()
        stem, ext = os.path.splitext(low)
        if ext not in IMAGE_EXTS:
            continue
        if stem in {"poster", "cover", "folder"} or stem == base_name.lower():
            poster = poster or os.path.join(dir_path, f)
        if stem in {"fanart", "backdrop", "background"}:
            fanart = fanart or os.path.join(dir_path, f)
    return poster, fanart


def find_local_images(dir_path: str, base_name: str) -> tuple[Optional[str], Optional[str]]:
    """查找同目录的 poster/fanart 本地图片（目录列表走本次扫描的缓存）"""
    return find_local_images_in(_list_dir_cached(dir_path), dir_path, base_name)


def find_external_subtitles(file_path: str) -> list[tuple[str, str]]:
    """本机文件的外挂字幕：返回 [(lang, 绝对路径)]（目录列表走本次扫描的缓存）

    判定本身在 subtitles.py；这里保留包装是因为它要用**本次扫描的目录缓存**，
    而缓存属于扫描器——反过来让 subtitles 依赖 scanner 会形成循环导入。
    """
    d = os.path.dirname(file_path)
    return find_external_subtitles_in(_list_dir_cached(d), file_path)


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

    @classmethod
    def of(cls, library) -> "LibrarySnapshot":
        return cls(
            library_id=library.id,
            name=library.name,
            collection_type=library.collection_type or "movies",
            paths=tuple(p.strip() for p in (library.paths or "").split(",") if p.strip()),
            scrape_policy=normalize_scrape_policy(getattr(library, "scrape_policy", None)),
            mount_ids=tuple(mount_lib.parse_mount_ids(library)),
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


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _local_dir_files(root: str, failed_roots: list) -> Iterator[ScanFile]:
    """本机目录：与历史行为一致，直接 os.walk 真实文件"""
    for dirpath, _dirnames, filenames in os.walk(
        root,
        # 带上来源根目录：失败原因要能归到具体某条来源上（见 _source_entry 的前缀匹配）
        onerror=lambda e: failed_roots.append(f"{root}: {getattr(e, 'strerror', '') or e}"),
    ):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in VIDEO_EXTS:
                continue
            full_path = os.path.join(dirpath, fname)
            try:
                target = mount_lib.local_play_target(full_path)
            except mount_lib.MountError as exc:
                logger.warning("跳过无法解析的媒体：%s（%s）", full_path, exc)
                continue
            container = ext.lstrip(".")
            if container == "strm":
                container = mount_lib.strm_container(target.value)
            try:
                _mtime_ns = os.stat(full_path).st_mtime_ns
            except OSError:
                _mtime_ns = None
            yield ScanFile(
                stored_path=full_path, name=fname, local_dir=dirpath,
                size=_safe_size(full_path), container=container, local_target=target,
                mtime_ns=_mtime_ns,
            )


def _remote_strm_container(provider, rel: str) -> str:
    """远程挂载里的 .strm：读文件内容取直链，从直链推断真实容器

    推断不出来（或直链临时失效）不阻断入库，先按 strm 记下——播放时会重新解析。
    """
    try:
        target = provider.resolve_final(rel)
    except mount_lib.MountError as exc:
        logger.warning("STRM 直链解析失败：%s（%s）", rel, exc)
        return "strm"
    return mount_lib.strm_container(target.value)


def _mount_files(src, provider, failed_roots: list) -> Iterator[ScanFile]:
    """一个挂载里的媒体文件

    本机可读的挂载（local / strm）入库真实路径；远程挂载（115 / WebDAV / AList）
    入库 ``mount://<id>/<rel>``，播放时再解析成直链。
    """
    root = provider.local_root
    mount_id = src.mount.id
    # src.subpath：库配置为 mount://<id>/<子目录> 时只扫描该子目录（默认为 "/" 即整个挂载）
    subpath = getattr(src, "subpath", "/") or "/"
    for mount_file in provider.walk_media(root=subpath):
        rel = mount_file.rel
        dir_rel = os.path.dirname(rel) or "/"
        if root is not None:
            full_path = os.path.join(root, rel.lstrip("/"))
            try:
                target = mount_lib.local_play_target(full_path)
            except mount_lib.MountError as exc:
                logger.warning("跳过无法解析的媒体：%s（%s）", full_path, exc)
                continue
            container = os.path.splitext(mount_file.name)[1].lstrip(".").lower()
            if container == "strm":
                container = mount_lib.strm_container(target.value)
            yield ScanFile(
                stored_path=full_path, name=mount_file.name,
                local_dir=os.path.dirname(full_path), dir_rel=dir_rel,
                size=mount_file.size, container=container,
                mount_id=mount_id, rel=rel, provider=provider, local_target=target,
            )
            continue
        container = os.path.splitext(mount_file.name)[1].lstrip(".").lower()
        if container == "strm":
            container = _remote_strm_container(provider, rel)
        yield ScanFile(
            stored_path=mount_lib.mount_path(mount_id, rel), name=mount_file.name,
            local_dir=None, dir_rel=dir_rel, size=mount_file.size,
            container=container, mount_id=mount_id, rel=rel, provider=provider,
        )


def iter_scan_sources(snap: "LibrarySnapshot", library, db: Session,
                      failed_roots: list,
                      report: Optional[list] = None) -> Iterator[tuple]:
    """遍历一个媒体库的全部扫描来源（本机路径 + 挂载），产出 ``(来源标签, 文件迭代器)``

    来源不可用（目录不存在 / 挂载停用 / 账号失效 / 网络不通）时**不会**抛出去中断整个扫描，
    而是记进 ``failed_roots``：扫描器据此跳过清理阶段，避免把「读不到」当成「文件已删除」。
    传了 ``report`` 时，不可用的来源也记一条 ``kind="unavailable"`` 的明细进去——
    「这轮一共几个来源、哪个一条都没扫到」在后台要能一眼看见（见 scan_result_payload）。
    明细在生成器收尾时补写：调用方中途退出也拿得到。
    """
    sources, failed = mount_lib.library_sources(library, db)
    unavailable = []
    for item in failed:
        logger.warning("媒体库「%s」来源不可用：%s（%s）", snap.name, item["label"], item["reason"])
        failed_roots.append(f"{item['label']}: {item['reason']}")
        unavailable.append({
            "label": item["label"], "kind": "unavailable", "error": item["reason"],
            # 形状与可用来源保持一致（计数器都在，只是全 0）：消费方不用为「读不到的来源」分支
            **{key: 0 for key in SCAN_SOURCE_COUNTERS},
        })

    try:
        for src in sources:
            if src.kind == "local":
                yield src.label, _local_dir_files(src.path, failed_roots)
                continue

            def _guarded(src=src):
                try:
                    yield from _mount_files(src, src.provider, failed_roots)
                except mount_lib.MountError as exc:
                    logger.warning("媒体库「%s」的挂载「%s」不可用：%s", snap.name, src.label, exc)
                    failed_roots.append(f"{src.label}: {exc}")
                except Exception as exc:  # noqa: BLE001 — 一个挂载坏掉不该拖垮整次扫描
                    logger.warning("媒体库「%s」的挂载「%s」异常：%s", snap.name, src.label, exc)
                    failed_roots.append(f"{src.label}: {exc}")

            yield src.label, _guarded()
    finally:
        if report is not None:
            report.extend(unavailable)


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


@dataclass
class _Pending:
    """一批里待处理的一个文件：解析结果 + 预取到的 IO 结果"""

    scan_file: Any
    guid: str
    parsed: dict
    item_type: str
    series_guid: Optional[str] = None
    season_guid: Optional[str] = None
    item: Any = None
    series: Any = None
    season: Any = None
    probe: Any = None   # Future[dict] | None
    probe_deferred: bool = False  # 两阶段 background 模式：本次不探测，写库时标 pending
    probe_needed: bool = False  # 本次是否需要探测（提交点按 needs_probe 语义算好）
    side: Any = None    # Future[(poster, fanart, subtitles)] | None
    tmdb: Any = None    # Future[(hit, details)] | None
    nfo: Any = None     # Future[(nfo_data, series_nfo_data, season_nfo_data)] | None
    series_tmdb: Any = None  # Future[(hit, details)] | None（剧集级 NFO 只补图用）
    # 上面三个是「排队中的 IO」，下面四个是**已经取回**的纯值。
    # 取回动作统一发生在批次开头（那时还没有任何写事务），写库循环里只读纯值——
    # 一旦在写事务里等网络，SQLite 的写锁就被按在网络 RTT 后面（见 docs/performance.md）。
    probe_data: Optional[dict] = None
    side_data: Any = None           # (poster, fanart, subtitles) | None
    tmdb_hit: Any = None
    tmdb_details: Any = None
    nfo_data: Any = None            # 本文件/电影的 NFO 解析结果
    series_nfo_data: Any = None     # tvshow.nfo 解析结果（episode 用）
    season_nfo_data: Any = None     # season.nfo 解析结果（episode 用）
    skipped: bool = False  # 增量扫描：目录没变且库里已是最新 → 本次不做任何写库工作
    fast_skipped: bool = False  # 分层 L1 秒跳：文件指纹命中且已补全 → 连目录指纹都不算
    file_fingerprint: Optional[str] = None  # 本批算出的文件指纹，写库时落库
    layered: bool = False  # 分层 L1：本文件只做极简入库，慢 IO 留给后台
    layered_local_fast: bool = False  # 分层 L1 本机文件：side/NFO 照常做（本地 IO 快）


@dataclass
class _ScanContext:
    """一次扫描里跨批次复用的状态（内存里只留 guid 集合与目录列表缓存）"""

    snap: LibrarySnapshot
    lib_id: int
    stats: dict
    seen_guids: set = field(default_factory=set)
    dir_cache: dict = field(default_factory=dict)          # 本机目录列表
    mount_dir_cache: dict = field(default_factory=dict)    # 远程挂载目录列表
    mount_lock: threading.Lock = field(default_factory=threading.Lock)
    mount_dir_locks: dict = field(default_factory=dict)     # 每个远程目录一把单飞锁
    # 剧集层级：guid → 条目对象（不是 id），一次扫描内复用
    # （同一部剧的多集只查一次、只建一次；存对象是因为写库循环后段还要用它们做
    #  「集 → 季 → 剧」的海报回退；同一 Session 的身份映射保证对象不会有两个实例）
    series_items: dict = field(default_factory=dict)
    season_items: dict = field(default_factory=dict)
    # 增量扫描：目录 → 本次指纹（None = 拿不到，这个目录不走捷径）
    dir_fingerprints: dict = field(default_factory=dict)
    # 本批处理过的目录（目录 → 当前指纹），批次提交时写回
    dirty_dirs: dict = field(default_factory=dict)
    # 列举失败的远程目录（读不到就别拿空列表当“目录没变”）
    dir_list_failed: set = field(default_factory=set)
    # NFO：已解析的 NFO 缓存（含阴性缓存），key 见 _read_nfo_cached
    nfo_cache: dict = field(default_factory=dict)
    # 剧集级 NFO 补图：series_guid → TMDB 详情（本轮已取过的不重复取）
    nfo_series_details: dict = field(default_factory=dict)
    # 本轮已处理过补图的 series_guid（去重，避免同剧多集/多批次重复调详情接口）
    nfo_series_imaged: set = field(default_factory=set)
    # episode 隐式 series 的 TMDB 搜索结果：series_guid → (hit, details)
    series_tmdb_results: dict = field(default_factory=dict)
    # 本轮已为隐式 series 提交过 TMDB 搜索的 series_guid（去重，避免同剧多集/多批次重复搜）
    series_tmdb_searched: set = field(default_factory=set)



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
SCAN_INCREMENTAL = (os.getenv("SCAN_INCREMENTAL", "1") or "1").strip().lower() \
    not in {"0", "false", "no", "off"}


# 分层扫描 L1/L2 总开关（v2.40.0）：1=开（默认）。
# 开：Phase 1 只做文件发现+指纹+极简入库（秒级可见），side/NFO/TMDB 全部
#     交给后台 enrich_worker 补全；关：回到旧行为（Phase 1 内联做完所有事）。
# 探测：background 模式走 probe_worker（不变）；inline 模式在分层下也推迟到
#     enrich_worker 排队（避免远程直链拖慢秒级入库），关分层则恢复当场探测。
SCAN_LAYERED = (os.getenv("SCAN_LAYERED", "1") or "1").strip().lower() \
    not in {"0", "false", "no", "off"}


# 文件指纹秒跳总开关（v2.40.0）：1=开（默认）。关掉后回到纯目录指纹增量逻辑，
# 供 smoke_test_scan_incremental.py 这类验证旧行为的测试使用。
SCAN_FAST_SKIP = (os.getenv("SCAN_FAST_SKIP", "1") or "1").strip().lower() \
    not in {"0", "false", "no", "off"}


def _dir_key_of(scan_file: "ScanFile") -> str:
    """目录的稳定标识：本机用绝对路径，挂载用 ``mount://<id>/<rel>``"""
    if scan_file.local_dir:
        return scan_file.local_dir
    return mount_lib.mount_path(scan_file.mount_id, scan_file.dir_rel)


def _dir_fingerprint(ctx: "_ScanContext", scan_file: "ScanFile") -> Optional[str]:
    """目录指纹（拿不到返回 None：这个目录这一次不走增量捷径）"""
    key = _dir_key_of(scan_file)
    if key in ctx.dir_fingerprints:
        return ctx.dir_fingerprints[key]
    value: Optional[str] = None
    if scan_file.local_dir:
        try:
            listing = _list_dir_cached(scan_file.local_dir)
            value = f"{os.stat(scan_file.local_dir).st_mtime_ns}:{len(listing)}"
        except OSError:
            value = None
    elif key not in ctx.dir_list_failed:
        entries = _mount_names(ctx, scan_file)
        if key not in ctx.dir_list_failed:
            value = f"{len(entries)}:{sum(int(e.size or 0) for e in entries)}"
    ctx.dir_fingerprints[key] = value
    return value


def _load_dir_states(db: Session, lib_id: int, dir_keys: list) -> dict:
    """一批目录的已存指纹（分片查，只取两个列）"""
    found: dict = {}
    unique = list(dict.fromkeys(k for k in dir_keys if k))
    for chunk in _chunks(unique, SQL_IN_CHUNK):
        for row in db.query(emby_models.ScanDirState.dir_key,
                            emby_models.ScanDirState.fingerprint).filter(
            emby_models.ScanDirState.library_id == lib_id,
            emby_models.ScanDirState.dir_key.in_(chunk),
        ):
            found[row.dir_key] = row.fingerprint
    return found


def _store_dir_states(db: Session, ctx: "_ScanContext") -> None:
    """把本批处理过的目录指纹写回（与条目在同一个事务里提交）"""
    dirty, ctx.dirty_dirs = ctx.dirty_dirs, {}
    if not dirty:
        return
    existing: dict = {}
    for chunk in _chunks(list(dirty.keys()), SQL_IN_CHUNK):
        for row in db.query(emby_models.ScanDirState).filter(
            emby_models.ScanDirState.library_id == ctx.lib_id,
            emby_models.ScanDirState.dir_key.in_(chunk),
        ):
            existing[row.dir_key] = row
    now = datetime.now()
    for dir_key, fingerprint in dirty.items():
        row = existing.get(dir_key)
        if row is None:
            db.add(emby_models.ScanDirState(library_id=ctx.lib_id, dir_key=dir_key,
                                            fingerprint=fingerprint, updated_at=now))
        elif row.fingerprint != fingerprint:
            row.fingerprint = fingerprint
            row.updated_at = now


def _can_skip_file(ctx: "_ScanContext", item, pending: "_Pending", fingerprint: Optional[str],
                   stored_fingerprint: Optional[str]) -> bool:
    """这个文件能不能不做任何写库工作（只记一笔）

    任何一条不满足都退回完整处理——宁可多做，不能漏文件或漏元数据。
    """
    if not SCAN_INCREMENTAL or item is None or not fingerprint:
        return False
    if fingerprint != stored_fingerprint:
        return False                     # 目录变过：图片/字幕/轨道都要重新看一遍
    scan_file = pending.scan_file
    if needs_probe(item, scan_file.stored_path, scan_file.size):
        return False                     # 没探过 / 文件大小变了
    if getattr(item, "repair_requested_at", None):
        return False
    # 刮削相关的条件只在「真的可能刮到东西」时才拦：没配 TMDB 的部署重试一万次也不会有结果，
    # 没道理因此让整库每轮都重做一遍（配好密钥的下一次扫描自然会重新处理这些条目）。
    # 另外只有**电影 / 剧集**参与刮削（写库循环里是 item_type in ("series", "movie")）：
    # 集与季根本没有 tmdb_id，`should_scrape` 对它们恒等于「缺元数据 → 要刮」，落到这里就是
    # 「配了 TMDB 的剧集库每轮重扫都得完整处理每一集」——增量扫描对这个最常见的库型等于关掉。
    if tmdb_client.configured and pending.item_type in ("series", "movie"):
        if should_scrape(item, ctx.snap.scrape_policy):
            return False                 # 到期重刮 / all 策略 / 缺元数据
        if item.tmdb_id and not (item.imdb_id and item.aliases):
            return False                 # 与循环里的 need_details 一致：详情还没补齐
    if (pending.item_type == "episode" and tmdb_client.configured
            and pending.series_guid):
        # B 方案补全：父 series 从没走过 TMDB（无 tmdb_id 且无尝试记录）时不能跳过——
        # episode 隐式创建的 series 平时走不到 TMDB 搜索分支，跳过了就永远刮不到。
        # 干净落地后（无论命中与否）会记 last_scraped_at，之后不再拦：
        # 否则配了 TMDB 的剧集库每轮重扫都得完整处理每一集（v2.31.0 钉住的行为）。
        s = ctx.series_items.get(pending.series_guid)
        if s is not None and not s.tmdb_id and not s.last_scraped_at:
            return False
    if pending.item_type == "episode" and not (item.series_id and item.parent_id):
        return False                     # 剧集/季层级没挂全，走完整处理补齐
    return True


def _prefetch_remote_listings(ctx: "_ScanContext", prepared: list, pool) -> None:
    """并发预热本批远程目录的列举（指纹与图片/字幕判定共用同一份）

    指纹要先列一次目录才拿得到，而那份列表本来就要为图片 / 外挂字幕判定而列——
    这里只是把它从「写库循环里等着」提前到批次开头，和其它 IO 一起并行跑，
    不会因为增量扫描而多出网络往返。
    """
    seen: set = set()
    futures: list = []
    for pending in prepared:
        scan_file = pending.scan_file
        if scan_file.local_dir or scan_file.mount_id is None:
            continue
        key = (scan_file.mount_id, scan_file.dir_rel)
        if key in seen:
            continue
        seen.add(key)
        with ctx.mount_lock:
            if key in ctx.mount_dir_cache:
                continue
        futures.append(pool.submit(_mount_names, ctx, scan_file))
    for fut in futures:
        _result(fut)                     # 读不到时 _mount_names 自己兜住（记进 dir_list_failed）


# 季目录名（远端挂载的剧集分组用）：Season 01 / S01 / 第1季 / 第一季
_SEASON_DIR_RE = re.compile(
    r"^(?:season\s*\.?\s*\d{1,2}|s\d{1,2}|第\s*(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*季)$",
    re.IGNORECASE,
)


def _series_guid_of(scan_file: "ScanFile") -> str:
    """剧集条目的 guid（由剧集目录推导）

    - 本机：文件目录的父目录（Season 子目录结构；与旧实现一致）
    - 远端：dir_rel 本身是季目录（Season 01 / S01 / 第1季）时取其父目录，
      否则取 dir_rel 本身——与本机分支同口径。旧实现对远端直接取文件目录，
      会把同一部剧的各季拆成多个剧集条目。
    """
    dirpath = scan_file.local_dir
    if dirpath:
        series_dir = os.path.dirname(dirpath.rstrip("/")) if dirpath else ""
        return item_guid(series_dir or (os.path.dirname(scan_file.stored_path) or scan_file.stored_path))
    d = (scan_file.dir_rel or "/").rstrip("/") or "/"
    if _SEASON_DIR_RE.match(os.path.basename(d)):
        d = posixpath.dirname(d) or "/"
    return item_guid(mount_lib.mount_path(scan_file.mount_id, d))


def _library_exists(db: Session, lib_id: int) -> bool:
    """媒体库是否还在（扫描可能跑很久，期间库可能被删）"""
    return db.query(emby_models.Library.id).filter(
        emby_models.Library.id == lib_id
    ).first() is not None


def _load_items(db: Session, guids: list) -> dict:
    """按 guid 批量取条目（分片，避免超出数据库的绑定变量上限）

    老实现每个文件查 1~3 次（条目、剧集、季），十万个文件就是几十万次往返；
    现在一批只查（guids / 200）次。
    """
    found: dict = {}
    unique = list(dict.fromkeys(g for g in guids if g))
    for chunk in _chunks(unique, SQL_IN_CHUNK):
        for row in db.query(emby_models.MediaItem).filter(emby_models.MediaItem.guid.in_(chunk)):
            found[row.guid] = row
    return found


def _local_names(ctx: "_ScanContext", dirpath: str) -> list:
    """本机目录列表（与写库线程共用同一份缓存，预热之后不会重复读目录）"""
    return _list_dir_cached(dirpath)


def _mount_dir_entries(ctx: "_ScanContext", scan_file: "ScanFile", dir_rel: str) -> list:
    """远程挂载目录列表（同一个目录只请求一次；大目录下这一项能省掉九成网络往返）

    同一个目录的文件会被分发到不同工作线程，所以这里按目录单飞：线程之间只等「别人正在
    列的这个目录」，不同目录仍然并行。分成两段的实现在并发时会各自去请求一次网盘。
    比旧 _mount_names 多一个 dir_rel 参数：NFO 发现要查父目录（tvshow.nfo），
    复用同一份缓存与单飞锁，不会多一次网络往返。
    """
    key = (scan_file.mount_id, dir_rel)
    with ctx.mount_lock:
        if key in ctx.mount_dir_cache:
            return ctx.mount_dir_cache[key]
        lock = ctx.mount_dir_locks.get(key)
        if lock is None:
            lock = ctx.mount_dir_locks[key] = threading.Lock()
    with lock:
        with ctx.mount_lock:               # 别人可能已经列完了
            if key in ctx.mount_dir_cache:
                return ctx.mount_dir_cache[key]
        try:
            entries = scan_file.provider.list_dir(dir_rel)
        except mount_lib.MountError as exc:
            logger.warning("读取挂载目录失败，跳过：%s（%s）", dir_rel, exc)
            entries = []
            ctx.dir_list_failed.add(_dir_key_of(scan_file))
        except Exception as exc:  # noqa: BLE001 — 目录读不到不该中断扫描
            logger.warning("读取挂载目录异常，跳过：%s（%s）", dir_rel, exc)
            entries = []
            ctx.dir_list_failed.add(_dir_key_of(scan_file))
        with ctx.mount_lock:
            ctx.mount_dir_cache[key] = entries
            ctx.mount_dir_locks.pop(key, None)  # 列完就不必再留着这把锁
        return entries


def _mount_names(ctx: "_ScanContext", scan_file: "ScanFile") -> list:
    """文件所在目录的远程列举（_mount_dir_entries 的便捷包装）"""
    return _mount_dir_entries(ctx, scan_file, scan_file.dir_rel)


def _side_info(ctx: "_ScanContext", scan_file: "ScanFile") -> tuple:
    """本地图片与外挂字幕（IO 密集，放在线程池里跑）"""
    if scan_file.local_dir:
        names = _local_names(ctx, scan_file.local_dir)
        poster, fanart = find_local_images_in(
            names, scan_file.local_dir, os.path.splitext(scan_file.name)[0],
        )
        return poster, fanart, find_external_subtitles_in(names, scan_file.stored_path)
    if scan_file.mount_id is not None:
        entries = _mount_names(ctx, scan_file)
        return None, None, find_external_subtitles_remote(
            scan_file.name, entries, scan_file.mount_id, scan_file.dir_rel,
        )
    return None, None, []


def _nfo_candidates(kind: str, name: str) -> list:
    """按 Kodi 约定给出 NFO 候选文件名（按优先级）"""
    stem = os.path.splitext(name)[0]
    if kind == "movie":
        return [f"{stem}.nfo", f"{name}.nfo", "movie.nfo"]
    if kind == "series":
        return ["tvshow.nfo"]
    # episode：实测远端形如 xxx.1080p.mp4.nfo（全名 + .nfo），也兼容去扩展名写法
    return [f"{name}.nfo", f"{stem}.nfo"]


def _read_nfo_cached(ctx: "_ScanContext", scan_file: "ScanFile",
                     local_path: Optional[str] = None,
                     mount_rel: Optional[str] = None):
    """读 + 解析一个 NFO（ctx 级缓存，含阴性缓存；异常当没有 NFO）"""
    key = ("local", local_path) if local_path else ("mount", scan_file.mount_id, mount_rel)
    if key not in ctx.nfo_cache:
        try:
            if local_path:
                with open(local_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    text = f.read()
            else:
                text = scan_file.provider.read_text(mount_rel)
            ctx.nfo_cache[key] = nfo_lib.parse_nfo(text)
        except Exception:  # noqa: BLE001 — 单个 NFO 读不到就当没有
            ctx.nfo_cache[key] = None
    return ctx.nfo_cache[key]


def _locate_series_dir(ctx: "_ScanContext", scan_file: "ScanFile", dirpath: str) -> Optional[str]:
    """episode 的剧集目录：本目录或父目录中含 tvshow.nfo 的那个（都没有返回 None）"""
    if scan_file.local_dir is not None:
        if "tvshow.nfo" in _list_dir_cached(dirpath):
            return dirpath
        parent = os.path.dirname(dirpath.rstrip("/"))
        if parent and parent != dirpath and "tvshow.nfo" in _list_dir_cached(parent):
            return parent
        return None
    if "tvshow.nfo" in {e.name for e in _mount_dir_entries(ctx, scan_file, dirpath)}:
        return dirpath
    parent = posixpath.dirname(dirpath.rstrip("/")) or "/"
    if parent != dirpath and "tvshow.nfo" in {
        e.name for e in _mount_dir_entries(ctx, scan_file, parent)
    }:
        return parent
    return None


def _find_nfos(ctx: "_ScanContext", scan_file: "ScanFile", kind: str) -> tuple:
    """发现并解析 NFO → (nfo_data, series_nfo_data, season_nfo_data)

    - movie：同目录 `<片名>.nfo` / `movie.nfo`
    - series（剧集库单文件）：同目录 `tvshow.nfo`
    - episode：同目录 `<集文件名>.nfo`；同目录 `season.nfo`；剧集目录 `tvshow.nfo`
    """
    is_local = scan_file.local_dir is not None
    if not is_local and not (scan_file.mount_id is not None and scan_file.provider is not None):
        return None, None, None
    dirpath = scan_file.local_dir if is_local else (scan_file.dir_rel or "/")

    def read_nfo(d: str, fname: str):
        if is_local:
            return _read_nfo_cached(ctx, scan_file, local_path=os.path.join(d, fname))
        return _read_nfo_cached(ctx, scan_file, mount_rel=posixpath.join(d, fname))

    if is_local:
        names = set(_list_dir_cached(dirpath))
    else:
        names = {e.name for e in _mount_dir_entries(ctx, scan_file, dirpath)}

    nfo_data = series_nfo_data = season_nfo_data = None
    if kind in ("movie", "episode"):
        for cand in _nfo_candidates(kind, scan_file.name):
            if cand in names:
                nfo_data = read_nfo(dirpath, cand)
                if nfo_data:
                    break
    elif kind == "series" and "tvshow.nfo" in names:
        nfo_data = read_nfo(dirpath, "tvshow.nfo")
    if kind == "episode":
        if "season.nfo" in names:
            season_nfo_data = read_nfo(dirpath, "season.nfo")
        series_dir = _locate_series_dir(ctx, scan_file, dirpath)
        if series_dir:
            series_nfo_data = read_nfo(series_dir, "tvshow.nfo")
    return nfo_data, series_nfo_data, season_nfo_data


def _nfo_work(ctx: "_ScanContext", scan_file: "ScanFile", kind: str) -> tuple:
    """NFO 发现与解析（IO 线程池里跑；单个失败不影响整批）"""
    try:
        return _find_nfos(ctx, scan_file, kind)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NFO 发现失败 %s：%s", scan_file.stored_path, exc)
        return None, None, None


def _tmdb_work(need_search: bool, name: str, year, kind: str,
               existing_id, want_details: bool) -> tuple:
    """在**同一个工作线程**里跑完这个条目需要的 TMDB 调用（搜索 → 详情）

    搜索与详情有先后依赖，所以不能拆到两个批次里；但条目之间可以并行——
    老实现是逐条串行等网络，追新时最卡的就是这里。多个条目共用同一个 httpx 客户端，
    它的连接池是线程安全的；密钥轮询只在配额报错时发生。

    ``want_details`` 由调用方按「写库那一步会不会用详情」算好（新条目要补 IMDb Id 与别名、
    带补图标记的条目要重取图）；这里不再对每个命中都无条件拉一次详情。
    """
    hit = tmdb_client.search(name, year, kind) if need_search else None
    details = None
    if hit:
        if want_details:
            details = tmdb_client.details(str(hit.get("id")), kind)
    elif existing_id and want_details:
        details = tmdb_client.details(str(existing_id), kind)
    return hit, details


def _result(handle, default=None):
    """取出预取结果（None 表示没提交任务；任务异常不影响整次扫描）"""
    if handle is None:
        return default
    if isinstance(handle, Future):
        try:
            return handle.result()
        except Exception as exc:  # noqa: BLE001 — 单个文件的探测/刮削失败不该拖垮整库
            logger.warning("扫描预取任务失败：%s", exc)
            return default
    return handle


# 扫描用的进程级线程池：同一进程里可能连续扫多个媒体库（多来源、多库批量扫描），
# 反复建池/销池反而更贵。池子只在第一次真正提交任务时才会创建线程，空闲时几乎不吃资源，
# 进程退出时由解释器统一回收。
_SCAN_POOL: Optional[ThreadPoolExecutor] = None
_SCAN_POOL_LOCK = threading.Lock()


def _scan_pool() -> ThreadPoolExecutor:
    global _SCAN_POOL
    with _SCAN_POOL_LOCK:
        if _SCAN_POOL is None or getattr(_SCAN_POOL, "_shutdown", False):
            _SCAN_POOL = ThreadPoolExecutor(max_workers=SCAN_WORKERS, thread_name_prefix="scan-io")
        return _SCAN_POOL


def _prepare_and_prefetch(db: Session, batch: list, ctx: "_ScanContext", pool) -> list:
    """把一批文件变成「可直接写库」的任务：一次查库 + 并行预取"""
    prepared: list = []
    guids: list = []
    for scan_file in batch:
        guid = item_guid(scan_file.stored_path)
        if guid in ctx.seen_guids:
            # 同一文件在本轮扫描里已经处理过：遍历器偶发产出重复
            # （rclone lsjson 网盘侧重复条目 / 分页异常，见 _CloudMount.walk_media
            # 的注释），第二次不再建任务。否则两个 _Pending 的 item 都为 None，
            # 写库循环里两次 db.add 同 guid，flush 时撞 emby_items.guid 唯一键、
            # 整批回滚、整库扫描 abort（2026-09-25 生产事故）。
            # seen_guids 里已有它，清理阶段不受影响；计数进统计方便事后排查。
            ctx.stats["duplicate_files"] = ctx.stats.get("duplicate_files", 0) + 1
            logger.debug("扫描跳过重复文件：%s", scan_file.stored_path)
            continue
        ctx.seen_guids.add(guid)
        parsed = parse_media_filename(scan_file.stored_path, ctx.snap.collection_type)
        item_type = (
            "episode" if parsed["season"] is not None
            else ("series" if ctx.snap.collection_type == "tvshows" else "movie")
        )
        pending = _Pending(scan_file=scan_file, guid=guid, parsed=parsed, item_type=item_type)
        if item_type == "episode":
            pending.series_guid = _series_guid_of(scan_file)
            pending.season_guid = item_guid(f"{pending.series_guid}:S{parsed['season']:02d}")
        prepared.append(pending)
        guids.append(guid)

    known = _load_items(db, guids)

    # 剧集层级一次查齐：老实现在写库循环里对**每一集**点查剧集、再点查季（两集一次往返
    # 各一次），十万集就是二十万次查询。这里在批次开头把这一批用到的剧集与季一次取回，
    # 结果按 guid 缓存到本次扫描结束——同一部剧的后续批次连这次查询都省了。
    parent_guids: list = []
    for pending in prepared:
        if not pending.series_guid:
            continue
        if pending.series_guid not in ctx.series_items:
            parent_guids.append(pending.series_guid)
        if pending.season_guid not in ctx.season_items:
            parent_guids.append(pending.season_guid)
    if parent_guids:
        parents = _load_items(db, parent_guids)
        for pending in prepared:
            if not pending.series_guid:
                continue
            row = parents.get(pending.series_guid)
            if row is not None:
                ctx.series_items[pending.series_guid] = row
            row = parents.get(pending.season_guid)
            if row is not None:
                ctx.season_items[pending.season_guid] = row

    # 增量扫描：先把本批远程目录的列举并发预热（指纹要用，写库循环里的图片/字幕判定
    # 也要用同一份，不会多一次网络往返），再一次取出这些目录的已存指纹
    if SCAN_INCREMENTAL:
        _prefetch_remote_listings(ctx, prepared, pool)
    stored_states = _load_dir_states(
        db, ctx.lib_id, [_dir_key_of(p.scan_file) for p in prepared]
    ) if SCAN_INCREMENTAL else {}

    policy = ctx.snap.scrape_policy
    for pending in prepared:
        item = known.get(pending.guid)
        pending.item = item
        scan_file = pending.scan_file
        is_new = item is None
        # 分层扫描 L1 秒跳：文件指纹是「文件本身变没变」的唯一依据，一次哈希比较。
        # 命中（且 L2/L3 已补全、没被标记重修）→ 本文件本轮零 IO：不算目录指纹、
        # 不提交 probe/side/NFO/TMDB，写库循环里只记 unchanged。
        # 注意顺序：这个检查必须在目录指纹之前——目录指纹要列目录（远程=网络 IO），
        # 文件指纹是纯内存计算。旧 _can_skip_file 保留做兜底（指纹缺失的老数据）。
        file_fp = _file_fingerprint(scan_file)
        pending.file_fingerprint = file_fp
        if (SCAN_FAST_SKIP
                and not is_new
                and (getattr(item, "file_fingerprint", None) or None) == file_fp
                and (getattr(item, "enrich_status", None) or "pending") == "done"
                and not getattr(item, "repair_requested_at", None)):
            pending.fast_skipped = True
            ctx.stats["unchanged"] = ctx.stats.get("unchanged", 0) + 1
            continue
        # 目录没变、库里这一行也是最新的 → 不做任何逐文件工作（guid 已在上面记进 seen_guids）
        dir_key = _dir_key_of(scan_file)
        fingerprint = _dir_fingerprint(ctx, scan_file) if SCAN_INCREMENTAL else None
        if _can_skip_file(ctx, item, pending, fingerprint, stored_states.get(dir_key)):
            pending.skipped = True
            # updated 照旧计一次（对用户来说这个条目本轮确实重新核对过），
            # 另外单独记 unchanged，方便看“增量到底省了多少”
            ctx.stats["updated"] = ctx.stats.get("updated", 0) + 1
            ctx.stats["unchanged"] = ctx.stats.get("unchanged", 0) + 1
            continue
        if fingerprint:
            ctx.dirty_dirs[dir_key] = fingerprint   # 这个目录这批真处理了 → 提交时写回指纹
        pending.probe_needed = bool(is_new or needs_probe(item, scan_file.stored_path,
                                                             scan_file.size))
        if SCAN_LAYERED and not pending.fast_skipped:
            # 分层 L1：本机文件只跳过 TMDB（side/NFO 是本地磁盘 IO，很快，照常做，
            # 保证本地海报扫描完立即可见）；远程文件跳过全部 IO（网络慢，后台补）。
            # 写库时 enrich_status='pending'，enrich_worker 随后补完剩下的。
            pending.layered = True
            pending.layered_local_fast = bool(scan_file.local_dir)
        if pending.probe_needed:
            if PROBE_BACKGROUND:
                # Phase 1：不提交 ffprobe（连 probe_input 的直链解析都省了），
                # 写库时把条目标 probe_status='pending' 交给后台 worker。
                pending.probe_deferred = True
            elif pool is not None and (not pending.layered or getattr(pending, "layered_local_fast", False)):
                # inline 模式当场探测：分层下本机文件也探（本地 ffprobe 很快），
                # 只有远程文件才推迟（直链解析要走网络）。
                pending.probe = pool.submit(probe_metadata, *scan_file.probe_input(), size=scan_file.size)
            # 分层 + inline + 远程：L1 不探，enrich_worker 补全时把 probe_status
            # 置 pending，probe_worker 接手
        if pool is not None and (not pending.layered or getattr(pending, "layered_local_fast", False)):
            pending.side = pool.submit(_side_info, ctx, scan_file)
        # NFO 发现与解析（与 probe / side / TMDB 并行；结果在下面先取回，
        # TMDB 预取口径按 NFO 有无决定：有 tmdb_id 就不调搜索）
        if pool is not None and pending.item_type in ("series", "movie", "episode") and (
            not pending.layered or getattr(pending, "layered_local_fast", False)):
            pending.nfo = pool.submit(_nfo_work, ctx, scan_file, pending.item_type)

    # NFO 先取回（小文件 IO），再决定 TMDB 预取口径——搜索是扫描里最贵的网络调用，
    # 远端已有 NFO 刮削的条目直接跳过它（B 方案：TMDB 只在缺图/缺详情时调详情接口）。
    for pending in prepared:
        if pending.skipped or pending.fast_skipped or pending.layered:
            continue
        nfo_data, series_nfo_data, season_nfo_data = (
            _result(pending.nfo, default=(None, None, None)) or (None, None, None)
        )
        pending.nfo_data = nfo_data
        pending.series_nfo_data = series_nfo_data
        pending.season_nfo_data = season_nfo_data
        if pending.item_type not in ("series", "movie", "episode"):
            continue
        item = pending.item
        is_new = item is None
        needs_repair = bool(getattr(item, "repair_requested_at", None))
        if pending.item_type in ("series", "movie"):
            kind = "series" if pending.item_type == "series" else "movie"
            nfo_id = (nfo_data or {}).get("tmdb_id")
            if nfo_id:
                # NFO 命中且有 tmdb_id：不调 TMDB 搜索；只在缺图/缺 imdb/别名/
                # 带补图标记时取详情（补图用）
                need_search = False
                existing_id = str(nfo_id)
                want_details = bool(
                    needs_repair
                    or not ((item.poster_path if item else None)
                            or (item.primary_image_url if item else None))
                    or not ((item.imdb_id if item else None)
                            and (item.aliases if item else None))
                )
            else:
                need_search = is_new or needs_repair or should_scrape(item, policy)
                existing_id = getattr(item, "tmdb_id", None)
                need_details = bool(existing_id) and bool(
                    needs_repair or not (item.imdb_id and item.aliases)
                )
                # 详情预取的口径必须**覆盖**写库那一步可能用到的所有情况：新条目（补 IMDb /
                # 别名）、带补图标记的条目、已有 tmdb_id 但缺 IMDb Id / 多别名的条目，
                # 以及「这一轮会重刮、而库里还缺这两项」的条目——后者 apply() 之后
                # tmdb_id 才被写上，写库那一步就会去要详情。
                # 少预取一次，写库那一步就会在事务里发一次网络请求（见 _tmdb_work）。
                want_details = bool(
                    is_new or needs_repair or need_details
                    or (should_scrape(item, policy) and not (item.imdb_id and item.aliases))
                )
            if pool is not None and (need_search or want_details):
                pending.tmdb = pool.submit(
                    _tmdb_work, need_search, pending.parsed["name"], pending.parsed["year"],
                    kind, existing_id, want_details,
                )
        else:  # episode：剧集级 NFO 的 TMDB 详情只补图，同一部剧一批只取一次
            series_id = (series_nfo_data or {}).get("tmdb_id")
            if series_id and pending.series_guid not in ctx.nfo_series_imaged:
                ctx.nfo_series_imaged.add(pending.series_guid)  # 占位去重：跨批次不重复取
                s_item = ctx.series_items.get(pending.series_guid)
                if pool is not None and (s_item is None or not (s_item.poster_path or s_item.primary_image_url)):
                    pending.series_tmdb = pool.submit(
                        _tmdb_work, False, "", None, "series", str(series_id), True,
                    )
            elif (not series_id and tmdb_client.configured
                    and pending.series_guid not in ctx.series_tmdb_searched):
                # B 方案补全：episode 隐式创建的 series 平时走不到 TMDB 搜索，
                # NFO 里又没有 tmdb_id 时，按剧名搜一次（TMDB 只补图与缺的字段，
                # NFO 文本随后在写库循环里覆盖，口径与顶层 series 分支一致）
                s_item = ctx.series_items.get(pending.series_guid)
                # 只给“从没走过 TMDB”的剧搜一次：干净落地后记 last_scraped_at，
                # 命中与否都不再重复——否则配了 TMDB 就每轮重做全集（v2.31.0）。
                # 注意这里故意不用 should_scrape：它对无 tmdb_id 的条目恒为 True。
                if s_item is None or (not s_item.tmdb_id and not s_item.last_scraped_at):
                    ctx.series_tmdb_searched.add(pending.series_guid)  # 占位去重：跨批次不重复搜
                    pending.series_tmdb = pool.submit(
                        _tmdb_work, True, pending.parsed["name"],
                        pending.parsed["year"], "series", None, True,
                    )

    # 把这一批的 IO 结果**全部取回**，然后才把写库交给调用方。
    # 这是「事务只包纯 DB 写」的关键一步：ffprobe / rclone 列目录 / TMDB 搜索都可能在
    # 这里等上几秒（远程挂载与刮削都是网络），而调用方拿到任务后立刻开始写库——
    # 如果等到写库循环里再取结果，SQLite 的写锁就要陪着一起等（超过 busy_timeout=30s
    # 就是那句 database is locked，前端表现是 30 秒超时）。
    for pending in prepared:
        if pending.skipped or pending.fast_skipped:
            continue
        pending.probe_data = _result(pending.probe)
        pending.side_data = _result(pending.side)
        if pending.layered:
            # 分层 L1：side/probe 结果已取回（本机文件的 side 在上面提交了），
            # TMDB 等慢活跳过，等 enrich_worker。
            continue
        hit, details = _result(pending.tmdb, default=(None, None)) or (None, None)
        pending.tmdb_hit, pending.tmdb_details = hit, details
        series_hit, series_details = _result(pending.series_tmdb, default=(None, None)) or (None, None)
        if series_details is not None:
            ctx.nfo_series_details[pending.series_guid] = series_details
        if series_hit is not None:
            # episode 分支为隐式 series 做的 TMDB 搜索命中，留给写库循环落到 series 上
            ctx.series_tmdb_results[pending.series_guid] = (series_hit, series_details)
        if pending.series_tmdb is not None and isinstance(pending.series_tmdb, Future):
            # 搜索任务本身抛异常了：别记“已搜过”，下次扫描重来
            # （_result 上面已经等过 future，这里 exception() 不会阻塞）
            if pending.series_tmdb.exception() is not None:
                ctx.series_tmdb_searched.discard(pending.series_guid)
    return prepared


def _iter_prepared(ctx: "_ScanContext", files, pool, db: Session):
    """按批次把文件流变成待写库的任务（顺序与调用方看到的一致）

    - 每批 SCAN_BATCH 个文件只查一次库，不再“每个文件查一两次”；
    - 探测 / 目录列举 / TMDB 在同一批内并行预热，写库线程随后取用不再等网络；
    - 每批结束只提交一次：几百个文件一次 fsync，会话也不会随库变大而堆积对象；
    - 增量扫描命中的文件（``pending.skipped``）不交给写库循环（本来就没活要干），
      并在这批提交之后把处理过的目录指纹写回（与条目同一个事务）。
    """
    pool = _scan_pool()  # 用进程级线程池（参数里的 pool 只作兼容，不再单独建池）
    batch: list = []
    real_commit = db.commit
    db.commit = db.flush  # 只改本 Session 实例：主体里的“每文件一次提交”退化成 flush

    def commit_batch() -> None:
        """批次提交：撞上别人占着写锁（另一台 EA / 备份 / checkpoint）时退避重试三次

        主体里之所以敢把「每文件一次提交」退化成 flush，是因为这里一批只提交一次；
        代价是这一批的写事务期间不能有任何 IO（见 _prepare_and_prefetch 的说明）。
        """
        retry_write(real_commit, label="扫描批次提交")
    try:
        for scan_file in files:
            batch.append(scan_file)
            if len(batch) < SCAN_BATCH:
                continue
            # 批次边界检查库还在不在：被删了就停手，不再往已删库插条目
            if not _library_exists(db, ctx.lib_id):
                logger.warning("媒体库 %s 在扫描期间被删除，扫描提前结束", ctx.lib_id)
                return
            yield from ((p.scan_file, p) for p in _prepare_and_prefetch(db, batch, ctx, pool)
                        if not p.skipped and not p.fast_skipped)
            _store_dir_states(db, ctx)   # 增量扫描：这批真处理过的目录指纹随本次提交写回
            batch = []
            commit_batch()  # 一批一次提交：几百个文件才一次 fsync
        if batch:
            yield from ((p.scan_file, p) for p in _prepare_and_prefetch(db, batch, ctx, pool)
                        if not p.skipped and not p.fast_skipped)
            _store_dir_states(db, ctx)
            commit_batch()
    finally:
        # 正常结束、中途报错、生成器被提前关闭：都要恢复真实提交
        db.commit = real_commit
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
    db.query(emby_models.MediaItem).filter(
        emby_models.MediaItem.id.in_(ids)
    ).delete(synchronize_session=False)


def _no_removals_possible(db: Session, library, seen_guids: set) -> bool:
    """快速路径：一眼判断「这一轮不可能有要清理的条目」

    两个条件都成立才返回 True，都只是计数查询（走索引），比遍历整库便宜两个数量级：

    1. **文件类条目数 == 本次扫描见到的文件数**：说明每个文件都有行，库里也没有多余的
       （来源里已经没有的）文件类条目；
    2. **剧/季行数 == 被引用的剧数 + 被引用的季数**：说明没有「没有子条目的剧或季」残留
       （剧被 season/episode 的 ``series_id`` 引用，季被 episode 的 ``parent_id`` 引用）。

    任何一个不成立就退回遍历——**宁可多花时间，也不能漏掉该删的条目**。
    实测十万条目（剧集库，稳定无删除）：这里约 40 ms，遍历整库约 2.2 s。
    """
    file_backed = int(db.execute(
        text(
            "SELECT COUNT(*) FROM emby_items "
            "WHERE library_id = :lib AND item_type IN ('movie', 'episode')"
        ),
        {"lib": library.id},
    ).scalar() or 0)
    if file_backed != len(seen_guids):
        return False                      # 条数与文件数对不上：可能有已消失的条目
    if not file_backed:
        return True                       # 空库：本来就没有可清理的
    parents = int(db.execute(
        text(
            "SELECT COUNT(*) FROM emby_items "
            "WHERE library_id = :lib AND item_type IN ('series', 'season')"
        ),
        {"lib": library.id},
    ).scalar() or 0)
    if not parents:
        return True                       # 电影库：没有剧/季要收拾
    refs_series = int(db.execute(
        text(
            "SELECT COUNT(DISTINCT series_id) FROM emby_items "
            "WHERE library_id = :lib AND item_type IN ('episode', 'season') "
            "AND series_id IS NOT NULL"
        ),
        {"lib": library.id},
    ).scalar() or 0)
    refs_season = int(db.execute(
        text(
            "SELECT COUNT(DISTINCT parent_id) FROM emby_items "
            "WHERE library_id = :lib AND item_type = 'episode' AND parent_id IS NOT NULL"
        ),
        {"lib": library.id},
    ).scalar() or 0)
    return parents == refs_series + refs_season


def _remove_missing_items(db: Session, library, seen_guids: set) -> int:
    """清理「来源里已经没有」的条目，返回删除条数

    三个刻意的选择：

    - **快速路径**：稳定库（每个文件都有行、没有多余行、没有无子条目的剧/季）根本不必
      遍历整库，两次计数就能证明「没有可清理的条目」；任何一条对不上就退回遍历。
    - **游标分批**：老实现 `db.query(...).all()` 把整库条目一次性读进内存——十万级库
      就是几十万个 ORM 对象，正是「扫描把机器拖垮」的主因。现在按 id 递增读取，
      且只取 4 个列（Core 语句，不构造 ORM 实体），删除也不会让游标卡住（每批只往后走）。
    - **显式删从属数据**：见 `_purge_items`。
    """
    global _CLEANUP_LAST
    started = time.perf_counter()
    _CLEANUP_LAST = {"fast_path": False, "walked": 0, "removed": 0, "elapsed_ms": 0.0}
    if _no_removals_possible(db, library, seen_guids):
        elapsed = (time.perf_counter() - started) * 1000
        _CLEANUP_LAST.update(fast_path=True, elapsed_ms=elapsed)
        logger.info(
            "清理阶段：%d 个文件与库内条目一一对应，无需遍历整库（%.0f ms）",
            len(seen_guids), elapsed,
        )
        return 0
    removed = 0
    walked = 0
    last_id = 0
    while True:
        rows = db.execute(
            select(
                emby_models.MediaItem.id,
                emby_models.MediaItem.guid,
                emby_models.MediaItem.item_type,
                emby_models.MediaItem.file_path,
            )
            .where(
                emby_models.MediaItem.library_id == library.id,
                emby_models.MediaItem.id > last_id,
            )
            .order_by(emby_models.MediaItem.id)
            .limit(CLEANUP_BATCH)
        ).all()
        if not rows:
            break
        last_id = rows[-1][0]
        walked += len(rows)
        doomed: list[int] = []
        for item_id, guid, item_type, file_path in rows:
            if guid in seen_guids:
                continue
            if item_type in ("movie", "episode"):
                # 本机路径与远程挂载都查：命中的说明是别的来源的文件，保留；
                # 查不到（挂载已删/已停用）才当删除处理。
                if file_path and mount_lib.media_exists(file_path, db, library):
                    continue  # 其他来源（路径 / 挂载）的文件
                doomed.append(item_id)
            elif item_type == "season":
                has_children = db.query(emby_models.MediaItem.id).filter(
                    emby_models.MediaItem.parent_id == item_id
                ).first()
                if not has_children:
                    doomed.append(item_id)
            elif item_type == "series":
                has_children = db.query(emby_models.MediaItem.id).filter(
                    emby_models.MediaItem.series_id == item_id
                ).first()
                if not has_children:
                    doomed.append(item_id)
        if doomed:
            _purge_items(db, doomed)
            removed += len(doomed)
            db.commit()  # 一批一次提交：与扫描主体同一套资源口径
    _CLEANUP_LAST.update(walked=walked, removed=removed,
                         elapsed_ms=(time.perf_counter() - started) * 1000)
    return removed


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
                   "repaired", "unchanged", "removal_skipped", "failed_roots",
                   "duplicate_files", "duration_ms", "sources")


def normalize_scan_trigger(trigger: Optional[str]) -> str:
    """把触发方收敛到枚举内（未知值当作 manual，不因为调用方写错就丢记录）"""
    value = (trigger or "").strip().lower()
    return value if value in SCAN_TRIGGERS else "manual"


# 需要跟着一轮扫描一起落库的来源计数器
SCAN_SOURCE_COUNTERS = ("files", "added", "updated", "probed", "scraped", "repaired", "unchanged")
SCAN_SOURCES_MAX = 50              # 一个库的来源（路径 + 挂载）远小于这个量级；超了只留前 N 条
SCAN_SOURCE_LABEL_MAX = 200
SCAN_SOURCE_TEXT_MAX = 300


class _FileCounter:
    """数一条来源里**发现**了多少媒体文件

    必须放在来源流的最外层：``_iter_prepared`` 会跳过增量扫描命中的文件（未变化，不交给
    写库循环），按「写库条数」计的话，一个全都没变的来源会显示成 0 个文件——那是假象。
    """

    def __init__(self, files):
        self.total = 0
        self._files = files

    def __iter__(self):
        for item in self._files:
            self.total += 1
            yield item


def _attribute_source(label: str, counted: "_FileCounter", prepared,
                      stats: dict, failed_roots: list) -> Iterator[tuple]:
    """把一条来源的发现数与它在处理期间对总计的改动记到它名下

    两件事各归各位：

    - **发现数**来自 ``counted``（来源流最外层），见 _FileCounter；
    - **各计数器增量**在这一层收尾时算差值——不在扫描循环里逐条累加，循环体一个字都不用改
      （那是最容易被改坏的地方），而且中途抛错时记下的也是真实的**部分**结果。
      放在里层（来源流上）会提前收尾，最后一批的改动会被算到下一条来源头上。
    """
    sink = stats.setdefault("sources", [])
    before = {key: stats.get(key) or 0 for key in SCAN_SOURCE_COUNTERS}
    try:
        yield from prepared
    finally:
        sink.append(_source_entry(label, before, stats, counted.total, failed_roots))


def _source_entry(label: str, before: dict, stats: dict, seen: int,
                  failed_roots: list) -> dict:
    """一条来源的明细：文件数 + 各计数器增量 + 该来源自己的失败原因（若有）"""
    entry: dict = {"label": label, "files": seen}
    for key in SCAN_SOURCE_COUNTERS:
        if key == "files":
            continue
        current = stats.get(key)
        entry[key] = max(0, int(current or 0) - int(before.get(key) or 0)) if current is not None else 0
    prefix = f"{label}: "
    errors = [str(r)[len(prefix):] for r in failed_roots if str(r).startswith(prefix)]
    if errors:
        entry["error"] = "；".join(dict.fromkeys(errors))
    return entry


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
        logger.warning("写入扫描流水失败: %s", exc)
        db.rollback()


def _write_scan_state(db: Session, library: emby_models.Library, status: str,
                      stats: Optional[dict], error: Optional[str]) -> None:
    """状态 / 统计 / 原因写回媒体库并提交（落盘失败只记日志，不覆盖真实异常）"""
    library.is_scanning = False
    library.last_scan_at = datetime.now()
    library.scan_status = status
    library.scan_stats = encode_scan_stats(stats)
    library.scan_error = (error or "")[:500] or None
    try:
        commit_with_retry(db, label="扫描结果写回")
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入扫描结果失败: %s", exc)
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
    return status


def fail_scan(db: Session, library: emby_models.Library, exc: Exception,
              run_id: Optional[int] = None,
              duration_ms: Optional[int] = None) -> None:
    """扫描抛异常时把原因落库（管理端要能看到「为什么没扫成」）"""
    error = f"{type(exc).__name__}: {exc}"
    _write_scan_state(db, library, SCAN_STATUS_FAILED, None, error)
    # 失败也要记耗时：扫了四十分钟才炸和刚开就炸不是一回事
    stats = {"duration_ms": duration_ms} if duration_ms is not None else None
    _finish_scan_run(db, run_id, SCAN_STATUS_FAILED, stats, error)


def scan_library_sync(db: Session, library: emby_models.Library,
                      snapshot: Optional[LibrarySnapshot] = None,
                      trigger: str = "manual") -> dict:
    """扫描单个媒体库（同步实现，可在后台线程运行）

    约定：

    - **配置快照**：整个任务只认 `snapshot`（默认在入口处拍一张），见 LibrarySnapshot。
    - **重复任务拒绝**：同一媒体库同时只允许一个任务，重复触发抛 `ScanInProgress`。
    - **目录不完整禁止清理**：任何根目录不可读或遍历报错时跳过清理阶段，
      避免“读取失败 → 当成文件已删除 → 误删整库记录”。
    - **探测/刮削按需**：已探测过的文件不再重复 ffprobe（除非文件大小变了），
      刮削按媒体库策略（missing_only / 3m / 6m / 1y / all）。
    - **外挂字幕与视频探测解耦**：换字幕文件不需要重探视频。
    - **结果可查**：成功 / 部分失败 / 异常三条路都会把这一轮的统计与原因写回媒体库
      （scan_status / scan_stats / scan_error），见 ``scan_result_payload``；
      同时记一条扫描流水（含 ``trigger``），见 ``scan_runs_payload``。
    """
    snap = snapshot or LibrarySnapshot.of(library)
    # 先在**进程内**占位（重复任务会在这一步被拒绝，不会写库、也不会启动扫描），再写库状态
    _acquire_scan(snap.library_id)
    try:
        run_id = begin_scan(db, library, trigger)
        started = time.perf_counter()
        try:
            stats = _scan_library_body(db, library, snap)
        except Exception as exc:  # noqa: BLE001 — 异常要落到库里，再原样抛给调用方
            logger.exception("媒体库「%s」扫描失败", snap.name)
            fail_scan(db, library, exc, run_id,
                      duration_ms=int((time.perf_counter() - started) * 1000))
            raise
        stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
        finish_scan(db, library, stats, run_id)
        return stats
    finally:
        # 无论成功、失败还是生成器被提前关闭，都释放进程内占位，否则这个库再也扫不动
        _release_scan(snap.library_id)


def _scan_library_body(db: Session, library: emby_models.Library,
                       snap: LibrarySnapshot) -> dict:
    """一轮扫描的主体（不含进程内互斥与结果落库，见 scan_library_sync）"""
    stats: dict = {
        "added": 0, "updated": 0, "removed": 0, "probed": 0, "scraped": 0,
        "repaired": 0, "removal_skipped": False, "failed_roots": [],
        "sources": [],  # 按来源记账（虚拟库没有来源，保持空列表）
    }
    clear_dir_cache()  # 新的一轮扫描不复用上一轮的目录列表
    ctx = _ScanContext(snap=snap, lib_id=library.id, stats=stats)
    seen_guids = ctx.seen_guids  # 清理阶段用它判断“文件还在不在”（与旧变量同名）
    failed_roots: list[str] = []
    pool: Optional[ThreadPoolExecutor] = None
    try:
        if getattr(library, "is_virtual", False):
            # 虚拟媒体库没有自己的文件：只按发行平台回算计数
            library.item_count = count_virtual_items(db, library)
            db.commit()
            return stats

        # 并行 IO 线程池：ffprobe / 目录列举 / TMDB 搜索都在这里跑，写库仍在当前线程按顺序进行
        pool = ThreadPoolExecutor(max_workers=SCAN_WORKERS, thread_name_prefix="scan-io")
        for label, source_files in iter_scan_sources(snap, library, db, failed_roots,
                                                     report=stats["sources"]):
            counted = _FileCounter(source_files)
            for scan_file, _pending in _attribute_source(
                    label, counted, _iter_prepared(ctx, counted, pool, db),
                    stats, failed_roots):
                    full_path = scan_file.stored_path
                    fname = scan_file.name
                    dirpath = scan_file.local_dir
                    guid = _pending.guid
                    parsed = _pending.parsed

                    # 条目（以及所属剧集/季）在批次开头已经一次查齐，这里直接用
                    item = _pending.item
                    is_new = item is None
                    if is_new:
                        item = emby_models.MediaItem(guid=guid, library_id=ctx.lib_id)
                        db.add(item)
                        _pending.item = item
                        stats["added"] += 1
                    else:
                        stats["updated"] += 1

                    # 探测 / 目录列举 / TMDB 的结果都在批次开头取回了（见 _prepare_and_prefetch）：
                    # 这里只读纯值，本循环里**不许再出现任何网络或磁盘 IO**——
                    # 从这一行往下到 db.commit() 之间，事务里只包纯 DB 写。
                    probe = _pending.probe_data
                    if probe is not None:
                        stats["probed"] += 1
                    side_poster, side_fanart, external = _pending.side_data or (None, None, [])

                    item_type = _pending.item_type  # 解析与查库在批次开头完成
                    item.item_type = item_type
                    item.name = parsed["name"]
                    item.original_title = parsed["name"]
                    item.sort_name = parsed["name"].lower()
                    item.production_year = parsed["year"]
                    item.file_path = full_path
                    item.container = scan_file.container or os.path.splitext(fname)[1].lstrip(".")
                    # 分层扫描：文件指纹落库（下次秒跳的依据）；补全状态标记。
                    # layered=本轮只做 L1 极简入库 → pending，等后台 enrich_worker；
                    # 非 layered=旧行为（本轮已做完所有补全）→ done。
                    if _pending.file_fingerprint:
                        item.file_fingerprint = _pending.file_fingerprint
                    if _pending.layered:
                        item.enrich_status = "pending"
                    elif (getattr(item, "enrich_status", None) or "pending") == "pending":
                        # 非分层路径本轮已做完补全（side/NFO/TMDB 都在上面处理了），标 done。
                        # 注意：series/season 骨架行由 episode 分支创建，它们走 L2 补全，
                        # 这里不抢标（它们的 enrich_status 由 enrich_worker 负责）。
                        if _pending.item_type in ("movie", "episode"):
                            item.enrich_status = "done"
                    platforms = detect_platforms(full_path)  # 发行平台标签（虚拟媒体库用）
                    if platforms:
                        item.platforms = ",".join(platforms)
                    if probe is not None:
                        item.size = probe.get("size", 0)
                        item.duration_ticks = probe["duration_ticks"]
                        item.bitrate = probe["bitrate"]
                        item.width = probe["width"]
                        item.height = probe["height"]
                        item.video_codec = probe["video_codec"]
                        item.audio_codec = probe["audio_codec"]
                        item.audio_languages = probe["audio_languages"]
                        item.subtitle_languages = probe["subtitle_languages"]
                        item.last_probed_at = datetime.now()
                        item.probe_status = "done"
                        item.probe_attempts = 0
                        item.probe_next_retry_at = None
                    elif _pending.probe_deferred:
                        # 两阶段 background 模式：Phase 1 不探测，交给后台 worker。
                        # 新文件（或换源：大小变了）优先探测；其余按默认优先级排队。
                        size_changed = (not is_new and bool(item.size)
                                        and bool(scan_file.size)
                                        and scan_file.size != item.size)
                        item.probe_status = "pending"
                        item.probe_priority = 100 if (is_new or size_changed) else 0
                        item.probe_attempts = 0
                        item.probe_next_retry_at = None
                        stats["probe_queued"] = stats.get("probe_queued", 0) + 1
                    elif (not _pending.probe_needed
                            and getattr(item, "probe_status", None) != "done"):
                        # 提交点判定为不需要探测 → 数据已有效，明确标 done。
                        # 作用：迁移来的 'pending' 默认值在这里被纠正，worker 不会空跑；
                        # 从 background 回滚到 inline 时，残留的 pending 也会被顺手纠正。
                        item.probe_status = "done"

                    # 本地图片 / 外挂字幕都在批次开头算好了（_side_info 在 IO 线程池里跑）：
                    # 远程挂载的目录列举因此只发生一次，且不在写事务里
                    item.poster_path = side_poster or item.poster_path
                    item.backdrop_path = side_fanart or item.backdrop_path

                    # 剧集层级：episode -> season -> series
                    # 剧集与季在**批次开头**已一次查齐（见 _prepare_and_prefetch），结果缓存
                    # 在 ctx.series_items / ctx.season_items，这里只在确实没有时才新建。
                    # 旧实现在这个循环里对每一集点查两次（先剧集、再季）：十万集就是二十万次
                    # 往返，即使每条都走 guid 唯一索引，也要多花几秒、把写库线程压在查询上。
                    # 两者在下面按需赋值；非剧集条目保持 None（后段的海报回退要求它们已绑定）
                    series = season_item = None
                    if item_type == "episode":
                        season_no, ep_no = parsed["season"], parsed["episode"]
                        series_guid = _pending.series_guid
                        series = ctx.series_items.get(series_guid)
                        if series is None:
                            series = emby_models.MediaItem(
                                guid=series_guid, library_id=library.id,
                                item_type="series", name=parsed["name"],
                                sort_name=parsed["name"].lower(),
                                production_year=parsed["year"],
                                platforms=item.platforms or "",
                                date_added=datetime.now(),
                                # 剧集/季没有文件可探测：直接 done，不进探测队列
                                probe_status="done",
                            )
                            db.add(series)
                            db.flush()
                            ctx.series_items[series_guid] = series
                        item.series_id = series.id
                        # B 方案补全：本批为隐式 series 预取的 TMDB 搜索命中先落库
                        # （补 tmdb_id/简介/海报/评分/别名；NFO 文本随后覆盖，保证 NFO 优先）
                        series_tmdb_applied = False
                        tmdb_res = ctx.series_tmdb_results.get(series_guid)
                        if tmdb_res and not series.tmdb_id:
                            series_hit, series_details = tmdb_res
                            if series_hit:
                                tmdb_client.apply(series, series_hit, "series")
                                stats["scraped"] += 1
                                series_tmdb_applied = True
                            if series_details:
                                tmdb_client.apply_details(series, series_details)
                        if (series_guid in ctx.series_tmdb_searched
                                and not series.tmdb_id and not series.last_scraped_at):
                            # 本轮干净地搜过但没命中：记一笔尝试，免得以后每轮重扫
                            # 都把这一集完整处理一遍（v2.31.0）
                            series.last_scraped_at = datetime.now()
                        series_nfo = _pending.series_nfo_data
                        if series_nfo and (not series.tmdb_id or not series.overview
                                           or series_tmdb_applied):
                            # 剧集级 NFO（tvshow.nfo）：这类 series 平时不走 TMDB，
                            # 远端有刮削就直接用；B 方案下 TMDB 只补图
                            if series_nfo.get("tmdb_id") and not (
                                series.poster_path or series.primary_image_url
                            ):
                                details = ctx.nfo_series_details.get(series_guid)
                                if details is not None:
                                    tmdb_client.apply_images(series, details)
                            nfo_lib.apply_nfo(series, series_nfo, "series")
                            stats["nfo"] = stats.get("nfo", 0) + 1

                        season_guid = _pending.season_guid
                        season_item = ctx.season_items.get(season_guid)
                        if season_item is None:
                            season_item = emby_models.MediaItem(
                                guid=season_guid, library_id=library.id,
                                item_type="season", name=f"第 {season_no} 季",
                                parent_id=series.id, series_id=series.id,
                                season_number=season_no, date_added=datetime.now(),
                                probe_status="done",  # 同上：无文件可探测
                            )
                            db.add(season_item)
                            db.flush()
                            ctx.season_items[season_guid] = season_item
                        if _pending.season_nfo_data and not season_item.overview:
                            # 季 NFO（season.nfo）：只补简介与评分
                            nfo_lib.apply_nfo(season_item, _pending.season_nfo_data, "season")
                        item.parent_id = season_item.id
                        item.season_number = season_no
                        item.episode_number = ep_no
                        ep_nfo = _pending.nfo_data
                        ep_title = (ep_nfo or {}).get("title")
                        item.name = _episode_display_name(ep_title or parsed["name"], season_no, ep_no)
                        if ep_nfo:
                            # 单集 NFO：简介与评分（标题已用于展示名）
                            nfo_lib.apply_nfo(item, ep_nfo, "episode")
                            stats["nfo"] = stats.get("nfo", 0) + 1

                    # TMDB 刮削：只刮剧集/电影这类顶层条目。
                    # 旧实现对**每一集**也发搜索请求，不但浪费配额，还会把电影元数据
                    # 写进 episode（污染 tmdb_id / 简介 / 图片），并让“只补缺”策略失效。
                    if item_type in ("series", "movie"):
                        kind = "series" if item_type == "series" else "movie"
                        # 图片丢失的条目（repair_requested_at）无论策略如何都要重取图
                        needs_repair = bool(item.repair_requested_at)
                        nfo_data = _pending.nfo_data
                        if nfo_data and nfo_data.get("tmdb_id"):
                            # —— NFO 优先（B 方案）：远端已有刮削，不调 TMDB 搜索 ——
                            # TMDB 只补图；NFO 里没给 imdb_id 时才用详情补 imdb/别名缺项，
                            # 最后 NFO 文本覆盖（用户整理的标题/简介/评分优先于 TMDB）。
                            if not nfo_data.get("imdb_id") and (
                                needs_repair or not (item.imdb_id and item.aliases)
                            ):
                                tmdb_client.apply_details(item, _pending.tmdb_details)
                            if needs_repair or not (item.poster_path or item.primary_image_url):
                                tmdb_client.apply_images(item, _pending.tmdb_details)
                            nfo_lib.apply_nfo(item, nfo_data, kind)
                            stats["nfo"] = stats.get("nfo", 0) + 1
                            if needs_repair:
                                item.repair_requested_at = None
                                stats["repaired"] = stats.get("repaired", 0) + 1
                        else:
                            if needs_repair or should_scrape(item, snap.scrape_policy):
                                # 搜索结果在批次开头就取回了（写事务里不发网络请求）
                                hit = _pending.tmdb_hit
                                if hit:
                                    tmdb_client.apply(item, hit, kind)
                                    stats["scraped"] += 1
                                if nfo_data:
                                    # 有 NFO 但无 tmdb_id：TMDB 打底，NFO 文本优先
                                    nfo_lib.apply_nfo(item, nfo_data, kind)
                                    stats["nfo"] = stats.get("nfo", 0) + 1
                            elif nfo_data and not item.overview:
                                # 策略不要求重刮、但条目缺简介且远端有 NFO：补上（幂等，不调 TMDB）
                                nfo_lib.apply_nfo(item, nfo_data, kind)
                                stats["nfo"] = stats.get("nfo", 0) + 1
                            # 已有 TMDB 命中但缺 IMDb Id / 多别名 → 用详情接口补齐
                            # （中英文、繁简、多别名搜索依赖 aliases）
                            # 详情同样是预取的：apply_details / apply_images 只把已取回的
                            # 数据落到条目上，不会在这里发请求（与 enrich / refresh_images 同口径）
                            if item.tmdb_id and (needs_repair or not (item.imdb_id and item.aliases)):
                                if not needs_repair or tmdb_client.apply_images(item, _pending.tmdb_details):
                                    tmdb_client.apply_details(item, _pending.tmdb_details)
                                if needs_repair:
                                    item.repair_requested_at = None
                                    stats["repaired"] = stats.get("repaired", 0) + 1

                    # 剧集海报回退：集 → 季 → 剧集（避免整库集图空白）
                    if item_type == "episode" and series is not None:
                        sources = [x for x in (season_item, series) if x is not None]
                        if not (item.poster_path or item.primary_image_url):
                            for src in sources:
                                if src.poster_path or src.primary_image_url:
                                    item.poster_path = src.poster_path
                                    item.primary_image_url = src.primary_image_url
                                    break
                        if not (item.backdrop_path or item.backdrop_image_url):
                            for src in sources:
                                if src.backdrop_path or src.backdrop_image_url:
                                    item.backdrop_path = src.backdrop_path
                                    item.backdrop_image_url = src.backdrop_image_url
                                    break

                    # 内封轨道：仅在真正探测过时重建（未探测则保留旧轨道）
                    if probe is not None:
                        # 新建条目此时还没落库，item.id 是 None：直接拿它写轨道的
                        # item_id 会在 flush 时撞 NOT NULL 约束，把**整库**扫描带崩
                        # （任何一批里的任何一个新条目都能触发，旧条目有 id 所以不炸）。
                        # 这里先把 item 落库拿到主键，再建轨道。
                        if item.id is None:
                            db.flush()
                        db.query(emby_models.MediaStream).filter(
                            emby_models.MediaStream.item_id == item.id,
                            emby_models.MediaStream.is_external.isnot(True),
                        ).delete(synchronize_session=False)
                        for s in probe["streams"]:
                            db.add(emby_models.MediaStream(item_id=item.id, **{
                                k: v for k, v in s.items()
                                if k in {"stream_index", "stream_type", "codec", "language",
                                         "display_title", "title", "channels", "bit_rate"}
                            }))

                    # 外挂字幕在批次开头就找好了（本地目录 / 挂载目录都在 IO 线程池里列过），
                    # 这里只剩纯 DB 写：绝大多数条目根本没有外挂字幕，也就不必为「给新字幕轨
                    # 分配 stream_index」再查一次 max()——十万条目的库就是十万次多余的 SELECT。
                    # 外挂字幕总是刷新（与视频探测无关），
                    # 并且需要合成 stream_index：客户端靠它拼
                    # /Videos/{id}/{mid}/Subtitles/{Index}/Stream.{Format}，
                    # 旧实现不写 stream_index（None），字幕地址会变成 Subtitles/None 无法拉取。
                    db.flush()
                    db.query(emby_models.MediaStream).filter(
                        emby_models.MediaStream.item_id == item.id,
                        emby_models.MediaStream.is_external.is_(True),
                    ).delete(synchronize_session=False)
                    next_index = 0
                    if external:
                        next_index = db.query(func.max(emby_models.MediaStream.stream_index)).filter(
                            emby_models.MediaStream.item_id == item.id
                        ).scalar() or 0
                    for offset, (lang, sub_path) in enumerate(external, start=1):
                        db.add(emby_models.MediaStream(
                            item_id=item.id, stream_index=next_index + offset,
                            stream_type="Subtitle",
                            codec=os.path.splitext(sub_path)[1].lstrip("."),
                            language=lang, display_title=os.path.basename(sub_path),
                            is_default=(offset == 1),
                            is_external=True, external_path=sub_path,
                        ))
                    db.commit()
    finally:
        # 扫描标志与结果由 scan_library_sync 统一写回（成功 / 部分失败 / 异常三条路都覆盖）
        try:
            commit_with_retry(db, label="扫描中间状态")
        except Exception as e:  # noqa: BLE001
            logger.warning("回写扫描中间状态失败: %s", e)
            db.rollback()

    stats["failed_roots"] = failed_roots
    if failed_roots or not (snap.paths or snap.mount_ids):
        # 来源列表不完整：禁止清理，宁肯多留几条记录，也不能误删整库
        stats["removal_skipped"] = True
        logger.warning(
            "媒体库「%s」来源列表不完整（%s），跳过清理阶段",
            snap.name, "; ".join(str(r) for r in failed_roots) or "无来源",
        )
    else:
        # 移除已不存在的文件条目（电影/集）；series/season 无实体文件，仅在没有子条目时清理
        stats["removed"] += _remove_missing_items(db, library, seen_guids)

    library.item_count = db.query(emby_models.MediaItem).filter(
        emby_models.MediaItem.library_id == library.id,
        emby_models.MediaItem.item_type.in_(["movie", "series"]),
    ).count()
    db.commit()
    return stats
