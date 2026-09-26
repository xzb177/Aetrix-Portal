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
import re
import threading
from datetime import datetime
from typing import Optional

from backend.emby_server import image_store
from backend.emby_server import models as emby_models

logger = logging.getLogger(__name__)

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"
TMDB_LANG = os.getenv("TMDB_LANGUAGE", "zh-CN")

# TMDB API Key 在 SystemConfig 里的键：管理后台「元数据与刮削」填写，保存即热生效
TMDB_KEYS_CONFIG_KEY = "tmdb_api_keys"


# ---------------------------------------------------------------------------
# 查询清洗与置信度校验（2026-09-26）
#
# 通用 bug：文件名解析出的剧名常带发行标签（DUAL/DD5.1/H264/BdC/集数标记/中字等），
# 直接拿去调 TMDB search 命中率极低；而 TMDB 的 results[0] 对短查询经常张冠李戴
# （如"虎子"→"老虎和兔子"、"骑士与魔法"→"魔法使的新娘"）。
# search() 因此改为：清洗查询 → 多候选 → 对多个返回结果做置信度校验，
# 只返回高置信命中；否则返回 None（调用方记 last_scraped_at，名字保持原样，
# 绝不写错名字）。

# 发行/压制/碟片/字幕类标签：只出现在文件名里，不属于标题
_QUERY_JUNK_RE = re.compile(r"""(?ix)
      \b(dual|ddp?\s?5\s?1|dd\s?5\s?1|dts\s?hd|dtshd|atmos|truehd|dts(?:-hd)?|ac3|aac|flac|[234]audios?)\b
    | \b([hx]?\s?264|[hx]?\s?265|hevc|avc|bdc|bluray|blu-ray|web-?dl|webrip|hdtv|dvdrip|bdrip|bdmv|remux)\b
    | \b(1080[ip]|720p|480p|2160p|4k|8k|10bit)\b
    | \b(s\d{1,2}e\d{1,3}|e\d{1,3}|ep\d{1,3}|d[12]|disc\s?\d|cd[12])\b
    | (原盘|中字|简繁\w{0,3}|繁中|简中|粤语|国语|双语|高码率|重制版|蓝光|特效|花絮|熟肉|生肉)
""")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ffー]+")
# 归一化：小写、去全部空白与标点（保留中日韩文字与字母数字）
_NORM_STRIP_RE = re.compile(
    r"[\s\u3000・·･—\-–_.,;:!?()（）【】《》\"'’‘“”/\\|&+*~^$#@%…‰「」『』〈〉＜＞★☆×″′©®™‖§]+"
)
_YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")


def _norm_text(s):
    return _NORM_STRIP_RE.sub("", s.lower()) if s else ""


