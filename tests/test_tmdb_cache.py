"""TMDB 刮削缓存与详情预取的口径（v2.31.0 扫描 / 刮削优化）

这里的每一条都「只是快一点」，但它们决定的是**扫描规模变大后配额花不花得值**：

- **缓存满了不再整表清空**：搜索与详情各占一条，一万部片子刚好撞上 ``_CACHE_MAX``（两万条）。
  整表清空会把「刚预热好的结果」连整张表一起扔掉，写库线程随后要取同一个片名就变成一次真的
  网络请求——规模越接近上限越容易撞上（预热与写库用的是同一份缓存，正是为了不重复花配额）。
  现在只淘汰最旧的一批，并保留大部分预热结果。
- **过期条目在读取时顺手删掉**：留着只会占名额，满载时把还在窗口内的预热结果挤出去。
- **详情只在写库那一步真的会用时才预取**：「到期重刮且 IMDb Id / 别名都齐」的条目不会取详情，
  预取却无条件对每个搜索命中拉一次详情——那部分配额是白花的。

这些是不碰网络、不碰数据库的纯逻辑，所以放在 ``tests/``（pytest）里，让它们也在
「只有 pytest 会跑」的那条门禁上守着；扫描器的端到端行为在 ``scripts/smoke_test_scan_*``。
"""
from datetime import datetime, timedelta

import pytest

from backend.emby_server import tmdb as tmdb_mod
from backend.emby_server.tmdb import TmdbClient


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个用例都从空缓存开始（``_cache`` 是类级 dict，整个进程共享）"""
    TmdbClient._cache.clear()
    yield
    TmdbClient._cache.clear()


@pytest.fixture
def cache_max(monkeypatch):
    """把上限压小，几行就能走到淘汰路径（不必真造两万条）"""
    monkeypatch.setattr(TmdbClient, "_CACHE_MAX", 10)
    return 10


def _client(monkeypatch) -> TmdbClient:
    """不配密钥的客户端：本文件只验证缓存逻辑，不需要 HTTP 会话"""
    monkeypatch.delenv("TMDB_API_KEYS", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    return TmdbClient()


def test_roundtrip_and_cached_none_is_a_hit(monkeypatch):
    client = _client(monkeypatch)
    client._cache_put("k", {"id": 1})
    assert client._cache_get("k") == {"id": 1}
    # 「没搜到」（None）也是合法结果，必须与「没查过」（_MISS）区分开
    client._cache_put("none", None)
    assert client._cache_get("none") is None
    assert client._cache_get("missing") is tmdb_mod._MISS


def test_expired_entry_is_dropped_on_read(monkeypatch):
    client = _client(monkeypatch)
    TmdbClient._cache["old"] = (
        datetime.now() - timedelta(seconds=TmdbClient._CACHE_TTL + 5), "v",
    )
    assert client._cache_get("old") is tmdb_mod._MISS
    assert "old" not in TmdbClient._cache      # 过期条目不再占名额


def test_full_cache_evicts_oldest_but_keeps_recent(monkeypatch, cache_max):
    client = _client(monkeypatch)
    for i in range(cache_max):
        client._cache_put(f"k{i}", i)
    assert len(TmdbClient._cache) == cache_max

    client._cache_put("fresh", "v")            # 触发一次淘汰
    keep = max(1, int(cache_max * TmdbClient._CACHE_KEEP_RATIO))
    assert len(TmdbClient._cache) == keep
    assert "fresh" in TmdbClient._cache
    assert "k0" not in TmdbClient._cache                        # 最旧的被淘汰
    # 最近的必须留下：旧实现（整表清空）会把刚预热好的 k9 一起扔掉，
    # 而写库线程马上要用它——那一次就变成真的网络请求
    assert f"k{cache_max - 1}" in TmdbClient._cache


def test_expired_entries_are_reaped_before_recent_ones(monkeypatch, cache_max):
    client = _client(monkeypatch)
    stale = datetime.now() - timedelta(seconds=TmdbClient._CACHE_TTL + 5)
    for i in range(cache_max):
        TmdbClient._cache[f"e{i}"] = (stale, i)

    client._cache_put("fresh", "v")
    # 全部过期 → 先整批清掉，不必再按写入顺序淘汰
    assert list(TmdbClient._cache) == ["fresh"]


def test_updating_an_existing_key_does_not_evict(monkeypatch, cache_max):
    client = _client(monkeypatch)
    for i in range(cache_max):
        client._cache_put(f"k{i}", i)

    client._cache_put("k0", "updated")         # 已存在的键：覆盖，不动别人
    assert len(TmdbClient._cache) == cache_max
    assert client._cache_get("k0") == "updated"


# ==================== 详情预取的口径 ====================

def test_details_only_fetched_when_the_write_step_needs_them(monkeypatch):
    """搜索命中、但写库那一步不用详情 → 不额外拉一次详情"""
    from backend.emby_server import scanner as sc

    calls: list = []

    class FakeClient:
        configured = True

        def search(self, name, year, kind):
            calls.append("search")
            return {"id": 42}

        def details(self, tmdb_id, kind):
            calls.append("details")
            return {"id": tmdb_id}

    monkeypatch.setattr(sc, "tmdb_client", FakeClient())

    hit, details = sc._tmdb_work(True, "Movie", 2020, "movie", None, False)
    assert hit == {"id": 42} and details is None
    assert calls == ["search"]

    calls.clear()
    hit, details = sc._tmdb_work(True, "Movie", 2020, "movie", None, True)
    assert details == {"id": "42"}
    assert calls == ["search", "details"]


def test_details_falls_back_to_the_stored_id(monkeypatch):
    """搜索没命中（比如已有 tmdb_id 只是要补信息）时，用库里存的 id 取详情"""
    from backend.emby_server import scanner as sc

    calls: list = []

    class FakeClient:
        configured = True

        def search(self, name, year, kind):
            calls.append("search")
            return None

        def details(self, tmdb_id, kind):
            calls.append(("details", tmdb_id))
            return {"id": tmdb_id}

    monkeypatch.setattr(sc, "tmdb_client", FakeClient())

    hit, details = sc._tmdb_work(True, "Movie", 2020, "movie", "77", True)
    assert hit is None and details == {"id": "77"}
    assert calls == ["search", ("details", "77")]

    calls.clear()
    hit, details = sc._tmdb_work(True, "Movie", 2020, "movie", "77", False)
    assert details is None and calls == ["search"]     # 不需要详情就不白花配额


def test_no_search_when_search_is_not_needed(monkeypatch):
    """只需补详情（已有 tmdb_id、策略又不重刮）时不该再搜一次"""
    from backend.emby_server import scanner as sc

    calls: list = []

    class FakeClient:
        configured = True

        def search(self, name, year, kind):
            calls.append("search")
            return {"id": 1}

        def details(self, tmdb_id, kind):
            calls.append(("details", tmdb_id))
            return {"id": tmdb_id}

    monkeypatch.setattr(sc, "tmdb_client", FakeClient())

    hit, details = sc._tmdb_work(False, "Movie", 2020, "movie", "1", True)
    assert hit is None and details == {"id": "1"}
    assert calls == [("details", "1")]
