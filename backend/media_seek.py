"""求片中心领域逻辑（用户端 / 管理端 / 自愈注册共用）

把「求片」这条链路的规则收在一处，避免三处各写一份：

- **额度**：每日上限走 SystemConfig ``media_seek_daily_limit``（后台可改），
  默认值只在这里定义一次（``DEFAULT_DAILY_LIMIT``），config_self_heal 引用它；
- **剧集按整季申请**：``season`` 存 ``"1,2"`` 或 ``"all"``（全季），
  ``normalize_season`` 负责校验与归一化，界面文案走 ``season_label``；
- **TMDB 候选搜索**：用户端「搜你想看的片」列的是 TMDB 条目，
  并标出哪些**已经在库**（在库的直接引导播放，不占用额度）；
- **库内匹配**：管理端「标记已入库」用它确认片真的进了库（按 tmdb_id 优先、
  退回片名），匹配上才允许把求片标记成已完成。

本模块不依赖 FastAPI：路由层只做鉴权 / 参数 / 通知，规则都在这里。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger(__name__)

# ==================== 配置键与默认值 ====================

# 每日求片上限（防止刷单）；后台「系统设置 → 经济」里可改
CONFIG_DAILY_LIMIT = "media_seek_daily_limit"
DEFAULT_DAILY_LIMIT = 5

# 用户主动撤回的求片：不再展示、也不再参与去重，但仍计入当天的提交数
WITHDRAWN_STATUS = "withdrawn"

# 求片「处理中」的状态：去重与撤回判定都用这一份口径
ACTIVE_STATUSES = ("pending", "approved")

# 剧集类求片必须带季（端点校验用；电影/纪录片等忽略该字段）
SERIES_TYPES = ("series", "anime")

# 全季：不指定具体季时归一化成它，记录里始终是显式值（界面不用猜空值含义）
SEASON_ALL = "all"
MAX_SEASON_NUMBER = 99
MAX_SEASON_COUNT = 30

_SEASON_SPLIT_RE = re.compile(r"[,，、/\s]+")


# ==================== 额度 ====================

def daily_limit(db: Session) -> int:
    """每日求片上限：SystemConfig 覆盖，缺省/脏值回默认值（绝不让脏配置把求片打死）"""
    cfg = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == CONFIG_DAILY_LIMIT
    ).first()
    raw = str(cfg.value).strip() if cfg and cfg.value is not None else ""
    if not raw.isdigit():
        return DEFAULT_DAILY_LIMIT
    return max(1, int(raw))


def used_today(db: Session, user_id: int) -> int:
    """今天提交过多少条（含后来撤回的）

    撤回不退还额度——否则「提交 → 撤回 → 再提交」可以无限刷新额度，
    同时每次提交都会给全体管理员推一条站内消息，那就成了通知刷屏器。
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(models.MovieRequest).filter(
        models.MovieRequest.user_id == user_id,
        models.MovieRequest.created_at >= today_start,
    ).count()


def quota(db: Session, user_id: int) -> dict:
    """今日额度快照（用户端「申请时显示剩余额度」直接用它）"""
    limit = daily_limit(db)
    used = used_today(db, user_id)
    return {"used_today": used, "daily_limit": limit, "remaining": max(0, limit - used)}


# ==================== 剧集按整季申请 ====================

