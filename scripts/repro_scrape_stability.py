"""复现「刮削不稳定」与「标题带冒号」——修复后跑出应全 ✅（修复前 1/10）。

问题一（不稳定）的机制（修复前实测）：
  1. search()/details() 瞬态失败（网络耗尽/5xx/429 全 key）返回 None —— 与「真搜不到」
     不可区分 → enrich 写终态 done+metadata_source='none'，条目永久不再重试；
  2. L1 把失败当「空结果」缓存 300 秒 → 网络恢复后同批条目仍搜不到；
  3. details() 失败进负缓存且不触发 ok=False → 条目写成「缺 IMDb/别名/演员」的半成品；
  4. 图片下载单次尝试、无重试，最终失败只打 INFO（看不见）。
问题二：apply() 只剥年份后缀，"黑鸟：第一季" 原样写进 item.name。

修复后（v2.53.0）本脚本应 10/10；正式回归由以下用例钉住：
  tests/test_tmdb_transient.py / tests/test_title_clean.py /
  tests/test_image_download_retry.py / tests/test_enrich_worker.py

用法：python3 scripts/repro_scrape_stability.py
"""
import logging
import os
import sys
from types import SimpleNamespace

os.environ["EMBY_TMDB_CACHE"] = "0"          # 关磁盘缓存：数真实 HTTP
os.environ.pop("TMDB_API_KEYS", None)
os.environ.pop("TMDB_API_KEY", None)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 拦掉真实 sleep（_request 退避 / 429 退避都会睡）
import time as _time
_orig_sleep = _time.sleep
_time.sleep = lambda s: None

from backend.emby_server import tmdb as tmdb_mod          # noqa: E402
from backend.emby_server import image_store               # noqa: E402
from backend.emby_server.tmdb import TmdbClient           # noqa: E402

tmdb_mod._read_config_value = lambda db: ""               # 密钥不读库

CHECKS = []


def check(name: str, ok: bool, detail: str) -> None:
    CHECKS.append(bool(ok))
    print(f"{'✅' if ok else '❌'} {name}: {detail}")


class _Resp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return {} if self._payload is None else self._payload


class _Session:
    def __init__(self, answer):
        self.calls = []
        self._answer = answer

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        return self._answer(url, params)


def _client(answer) -> TmdbClient:
    TmdbClient._cache.clear()
    client = TmdbClient()
    client._set_keys(["k_repro"], "env")
    client._limiter = tmdb_mod._RequestLimiter(rate=1_000_000.0, min_rate=1.0)
    client.session = _Session(answer)
    client._ensure_session = lambda: None
    return client


def _raised(fn):
    """跑 fn：返回 ('raise', exc) / ('return', value)"""
    try:
        return "return", fn()
    except Exception as exc:  # noqa: BLE001
        return "raise", exc


NAME = "进击的巨人 (2013) 中字"


def repro_search_transient() -> None:
    """网络彻底不通时，search 应抛可重试异常；修复前返回 None（= 终态搜不到）"""
    def boom(url, params):
        raise ConnectionError("network unreachable")

    client = _client(boom)
    kind, val = _raised(lambda: client.search(NAME, 2013, "series"))
    check("search 瞬态失败抛 TmdbTransientError",
          kind == "raise" and val.__class__.__name__ == "TmdbTransientError",
          f"现状：{kind} = {val!r}")

    # 失败不得污染 L1：修复前 [] 被缓存 300s，第二个同名查询 0 请求
    before_calls = len(client.session.calls)
    _raised(lambda: client.search(NAME, 2013, "series"))
    extra = len(client.session.calls) - before_calls
    check("失败后 L1 不缓存空结果（再次查询真发请求）",
          extra > 0,
          f"第二次 search 只新增 {extra} 次 HTTP（修复前 0 次=被投毒 300 秒）")


def repro_details_transient() -> None:
    """details 瞬态失败应抛出；修复前 None 且进负缓存（enrich 写半成品后 done）"""
    def boom(url, params):
        raise ConnectionError("network unreachable")

    client = _client(boom)
    kind, val = _raised(lambda: client.details("197646", "series"))
    check("details 瞬态失败抛 TmdbTransientError",
          kind == "raise" and val.__class__.__name__ == "TmdbTransientError",
          f"现状：{kind} = {val!r}")


