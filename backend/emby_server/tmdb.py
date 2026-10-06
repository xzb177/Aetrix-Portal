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
import contextlib
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from backend.emby_server import image_store
from backend.emby_server import models as emby_models
from backend.emby_server import scan_progress as progress
from backend.emby_server import tmdb_cache

logger = logging.getLogger(__name__)

TMDB_API_DEFAULT = "https://api.themoviedb.org/3"
TMDB_IMAGE_DEFAULT = "https://image.tmdb.org/t/p"
# 兼容旧引用（scanner.py 再导出这两个名字）：真正生效的地址走 ``api_base()`` /
# ``image_base()``，可以在管理后台配镜像（境内直连不通时用）。
TMDB_API = TMDB_API_DEFAULT
TMDB_IMAGE = TMDB_IMAGE_DEFAULT
TMDB_LANG = os.getenv("TMDB_LANGUAGE", "zh-CN")

# TMDB API Key 在 SystemConfig 里的键：管理后台「元数据与刮削」填写，保存即热生效
TMDB_KEYS_CONFIG_KEY = "tmdb_api_keys"
# 镜像 / 反代地址（空 = 用官方地址）。API 与图片分开：跨境时常见的是图片 CDN 可走
# 镜像而 API 直连（或反过来），一条配置管两件事会互相绑死。
TMDB_API_BASE_CONFIG_KEY = "tmdb_api_base"
TMDB_IMAGE_BASE_CONFIG_KEY = "tmdb_image_base"
# 密钥冷却时长：单把密钥 429 / 401 之后跳过它多久（阈值走配置，不写死）
TMDB_KEY_COOLDOWN_CONFIG_KEY = "tmdb_key_cooldown_sec"
TMDB_KEY_INVALID_COOLDOWN_CONFIG_KEY = "tmdb_key_invalid_cooldown_sec"
DEFAULT_KEY_COOLDOWN_SEC = 900          # 15 分钟：配额窗口一般几分钟
DEFAULT_KEY_INVALID_COOLDOWN_SEC = 21600  # 6 小时：401 多半是 key 废了，等管理员换
# 冷却 / 镜像配置的进程内 TTL：跨进程（API / worker / EA）靠它兜底，同进程保存即失效
SETTINGS_TTL_SEC = 30.0

# ---------------------------------------------------------------------------
# 请求级限流 / 超时 / 429 退避（v2.42.9）
#
# 旧实现把令牌桶放在 enrich_worker 里，**按条目**扣一个 token，而一个条目后面可能是
# 0~6 个 HTTP（中文标题 4~5 个候选搜索，最贵）；于是“4/秒”实际上是 8~24 请求/秒，
# 而且扫描那条路（scanner._tmdb_work）**完全没有限流**。
# 现在桶搬到这里，一条请求一个 token，口径与 TMDB 配额一致，两条路共用同一个桶。
#
# 注：TMDB 2019-12-16 已取消旧的 40 次/10 秒硬限流，现在是非正式 ~50 请求/秒/IP，
# 所以**不要**把速率拉满；429 时下面的自适应会自己降下来。
#
# 环境变量（沿用旧名字，但语义已从「条目/秒」改为「请求/秒」）：
#   ENRICH_TMDB_PER_SEC      请求上限（默认 2）
#   ENRICH_TMDB_MIN_PER_SEC  429 自适应下降的下限（默认 1）
#   TMDB_TIMEOUT             单次请求超时秒数（默认 10；带 append_to_response 的详情请求
#                            在跨境链路上 8 秒偏紧）
#   TMDB_NET_RETRIES         读超时/连接错误的重试次数（默认 2）
TMDB_PER_SEC = max(1.0, float(os.getenv("ENRICH_TMDB_PER_SEC", "2") or 2))
TMDB_MIN_PER_SEC = max(1.0, float(os.getenv("ENRICH_TMDB_MIN_PER_SEC", "1") or 1))
TMDB_TIMEOUT = max(5.0, float(os.getenv("TMDB_TIMEOUT", "10") or 10))
TMDB_NET_RETRIES = max(0, min(4, int(os.getenv("TMDB_NET_RETRIES", "2") or 2)))
# Retry-After 上限：后台 worker 睡太久会白白占着线程， 超过就按上限退避
TMDB_RETRY_AFTER_CAP_SEC = max(1.0, float(os.getenv("TMDB_RETRY_AFTER_CAP_SEC", "20") or 20))
# 连续成功多少次之后才试着恢复速率（避免成功一次就立刻又撞 429）
TMDB_RECOVER_AFTER = max(5, int(os.getenv("TMDB_RECOVER_AFTER", "50") or 50))


