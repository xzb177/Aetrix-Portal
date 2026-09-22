"""TMDB 刮削客户端（从 scanner.py 拆出）

扫描器有两件完全不同性质的事：**遍历文件系统**（IO 密集、状态多）与**跟 TMDB 说话**
（网络、配额轮询、短 TTL 缓存）。前者是 scanner.py 的主体，后者是这里的 `TmdbClient`：

- 密钥轮询（`TMDB_API_KEYS=key1,key2,key3`，单个 key 429/401 自动切换）；
- 短 TTL 进程内缓存：扫描时工作线程先「搜索 + 详情」预热，写库线程随后调同一请求直接命中，
  既并行又不重复消耗配额。

拆开之后扫描器只剩扫描逻辑，客户端也能单独测（不依赖扫描器的目录缓存、线程池等状态）。
`scanner.tmdb_client` 等既有引用由 scanner.py 重新导出，调用方无需改动。
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Optional

from backend.emby_server import image_store
from backend.emby_server import models as emby_models

logger = logging.getLogger(__name__)

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"
TMDB_LANG = os.getenv("TMDB_LANGUAGE", "zh-CN")

# 缓存未命中的哨兵：TMDB 的“没搜到”也是合法结果，必须与“没查过”区分开
_MISS = object()


def _set_image(item: emby_models.MediaItem, kind: str, url: str) -> None:
    """落一个刮削到的图片地址；开启本地化时同时把图落成本地文件

    远程地址**始终**保留（唯一事实来源）：本地那份只是缓存，被清掉/被删掉都能自愈——
    取图时若发现本地文件不在了，会按需再落一份（见 media_routes.item_image）。
    下载失败只是“没本地化”，不影响入库。
    """
    if kind == "Backdrop":
        item.backdrop_image_url = url
    else:
        item.primary_image_url = url
    local = image_store.localize(url)
    if not local:
        return
    if kind == "Backdrop":
        item.backdrop_path = local
    else:
        item.poster_path = local


class TmdbClient:
    """轻量 TMDB 客户端（未配置 key 时静默跳过）

    支持多密钥轮询：`TMDB_API_KEYS=key1,key2,key3`（或 `TMDB_API_KEY` 单键）。
    单个密钥超出配额（429）或报 401 时自动轮到下一个，整库刮削不会因为一个 key 限额就停滞。

    带短 TTL 缓存：扫库时引擎会先在后台线程把「搜索 + 详情」预热，写库线程随后
    调用的同一请求直接命中缓存——既能并行，又不会重复消耗 TMDB 配额。
    """

    _CACHE_TTL = 300        # 秒；一次扫描的预热结果在这个窗口内有效
    _CACHE_MAX = 20000      # 缓存条数上限，超过就整表清空（内存优先）
    _cache: dict = {}
    _cache_lock = threading.Lock()

    def __init__(self) -> None:
        raw = os.getenv("TMDB_API_KEYS", "") or os.getenv("TMDB_API_KEY", "")
        self.api_keys = [k.strip() for k in raw.split(",") if k.strip()]
        self.api_key = self.api_keys[0] if self.api_keys else ""
        self._key_index = 0
        self.session = None
        self._session_proxy_sig: Optional[str] = None
        self._session_lock = threading.Lock()
        self._ensure_session()

    def _ensure_session(self) -> None:
        """按需创建 / 重建 HTTP 会话——让后台改完「网络代理」立刻对刮削生效

        httpx 只在**构造 client 时**读一遍代理环境变量（``trust_env``），建好之后改环境不再
        有效；而刮削客户端是进程级单例、活得比一次扫描久得多。不重建的话，管理员填完代理
        依然会看到「TMDB 连不上」，只能靠重启进程解决。

        这里不依赖「保存代理时通知谁」，而是每次请求前比一次代理指纹：进程内任何路径改了
        代理（``apply`` / ``apply_all``，将来别处也一样）都会被察觉，指纹没变时只是拼一次
        字符串，不会每次请求都换连接。
        """
        if not self.api_keys:
            return
        from backend.integrations import proxy

        sig = proxy.signature()
        with self._session_lock:
            if self.session is not None:
                if self._session_proxy_sig is None:
                    # 会话不是这里建的（密钥/会话后来被注入，测试也这么接）：只补记指纹，
                    # 不在别人刚换上的会话上动手。
                    self._session_proxy_sig = sig
                    return
                if sig == self._session_proxy_sig:
                    return
            import httpx

            stale, self.session = self.session, httpx.Client(timeout=8)
            self._session_proxy_sig = sig
        if stale is not None:
            # 可能还有别的扫描线程正拿旧会话取数据：它会拿到一次异常，_get 按「一次失败的
            # 网络请求」处理（条目这轮不刮削，下轮再来）。重建只发生在管理员改代理时。
            try:
                stale.close()
            except Exception:  # noqa: BLE001
                pass
            logger.info("TMDB 客户端已按新的代理设置重建连接")

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
        self._ensure_session()
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

    def _cache_get(self, key):
        """取缓存（未命中返回 _MISS；过期视为未命中）"""
        with TmdbClient._cache_lock:
            hit = TmdbClient._cache.get(key)
        if hit is None:
            return _MISS
        ts, value = hit
        if (datetime.now() - ts).total_seconds() > self._CACHE_TTL:
            return _MISS
        return value

    def _cache_put(self, key, value) -> None:
        with TmdbClient._cache_lock:
            if len(TmdbClient._cache) >= self._CACHE_MAX:
                TmdbClient._cache.clear()
            TmdbClient._cache[key] = (datetime.now(), value)

    def search(self, name: str, year: Optional[int], kind: str) -> Optional[dict]:
        self._ensure_session()
        if not self.session:
            return None
        endpoint = "tv" if kind == "series" else "movie"
        key = ("search", endpoint, name, year or 0)
        cached = self._cache_get(key)
        if cached is not _MISS:
            return cached
        params: dict = {"language": TMDB_LANG, "query": name}
        if year:
            if endpoint == "tv":
                params["first_air_date_year"] = year
            else:
                params["year"] = year
        data = self._get(f"/search/{endpoint}", params)
        results = (data or {}).get("results") or []
        hit = results[0] if results else None
        self._cache_put(key, hit)
        return hit

    def details(self, tmdb_id: str, kind: str) -> Optional[dict]:
        """详情（补 IMDb Id 与多别名）——只在条目缺这两项时调用"""
        endpoint = "tv" if kind == "series" else "movie"
        key = ("details", endpoint, str(tmdb_id))
        cached = self._cache_get(key)
        if cached is not _MISS:
            return cached
        data = self._get(f"/{endpoint}/{tmdb_id}", {"language": TMDB_LANG,
                                                     "append_to_response": "alternative_titles,external_ids"})
        self._cache_put(key, data)
        return data

    def enrich(self, item: emby_models.MediaItem, kind: str) -> None:
        """补齐 imdb_id 与 aliases（中英文/繁简多别名搜索的基础）"""
        if not item.tmdb_id or (item.imdb_id and item.aliases):
            return
        data = self.details(str(item.tmdb_id), kind)
        if not data:
            return
        self.apply_details(item, data)

    def apply_details(self, item: emby_models.MediaItem, data: dict) -> None:
        """把详情接口的返回落到条目上（与 enrich 同口径，供批量扫描预先取回后套用）"""
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
        return self.apply_images(item, data)

    def apply_images(self, item: emby_models.MediaItem, data: dict) -> bool:
        """把详情接口里的图片落到条目上（返回是否拿到图）"""
        if not data:
            return False
        poster = data.get("poster_path")
        backdrop = data.get("backdrop_path")
        if poster:
            _set_image(item, "Primary", f"{TMDB_IMAGE}/w500{poster}")
        if backdrop:
            _set_image(item, "Backdrop", f"{TMDB_IMAGE}/w1280{backdrop}")
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
            _set_image(item, "Primary", f"{TMDB_IMAGE}/w500{poster}")
        if backdrop:
            _set_image(item, "Backdrop", f"{TMDB_IMAGE}/w1280{backdrop}")
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


tmdb_client = TmdbClient()  # 进程级单例：一次扫描里的预热与写库共用同一份缓存与连接池
