"""豆瓣元数据客户端：中文内容刮削的主数据源。

TMDB 对中文剧集/综艺收录偏少（短中文剧名 Tier1 LCS>=6 永远达不到），
中文标题优先走豆瓣，搜中率高、速度快。

数据源：
- 搜索：https://movie.douban.com/j/subject_suggest?q=（无需 key，实测 200）
- 详情：https://movie.douban.com/subject/{id}/ 页面的 JSON-LD（schema.org）

反爬：Chrome UA + 线程安全限速器（默认 1 秒/次，可配置）。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

SUGGEST_URL = "https://movie.douban.com/j/subject_suggest"
# 管理后台配置键
DOUBAN_ENABLED_KEY = "douban_enabled"
DOUBAN_RATE_KEY = "douban_min_interval"
DEFAULT_MIN_INTERVAL = 1.0
REQUEST_TIMEOUT = 15

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# CJK 字符范围：中日韩统一表意文字 + 假名 + 韩文
_CJK_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\u3040-\u309f\u30a0-\u30ff\U00020000-\U0002a6df"
    "\uac00-\ud7af]"
)

# JSON-LD 提取：豆瓣 subject 页面的结构化数据
_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

# 电视剧/综艺的 type 值（subject_suggest 返回 movie/tv/book/music）
_SERIES_TYPES = {"tv", "show", "series"}

_lock = threading.Lock()


class _RateLimiter:
    """线程安全限速器：两次请求之间的最小间隔秒数。"""

    def __init__(self) -> None:
        self._last: float = 0.0

    def acquire(self, min_interval: float) -> None:
        if min_interval <= 0:
            with _lock:
                self._last = time.time()
            return
        while True:
            with _lock:
                now = time.time()
                wait = self._last + min_interval - now if self._last else 0.0
                if wait <= 0:
                    self._last = now
                    return
            time.sleep(min(wait, 5.0))


_limiter = _RateLimiter()


def has_cjk(text: str) -> bool:
    """检测文本是否包含中日韩字符。"""
    if not text:
        return False
    return _CJK_RE.search(text) is not None


def _clean(title: str) -> str:
    """归一化标题用于比对：去空白与常见标点。"""
    return re.sub(r"[\s:：·\-—_\.、,，!！?？~～'\"“”‘’()（）\[\]【】]+",
                  "", (title or "").lower())


def enabled(db: Any) -> bool:
    """豆瓣总开关（默认开）。"""
    from backend.integrations import store
    try:
        v = store.get_value(db, DOUBAN_ENABLED_KEY, "1")
    except Exception:
        return True
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def min_interval(db: Any) -> float:
    """两次豆瓣请求的最小间隔秒数（默认 1.0，0 = 不限速）。"""
    from backend.integrations import store
    try:
        return max(0.0, float(store.get_value(db, DOUBAN_RATE_KEY,
                                              str(DEFAULT_MIN_INTERVAL))))
    except (TypeError, ValueError):
        return DEFAULT_MIN_INTERVAL


class DoubanClient:
    """豆瓣元数据客户端：搜索 + 详情，内置限速。"""

    def __init__(self, interval: float = DEFAULT_MIN_INTERVAL) -> None:
        self._interval = interval

    def _get(self, url: str) -> Optional[str]:
        _limiter.acquire(self._interval)
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as exc:
            logger.debug("[douban] 请求失败 %s: %s", url, exc)
            return None

    def search(self, title: str, year: Optional[int] = None,
               kind: str = "series") -> Optional[dict]:
        """搜一条，返回 {id, title, year, image, type, url}；无可信命中返回 None。

        只取首条结果，且要求清洗后标题与查询高度一致——豆瓣 suggest 结果里
        常常是同名的别的作品，宁可漏也不错配。
        """
        q = (title or "").strip()
        if not q:
            return None
        url = f"{SUGGEST_URL}?q={urllib.parse.quote(q)}"
        raw = self._get(url)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, list) or not data:
            return None
        hit = data[0]
        if not isinstance(hit, dict):
            return None
        # 标题必须完全一致，或一方是另一方的前缀
        got = _clean(str(hit.get("title") or ""))
        want = _clean(q)
        if not got or not want:
            return None
        if got != want and not (got.startswith(want) or want.startswith(got)):
            logger.debug("[douban] 首条标题不匹配，丢弃：%r -> %r", q, got)
            return None
        # 年份校验
        if year and hit.get("year"):
            try:
                if int(hit["year"]) != int(year):
                    logger.debug("[douban] 年份不符，丢弃：%r %s vs %s",
                                 q, hit.get("year"), year)
                    return None
            except (TypeError, ValueError):
                pass
        # 类型校验：剧集不能拿电影条目
        if kind in ("series", "season", "episode") \
                and hit.get("type") not in _SERIES_TYPES:
            logger.debug("[douban] 类型不符(%s)，丢弃：%r", hit.get("type"), q)
            return None
        return {
            "id": str(hit.get("id") or ""),
            "title": str(hit.get("title") or ""),
            "year": hit.get("year") or None,
            "image": str(hit.get("img") or ""),
            "type": str(hit.get("type") or ""),
            "url": str(hit.get("url") or ""),
        }

    def get_details(self, douban_id: str) -> Optional[dict]:
        """按豆瓣 ID 取详情：标题/简介/评分/年份/海报/类型。

        解析 subject 页面的 JSON-LD（schema.org 结构化数据）。
        失败返回 None（调用方用 search 结果兜底，不中断流程）。
        """
        if not douban_id:
            return None
        url = "https://movie.douban.com/subject/{}/".format(
            urllib.parse.quote(str(douban_id)))
        html = self._get(url)
        if not html:
            return None
        for m in _LD_JSON_RE.finditer(html):
            try:
                data = json.loads(m.group(1).strip())
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict) or not data.get("name"):
                continue
            rating = data.get("aggregateRating") or {}
            return {
                "title": str(data.get("name") or ""),
                "overview": str(data.get("description") or ""),
                "rating": rating.get("ratingValue"),
                "year": str(data.get("datePublished") or "")[:4] or None,
                "image": str(data.get("image") or ""),
                "genres": data.get("genre") or [],
            }
        logger.debug("[douban] subject %s 无 JSON-LD", douban_id)
        return None


client = DoubanClient()