class _RequestLimiter:
    """请求级令牌桶 + 429 自适应（进程内；两条 TMDB 调用路径共用）

    - `acquire()`：拿一个 token（不够就睡到够），与旧桶同形状；
    - `note_throttled()`：429 时速率乘性下调（×0.5，下限 min_rate），返回建议等待秒数；
    - `note_success()`：连续成功到 TMDB_RECOVER_AFTER 次后速率 +25%，上限是配置值。
    """

    def __init__(self, rate: float = TMDB_PER_SEC, min_rate: float = TMDB_MIN_PER_SEC):
        self._ceiling = max(1.0, float(rate))
        self._min_rate = max(1.0, min(float(min_rate), self._ceiling))
        self._rate = self._ceiling
        self._tokens = self._ceiling
        self._updated = time.monotonic()
        self._lock = threading.Lock()
        self._ok_streak = 0
        self._throttled = 0

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def ceiling(self) -> float:
        """配置上限（ENRICH_TMDB_PER_SEC）：自适应恢复最多回到这里"""
        return self._ceiling

    @property
    def throttled_count(self) -> int:
        return self._throttled

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._rate, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(min(wait, 0.5))

    def note_throttled(self, retry_after: Optional[float] = None) -> float:
        """429：速率乘性下调并返回建议等待秒数（已按上限截断）"""
        with self._lock:
            self._rate = max(self._min_rate, self._rate * 0.5)
            self._tokens = 0.0          # 下调后桶也清空：立刻再打一次毫无意义
            self._updated = time.monotonic()
            self._ok_streak = 0
            self._throttled += 1
            rate = self._rate
        wait = TMDB_RETRY_AFTER_CAP_SEC if retry_after is None else max(0.0, float(retry_after))
        wait = min(wait, TMDB_RETRY_AFTER_CAP_SEC)
        if wait <= 0:
            # 没给 Retry-After（或给了 0）：按新速率等一个 token 的时间，别直接转圈
            wait = min(1.0 / rate, TMDB_RETRY_AFTER_CAP_SEC)
        return wait

    def note_success(self) -> None:
        """连续成功后缓慢恢复（每次 +25%，不超上限）"""
        with self._lock:
            if self._rate >= self._ceiling:
                self._ok_streak = 0
                return
            self._ok_streak += 1
            if self._ok_streak >= TMDB_RECOVER_AFTER:
                self._rate = min(self._ceiling, self._rate * 1.25)
                self._ok_streak = 0


def _retry_after_seconds(resp) -> Optional[float]:
    """读 Retry-After（秒数或 HTTP 日期）——旧实现全文未读取该头"""
    try:
        raw = (resp.headers.get("retry-after") or "").strip()
    except Exception:  # noqa: BLE001 — 响应对象可能是测试替身
        return None
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except Exception:  # noqa: BLE001 — 格式不认识就当没给
        return None


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
# 全角标点先折成半角再做归一化：TMDB 用半角冒号，而国内剧名常见全角
# （`90 Day： The Last Resort`、`GIGN：精英部队`），不折就必然零结果。
_PUNCT_FOLD = {
    "：": ":", "，": ",", "。": ".", "！": "!", "？": "?",
    "（": "(", "）": ")", "［": "[", "］": "]", "｛": "{", "｝": "}",
    "、": ",", "；": ";", "／": "/", "＼": "\\", "｜": "|", "％": "%",
    "＃": "#", "＠": "@", "＆": "&", "＊": "*", "＋": "+", "－": "-",
    "＝": "=", "～": "~", "＄": "$", "＾": "^", "｀": "`", "　": " ",
}
_PUNCT_FOLD_RE = re.compile("|".join(re.escape(k) for k in _PUNCT_FOLD))

_NORM_STRIP_RE = re.compile(
    r"[\s\u3000・·･—\-–_.,;:!?()（）【】《》\"'’‘“”/\\|&+*~^$#@%…‰「」『』〈〉＜＞★☆×″′©®™‖§]+"
)
_YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")
# 目录名尾部的年份：` (2009)` / `(2023-)` / ` - 2019` / ` 2019 年` 等
_YEAR_TAIL_RE = re.compile(
    r"[\(\（\[【]?\s*(?:19|20)\d{2}\s*(?:[-–—~]\s*\d{0,4})?\s*[\)）\]】]?\s*(?:年|Season\s*\d{1,2}?)?\s*$",
    re.IGNORECASE,
)


def _fold_punct(s: str) -> str:
    """全角标点折半角（见 _PUNCT_FOLD）"""
    return _PUNCT_FOLD_RE.sub(lambda m: _PUNCT_FOLD[m.group(0)], s) if s else s


# TMDB 类型 id → 中文名：全项目唯一一份映射（横切纪律：不许有第二套）。
# 搜索接口只给 genre_ids，用它翻译；详情接口给 genres=[{id, name}]，
# name 已是本地化中文、优先用 name，缺 name 时才回退到这张表。
_GENRE_NAMES = {
    28: "动作", 12: "冒险", 16: "动画", 35: "喜剧", 80: "犯罪",
    99: "纪录片", 18: "剧情", 10751: "家庭", 14: "奇幻", 36: "历史",
    27: "恐怖", 10402: "音乐", 9648: "悬疑", 10749: "爱情",
    878: "科幻", 10770: "电视电影", 53: "惊悚", 10752: "战争", 37: "西部",
}
_MAX_GENRES = 4


def _genres_from_details(data: dict) -> list:
    """从详情接口 payload 提取类型名（不发请求，纯解析）。

    payload 形态：``genres=[{"id": 28, "name": "动作"}, ...]``。
    name 为空或缺失时回退到 ``_GENRE_NAMES`` 按 id 翻译；都取不到就跳过
    （不写原文 id 数字——搜索路径 apply() 写数字是历史行为，保持不动）。
    """
    out = []
    for g in (data or {}).get("genres") or []:
        name = ""
        gid = None
        if isinstance(g, dict):
            name = (g.get("name") or "").strip()
            gid = g.get("id")
        elif isinstance(g, (int, str)):
            gid = g
        if not name and gid is not None:
            try:
                name = _GENRE_NAMES.get(int(gid), "")
            except (TypeError, ValueError):
                name = ""
        if name and name not in out:
            out.append(name)
        if len(out) >= _MAX_GENRES:
            break
    return out


def _norm_text(s):
    if not s:
        return ""
    return _NORM_STRIP_RE.sub("", _fold_punct(s).lower())


