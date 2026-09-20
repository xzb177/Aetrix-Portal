"""自建 Emby 服务器：媒体库扫描 + 元数据刮削"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.emby_server import models as emby_models

logger = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m2ts", ".ts", ".m4v"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# 剧集文件名解析: S01E02 / 1x02 / 第1集
EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})\s?[\s._-]*[Ee](\d{1,3})"),
    re.compile(r"(\d{1,2})x(\d{1,3})"),
    re.compile(r"第\s*(\d{1,3})\s*[集话話]"),
]
# 电影文件名解析: Name (2019) / Name.2019.1080p
YEAR_RE = re.compile(r"[\(\.\s](\d{4})[\)\.\s]")
CLEAN_RE = re.compile(r"[\.\_\-_\[\]【】]+'")

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"
TMDB_LANG = os.getenv("TMDB_LANGUAGE", "zh-CN")


def item_guid(path: str) -> str:
    """由稳定路径生成 32 位 guid"""
    return hashlib.md5(("rb:item:" + path.lower()).encode("utf-8")).hexdigest()


def clean_name(raw: str) -> str:
    name = CLEAN_RE.sub(" ", raw)
    # 去掉质量标签
    name = re.sub(
        r"\b(2160p|1080p|720p|4k|hdr|dv|hevc|h264|x264|x265|aac|dts|flac|web-?dl|remux|bluray|blu-ray|webrip|hdtv|chs|cht|eng|chs&eng)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", name).strip(" .-_") or raw


def parse_media_filename(path: str, library_type: str) -> dict:
    """从文件路径解析 基础名称/年份/季/集"""
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    folder = os.path.basename(os.path.dirname(path))

    season = episode = None
    for pat in EP_PATTERNS:
        m = pat.search(stem) or (pat.search(folder) if library_type == "tvshows" else None)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                season, episode = int(groups[0]), int(groups[1])
            else:
                season, episode = 1, int(groups[0])
            break

    name_part = stem
    if season is not None:
        # 剧集名取集文件名中 S 标记之前的部分，或父目录名
        idx = re.search(r"[\.\s_\-]*[Ss]\d", name_part)
        candidate = name_part[: idx.start()] if idx else folder
        name_part = candidate or folder
    name_part = clean_name(name_part)

    year = None
    m = YEAR_RE.search(stem) or YEAR_RE.search(folder)
    if m:
        y = int(m.group(1))
        if 1900 <= y <= datetime.now().year + 2:
            year = y
    if year and str(year) in name_part:
        name_part = name_part.replace(str(year), "").strip(" .-_()")

    return {"name": name_part or stem, "year": year, "season": season, "episode": episode}


def _ffprobe(path: str) -> Optional[dict]:
    """ffprobe 提取媒体信息（无 ffprobe 时优雅降级）"""
    if not shutil_which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", path,
            ],
            capture_output=True, text=True, timeout=60,
        )
        import json

        return json.loads(out.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        logger.warning("ffprobe 失败 %s: %s", path, e)
        return None


def shutil_which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


def probe_metadata(path: str) -> dict:
    """返回 duration_ticks/bitrate/尺寸/编码/轨道信息"""
    info: dict = {
        "duration_ticks": 0, "bitrate": 0, "width": 0, "height": 0,
        "video_codec": None, "audio_codec": None,
        "audio_languages": "", "subtitle_languages": "", "streams": [],
    }
    data = _ffprobe(path)
    if not data:
        try:
            info["size"] = os.path.getsize(path)
        except OSError:
            pass
        return info

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0)
    info["duration_ticks"] = int(duration * 10_000_000)
    info["bitrate"] = int(fmt.get("bit_rate") or 0)
    try:
        info["size"] = os.path.getsize(path)
    except OSError:
        info["size"] = int(fmt.get("size") or 0)

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
    """轻量 TMDB 客户端（未配置 key 时静默跳过）"""

    def __init__(self) -> None:
        self.api_key = os.getenv("TMDB_API_KEY", "")
        self.session = None
        if self.api_key:
            import httpx

            self.session = httpx.Client(timeout=8)

    def search(self, name: str, year: Optional[int], kind: str) -> Optional[dict]:
        if not self.session:
            return None
        try:
            endpoint = "tv" if kind == "series" else "movie"
            params = {"api_key": self.api_key, "language": TMDB_LANG, "query": name}
            if year:
                if endpoint == "tv":
                    params["first_air_date_year"] = year
                else:
                    params["year"] = year
            r = self.session.get(f"{TMDB_API}/search/{endpoint}", params=params)
            results = r.json().get("results") or []
            return results[0] if results else None
        except Exception as e:  # noqa: BLE001
            logger.warning("TMDB 搜索失败 %s: %s", name, e)
            return None

    def apply(self, item: emby_models.MediaItem, hit: dict, kind: str) -> None:
        item.tmdb_id = str(hit.get("id"))
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


def find_external_subtitles(file_path: str) -> list[tuple[str, str]]:
    """返回 [(lang, path)] 外挂字幕"""
    d = os.path.dirname(file_path)
    stem = os.path.splitext(os.path.basename(file_path))[0]
    found: list[tuple[str, str]] = []
    try:
        for f in os.listdir(d):
            base, ext = os.path.splitext(f)
            if ext.lower() not in SUBTITLE_EXTS:
                continue
            if base == stem or base.startswith(stem + "."):
                lang = "chi" if ("chi" in base.lower() or "chs" in base.lower() or "zh" in base.lower()) else "eng"
                found.append((lang, os.path.join(d, f)))
    except OSError:
        pass
    return found


def scan_library_sync(db: Session, library: emby_models.Library) -> dict:
    """扫描单个媒体库（同步实现，可在后台线程运行）"""
    stats = {"added": 0, "updated": 0, "removed": 0}
    library.is_scanning = True
    db.commit()

    seen_guids: set[str] = set()
    try:
        roots = [p.strip() for p in (library.paths or "").split(",") if p.strip()]
        for root in roots:
            for dirpath, _dirnames, filenames in os.walk(root):
                for fname in filenames:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in VIDEO_EXTS:
                        continue
                    full_path = os.path.join(dirpath, fname)
                    guid = item_guid(full_path)
                    seen_guids.add(guid)
                    parsed = parse_media_filename(full_path, library.collection_type)
                    probe = probe_metadata(full_path)

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

                    item_type = (
                        "episode"
                        if parsed["season"] is not None
                        else ("series" if library.collection_type == "tvshows" else "movie")
                    )
                    item.item_type = item_type
                    item.name = parsed["name"]
                    item.original_title = parsed["name"]
                    item.sort_name = parsed["name"].lower()
                    item.production_year = parsed["year"]
                    item.file_path = full_path
                    item.container = ext.lstrip(".")
                    item.size = probe.get("size", 0)
                    item.duration_ticks = probe["duration_ticks"]
                    item.bitrate = probe["bitrate"]
                    item.width = probe["width"]
                    item.height = probe["height"]
                    item.video_codec = probe["video_codec"]
                    item.audio_codec = probe["audio_codec"]
                    item.audio_languages = probe["audio_languages"]
                    item.subtitle_languages = probe["subtitle_languages"]

                    # 本地图片
                    poster, fanart = find_local_images(dirpath, os.path.splitext(fname)[0])
                    item.poster_path = poster or item.poster_path
                    item.backdrop_path = fanart or item.backdrop_path

                    # TMDB 刮削（仅顶层条目）
                    if not item.tmdb_id:
                        kind = "series" if item_type == "series" else "movie"
                        hit = tmdb_client.search(parsed["name"], parsed["year"], kind)
                        if hit:
                            tmdb_client.apply(item, hit, kind)

                    # 剧集层级：episode -> season -> series
                    if item_type == "episode":
                        season_no, ep_no = parsed["season"], parsed["episode"]
                        series_guid = item_guid(os.path.dirname(dirpath) or dirpath)
                        series = db.query(emby_models.MediaItem).filter(
                            emby_models.MediaItem.guid == series_guid
                        ).first()
                        if not series:
                            series = emby_models.MediaItem(
                                guid=series_guid, library_id=library.id,
                                item_type="series", name=parsed["name"],
                                sort_name=parsed["name"].lower(),
                                production_year=parsed["year"],
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

                    # 轨道
                    db.query(emby_models.MediaStream).filter(
                        emby_models.MediaStream.item_id == item.id
                    ).delete()
                    for s in probe["streams"]:
                        db.add(emby_models.MediaStream(item_id=item.id, **{
                            k: v for k, v in s.items()
                            if k in {"stream_index", "stream_type", "codec", "language",
                                     "display_title", "title", "channels", "bit_rate"}
                        }))
                    # 外挂字幕需要合成 stream_index：客户端靠它拼
                    # /Videos/{id}/{mid}/Subtitles/{Index}/Stream.{Format}，
                    # 旧实现不写 stream_index（None），字幕地址会变成 Subtitles/None 无法拉取。
                    next_index = max(
                        [s.get("stream_index") or 0 for s in probe["streams"]] + [0]
                    )
                    for offset, (lang, sub_path) in enumerate(
                        find_external_subtitles(full_path), start=1
                    ):
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

    # 移除已不存在的文件条目（电影/集）；series/season 无实体文件，仅在没有子条目时清理
    existing = db.query(emby_models.MediaItem).filter(
        emby_models.MediaItem.library_id == library.id
    ).all()
    removed_series: list[int] = []
    for it in existing:
        if it.guid in seen_guids:
            continue
        if it.item_type in ("movie", "episode"):
            if it.file_path and os.path.exists(it.file_path):
                continue  # 其他根目录的文件
            db.delete(it)
            stats["removed"] += 1
        elif it.item_type == "season":
            has_children = db.query(emby_models.MediaItem).filter(
                emby_models.MediaItem.parent_id == it.id
            ).count()
            if not has_children:
                db.delete(it)
                stats["removed"] += 1
                removed_series.append(it.series_id) if it.series_id else None
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
