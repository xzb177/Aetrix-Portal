"""缺失集数计算（StrmAssistant 对标）——轻量通用能力。

纯计算：本地已有集 vs TMDB 预期集，算出缺失的集号。
- 只读磁盘缓存（tmdb_cache.load_details），零网络请求
- 不写库、无后台任务、无 per-user 开关，默认生效
- 优先用用户选定的剧集组（episode_groups，仅读缓存），否则用 TMDB TV 详情

TMDB TV 详情结构：{"seasons": [{"season_number": N, "episode_count": M}, ...]}
剧集组详情结构：{"groups": [{"name":..., "episodes": [{"season_number","episode_number","order"}]}]}
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _tmdb_tv_seasons_from_cache(tmdb_id: str) -> Optional[dict]:
    """仅读磁盘缓存取 TV 详情的 seasons（未命中返回 None，不打网络）。"""
    from backend.emby_server import tmdb_cache
    from backend.emby_server.tmdb import preferred_language

    tmdb_id = str(tmdb_id or "").strip()
    if not tmdb_id:
        return None
    # 语言维度：优先当前首选语言，逐个试读缓存（纯读盘，无网络）
    langs = []
    try:
        langs.append(preferred_language())
    except Exception:
        pass
    for extra in ("zh-CN", "en-US", ""):
        if extra not in langs:
            langs.append(extra)
    for lang in langs:
        try:
            hit, data = tmdb_cache.load_details("tv", tmdb_id, lang)
        except Exception:
            continue
        if hit and isinstance(data, dict) and data.get("seasons"):
            return data
    return None


def _episode_group_from_cache(db, tmdb_id: str) -> Optional[dict]:
    """用户选定的剧集组详情（仅读磁盘缓存，未命中返回 None，不打网络）。"""
    from backend.emby_server import episode_groups as _eg
    from backend.emby_server import tmdb_cache

    try:
        group_id = _eg.get_selected_group(db, tmdb_id)
    except Exception:
        return None
    if not group_id:
        return None
    try:
        hit, data = tmdb_cache.load_details("episode_group", str(group_id), "en-US")
    except Exception:
        return None
    if hit and isinstance(data, dict):
        return data
    return None


def compute_missing(db, series_item) -> dict:
    """计算某剧的缺失集数。

    返回 {"seasons": [...], "total_missing": N, "source": "tmdb"|"episode_group"|"none"}。
    本地集按 (season_number, episode_number) 去重；season_number 为空的记为 1 季。
    """
    from backend.emby_server import models as em

    series_id = series_item.id
    tmdb_id = (getattr(series_item, "tmdb_id", None) or "").strip()

    # 本地集：{season: set(episodes)}
    local: dict[int, set[int]] = {}
    try:
        rows = (
            db.query(em.MediaItem.season_number, em.MediaItem.episode_number)
            .filter(
                em.MediaItem.series_id == series_id,
                em.MediaItem.item_type == "episode",
            )
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("缺失集数：查本地集失败 series=%s: %s", series_id, exc)
        rows = []
    for s, e in rows:
        try:
            sn, en = int(s or 1), int(e or 0)
        except (TypeError, ValueError):
            continue
        if en <= 0:
            continue
        local.setdefault(sn, set()).add(en)

    seasons_out: list[dict] = []
    source = "none"

    # 优先：用户选定的剧集组（仅缓存）
    group_data = _episode_group_from_cache(db, tmdb_id) if tmdb_id else None
    if group_data:
        # groups 是该剧集组下的分组（如不同季），每组有 episodes 列表
        expected: dict[int, set[int]] = {}
        for grp in group_data.get("groups") or []:
            for ep in grp.get("episodes") or []:
                try:
                    sn = int(ep.get("season_number") or 1)
                    en = int(ep.get("episode_number") or 0)
                except (TypeError, ValueError):
                    continue
                if en > 0:
                    expected.setdefault(sn, set()).add(en)
        if expected:
            source = "episode_group"
            for sn in sorted(set(expected) | set(local)):
                exp = expected.get(sn, set())
                have = local.get(sn, set())
                missing = sorted(exp - have)
                seasons_out.append({
                    "SeasonNumber": sn,
                    "ExpectedCount": len(exp),
                    "HaveCount": len(have),
                    "Missing": missing,
                })

    # 回退：TMDB TV 详情（仅缓存）
    if source == "none" and tmdb_id:
        tv = _tmdb_tv_seasons_from_cache(tmdb_id)
        if tv:
            source = "tmdb"
            for s in tv.get("seasons") or []:
                try:
                    sn = int(s.get("season_number"))
                    cnt = int(s.get("episode_count") or 0)
                except (TypeError, ValueError):
                    continue
                if sn < 0 or cnt <= 0:
                    continue  # 跳过特别篇季（season 0）无集数的情况按实际处理
                if sn == 0 and cnt == 0:
                    continue
                exp = set(range(1, cnt + 1))
                have = local.get(sn, set())
                missing = sorted(exp - have)
                seasons_out.append({
                    "SeasonNumber": sn,
                    "ExpectedCount": cnt,
                    "HaveCount": len(have),
                    "Missing": missing,
                })
            # TMDB 有但本地完全没有的季也列出（本地只有的季不算缺失）
            # 已在上面按 TMDB seasons 遍历，无需额外处理

    total_missing = sum(len(s["Missing"]) for s in seasons_out)
    return {
        "SeriesId": series_item.guid,
        "SeriesName": series_item.name or "",
        "Seasons": seasons_out,
        "TotalMissing": total_missing,
        "Source": source,
    }