def normalize_season(raw, *, series: bool) -> str:
    """归一化「申请的季」：``"1,2"`` / ``"all"``；非剧集返回空串

    - 剧集（series / anime）必须给出季：空值当作「全季」（``all``），
      这样记录里永远是显式值，后台和用户列表都不用猜空字段的含义；
    - 合法写法：数字、逗号/顿号/斜杠分隔的多季、``all`` / ``全季`` / ``全部``；
    - 非法写法（``"第一季"``、``"abc"``、超过 99、多于 30 个季）抛 ``ValueError``，
      由路由转成 400 并说清怎么填。
    """
    text = str(raw or "").strip().lower()
    if not series:
        return ""
    if not text or text in (SEASON_ALL, "*", "全部", "全季", "all season", "all seasons"):
        return SEASON_ALL

    nums: list[int] = []
    for part in _SEASON_SPLIT_RE.split(text):
        if not part:
            continue
        if not part.isdigit():
            raise ValueError("季要填数字，例如 1 或 1,2；不指定就留空表示全部季")
        num = int(part)
        if num < 0 or num > MAX_SEASON_NUMBER:
            raise ValueError(f"季号要在 0 ~ {MAX_SEASON_NUMBER} 之间（0 = 特别篇）")
        if num not in nums:
            nums.append(num)
    if not nums:
        return SEASON_ALL
    if len(nums) > MAX_SEASON_COUNT:
        raise ValueError(f"一次最多申请 {MAX_SEASON_COUNT} 个季")
    return ",".join(str(n) for n in sorted(nums))


def season_label(season) -> str:
    """界面文案：``"all"`` → 全季；``"1,3"`` → 第 1、3 季；空 → 空串"""
    text = str(season or "").strip()
    if not text:
        return ""
    if text == SEASON_ALL:
        return "全季"
    return "第 " + "、".join(text.split(",")) + " 季"


def normalize_tmdb_id(raw) -> str:
    """TMDB id：只接受纯数字（搜索候选带过来的值），其它一律丢弃为空"""
    text = str(raw or "").strip()
    if not text or not text.isdigit() or len(text) > 12:
        return ""
    return text


# ==================== 库内匹配 ====================

# 求片类型 → 库内条目类型（判断「入库了没有」时用；未列出的类型不按类型过滤）
_TYPE_MATCH = {
    "movie": ("movie",),
    "series": ("series",),
    "anime": ("series",),
}


def library_hit(db: Session, *, tmdb_id: Optional[str] = None,
                name: str = "", item_type: Optional[str] = None):
    """在自建媒体库里找一条匹配的条目（找到返回 MediaItem，否则 None）

    先按 ``tmdb_id`` 精确匹配（刮削过的条目都有，最可靠），没有再退回片名包含匹配
    （老条目可能还没补全 tmdb_id）。片名匹配时尽量按类型过滤，避免
    「电影《某某》」被同名的剧集顶掉。
    """
    from backend.emby_server import models as em

    if tmdb_id:
        hit = (
            db.query(em.MediaItem)
            .filter(em.MediaItem.tmdb_id == str(tmdb_id))
            .order_by(em.MediaItem.date_added.desc())
            .first()
        )
        if hit is not None:
            return hit

    keyword = (name or "").strip()
    if len(keyword) < 2:
        return None
    query = db.query(em.MediaItem).filter(em.MediaItem.name.ilike(f"%{keyword}%"))
    allowed = _TYPE_MATCH.get(str(item_type or ""))
    if allowed:
        query = query.filter(em.MediaItem.item_type.in_(allowed))
    return query.order_by(em.MediaItem.date_added.desc()).first()


def find_library_match(db: Session, request: models.MovieRequest):
    """给一条求片找库内条目（管理端「标记已入库」的判定口径）"""
    return library_hit(
        db,
        tmdb_id=getattr(request, "tmdb_id", None),
        name=getattr(request, "movie_name", "") or "",
        item_type=getattr(request, "type", None),
    )


# ==================== TMDB 候选搜索 ====================

def _poster_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    # 图片 CDN 地址跟刮削侧同源：后台配了镜像，这里自动跟着走
    from backend.emby_server import tmdb

    return f"{tmdb.image_base()}/w300{path}"


def _year_of(hit: dict, kind: str) -> str:
    raw = hit.get("first_air_date") if kind == "series" else hit.get("release_date")
    text = str(raw or "")
    return text[:4] if len(text) >= 4 else ""