def _clean_query(name):
    """去发行标签与分隔符，返回可用于搜索的干净查询。"""
    # 先折全角标点，否则「剧名：副标题」里的全角冒号会让 TMDB 零结果
    s = _QUERY_JUNK_RE.sub(" ", _fold_punct(name or ""))
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
    # 原始名也要折全角标点：它会直接进 _query_variants 去和 TMDB 标题比对
    raw = _fold_punct((name or "").strip())
    cleaned = _clean_query(name)
    cands = []
    for c, fuzzy in ((cleaned, True), (raw, True), (_first_run(cleaned), True)):
        if c and c not in [x[0] for x in cands]:
            cands.append((c, fuzzy))
    # 剥掉年份再搜一次：目录名几乎都带「(YYYY)」，而归一化后年份仍在字符串里
    # （`Schlag den Star (2009)` → `schlagdenstar2009`），永远匹配不上 TMDB 标题
    # `schlagdenstar`。西方剧几乎全带年份，不剥就是全军覆没（欧美剧 679 条
    # 曾有 129 条因此零命中）。年份已作为 _hit_score 的排序信号单独使用。
    no_year = _YEAR_TAIL_RE.sub(" ", cleaned).strip()
    no_year = re.sub(r"\s+", " ", no_year).strip(" -_.()（）")
    if no_year and no_year != cleaned and no_year not in [x[0] for x in cands]:
        cands.append((no_year, True))
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


def _cjk_contain_rank(variants, names, hit):
    """Tier 1.5（C-14）：CJK 包含式匹配的 rank；不达标返回 None。

    短中文标题的 LCS 上限就是标题长度——四字名永远进不了 Tier 1
    （lcs≥6），这是 PR #119 那个坑的精确成因。查询 ≥3 字时改用「字符级
    包含」（子串，或字符全含且标题只多出 2 字以内），并用**语种/地区闸门**
    防错配：TMDB 条目必须是中日韩原生产物。≥3 字这一条先挡掉了
    「虎子」→「老虎和兔子」这类两字名错配；闸门再挡掉拉丁世界同名巧合。
    rank = 标题超长度的负值（越接近 0 = 标题越贴近查询）。
    """
    cjk_ok = (
        (hit.get("original_language") or "") in ("zh", "ja", "ko", "cn", "tw", "hk")
        or any(c in ("CN", "TW", "HK", "JP", "KR")
               for c in (hit.get("origin_country") or []))
        or bool(_CJK_RE.search(hit.get("original_name") or ""))
    )
    if not cjk_ok:
        return None
    for v in variants:
        if re.search(r"[a-z]", v) or len(v) < 3:
            continue
        for hn in names:
            if v in hn or (set(v) <= set(hn) and len(hn) <= len(v) + 2):
                return -(len(hn) - len(v))
    return None


def _hit_score(raw_name, query, hit, fuzzy_ok=True):
    """置信度打分：返回 (tier, rank)，tier 大者优先，同 tier 比 rank；None 表拒绝。

    Tier 2（精确）：任一归一化变体与任一标题字段（name/title/原名）精确相等。
    Tier 1（模糊）：纯中日韩变体与标题有足够长的公共子串（防"虎子"→"老虎和兔子"
    类错配）；此时查询里的拉丁关键词必须在标题里出现过（防"S.H.E 安可场"配到
    "蔡依林 安可场"），同 tier 内用"全查询与标题的最长公共子串"排名消歧
    （如"高达0079"应在 SEED 之前选中 0079）。
    Tier 1.5（包含式，C-14）：短中文标题（2~5 字）的 LCS 上限就是标题长度，
    在 Tier 1 的 lcs≥6 口径下结构性永远不达标（PR #119 的坑）。仅在 Tier 1
    未命中时启用：CJK 查询 ≥3 字用字符级包含，并以语种/地区闸门防同名错配。
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
        # Tier 1.5：短中文标题在 LCS≥6 口径下结构性永远不达标；包含式 + 闸门补上。
        # tier 用 1.5：仍低于 Tier 2、高于「无结果」，但排在该条目可用的 Tier 1 之后。
        t15 = _cjk_contain_rank(variants, names, hit)
        if t15 is not None:
            best = (1.5, t15)
    if best is None:
        return None
    # 年份不符**不再直接否决**。目录里的年份常是季/版本/重制年份，而不是 TMDB
    # 的首播年；早先「年份对不上就 return None」把大量本可命中的条目毙掉
    # （欧美剧 679 条里有 129 条因此没刮上）。现在只把年份不符的结果排在后面。
    m = _YEAR_RE.search(raw_name or "")
    if m:
        qy = m.group(1)
        hy = (hit.get("first_air_date") or hit.get("release_date") or "")[:4]
        if hy and hy != qy:
            if isinstance(best, tuple):
                best = (best[0], best[1] - 1)
            else:
                best -= 1
    return best if isinstance(best, tuple) else (1, best)



def _split_keys(raw: str) -> list[str]:
    """多 key 切分：逗号 / 换行 / 空白分隔，去重保序"""
    parts = re.split(r"[\s,;，；]+", str(raw or ""))
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))


def _env_keys() -> list[str]:
    """环境变量里的 key（TMDB_API_KEYS 优先，兼容单键 TMDB_API_KEY）"""
    return _split_keys(os.getenv("TMDB_API_KEYS", "") or os.getenv("TMDB_API_KEY", ""))


def _read_config_value(db) -> str:
    """统一热读（只许这一套）：短 TTL 缓存，保存时失效"""
    from backend.integrations import store
    return store.get_value(db, TMDB_KEYS_CONFIG_KEY, "")


# ---------------------------------------------------------------------------
# 镜像地址与冷却时长：进程内短 TTL 缓存（读多写少，跨进程靠 TTL 兜底）
# ---------------------------------------------------------------------------

_SETTINGS_CACHE: dict = {"at": 0.0, "data": {}}
_settings_lock = threading.Lock()


def normalize_base(raw: str, default: str) -> str:
    """镜像地址归一化：补 https://、去尾部斜杠；空值回落默认"""
    value = str(raw or "").strip()
    if not value:
        return default
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value.rstrip("/")