def _clean_query(name):
    """去发行标签与分隔符，返回可用于搜索的干净查询。"""
    s = _QUERY_JUNK_RE.sub(" ", name or "")
    s = re.sub(r"[._\-+]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _first_run(query):
    """首个"标题式"词段：连续的中日韩/拉丁/数字（如"机动战士高达0079"、"X战警"）。

    文件名里标题通常在最前面，后面跟的是集标题/发行信息；取首段能保住
    "0079"这类数字后缀（纯中日韩提取会把它弄丢）。只取含中日韩的首段：
    纯拉丁单词（如 Blossom / 2gether）精确撞上同名不相干条目的概率太高。
    """
    for m in re.finditer(r"[\u4e00-\u9fff\u3040-\u30ffーa-zA-Z0-9]+", query or ""):
        w = m.group(0)
        if len(w) >= 2 and _CJK_RE.search(w):
            return w
    return ""


def _search_candidates(name):
    """按优先级返回 (候选查询, 是否允许模糊接受)。

    顺序：清洗后全名 → 原名 → 首个标题词段 → 中日韩部分。
    只有"中日韩部分"是信息有损的（丢了拉丁关键词，如演唱会的艺人名），
    它只允许 Tier 2 精确接受，不做模糊——否则"容祖儿 演唱会"会配到
    "容祖儿1314演唱会"（原文件名是 My Secret Live）。
    """
    raw = (name or "").strip()
    cleaned = _clean_query(name)
    cands = []
    for c, fuzzy in ((cleaned, True), (raw, True), (_first_run(cleaned), True)):
        if c and c not in [x[0] for x in cands]:
            cands.append((c, fuzzy))
    cjk = " ".join(_CJK_RE.findall(cleaned))
    if cjk and cjk not in [x[0] for x in cands]:
        cands.append((cjk, False))
    return cands


def _query_variants(query):
    """一个候选查询的归一化变体：全串、中日韩部分。"""
    out = []
    nq = _norm_text(query)
    if nq:
        out.append(nq)
    cjk = _norm_text(" ".join(_CJK_RE.findall(query)))
    if cjk and cjk not in out:
        out.append(cjk)
    return out


def _lcs_len(a, b):
    """最长公共子串长度（短串优化的 DP）。"""
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    prev = [0] * (len(a) + 1)
    best = 0
    for cb in b:
        cur = [0] * (len(a) + 1)
        for i, ca in enumerate(a, 1):
            if ca == cb:
                cur[i] = prev[i - 1] + 1
                if cur[i] > best:
                    best = cur[i]
        prev = cur
    return best


def _latin_words(query):
    """查询里的拉丁单词（长度≥4）：艺人/专辑等关键信息，不能丢。"""
    return [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", query or "")]


def _hit_score(raw_name, query, hit, fuzzy_ok=True):
    """置信度打分：返回 (tier, rank)，tier 大者优先，同 tier 比 rank；None 表拒绝。

    Tier 2（精确）：任一归一化变体与任一标题字段（name/title/原名）精确相等。
    Tier 1（模糊）：纯中日韩变体与标题有足够长的公共子串（防"虎子"→"老虎和兔子"
    类错配）；此时查询里的拉丁关键词必须在标题里出现过（防"S.H.E 安可场"配到
    "蔡依林 安可场"），同 tier 内用"全查询与标题的最长公共子串"排名消歧
    （如"高达0079"应在 SEED 之前选中 0079）。
    另：文件名里有年份而 TMDB 条目年份对不上，直接否决。
    """
    variants = _query_variants(query)
    names = [_norm_text(hit.get(k)) for k in ("name", "title", "original_name", "original_title")]
    names = [n for n in names if n]
    if not variants or not names:
        return None
    for v in variants:
        if v in names:
            return (2, len(v))
    if not fuzzy_ok:
        return None
    latin_ok = all(any(w in hn for hn in names) for w in _latin_words(query))
    if not latin_ok:
        return None
    raw_norm = _norm_text(raw_name)
    best = None
    for v in variants:
        if re.search(r"[a-z]", v):
            continue
        for hn in names:
            lcs = _lcs_len(v, hn)
            short = min(len(v), len(hn))
            if lcs >= 6 and short > 0 and lcs / short >= 0.5:
                rank = _lcs_len(raw_norm, hn)
                if best is None or rank > best:
                    best = rank
    if best is None:
        return None
    m = _YEAR_RE.search(raw_name or "")
    if m:
        qy = m.group(1)
        hy = (hit.get("first_air_date") or hit.get("release_date") or "")[:4]
        if hy and hy != qy:
            return None
    return (1, best)



def _split_keys(raw: str) -> list[str]:
    """多 key 切分：逗号 / 换行 / 空白分隔，去重保序"""
    parts = re.split(r"[\s,;，；]+", str(raw or ""))
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))


def _env_keys() -> list[str]:
    """环境变量里的 key（TMDB_API_KEYS 优先，兼容单键 TMDB_API_KEY）"""
    return _split_keys(os.getenv("TMDB_API_KEYS", "") or os.getenv("TMDB_API_KEY", ""))


def _read_config_value(db) -> str:
    from backend.integrations import store
    return store.read_values(db, [TMDB_KEYS_CONFIG_KEY], {TMDB_KEYS_CONFIG_KEY: ""})[TMDB_KEYS_CONFIG_KEY]


