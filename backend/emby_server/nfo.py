"""Kodi / Emby 风格 NFO 解析与落库。

远端网盘里如果已经有刮削（``tvshow.nfo`` / ``movie.nfo`` / 与视频同名的 ``.nfo``），
扫描时优先使用它，不再调 TMDB 搜索（B 方案：TMDB 只用来补海报/背景图）。
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

# 支持的 NFO 根标签：电影 / 剧集 / 单集 / 季
_NFO_ROOTS = {"movie", "tvshow", "episodedetails", "season"}


def _text(root: ET.Element, tag: str) -> str:
    child = root.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _texts(root: ET.Element, tag: str) -> List[str]:
    out: List[str] = []
    for child in root.findall(tag):
        if child.text and child.text.strip():
            out.append(child.text.strip())
    return out


def _pick_rating(root: ET.Element) -> Optional[float]:
    """Kodi 两种评分写法：

    - ``<ratings><rating name="tmdb" default="true"><value>8</value></rating></ratings>``
    - 直写 ``<rating>8</rating>``
    """
    ratings = root.find("ratings")
    if ratings is not None:
        fallback: Optional[float] = None
        for r in ratings.findall("rating"):
            name = (r.get("name") or "").lower()
            default = (r.get("default") or "").lower() == "true"
            try:
                value = float(_text(r, "value"))
            except (TypeError, ValueError):
                continue
            if name == "tmdb" or default:
                return round(value, 1)
            if fallback is None:
                fallback = value
        if fallback is not None:
            return round(fallback, 1)
    try:
        return round(float(_text(root, "rating")), 1)
    except (TypeError, ValueError):
        return None


def _pick_id(root: ET.Element, id_type: str) -> str:
    """tmdb / imdb / tvdb 三种写法：``<tmdbid>`` / ``<imdb_id>`` / ``<uniqueid type="tmdb">``"""
    tag_map = {
        "tmdb": ("tmdbid",),
        "imdb": ("imdb_id", "imdbid"),
        "tvdb": ("tvdbid",),
    }
    for tag in tag_map.get(id_type, ()):
        value = _text(root, tag)
        if value:
            return value
    for u in root.findall("uniqueid"):
        if (u.get("type") or "").lower() == id_type and u.text and u.text.strip():
            return u.text.strip()
    return ""


def _pick_year(root: ET.Element) -> Optional[int]:
    for tag in ("year", "premiered", "aired", "releasedate"):
        m = re.search(r"(\d{4})", _text(root, tag))
        if m:
            year = int(m.group(1))
            if 1900 <= year <= datetime.now().year + 2:
                return year
    return None


def parse_nfo(text: str) -> Optional[Dict[str, Any]]:
    """解析 NFO 文本 → 元数据 dict；解析失败或没有可用字段返回 None。"""
    if not text or not isinstance(text, str):
        return None
    text = text.lstrip("﻿").strip()
    if not text.startswith("<"):
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    kind = (root.tag or "").lower()
    if kind not in _NFO_ROOTS:
        return None
    data: Dict[str, Any] = {
        "nfo_kind": kind,
        "title": _text(root, "title"),
        "originaltitle": _text(root, "originaltitle"),
        # 简介：plot 为空时退回 outline（部分刮削器只写 outline）
        "plot": _text(root, "plot") or _text(root, "outline"),
        "tagline": _text(root, "tagline"),
        "rating": _pick_rating(root),
        "year": _pick_year(root),
        "genres": _texts(root, "genre"),
        "studios": _texts(root, "studio"),
        "mpaa": _text(root, "mpaa"),
        "tmdb_id": _pick_id(root, "tmdb"),
        "imdb_id": _pick_id(root, "imdb"),
        "tvdb_id": _pick_id(root, "tvdb"),
    }
    if kind == "episodedetails":
        data["season"] = _text(root, "season")
        data["episode"] = _text(root, "episode")
    if not (data["title"] or data["plot"] or data["tmdb_id"] or data["imdb_id"]):
        return None
    return data


def _merge_aliases(item: Any, names: List[Optional[str]]) -> None:
    existing = [a for a in (item.aliases or "").split(",") if a]
    merged = existing + [n.strip() for n in names if n and n.strip() not in existing]
    if merged:
        item.aliases = ",".join(dict.fromkeys(merged))[:2000]


def apply_nfo(item: Any, data: Dict[str, Any], kind: str) -> None:
    """把 NFO 元数据落到 MediaItem 上（用户整理的文本优先于 TMDB）。

    kind: movie / series / episode / season。episode / season 只写简介与评分，
    名称由调用方按展示格式处理；只有 movie / series 参与 TMDB 刮削策略，
    也只有它们写 ``last_scraped_at``。
    """
    if kind in ("movie", "series"):
        if data.get("title"):
            item.name = data["title"]
            item.sort_name = data["title"].lower()
        if data.get("originaltitle"):
            item.original_title = data["originaltitle"]
        _merge_aliases(item, [data.get("title"), data.get("originaltitle")])
        if data.get("year") and not item.production_year:
            item.production_year = data["year"]
        if data.get("mpaa"):
            item.official_rating = data["mpaa"]
        if data.get("genres"):
            item.genres = ",".join(data["genres"])
        if data.get("studios"):
            item.studios = ",".join(data["studios"])
        if data.get("tmdb_id"):
            item.tmdb_id = str(data["tmdb_id"])
        if data.get("imdb_id"):
            item.imdb_id = data["imdb_id"]
        item.last_scraped_at = datetime.now()
    if data.get("plot"):
        item.overview = data["plot"]
    if data.get("rating") is not None:
        item.community_rating = data["rating"]