def validate_base(raw: str, field: str) -> str:
    """后台保存镜像地址时的校验：必须是 http(s) 绝对地址，错误要能直接给管理员看"""
    value = str(raw or "").strip()
    if not value:
        return ""  # 空 = 回到官方地址
    if any(ch.isspace() for ch in value):
        raise ValueError(f"{field}不能包含空格")
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"{field}必须以 http:// 或 https:// 开头")
    body = value.split("://", 1)[1]
    if not body or "/" == body[0] or "." not in body.split("/")[0]:
        raise ValueError(f"{field}看起来不像完整地址（例如 https://tmdb.example.com）")
    return normalize_base(value, "")


def _config_text(key: str, db=None) -> str:
    """读一个 SystemConfig 字符串；读不到返回空（表没建好 / 未配置）"""
    from backend.integrations import store
    try:
        if db is None:
            from backend.database import SessionLocal
            session = SessionLocal()
            try:
                return store.get_value(session, key, "")
            finally:
                session.close()
        return store.get_value(db, key, "")
    except Exception:  # noqa: BLE001 — DB 没建好时当没配
        return ""


def settings(db=None, *, refresh: bool = False) -> dict:
    """镜像地址与冷却时长（环境变量 > SystemConfig > 默认）

    这是**唯一**读这四个配置的地方：热路径（每次拼图片 URL、每次发请求）都走它，
    内部 30 秒 TTL 缓存，不会每次都开一次数据库会话。
    """
    now = time.monotonic()
    with _settings_lock:
        if not refresh and (now - _SETTINGS_CACHE["at"]) < SETTINGS_TTL_SEC \
                and _SETTINGS_CACHE.get("data"):
            return dict(_SETTINGS_CACHE["data"])
    env_api = (os.getenv("TMDB_API_BASE") or "").strip()
    env_image = (os.getenv("TMDB_IMAGE_BASE") or "").strip()
    env_cooldown = (os.getenv("TMDB_KEY_COOLDOWN_SEC") or "").strip()
    env_invalid = (os.getenv("TMDB_KEY_INVALID_COOLDOWN_SEC") or "").strip()
    data = {
        "api_base": normalize_base(env_api or _config_text(TMDB_API_BASE_CONFIG_KEY, db),
                                   TMDB_API_DEFAULT),
        "image_base": normalize_base(env_image or _config_text(TMDB_IMAGE_BASE_CONFIG_KEY, db),
                                     TMDB_IMAGE_DEFAULT),
        "cooldown_sec": _positive_float(env_cooldown, DEFAULT_KEY_COOLDOWN_SEC, 1.0),
        "invalid_cooldown_sec": _positive_float(
            env_invalid, DEFAULT_KEY_INVALID_COOLDOWN_SEC, 1.0),
        "api_base_from_env": bool(env_api),
        "image_base_from_env": bool(env_image),
    }
    with _settings_lock:
        _SETTINGS_CACHE.update({"at": now, "data": dict(data)})
    return data


