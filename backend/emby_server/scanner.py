"""自建 Emby 服务器：媒体库扫描 + 元数据刮削"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.emby_server import models as emby_models
from backend.emby_server import mounts as mount_lib

logger = logging.getLogger(__name__)

# `.strm` 不是视频文件，而是「内容为播放直链的文本文件」；是否把 strm 当媒体由调用方决定
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m2ts", ".ts", ".m4v", ".strm"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
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

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"
TMDB_LANG = os.getenv("TMDB_LANGUAGE", "zh-CN")


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


class TmdbClient:
    """轻量 TMDB 客户端（未配置 key 时静默跳过）

    支持多密钥轮询：`TMDB_API_KEYS=key1,key2,key3`（或 `TMDB_API_KEY` 单键）。
    单个密钥超出配额（429）或报 401 时自动轮到下一个，整库刮削不会因为一个 key 限额就停滞。
    """

    def __init__(self) -> None:
        raw = os.getenv("TMDB_API_KEYS", "") or os.getenv("TMDB_API_KEY", "")
        self.api_keys = [k.strip() for k in raw.split(",") if k.strip()]
        self.api_key = self.api_keys[0] if self.api_keys else ""
        self._key_index = 0
        self.session = None
        if self.api_key:
            import httpx

            self.session = httpx.Client(timeout=8)

    def _rotate(self) -> bool:
        """轮到下一个密钥，全部用过则返回 False"""
        if len(self.api_keys) <= 1:
            return False
        self._key_index = (self._key_index + 1) % len(self.api_keys)
        self.api_key = self.api_keys[self._key_index]
        logger.warning("TMDB 密钥轮询到第 %s 个", self._key_index + 1)
        return True

    def _get(self, path: str, params: dict) -> Optional[dict]:
        """带密钥轮询的 GET：配额类错误自动换 key 重试"""
        if not self.session:
            return None
        tried = 0
        while tried <= len(self.api_keys) or tried == 0:
            try:
                r = self.session.get(f"{TMDB_API}{path}", params={**params, "api_key": self.api_key})
            except Exception as e:  # noqa: BLE001 — 网络异常不应中断整次扫描
                logger.warning("TMDB 请求失败 %s: %s", path, e)
                return None
            if r.status_code in (401, 429):
                if self._rotate():
                    tried += 1
                    continue
                logger.warning("TMDB 全部密钥不可用（HTTP %s）", r.status_code)
                return None
            if r.status_code >= 400:
                logger.warning("TMDB 响应异常 %s: HTTP %s", path, r.status_code)
                return None
            try:
                return r.json()
            except Exception:  # noqa: BLE001
                return None
        return None

    @property
    def configured(self) -> bool:
        return bool(self.api_keys)

    def search(self, name: str, year: Optional[int], kind: str) -> Optional[dict]:
        if not self.session:
            return None
        endpoint = "tv" if kind == "series" else "movie"
        params: dict = {"language": TMDB_LANG, "query": name}
        if year:
            if endpoint == "tv":
                params["first_air_date_year"] = year
            else:
                params["year"] = year
        data = self._get(f"/search/{endpoint}", params)
        results = (data or {}).get("results") or []
        return results[0] if results else None

    def details(self, tmdb_id: str, kind: str) -> Optional[dict]:
        """详情（补 IMDb Id 与多别名）——只在条目缺这两项时调用"""
        endpoint = "tv" if kind == "series" else "movie"
        return self._get(f"/{endpoint}/{tmdb_id}", {"language": TMDB_LANG,
                                                     "append_to_response": "alternative_titles,external_ids"})

    def enrich(self, item: emby_models.MediaItem, kind: str) -> None:
        """补齐 imdb_id 与 aliases（中英文/繁简多别名搜索的基础）"""
        if not item.tmdb_id or (item.imdb_id and item.aliases):
            return
        data = self.details(str(item.tmdb_id), kind)
        if not data:
            return
        imdb = (data.get("external_ids") or {}).get("imdb_id") or data.get("imdb_id")
        if imdb:
            item.imdb_id = imdb
        alt = (data.get("alternative_titles") or {})
        titles = [t.get("title") for t in (alt.get("titles") or [])]
        titles += [t.get("title") for t in (alt.get("results") or [])]
        names = [n for n in ([data.get("name"), data.get("original_name"),
                              data.get("title"), data.get("original_title")] + titles) if n]
        if names:
            seen: list[str] = []
            for n in names:
                n = str(n).strip()
                if n and n not in seen:
                    seen.append(n)
            item.aliases = ",".join(seen[:12])

    def refresh_images(self, item: emby_models.MediaItem, kind: str) -> bool:
        """重新取图——数据库里有图片记录但本地文件已丢失时用

        （客户端取图 404 会把条目排进修复队列，下一轮扫描到这里把图换成 TMDB 远程图）
        """
        if not item.tmdb_id:
            return False
        data = self.details(str(item.tmdb_id), kind)
        if not data:
            return False
        poster = data.get("poster_path")
        backdrop = data.get("backdrop_path")
        if poster:
            item.primary_image_url = f"{TMDB_IMAGE}/w500{poster}"
        if backdrop:
            item.backdrop_image_url = f"{TMDB_IMAGE}/w1280{backdrop}"
        return bool(poster or backdrop)

    def apply(self, item: emby_models.MediaItem, hit: dict, kind: str) -> None:
        item.tmdb_id = str(hit.get("id"))
        item.last_scraped_at = datetime.now()
        item.overview = hit.get("overview") or item.overview
        rating = hit.get("vote_average")
        if rating:
            item.community_rating = round(float(rating), 1)
        poster = hit.get("poster_path")
        backdrop = hit.get("backdrop_path")
        if poster:
            item.primary_image_url = f"{TMDB_IMAGE}/w500{poster}"
        if backdrop:
            item.backdrop_image_url = f"{TMDB_IMAGE}/w1280{backdrop}"
        if kind == "series" and hit.get("name"):
            item.name = hit.get("name")
        elif hit.get("title"):
            item.name = hit.get("title")
        # 搜索命中里就能拿到的多别名（中英文/原名）：先落库，详情接口再补全
        hit_aliases = [hit.get("name"), hit.get("title"),
                       hit.get("original_name"), hit.get("original_title")]
        existing = [a for a in (item.aliases or "").split(",") if a]
        merged = existing + [a.strip() for a in hit_aliases if a and a.strip() not in existing]
        if merged:
            item.aliases = ",".join(dict.fromkeys(merged))[:2000]
        genre_ids = hit.get("genre_ids") or []
        if genre_ids:
            mapping = {
                28: "动作", 12: "冒险", 16: "动画", 35: "喜剧", 80: "犯罪",
                99: "纪录片", 18: "剧情", 10751: "家庭", 14: "奇幻", 36: "历史",
                27: "恐怖", 10402: "音乐", 9648: "悬疑", 10749: "爱情",
                878: "科幻", 10770: "电视电影", 53: "惊悚", 10752: "战争", 37: "西部",
            }
            item.genres = ",".join(mapping.get(g, str(g)) for g in genre_ids[:4])


tmdb_client = TmdbClient()


def find_local_images(dir_path: str, base_name: str) -> tuple[Optional[str], Optional[str]]:
    """查找同目录的 poster/fanart 本地图片"""
    poster = fanart = None
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return None, None
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


# 语言标签 → Emby 三字码（客户端按这个选字幕轨）
_SUB_LANG_TAGS: tuple[tuple[str, str], ...] = (
    ("zh-cn", "chi"), ("zh-tw", "chi"), ("zh-hans", "chi"), ("zh-hant", "chi"),
    ("chs", "chi"), ("cht", "chi"), ("chi", "chi"), ("zho", "chi"), ("zh", "chi"),
    ("sc", "chi"), ("tc", "chi"), ("简", "chi"), ("繁", "chi"),
    ("中英", "chi"), ("双语", "chi"), ("中字", "chi"), ("中文", "chi"),
    ("eng", "eng"), ("english", "eng"), ("en", "eng"), ("英文", "eng"),
    ("jpn", "jpn"), ("japanese", "jpn"), ("jp", "jpn"), ("日", "jpn"),
    ("kor", "kor"), ("ko", "kor"), ("韩", "kor"),
)
# 发布标签：比较“是不是同一条媒体”时要先去掉
_RELEASE_TAG_RE = re.compile(
    r"\b(2160p|1080p|720p|480p|4k|uhd|hdr10\+?|hdr|dolby|dv|web-?dl|webrip|web|bluray|"
    r"blu-ray|bdrip|brrip|remux|hdtv|dvdrip|x264|x265|h264|h265|hevc|avc|aac|ac3|eac3|"
    r"dts|dts-hd|flac|truehd|atmos|repack|proper|multi|internal|complete|10bit|8bit)\b",
    re.IGNORECASE,
)
_EP_MARK_RE = re.compile(
    r"([sS]\d{1,2}\s?[\s._-]*[eE]\d{1,3}|\d{1,2}x\d{1,3}|第\s*\d{1,3}\s*[集话話]|\b[eE][pP]\.?\s?\d{1,3}(?!\d))"
)


def _subtitle_core(text: str) -> str:
    """字幕/视频名的“核心”形式：去发布标签与分隔符，用于同名判定"""
    core = _RELEASE_TAG_RE.sub(" ", text or "")
    core = re.sub(r"[\.\-_\[\]()【】]+", " ", core)
    return re.sub(r"\s+", " ", core).strip().lower()


_RESOLUTION_RE = re.compile(
    r"(?<![A-Za-z0-9])(2160p|1080p|720p|480p|4k|uhd)(?![A-Za-z0-9])", re.IGNORECASE
)


def _resolution_of(text: str) -> str:
    """分辨率归一（4k/uhd 都算 2160p）——用于区分同一部片子的多个版本"""
    m = _RESOLUTION_RE.search(text or "")
    if not m:
        return ""
    value = m.group(1).lower()
    return "2160p" if value in ("4k", "uhd") else value


def _episode_key(text: str) -> str:
    m = _EP_MARK_RE.search(text or "")
    if not m:
        return ""
    return re.sub(r"[\s._-]+", "", m.group(1)).lower()


def subtitle_language(name: str) -> str:
    """从字幕文件名猜语言（返回 Emby 三字码）"""
    raw = name or ""
    low = raw.lower()
    for tag, lang in _SUB_LANG_TAGS:
        if not tag:
            continue
        if tag.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(tag)}(?![a-z0-9])", low):
                return lang
        elif tag in raw:
            return lang
    return "chi" if re.search(r"[\u4e00-\u9fff]", raw) else "eng"


def match_subtitle_names(base_name: str, names) -> list[str]:
    """从同目录文件名里挑出与 ``base_name`` 匹配的外挂字幕文件名

    覆盖实际会碰到的各种命名（旧实现只认「与视频完全同名」或「同名 + 点后缀」）：

    - 标准同名：`Show.S01E01.mkv` + `Show.S01E01.chi.srt`
    - 较短字幕名：`Show.S01E01.1080p.WEB-DL.mkv` + `Show.S01E01.ass`
    - 发行组差异：视频 `x265-GROUP`，字幕只写 `Show.S01E01.chs.ass`
    - 多版本媒体：`Show.S01E01.v2.mkv` / `Movie.2024.UHD.mkv` 各带自己的字幕
    - rclone / GD sidecar：`Show.S01E01.mkv.zh.srt`（字幕名以视频全名加点开头）

    不会把同目录里**别的集**的字幕认给本集（旧实现只比前缀）。
    单独抽出来是为了让**远程挂载**（115 / WebDAV / AList）也能用同一套判定：
    远程只有目录列表里的一串文件名，没有本机路径。
    """
    base_name = os.path.basename(base_name)
    stem = os.path.splitext(base_name)[0]
    video_core = _subtitle_core(stem)
    video_res = _resolution_of(stem)
    ep_key = _episode_key(stem)
    ep_head = _subtitle_core(stem[: _EP_MARK_RE.search(stem).start()]) if ep_key else ""

    def _same_media(name: str) -> bool:
        if name == base_name or name.startswith(base_name + "."):
            return True  # rclone/GD sidecar：字幕名 = 视频全名 + 语言后缀
        # 多版本：字幕自己标了分辨率时，必须与视频一致
        # （Movie.2024.2160p.srt 不应被认给 Movie.2024.1080p.mkv）
        sub_res = _resolution_of(name)
        if sub_res and video_res and sub_res != video_res:
            return False
        sub_core = _subtitle_core(name)
        if not sub_core or not video_core:
            return False
        if sub_core == video_core:
            return True
        # 去掉发布标签后互为前缀（字幕名更短、或多一个语言/版本后缀）
        short, long_ = sorted((sub_core, video_core), key=len)
        if short and long_.startswith(short):
            return True
        # 同一集号 + 同一剧名核心：Show.S01E01.ass ↔ Show.S01E01.1080p.WEB-DL.mkv
        if ep_key and _episode_key(name) == ep_key:
            mark = _EP_MARK_RE.search(name)
            head = _subtitle_core(name[: mark.start()]) if mark else ""
            if not ep_head or not head or head.startswith(ep_head) or ep_head.startswith(head):
                return True
        return False

    found: list[str] = []
    for f in names:
        base, ext = os.path.splitext(f)
        if ext.lower() not in SUBTITLE_EXTS:
            continue
        probe = base
        for _ in range(2):  # 去掉 sidecar 命名里残留的视频扩展名
            probe = re.sub(r"\.(mkv|mp4|avi|mov|ts|m2ts|m4v|wmv|flv|webm)$", "", probe, flags=re.IGNORECASE)
        if _same_media(probe):
            found.append(f)
    return found


def find_external_subtitles(file_path: str) -> list[tuple[str, str]]:
    """本机文件的外挂字幕：返回 [(lang, 绝对路径)]"""
    d = os.path.dirname(file_path)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return [
        (subtitle_language(os.path.splitext(f)[0]), os.path.join(d, f))
        for f in match_subtitle_names(os.path.basename(file_path), names)
    ]


def find_external_subtitles_remote(base_name: str, entries, mount_id: int,
                                   dir_rel: str) -> list[tuple[str, str]]:
    """远程挂载的外挂字幕：返回 [(lang, mount://<id>/<相对路径>)]"""
    names = [e.name for e in entries if not e.is_dir]
    base_dir = "/" + (dir_rel or "/").strip("/")
    return [
        (
            subtitle_language(os.path.splitext(f)[0]),
            mount_lib.mount_path(mount_id, f"{base_dir.rstrip('/')}/{f}"),
        )
        for f in match_subtitle_names(base_name, names)
    ]


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
        onerror=lambda e: failed_roots.append(getattr(e, "filename", "") or str(e)),
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
            yield ScanFile(
                stored_path=full_path, name=fname, local_dir=dirpath,
                size=_safe_size(full_path), container=container, local_target=target,
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
    for mount_file in provider.walk_media():
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
                      failed_roots: list) -> Iterator[Iterator[ScanFile]]:
    """遍历一个媒体库的全部扫描来源（本机路径 + 挂载），每个来源一个迭代器

    来源不可用（目录不存在 / 挂载停用 / 账号失效 / 网络不通）时**不会**抛出去中断整个扫描，
    而是记进 ``failed_roots``：扫描器据此跳过清理阶段，避免把「读不到」当成「文件已删除」。
    """
    sources, failed = mount_lib.library_sources(library, db)
    for item in failed:
        logger.warning("媒体库「%s」来源不可用：%s（%s）", snap.name, item["label"], item["reason"])
        failed_roots.append(f"{item['label']}: {item['reason']}")

    for src in sources:
        if src.kind == "local":
            yield _local_dir_files(src.path, failed_roots)
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

        yield _guarded()


# 同一媒体库同时只允许一个扫描任务（进程内互斥；EM/EA 都是单进程部署）
_ACTIVE_SCANS: dict[int, datetime] = {}
_ACTIVE_SCANS_LOCK = threading.Lock()


class ScanInProgress(RuntimeError):
    """同一媒体库已有扫描任务在运行"""


def is_scan_active(library_id: int) -> bool:
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


def scan_library_sync(db: Session, library: emby_models.Library,
                      snapshot: Optional[LibrarySnapshot] = None) -> dict:
    """扫描单个媒体库（同步实现，可在后台线程运行）

    约定：

    - **配置快照**：整个任务只认 `snapshot`（默认在入口处拍一张），见 LibrarySnapshot。
    - **重复任务拒绝**：同一媒体库同时只允许一个任务，重复触发抛 `ScanInProgress`。
    - **目录不完整禁止清理**：任何根目录不可读或遍历报错时跳过清理阶段，
      避免“读取失败 → 当成文件已删除 → 误删整库记录”。
    - **探测/刮削按需**：已探测过的文件不再重复 ffprobe（除非文件大小变了），
      刮削按媒体库策略（missing_only / 3m / 6m / 1y / all）。
    - **外挂字幕与视频探测解耦**：换字幕文件不需要重探视频。
    """
    snap = snapshot or LibrarySnapshot.of(library)
    _acquire_scan(snap.library_id)
    stats: dict = {
        "added": 0, "updated": 0, "removed": 0, "probed": 0, "scraped": 0,
        "repaired": 0, "removal_skipped": False, "failed_roots": [],
    }
    library.is_scanning = True
    db.commit()

    seen_guids: set[str] = set()
    failed_roots: list[str] = []
    try:
        if getattr(library, "is_virtual", False):
            # 虚拟媒体库没有自己的文件：只按发行平台回算计数
            library.item_count = count_virtual_items(db, library)
            db.commit()
            return stats

        for source_files in iter_scan_sources(snap, library, db, failed_roots):
            for scan_file in source_files:
                    full_path = scan_file.stored_path
                    fname = scan_file.name
                    dirpath = scan_file.local_dir
                    guid = item_guid(full_path)
                    seen_guids.add(guid)
                    parsed = parse_media_filename(full_path, snap.collection_type)

                    item = db.query(emby_models.MediaItem).filter(
                        emby_models.MediaItem.guid == guid
                    ).first()
                    is_new = item is None
                    if is_new:
                        item = emby_models.MediaItem(guid=guid, library_id=library.id)
                        db.add(item)
                        stats["added"] += 1
                    else:
                        stats["updated"] += 1

                    # 文件信息已获取过就不再重复探测（ffprobe 是扫描里最贵的一步）；
                    # 远程挂载的探测输入是解析出来的直链（带鉴权头，只在本机使用）。
                    probe = (
                        probe_metadata(*scan_file.probe_input(), size=scan_file.size)
                        if (is_new or needs_probe(item, full_path, scan_file.size))
                        else None
                    )
                    if probe is not None:
                        stats["probed"] += 1

                    item_type = (
                        "episode"
                        if parsed["season"] is not None
                        else ("series" if snap.collection_type == "tvshows" else "movie")
                    )
                    item.item_type = item_type
                    item.name = parsed["name"]
                    item.original_title = parsed["name"]
                    item.sort_name = parsed["name"].lower()
                    item.production_year = parsed["year"]
                    item.file_path = full_path
                    item.container = scan_file.container or os.path.splitext(fname)[1].lstrip(".")
                    platforms = detect_platforms(full_path)
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

                    # 本地图片（远程挂载没有本机目录，交给 TMDB 远程图）
                    poster = fanart = None
                    if dirpath:
                        poster, fanart = find_local_images(dirpath, os.path.splitext(fname)[0])
                    item.poster_path = poster or item.poster_path
                    item.backdrop_path = fanart or item.backdrop_path

                    # 剧集层级：episode -> season -> series
                    series = season_item = None
                    if item_type == "episode":
                        season_no, ep_no = parsed["season"], parsed["episode"]
                        series_dir = os.path.dirname(dirpath.rstrip("/")) if dirpath else ""
                        series_guid = item_guid(series_dir or (os.path.dirname(full_path) or full_path))
                        series = db.query(emby_models.MediaItem).filter(
                            emby_models.MediaItem.guid == series_guid
                        ).first()
                        if not series:
                            series = emby_models.MediaItem(
                                guid=series_guid, library_id=library.id,
                                item_type="series", name=parsed["name"],
                                sort_name=parsed["name"].lower(),
                                production_year=parsed["year"],
                                platforms=item.platforms or "",
                                date_added=datetime.now(),
                            )
                            db.add(series)
                            db.flush()
                        item.series_id = series.id

                        season_guid = item_guid(f"{series_guid}:S{season_no:02d}")
                        season_item = db.query(emby_models.MediaItem).filter(
                            emby_models.MediaItem.guid == season_guid
                        ).first()
                        if not season_item:
                            season_item = emby_models.MediaItem(
                                guid=season_guid, library_id=library.id,
                                item_type="season", name=f"第 {season_no} 季",
                                parent_id=series.id, series_id=series.id,
                                season_number=season_no, date_added=datetime.now(),
                            )
                            db.add(season_item)
                            db.flush()
                        item.parent_id = season_item.id
                        item.season_number = season_no
                        item.episode_number = ep_no
                        item.name = f'{parsed["name"]} S{season_no:02d}E{ep_no:02d}'

                    # TMDB 刮削：只刮剧集/电影这类顶层条目。
                    # 旧实现对**每一集**也发搜索请求，不但浪费配额，还会把电影元数据
                    # 写进 episode（污染 tmdb_id / 简介 / 图片），并让“只补缺”策略失效。
                    if item_type in ("series", "movie"):
                        kind = "series" if item_type == "series" else "movie"
                        # 图片丢失的条目（repair_requested_at）无论策略如何都要重取图
                        needs_repair = bool(item.repair_requested_at)
                        if needs_repair or should_scrape(item, snap.scrape_policy):
                            hit = tmdb_client.search(parsed["name"], parsed["year"], kind)
                            if hit:
                                tmdb_client.apply(item, hit, kind)
                                stats["scraped"] += 1
                        # 已有 TMDB 命中但缺 IMDb Id / 多别名 → 用详情接口补齐
                        # （中英文、繁简、多别名搜索依赖 aliases）
                        if item.tmdb_id and (needs_repair or not (item.imdb_id and item.aliases)):
                            if not needs_repair or tmdb_client.refresh_images(item, kind):
                                tmdb_client.enrich(item, kind)
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

                    # 外挂字幕总是刷新（与视频探测无关），
                    # 并且需要合成 stream_index：客户端靠它拼
                    # /Videos/{id}/{mid}/Subtitles/{Index}/Stream.{Format}，
                    # 旧实现不写 stream_index（None），字幕地址会变成 Subtitles/None 无法拉取。
                    db.flush()
                    db.query(emby_models.MediaStream).filter(
                        emby_models.MediaStream.item_id == item.id,
                        emby_models.MediaStream.is_external.is_(True),
                    ).delete(synchronize_session=False)
                    next_index = db.query(func.max(emby_models.MediaStream.stream_index)).filter(
                        emby_models.MediaStream.item_id == item.id
                    ).scalar() or 0
                    if scan_file.mount_id is not None and dirpath is None:
                        try:
                            siblings = scan_file.provider.list_dir(scan_file.dir_rel)
                        except mount_lib.MountError as exc:
                            logger.warning("读取挂载目录失败，跳过外挂字幕：%s（%s）", scan_file.dir_rel, exc)
                            siblings = []
                        external = find_external_subtitles_remote(
                            fname, siblings, scan_file.mount_id, scan_file.dir_rel,
                        )
                    else:
                        external = find_external_subtitles(full_path)
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
        library.is_scanning = False
        library.last_scan_at = datetime.now()
        _release_scan(snap.library_id)
        try:
            db.commit()  # 扫描标志必须落库，否则崩溃后 is_scanning 永久为真
        except Exception as e:  # noqa: BLE001
            logger.warning("回写扫描状态失败: %s", e)
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
        existing = db.query(emby_models.MediaItem).filter(
            emby_models.MediaItem.library_id == library.id
        ).all()
        for it in existing:
            if it.guid in seen_guids:
                continue
            if it.item_type in ("movie", "episode"):
                # 本机路径与远程挂载都查：命中的说明是别的来源的文件，保留；
                # 查不到（挂载已删/已停用）才当删除处理。
                if it.file_path and mount_lib.media_exists(it.file_path, db, library):
                    continue  # 其他来源（路径 / 挂载）的文件
                db.delete(it)
                stats["removed"] += 1
            elif it.item_type == "season":
                has_children = db.query(emby_models.MediaItem).filter(
                    emby_models.MediaItem.parent_id == it.id
                ).count()
                if not has_children:
                    db.delete(it)
                    stats["removed"] += 1
            elif it.item_type == "series":
                has_children = db.query(emby_models.MediaItem).filter(
                    emby_models.MediaItem.series_id == it.id
                ).count()
                if not has_children:
                    db.delete(it)
                    stats["removed"] += 1
        db.commit()

    library.item_count = db.query(emby_models.MediaItem).filter(
        emby_models.MediaItem.library_id == library.id,
        emby_models.MediaItem.item_type.in_(["movie", "series"]),
    ).count()
    db.commit()
    return stats