def repro_http_statuses() -> None:
    # 5xx：TMDB 服务端错误 → 可重试
    client = _client(lambda url, params: _Resp(status=503))
    kind, val = _raised(lambda: client.search(NAME, 2013, "series"))
    check("5xx 抛 TmdbTransientError（转重试队列）",
          kind == "raise", f"现状：{kind} = {val!r}")

    # 429 全 key → 应抛；修复前睡完 Retry-After 返回 None
    client = _client(lambda url, params: _Resp(
        status=429, headers={"Retry-After": "1"}))
    kind, val = _raised(lambda: client.search(NAME, 2013, "series"))
    check("429 全 key 试尽抛 TmdbTransientError",
          kind == "raise", f"现状：{kind} = {val!r}")

    # 404：真没有 → 返回 None（不抛，保持「阴性」语义）
    client = _client(lambda url, params: _Resp(status=404))
    kind, val = _raised(lambda: client.search(NAME, 2013, "series"))
    check("404 返回 None（不误报成瞬态）",
          kind == "return" and val is None, f"现状：{kind} = {val!r}")


def repro_title_colon() -> None:
    """apply() 写 name：冒号副标题应被切掉"""
    from backend.emby_server.tmdb import TmdbClient as TC

    item = SimpleNamespace(
        tmdb_id=None, last_scraped_at=None, metadata_source=None,
        overview=None, community_rating=None, poster_path=None,
        primary_image_url=None, backdrop_path=None, backdrop_image_url=None,
        name="黑鸟", aliases="", genres="", production_year=None, imdb_id=None,
    )
    hit = {"id": 900, "name": "黑鸟：第一季", "first_air_date": "2023-01-05"}
    TC().apply(item, hit, "series")
    check("标题冒号副标题被清洗",
          item.name == "黑鸟", f"现状：item.name = {item.name!r}")

    # 控制字符与冒号副标题一起清（引号/尖括号同样不该出现在标题里）
    item2 = SimpleNamespace(
        tmdb_id=None, last_scraped_at=None, metadata_source=None,
        overview=None, community_rating=None, poster_path=None,
        primary_image_url=None, backdrop_path=None, backdrop_image_url=None,
        name="x", aliases="", genres="", production_year=None, imdb_id=None,
    )
    TC().apply(item2, {"id": 1, "title": '迷宫\t第七话：终局 <ver>\x07'},
               "movie")
    check("控制字符/冒号副标题被清洗",
          item2.name == "迷宫 第七话", f"现状：item.name = {item2.name!r}")


def repro_image_retry() -> None:
    """图片下载失败应重试并打 WARNING；修复前只试 1 次且只打 INFO"""
    attempts = {"n": 0}
    logs = []

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            attempts["n"] += 1
            raise ConnectionError("cdn unreachable")

    sys.modules["httpx"] = SimpleNamespace(Client=_FakeClient)

    class _H(logging.Handler):
        def emit(self, record):
            logs.append(record)

    handler = _H()
    image_store.logger.addHandler(handler)
    try:
        got = image_store._download("https://image.tmdb.org/t/p/w500/x.jpg")
    finally:
        image_store.logger.removeHandler(handler)

    want = 1 + int(os.getenv("EMBY_IMAGE_RETRIES", "2"))
    check("图片下载失败自动重试", attempts["n"] >= want and got is None,
          f"实际尝试 {attempts['n']} 次（修复前 1 次，期望 {want} 次）")
    warn = [r for r in logs if r.levelno >= logging.WARNING]
    check("最终失败打 WARNING 日志", bool(warn),
          f"捕获 {len(logs)} 条日志，WARNING {len(warn)} 条（修复前 0 条）")


def main() -> int:
    repro_search_transient()
    repro_details_transient()
    repro_http_statuses()
    repro_title_colon()
    repro_image_retry()
    total = len(CHECKS)
    passed = sum(CHECKS)
    print(f"\n{passed}/{total} 通过"
          + ("" if passed == total else "（未全过：修复被回退或有新回归）"))
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _time.sleep = _orig_sleep