def search_candidates(db: Session, query: str, kind: Optional[str] = None) -> dict:
    """TMDB 候选搜索（求片用）：列条目并标出哪些已在库

    与刮削用的 ``TmdbClient.search`` 不同：这里**不做置信度裁剪**——用户搜什么就列什么，
    让他自己认片（刮削要的是唯一正确答案，求片要的是候选列表）。
    返回 ``{"configured": bool, "results": [...]}``；TMDB 未配置时 ``configured=False``，
    前端据此回退到「按片名查本地库」的旧路径，而不是给一个永远搜不出东西的框。
    """
    from backend.emby_server import tmdb

    client = tmdb.tmdb_client
    keyword = (query or "").strip()
    if len(keyword) < 1:
        return {"configured": bool(client.configured), "results": []}
    if not client.configured:
        return {"configured": False, "results": []}

    kinds = [kind] if kind in ("movie", "series") else ["movie", "series"]
    results: list[dict] = []
    for one_kind in kinds:
        try:
            hits = client.search_candidates(keyword, one_kind)
        except Exception as exc:  # noqa: BLE001 — 搜索失败只影响这次候选列表
            logger.warning("TMDB 求片搜索失败（%s / %s）: %s", keyword, one_kind, exc)
            continue
        for hit in hits:
            tmdb_id = str(hit.get("id") or "").strip()
            name = str(hit.get("title") or hit.get("name") or "").strip()
            if not tmdb_id or not name:
                continue
            match = library_hit(db, tmdb_id=tmdb_id, name=name, item_type=one_kind)
            results.append({
                "tmdb_id": tmdb_id,
                "kind": one_kind,               # movie / series（前端用来选「季」）
                "name": name,
                "year": _year_of(hit, one_kind),
                "overview": str(hit.get("overview") or "")[:300],
                "poster_url": _poster_url(hit.get("poster_path")),
                "rating": round(float(hit.get("vote_average") or 0), 1) or None,
                "in_library": match is not None,
                "library_item_id": str(getattr(match, "guid", "") or "") or None,
            })
    # 已在库的沉到下面：用户要的是「还没入库、可以求」的候选
    results.sort(key=lambda r: (r["in_library"], -float(r.get("rating") or 0)))
    return {"configured": True, "results": results[:12]}


def seasons_for(tmdb_id: str) -> list[dict]:
    """剧集的季列表（用户选「按整季申请」时用）；未配置/查不到返回空表"""
    from backend.emby_server import tmdb

    client = tmdb.tmdb_client
    text = normalize_tmdb_id(tmdb_id)
    if not text or not client.configured:
        return []
    try:
        data = client.details(text, "series")
    except Exception as exc:  # noqa: BLE001 — 查不到季不影响手动填季
        logger.warning("TMDB 拉取季列表失败（%s）: %s", text, exc)
        return []
    seasons: list[dict] = []
    for row in (data or {}).get("seasons") or []:
        num = row.get("season_number")
        if num is None:
            continue
        try:
            number = int(num)
        except (TypeError, ValueError):
            continue
        seasons.append({
            "season_number": number,
            "name": str(row.get("name") or f"第 {number} 季"),
            "episode_count": int(row.get("episode_count") or 0),
            "air_date": str(row.get("air_date") or ""),
        })
    seasons.sort(key=lambda s: s["season_number"])
    return seasons


__all__ = [
    "ACTIVE_STATUSES",
    "CONFIG_DAILY_LIMIT",
    "DEFAULT_DAILY_LIMIT",
    "MAX_SEASON_COUNT",
    "MAX_SEASON_NUMBER",
    "SERIES_TYPES",
    "SEASON_ALL",
    "WITHDRAWN_STATUS",
    "daily_limit",
    "find_library_match",
    "library_hit",
    "normalize_season",
    "normalize_tmdb_id",
    "quota",
    "search_candidates",
    "season_label",
    "seasons_for",
    "used_today",
]
