"""豆瓣兜底刮削（altmeta）：只在 TMDB 搜不到时补，绝不覆盖已有数据。

实测价值：生产 `metadata_source='none'` 的样本里，豆瓣能找回多数
（电锯人→链锯人：刺客篇、落语朱音→朱音落语、B PROJECT→B-PROJECT）。

关键不变量：
1. 只兜底不覆盖——已有 TMDB 命中的条目一律不动；
2. 匹配要严——首条标题对不上就丢弃，宁可漏也不错配；
3. subject_suggest 没有简介/评分，所以补到标题/年份/海报就算完成，
   否则这批条目会永远停在 pending 反复重试。
"""
import json
from types import SimpleNamespace

from backend.emby_server import altmeta


def _item(**kw):
    base = dict(tmdb_id=None, last_scraped_at=None, overview=None,
                community_rating=None, primary_image_url=None, poster_path=None,
                backdrop_path=None, backdrop_image_url=None, name="原名",
                production_year=None, metadata_source=None, douban_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _resp(monkeypatch, payload):
    class _R:
        status = 200

        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request
    monkeypatch.setattr(altmeta.urllib.request, "urlopen", lambda *a, **k: _R())


def test_search_returns_hit_when_title_matches(monkeypatch):
    _resp(monkeypatch, [{"title": "电锯人", "year": "2026", "type": "tv",
                         "id": "1", "img": "http://img/p.jpg"}])
    hit = altmeta.search("电锯人", 2026, "series", per_min=0)
    assert hit and hit["title"] == "电锯人"
    assert hit["year"] == "2026"


def test_search_discards_mismatched_title(monkeypatch):
    """首条标题对不上必须丢弃——宁可漏也不错配"""
    _resp(monkeypatch, [{"title": "完全不相干的片子", "year": "2020", "type": "tv"}])
    assert altmeta.search("电锯人", 2020, "series", per_min=0) is None


def test_search_discards_year_mismatch(monkeypatch):
    _resp(monkeypatch, [{"title": "同名剧", "year": "2015", "type": "tv"}])
    assert altmeta.search("同名剧", 2023, "series", per_min=0) is None


def test_search_rejects_movie_for_series(monkeypatch):
    """类型不符（电影 vs 剧集）不能当成剧集写入"""
    _resp(monkeypatch, [{"title": "同名", "year": "2020", "type": "movie"}])
    assert altmeta.search("同名", 2020, "series", per_min=0) is None


def test_search_empty_query_returns_none():
    assert altmeta.search("", None, "series", per_min=0) is None
    assert altmeta.search(None, None, "series", per_min=0) is None


def test_search_survives_network_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(altmeta.urllib.request, "urlopen", boom)
    assert altmeta.search("任意片名", None, "series", per_min=0) is None


def test_apply_does_not_overwrite_tmdb_data():
    """已有 TMDB 名字/海报/简介时，豆瓣不得覆盖"""
    it = _item(name="用户整理的名字", production_year=2020, overview="原简介",
               poster_path="/keep.jpg")
    altmeta.apply(it, {"title": "豆瓣名", "year": "2026", "image": "http://douban/x.jpg"})
    assert it.name == "用户整理的名字", it.name
    assert it.production_year == 2020, it.production_year
    assert it.overview == "原简介"
    assert it.poster_path == "/keep.jpg", it.poster_path
    assert it.metadata_source == "douban"


def test_apply_fills_gaps_for_unmatched_item():
    """什么都没有的条目：补标题/年份/海报，并打上 douban 来源"""
    it = _item()
    altmeta.apply(it, {"title": "朱音落语", "year": "2026",
                       "image": "http://douban/p.jpg"})
    assert it.name == "朱音落语", it.name
    assert it.production_year == 2026
    assert it.primary_image_url == "http://douban/p.jpg", it.primary_image_url
    assert it.metadata_source == "douban"


def test_rate_per_min_reads_config():
    db = SimpleNamespace(query=lambda *a, **k: SimpleNamespace(
        filter=lambda *x, **y: SimpleNamespace(
            first=lambda: SimpleNamespace(value="12.5"))))
    assert altmeta.rate_per_min(db) == 12.5


def test_workers_reads_config():
    db = SimpleNamespace(query=lambda *a, **k: SimpleNamespace(
        filter=lambda *x, **y: SimpleNamespace(
            first=lambda: SimpleNamespace(value="5"))))
    assert altmeta.workers(db) == 5