def _positive_float(raw: str, default: float, floor: float) -> float:
    try:
        return max(floor, float(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def invalidate_settings() -> None:
    """保存镜像 / 冷却配置后立刻失效缓存（同进程即时生效，跨进程靠 TTL）"""
    with _settings_lock:
        _SETTINGS_CACHE.update({"at": 0.0, "data": {}})


def api_base(db=None) -> str:
    """当前生效的 API 基础地址（镜像 / 反代）"""
    return settings(db)["api_base"]


def image_base(db=None) -> str:
    """当前生效的图片 CDN 基础地址（与 API 分开配）"""
    return settings(db)["image_base"]


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


def image_specs(*payloads) -> list[tuple[str, str]]:
    """一次刮削要落的图片 ``(kind, url)`` 列表——IO 阶段按这个预热，写库阶段按这个落字段

    必须是单一口径：``_set_image`` 在写事务里**不再下载**，所以预热要看**同一份** URL，
    否则本地化会静默失效（w500 海报 / w1280 背景这两个尺寸不要在任何地方再拼一遍）。
    """
    out: list[tuple[str, str]] = []
    # 图片地址走**可配的 CDN 镜像**：境内直连 image.tmdb.org 不稳时，单独改这一项就行
    base = image_base()
    for data in payloads:
        if not data:
            continue
        poster = data.get("poster_path")
        backdrop = data.get("backdrop_path")
        if poster:
            out.append(("Primary", f"{base}/w500{poster}"))
        if backdrop:
            out.append(("Backdrop", f"{base}/w1280{backdrop}"))
    return out


def prewarm_images(*payloads, extra=()) -> int:
    """IO 阶段把这一批刮削要落的图先下到本地（写库阶段只落字段，v2.42.9）

    ``payloads`` 是 TMDB 的 hit / details（按 ``image_specs`` 拼 URL）；``extra`` 是不走
    TMDB 尺寸规则的图（豆瓣 / Bangumi 兜底源给的原图 URL）。

    写事务里的 ``_set_image`` 是 ``allow_download=False``：只认已经在本地的那份。所以只要
    要调 ``apply`` / ``apply_images``，就应在**写事务之前**调一次这里。预热失败或被并发旋钮
    挡住（``image_store._STATS["throttled"]``）只是「这轮不本地化」，取图时会按需补一份。
    """
    try:
        urls = [url for _kind, url in image_specs(*payloads)]
        urls += [str(u) for u in extra if u]
        return image_store.prewarm(urls) if urls else 0
    except Exception as exc:  # noqa: BLE001 — 预热失败不影响刮削
        logger.debug("图片预热失败: %s", exc)
        return 0


def _set_image(item: emby_models.MediaItem, kind: str, url: str) -> None:
    """落一个刮削到的图片地址；本地文件**已预热**时同时落本地路径

    远程地址**始终**保留（唯一事实来源）：本地那份只是缓存，被清掉/被删掉都能自愈——
    取图时若发现本地文件不在了，会按需再落一份（见 media_routes.item_image）。

    这个函数只在**写事务里**被调用，所以这里绝不发 HTTP（``allow_download=False``）：
    下载统一在 IO 阶段做（``image_specs`` + ``image_store.prewarm``）。在此处下载一张图
    超时 15s，就等于攥着数据库写锁 15s，而且与 scanner 里「写库不调网络」的声明相矛的
    （v2.42.9 之前的实情）。没预热上的图只是「这轮不本地化」，取图时会按需补一份。
    """
    if kind == "Backdrop":
        item.backdrop_image_url = url
    else:
        item.primary_image_url = url
    local = image_store.localize(url, allow_download=False)
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
        # 密钥池健康：key -> {"until": 单调时钟截止, "reason", "hits"}
        # 冷却是**进程内**状态（同令牌桶的性质）：重启后全部重新试一遍，
        # 写进配置反而会变成“记得某个 key 坏过”这种陈旧结论。
        self._cooldown: dict = {}
        self.session = None
        self._session_proxy_sig: Optional[str] = None
        self._session_lock = threading.Lock()
        # 请求级限流器：所有 TMDB 调用（扫描 + 补全）共用（v2.42.9）
        self._limiter = _RequestLimiter()
        # 运行观测：短路 / 重试 / 网络失败（429 次数在 _limiter 里，那边是加锁的）
        self._stats = {"short_circuit": 0, "retry": 0, "net_fail": 0}
        self.refresh_keys()  # 环境变量优先，为空则回落 SystemConfig
        self._ensure_session()

    def _set_keys(self, keys: list[str], source: str) -> None:
        with self._keys_lock:
            self.api_keys = list(keys)
            self.api_key = self.api_keys[0] if self.api_keys else ""
            self._key_index = 0
            self.key_source = source if keys else "none"
            # 已被换掉的 key 不再留着冷却记录（它不在池子里了，记着也没用）
            alive = set(self.api_keys)
            self._cooldown = {k: v for k, v in self._cooldown_map().items() if k in alive}

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

            # timeout 8 → 10：带 append_to_response 的详情请求在跨境链路上 8 秒偏紧。
            # 重试统一交给 _request()（连接错误与读超时一视同仁，见那里）——**不要**在这里
            # 传自定义 transport：一旦显式给 transport，httpx 就不再按环境变量挂代理了，
            # 后台配的代理会静默失效（scripts/smoke_test_capabilities.py 钉住了这一点）。
            stale, self.session = self.session, httpx.Client(timeout=TMDB_TIMEOUT)
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
        """轮到下一个密钥，全部用过则返回 False（保留给旧调用方）"""
        if len(self.api_keys) <= 1:
            return False
        self._key_index = (self._key_index + 1) % len(self.api_keys)
        self.api_key = self.api_keys[self._key_index]
        logger.warning("TMDB 密钥轮询到第 %s 个", self._key_index + 1)
        return True

    # ---------------- 密钥池：轮换 + 逐把冷却 ----------------

    def _key_lock(self):
        """密钥锁（防御式：测试里会用 ``__new__`` 绕开 ``__init__`` 造客户端）"""
        lock = getattr(self, "_keys_lock", None)
        return lock if lock is not None else contextlib.nullcontext()

    def _cooldown_map(self) -> dict:
        """冷却表（防御式取：测试里会用 ``__new__`` 绕开 ``__init__`` 造客户端）"""
        data = getattr(self, "_cooldown", None)
        if data is None:
            data = {}
            self._cooldown = data
        return data

    def _pick_key(self, exclude=(), *, allow_cooled: bool = False) -> str:
        """从池子里挑一把能用的 key（轮转起点，避免总是第一把先死）

        ``exclude`` 是**这一次调用已经试过**的 key：冷却是给后续请求用的，
        不能让一把刚被判 429 的 key 在同一次调用里立刻又被选上（那会变成死循环）。
        ``allow_cooled=True`` 是兵底：全池都在冷却时也得把请求发出去，
        冷却是优化，不是锁死。
        """
        keys = self.api_keys
        if not keys:
            return ""
        excluded = set(exclude)
        now = time.monotonic()
        # 轮转起点：默认从第一把开始（裸客户端没有 _key_index 时也是从 0 起）
        start = int(getattr(self, "_key_index", 0) or 0)
        with self._key_lock():
            total = len(keys)
            for step in range(total):
                idx = (start + step) % total
                key = keys[idx]
                if key in excluded:
                    continue
                entry = self._cooldown_map().get(key)
                if entry and entry.get("until", 0) > now and not allow_cooled:
                    continue
                self._key_index = (idx + 1) % total
                self.api_key = key
                return key
        return ""

    def _cool_key(self, key: str, reason: str, seconds: float) -> None:
        """把一把 key 放进冷却，并记下原因（界面上要能写出“为什么这把在休息”）"""
        seconds = max(1.0, float(seconds or 0))
        with self._key_lock():
            entry = self._cooldown_map().setdefault(key, {"until": 0.0, "reason": "", "hits": 0})
            entry["until"] = max(float(entry.get("until") or 0), time.monotonic() + seconds)
            entry["reason"] = reason
            entry["hits"] = int(entry.get("hits") or 0) + 1
        logger.warning("TMDB 密钥 ****%s 冷却 %.0f 秒（%s）", key[-4:] if key else "", seconds, reason)

    def note_key_throttled(self, key: str, retry_after: Optional[float] = None) -> float:
        """429：按 Retry-After（读不到则用配置值）冷却这把 key，返回建议等待秒数"""
        wait = float(retry_after) if retry_after and retry_after > 0 else 0.0
        if wait <= 0:
            wait = float(settings()["cooldown_sec"])
        self._cool_key(key, "限流（HTTP 429）", min(wait, TMDB_RETRY_AFTER_CAP_SEC) or wait)
        return wait

    def note_key_invalid(self, key: str) -> None:
        """401：这把 key 基本废了，冷却更久（等管理员换掉它）"""
        self._cool_key(key, "无效（HTTP 401）", float(settings()["invalid_cooldown_sec"]))

    def clear_cooldowns(self) -> int:
        """手动清除全部冷却（管理员换完 key / 网络恢复后用）"""
        with self._key_lock():
            count = len(self._cooldown_map())
            self._cooldown_map().clear()
        return count

    def key_pool(self, db=None) -> list:
        """密钥池快照（只给掩码与状态，**不返回原文**）

        冷却剩余秒数是运行时事实，前端据此显示“这把在休息，还要 xx 秒”。
        """
        now = time.monotonic()
        cfg = settings(db)
        rows: list[dict] = []
        for idx, key in enumerate(self.api_keys):
            with self._key_lock():
                entry = dict(self._cooldown_map().get(key) or {})
            remaining = max(0.0, float(entry.get("until") or 0) - now)
            rows.append({
                "index": idx + 1,
                "masked": f"****{key[-4:]}" if len(key) > 4 else "****",
                "current": key == self.api_key,
                "cooling": remaining > 0,
                "cooldown_remaining": int(round(remaining)),
                "reason": entry.get("reason") or "",
                "hits": int(entry.get("hits") or 0),
            })
        return rows

    def _throttle(self, retry_after: Optional[float] = None) -> float:
        """429：速率自适应下调，返回建议退避秒数（睡不睡由调用方决定）"""
        return self._limiter.note_throttled(retry_after)

    def _request(self, path: str, params: dict, key: str = ""):
        """单次 GET：先过**请求级**令牌桶，再按 TMDB_NET_RETRIES 退避重试网络异常

        连接错误与读超时都在这里重试（httpx 默认的连接级重试不覆盖读超时，而跨境
        链路上更常见的恰恰是读超时）；一次抖动不再让条目这轮刮不上、要等下一轮
        补全才回来。
        """
        if not self.session:
            return None
        payload = {**params, "api_key": key or self.api_key}
        base = api_base()
        delay = 0.5
        for attempt in range(TMDB_NET_RETRIES + 1):
            # 重试也要重新取 token：一次重试就是一次真的请求，配额照样要花
            self._limiter.acquire()
            try:
                # v2.42.9：每一次真实发出的 HTTP 都计进 tmdb_req（含重试与换 key 后的重试）
                with progress.stage_timer("tmdb_req"):
                    return self.session.get(f"{base}{path}", params=payload)
            except Exception as e:  # noqa: BLE001 — 网络异常不应中断整次扫描
                if attempt >= TMDB_NET_RETRIES:
                    self._stats["net_fail"] += 1
                    logger.warning("TMDB 请求失败 %s（重试 %s 次后放弃）: %s", path, attempt, e)
                    return None
                self._stats["retry"] += 1
                # 加抖动：多个 worker 同时撞上抖动时不要齐步重打
                time.sleep(delay + random.random() * 0.25)
                delay = min(delay * 2, 4.0)
        return None

    def _get(self, path: str, params: dict) -> Optional[dict]:
        """带密钥轮询的 GET：限流 → 网络重试 → 429 退避/换 key（v2.42.9 收口）

        旧实现的限速是「条目/秒」且只在补全那条路上：一个条目背后是 0~6 次 HTTP，
        于是「2/秒」实际打出去 4~12 请求/秒，而扫描那条路完全没限速。现在两条路都
        收敛到 `_request()` 的同一个桶上，口径与 TMDB 配额一致（``tmdb_req`` 阶段计数
        记的是**请求**，与这个桶同一个口径；旧的条目级桶记的是条目，两者对不上正是
        积压期最容易看错的地方）。

        429 也不再是「单 key 直接放弃」：真的读 `Retry-After` 并据此退避，同时把
        速率自适应减半——否则后续条目会在同一个窗口里继续把配额撞满。
        """
        self._ensure_session()
        if not self.session:
            return None
        total = max(1, len(self.api_keys))
        tried: set[str] = set()
        last_wait = 0.0
        while True:
            # 先跳在冷却里的 key；全都在冷却时宁可硬用一把（冷却是优化，不是锁死）
            key = self._pick_key(tried) or self._pick_key(tried, allow_cooled=True)
            if not key:
                break
            tried.add(key)
            r = self._request(path, params, key)
            if r is None:
                return None
            status = r.status_code
            if status in (401, 429):
                if status == 429:
                    wait = self._throttle(_retry_after_seconds(r))
                    self.note_key_throttled(key, wait)
                else:
                    wait = 0.0
                    self.note_key_invalid(key)
                last_wait = max(last_wait, wait)
                # 还有别的 key 就换一把（配额是按 key 算的，每把 key 只试一次）
                if len(tried) < total:
                    if wait > 0:
                        time.sleep(min(wait, 1.0))
                    continue
                break
            if status >= 400:
                logger.warning("TMDB 响应异常 %s: HTTP %s", path, status)
                return None
            try:
                data = r.json()
            except Exception:  # noqa: BLE001
                return None
            # 成功一次就清掉这把的失败计数（它可能只是碰到了临时配额窗口）
            with self._key_lock():
                entry = self._cooldown_map().pop(key, None)
            if entry:
                logger.info("TMDB 密钥 ****%s 恢复正常", key[-4:])
            self._limiter.note_success()
            return data
        if last_wait > 0:
            # 全部 key 都不可用：退避一轮再放行后续请求（这段窗口内的条目会
            # 落到重试队列，而不是继续把已经超限的配额撞满）
            time.sleep(last_wait)
        logger.warning("TMDB 全部密钥不可用或已用尽")
        return None

    @property
    def configured(self) -> bool:
        return bool(self.api_keys)

    def stats(self) -> dict:
        """运行观测：实际限速、429 次数、网络重试/失败、Tier 2 短路次数（v2.42.9）

        限速是**自适应**的（撞 429 减半、连续成功再慢慢加回来），所以「配置里写的
        ENRICH_TMDB_PER_SEC」并不等于「实际在打的速率」——管理后台要看这里的实际值。
        """
        return {
            "rate": round(self._limiter.rate, 3),
            "ceiling": round(self._limiter.ceiling, 3),
            "throttled": self._limiter.throttled_count,
            "retries": self._stats["retry"],
            "net_fail": self._stats["net_fail"],
            "short_circuits": self._stats["short_circuit"],
            "keys_cooling": len([row for row in self.key_pool() if row["cooling"]]),
        }

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
        """原始搜索（带两级缓存），返回 results 列表。

        L1 进程内（300 秒，同一次扫描的预热/写库复用）→ L2 磁盘
        （``tmdb_cache``，跨进程/跨重启，search 命中 7 天、阴性 24 小时）
        → 单飞后真的发请求。缓存键用 ``_norm_text`` 归一化（年份独立维度）：
        同一部剧的两个文件名（``Some Show`` 与 ``Some Show (2024)``）不再各打
        一遍——跨条目去重从此可靠而非碰运气（§7.3③）。
        请求失败（data=None）**不落盘**：让这类条目照旧走重试队列。
        """
        self._ensure_session()
        if not self.session:
            return []
        endpoint = "tv" if kind == "series" else "movie"
        norm = _norm_text(query)
        key = ("search", endpoint, norm, year or 0)
        cached = self._cache_get(key)
        if cached is not _MISS:
            return cached or []
        hit, results = tmdb_cache.load_search(endpoint, norm, year or 0)
        if hit:
            progress.note_stage("tmdb_disk_hit")
            self._cache_put(key, results)   # 回填 L1：同批后续请求走内存
            return results or []
        with tmdb_cache.single_flight(key):
            # 拿到锁后二次检查：等锁期间别的线程可能已经填好 L1 或磁盘
            cached = self._cache_get(key)
            if cached is not _MISS:
                return cached or []
            hit, results = tmdb_cache.load_search(endpoint, norm, year or 0)
            if hit:
                progress.note_stage("tmdb_disk_hit")
                self._cache_put(key, results)
                return results or []
            params: dict = {"language": TMDB_LANG, "query": query}
            if year:
                if endpoint == "tv":
                    params["first_air_date_year"] = year
                else:
                    params["year"] = year
            data = self._get(f"/search/{endpoint}", params)
            results = (data or {}).get("results") or []
            if data is not None:
                tmdb_cache.save_search(endpoint, norm, year or 0, results)
            self._cache_put(key, results)
            return results

    def search(self, name: str, year: Optional[int], kind: str) -> Optional[dict]:
        """智能搜索：清洗查询 → 多候选 → 置信度校验，只返回高置信命中。

        无高置信命中时返回 None（调用方按既有口径记 last_scraped_at，
        条目名字保持原样，绝不写错）。
        """
        best = None  # (tier, rank, hit)：跨候选、跨结果取全局最可信
        for query, fuzzy_ok in _search_candidates(name):
            # 短路（v2.42.9）：已有 Tier 2（归一化后**精确相等**）就收手。
            # Tier 2 永远压过 Tier 1（元组比较先看 tier），后续候选最多只能换来
            # 「更长的精确变体」这一个 rank 的差别，不值得再打 1~4 次 HTTP。
            # 中文短标题的候选数最多（4~5 个）而命中率最低，正是这一条最划算的地方。
            if best is not None and best[0] == 2:
                self._stats["short_circuit"] += 1
                progress.note_stage("tmdb_search_short")
                break
            try:
                results = self._search_raw(query, year, kind)
            except Exception:  # noqa: BLE001 — 单个候选失败换下一个
                continue
            for hit in results[:10]:
                sc = _hit_score(name, query, hit, fuzzy_ok)
                if sc and (best is None or sc > best[:2]):
                    best = (sc[0], sc[1], hit)
        return best[2] if best else None

    def search_candidates(self, name: str, kind: str, limit: int = 6) -> list[dict]:
        """原始候选搜索（求片中心用）：不做置信度裁剪，用户自己认片

        刮削要的是「唯一正确答案」（``search()`` 会按置信度裁剪、宁缺毋滥），
        而求片要的是「一组候选」：用户搜什么就列什么，选哪部由他决定。
        同样走两级缓存与请求限流，失败返回空表（不让一次网络抖动把用户的搜索框打成报错）。
        """
        query = _clean_query(name) or (name or "").strip()
        if not query:
            return []
        try:
            results = self._search_raw(query, None, kind)
        except Exception:  # noqa: BLE001 — 与 search() 同口径：单个查询失败不当成致命错误
            return []
        return [hit for hit in list(results or [])[:limit] if isinstance(hit, dict)]

    def details(self, tmdb_id: str, kind: str) -> Optional[dict]:
        """详情（补 IMDb Id 与多别名）——只在条目缺这两项时调用。

        两级缓存同 ``_search_raw``（L1 300 秒 → L2 磁盘 30 天，按 id 键）。
        """
        endpoint = "tv" if kind == "series" else "movie"
        key = ("details", endpoint, str(tmdb_id))
        cached = self._cache_get(key)
        if cached is not _MISS:
            return cached
        hit, data = tmdb_cache.load_details(endpoint, str(tmdb_id))
        if hit:
            progress.note_stage("tmdb_disk_hit")
            self._cache_put(key, data)
            return data
        with tmdb_cache.single_flight(key):
            cached = self._cache_get(key)
            if cached is not _MISS:
                return cached
            hit, data = tmdb_cache.load_details(endpoint, str(tmdb_id))
            if hit:
                progress.note_stage("tmdb_disk_hit")
                self._cache_put(key, data)
                return data
            data = self._get(f"/{endpoint}/{tmdb_id}",
                             {"language": TMDB_LANG,
                              "append_to_response": "alternative_titles,external_ids"})
            if data is not None:
                tmdb_cache.save_details(endpoint, str(tmdb_id), data)
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
        # 详情只补缺项（简介/评分/别名/类型），不覆盖 NFO 提供的文字。
        # 用 getattr 兜底：调用方（含测试里的轻量替身）未必带这个字段。
        if not getattr(item, "metadata_source", None):
            item.metadata_source = "tmdb"
        # 类型：详情接口直接给 genres=[{id, name}]（language=zh-CN 下 name 已是中文）。
        # 这是「有 tmdb_id 却无类型」的主因：以前 apply_details 完全忽略它，
        # 凡走 tmdb_id → 详情分支的（NFO 自带 tmdb_id、别名匹配、已有 id 补缺）
        # 都永远拿不到类型，只有搜索命中走 apply() 的才有。
        if not (getattr(item, "genres", None) or "").strip():
            gnames = _genres_from_details(data)
            if gnames:
                item.genres = ",".join(gnames)
        imdb = (data.get("external_ids") or {}).get("imdb_id") or data.get("imdb_id")
        if imdb:
            item.imdb_id = imdb
        # 简介与评分也从详情补：搜索结果的 overview/vote_average 经常是空或 0，
        # 只靠 apply() 会让「有 tmdb_id 却缺简介/评分」的一大批永远补不上。
        overview = data.get("overview")
        if overview:
            item.overview = overview
        rating = data.get("vote_average")
        if rating is not None and rating != "":
            try:
                item.community_rating = round(float(rating), 1)
            except (TypeError, ValueError):
                pass
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
        # 修复路径同样是「先落盘再落字段」：写库阶段不发 HTTP（见 _set_image）
        image_store.prewarm(url for _kind, url in image_specs(data))
        return self.apply_images(item, data)

    def apply_images(self, item: emby_models.MediaItem, data: dict) -> bool:
        """把详情接口里的图片落到条目上（返回是否拿到图）"""
        if not data:
            return False
        specs = image_specs(data)
        for img_kind, url in specs:
            _set_image(item, img_kind, url)
        if specs and getattr(item, "metadata_source", None) == "nfo":
            # NFO 管文字、TMDB 补图（B 方案）——这是最常见的组合，单独标记出来
            item.metadata_source = "tmdb_img"
        return bool(specs)

    def apply(self, item: emby_models.MediaItem, hit: dict, kind: str) -> None:
        item.tmdb_id = str(hit.get("id"))
        item.last_scraped_at = datetime.now()
        # 文字与图片都来自 TMDB 搜索结果
        item.metadata_source = "tmdb"
        item.overview = hit.get("overview") or item.overview
        rating = hit.get("vote_average")
        # 注意不能用 `if rating:`：TMDB 对没有评分的条目返回 0.0，那是**合法数据**，
        # 判假值会让这类条目永远没有评分（生产实测 21天重养自己 就是 0.0）。
        if rating is not None and rating != "":
            try:
                item.community_rating = round(float(rating), 1)
            except (TypeError, ValueError):
                pass
        for img_kind, url in image_specs(hit):
            _set_image(item, img_kind, url)
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
            item.genres = ",".join(
                _GENRE_NAMES.get(g, str(g)) for g in genre_ids[:_MAX_GENRES]
            )


tmdb_client = TmdbClient()  # 进程级单例：一次扫描里的预热与写库共用同一份缓存与连接池