def _db_keys(db=None) -> list[str]:
    """SystemConfig 里的 key。db 未给时自己开短会话；读不到返回空（不抛异常）"""
    try:
        if db is None:
            from backend.database import SessionLocal
            session = SessionLocal()
            try:
                raw = _read_config_value(session)
            finally:
                session.close()
        else:
            raw = _read_config_value(db)
    except Exception:  # noqa: BLE001 — DB 没建好 / 表不存在时当没配
        return []
    return _split_keys(raw)

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
    密钥来源：环境变量优先，为空时回落 SystemConfig（管理后台「元数据与刮削」填写，
    保存后调 `refresh_keys()` 即时生效，无需重启）。
    单个密钥超出配额（429）或报 401 时自动轮到下一个，整库刮削不会因为一个 key 限额就停滞。

    带短 TTL 缓存：扫库时引擎会先在后台线程把「搜索 + 详情」预热，写库线程随后
    调用的同一请求直接命中缓存——既能并行，又不会重复消耗 TMDB 配额。
    """

    _CACHE_TTL = 300        # 秒；一次扫描的预热结果在这个窗口内有效
    _CACHE_MAX = 20000      # 缓存条数上限，满时按写入顺序淘汰最旧的一批（保留大部分预热结果）
    # 淘汰到只剩这个比例：一万部片子的库刚好是两万条，整表清空会顺手扔掉刚预热好的条目，
    # 写库线程接着取同一个片名就变成一次真的网络请求（见 _cache_put 的说明）
    _CACHE_KEEP_RATIO = 0.75
    _cache: dict = {}
    _cache_lock = threading.Lock()

    def __init__(self) -> None:
        self._keys_lock = threading.Lock()
        # 当前 key 来源：env（环境变量）/ db（后台填写）/ none（未配置），界面展示用
        self.key_source = "none"
        self.api_keys: list[str] = []
        self.api_key = ""
        self._key_index = 0
        self.session = None
        self._session_proxy_sig: Optional[str] = None
        self._session_lock = threading.Lock()
        self.refresh_keys()  # 环境变量优先，为空则回落 SystemConfig
        self._ensure_session()

    def _set_keys(self, keys: list[str], source: str) -> None:
        with self._keys_lock:
            self.api_keys = list(keys)
            self.api_key = self.api_keys[0] if self.api_keys else ""
            self._key_index = 0
            self.key_source = source if keys else "none"

    def refresh_keys(self, db=None) -> dict:
        """重算有效密钥：后台保存与进程启动都走这里，无需重启进程。

        优先级：环境变量 ``TMDB_API_KEYS``（非空即用）> SystemConfig ``tmdb_api_keys``。
        返回来源与数量（不含原文，可直接给界面）。
        """
        keys = _env_keys()
        source = "env"
        if not keys:
            keys = _db_keys(db)
            source = "db" if keys else "none"
        self._set_keys(keys, source)
        self._ensure_session()
        return {"source": self.key_source, "count": len(self.api_keys)}

    def masked_keys(self) -> list[str]:
        """界面展示用：只露后 4 位"""
        return [f"****{k[-4:]}" if len(k) > 4 else "****" for k in self.api_keys]

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
        """取缓存（未命中返回 _MISS；过期视为未命中，顺手删掉）"""
        with TmdbClient._cache_lock:
            hit = TmdbClient._cache.get(key)
            if hit is None:
                return _MISS
            ts, value = hit
            if (datetime.now() - ts).total_seconds() > self._CACHE_TTL:
                # 过期条目留着只会占名额：满载时它会把还在窗口内的预热结果一起挤出去
                TmdbClient._cache.pop(key, None)
                return _MISS
            return value

    def _cache_put(self, key, value) -> None:
        """写缓存：满了先清过期，再按写入顺序淘汰最旧的一批（不再是整表清空）

        整表清空看似简单，代价却是「把自己刚预热好的结果扔掉」：写库线程随后要取同一个
        片名，缓存已经空了，于是同一个请求又发一次。扫描规模越接近上限越容易撞上
        （一万部片子的库：搜索 + 详情刚好两万条），配额也就跟着白花。
        """
        now = datetime.now()
        with TmdbClient._cache_lock:
            cache = TmdbClient._cache
            if key not in cache and len(cache) >= self._CACHE_MAX:
                for stale in [k for k, (ts, _) in cache.items()
                              if (now - ts).total_seconds() > self._CACHE_TTL]:
                    cache.pop(stale, None)
                keep = max(1, int(self._CACHE_MAX * self._CACHE_KEEP_RATIO))
                # 多淘汰一条：给正在写的这个新条目腾位置（否则下一次写入又会触发一轮淘汰）
                for old in list(cache)[:max(0, len(cache) - keep + 1)]:
                    cache.pop(old, None)
            cache[key] = (now, value)

    def _search_raw(self, query: str, year: Optional[int], kind: str) -> list:
        """原始搜索（带缓存），返回 results 列表。"""
        self._ensure_session()
        if not self.session:
            return []
        endpoint = "tv" if kind == "series" else "movie"
        key = ("search", endpoint, query, year or 0)
        cached = self._cache_get(key)
        if cached is not _MISS:
            return cached or []
        params: dict = {"language": TMDB_LANG, "query": query}
        if year:
            if endpoint == "tv":
                params["first_air_date_year"] = year
            else:
                params["year"] = year
        data = self._get(f"/search/{endpoint}", params)
        results = (data or {}).get("results") or []
        self._cache_put(key, results)
        return results

    def search(self, name: str, year: Optional[int], kind: str) -> Optional[dict]:
        """智能搜索：清洗查询 → 多候选 → 置信度校验，只返回高置信命中。

        无高置信命中时返回 None（调用方按既有口径记 last_scraped_at，
        条目名字保持原样，绝不写错）。
        """
        best = None  # (tier, rank, hit)：跨候选、跨结果取全局最可信
        for query, fuzzy_ok in _search_candidates(name):
            try:
                results = self._search_raw(query, year, kind)
            except Exception:  # noqa: BLE001 — 单个候选失败换下一个
                continue
            for hit in results[:10]:
                sc = _hit_score(name, query, hit, fuzzy_ok)
                if sc and (best is None or sc > best[:2]):
                    best = (sc[0], sc[1], hit)
        return best[2] if best else None

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
