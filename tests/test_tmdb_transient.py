"""瞬态失败与「真搜不到」必须分得开（问题一：刮削时好时坏的根因）。

复现脚本 ``scripts/repro_scrape_stability.py``（修复前 1/10，修复后 10/10）证明：

- 网络重试耗尽 / 5xx / 响应解析失败 / 全 key 429 → 旧实现返回 ``None``，
  与「真搜不到」不可区分 → ``_enrich_apply`` 写终态 ``done + metadata_source='none'``，
  条目从此不再重试；L1 还把失败当空结果缓存 300 秒，网络恢复也白搭。
- 修复后这些情况抛 ``TmdbTransientError``：补全 worker 走既有的
  ``ok=False → _mark_failed`` 指数退避重试（见 tests/test_enrich_worker.py 的集成用例）。
- 404 / 401 / 未配置仍返回 ``None``（阴性语义，不烧重试预算）。

全部在假会话上跑，不发真请求。
"""
from types import SimpleNamespace

import pytest

from backend.emby_server import tmdb as tmdb_mod
from backend.emby_server.tmdb import TmdbClient, TmdbTransientError

NAME = "迷宫 (2013) 中字"   # 中文标题：_search_candidates 给 3 个候选


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    """空缓存起步（L1 是类级 dict 全进程共享），并关掉磁盘缓存（数真实 HTTP）"""
    monkeypatch.setenv("EMBY_TMDB_CACHE", "0")
    TmdbClient._cache.clear()
    yield
    TmdbClient._cache.clear()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """_request 的网络退避、429 的 Retry-After 都会睡——用例不真睡"""
    monkeypatch.setattr(tmdb_mod.time, "sleep", lambda s: None)


class _Session:
    """假会话：记录每次请求，结果由 answer 决定"""

    def __init__(self, answer):
        self.calls = []
        self._answer = answer

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        return self._answer(url, params)


def _resp(status=200, payload=None, headers=None):
    class _R:
        status_code = status

        def json(self):
            if isinstance(payload, Exception):
                raise payload
            return {} if payload is None else payload

    _R.headers = headers or {}
    return _R()


def _client(monkeypatch, answer) -> TmdbClient:
    """不带 env key 的客户端 + 假会话（与 test_tmdb_limiter 同一套 harness）"""
    monkeypatch.delenv("TMDB_API_KEYS", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.setattr(tmdb_mod, "_read_config_value", lambda db: "")
    client = TmdbClient()
    client._set_keys(["k1"], "env")
    client._limiter = tmdb_mod._RequestLimiter(rate=1_000_000.0, min_rate=1.0)
    client.session = _Session(answer)
    monkeypatch.setattr(client, "_ensure_session", lambda: None)
    return client


# ---------- _get：什么抛、什么返回 None ----------

def test_network_exhausted_raises(monkeypatch):
    """网络异常重试耗尽 → 抛（吞成 None 就是终态 none 的根因）"""
    def boom(url, params):
        raise ConnectionError("network unreachable")

    client = _client(monkeypatch, boom)
    with pytest.raises(TmdbTransientError):
        client._get("/search/tv", {"query": "x"})
    # 每个 key/请求都真的退避重试过（TMDB_NET_RETRIES 默认 2 → 3 次尝试）
    assert len(client.session.calls) == tmdb_mod.TMDB_NET_RETRIES + 1


def test_5xx_raises(monkeypatch):
    """TMDB 服务端错误（5xx）→ 抛（旧实现只打一条 warning 就当阴性）"""
    client = _client(monkeypatch, lambda u, p: _resp(status=503))
    with pytest.raises(TmdbTransientError):
        client._get("/search/tv", {"query": "x"})


def test_bad_json_raises(monkeypatch):
    """200 却解析不出（多半是网关错误页）→ 抛，不当阴性缓存"""
    client = _client(monkeypatch, lambda u, p: _resp(payload=ValueError("no json")))
    with pytest.raises(TmdbTransientError):
        client._get("/search/tv", {"query": "x"})


def test_all_keys_429_raises(monkeypatch):
    """全部密钥撞限流（配额窗口未恢复）→ 抛；退避已按 Retry-After 执行"""
    client = _client(monkeypatch, lambda u, p: _resp(
        status=429, headers={"retry-after": "1"}))
    with pytest.raises(TmdbTransientError):
        client._get("/search/tv", {"query": "x"})


def test_404_stays_none(monkeypatch):
    """404 是「真没有」→ 返回 None（阴性语义不烧重试预算）"""
    client = _client(monkeypatch, lambda u, p: _resp(status=404))
    assert client._get("/tv/999", {}) is None


def test_all_keys_401_stays_none(monkeypatch):
    """全 401 是密钥配置坏掉（换 key 才能修）→ 返回 None，不进重试队列空转"""
    client = _client(monkeypatch, lambda u, p: _resp(status=401))
    assert client._get("/search/tv", {"query": "x"}) is None


# ---------- search：候选失败与命中的取舍 ----------

def test_search_raises_when_no_candidate_succeeded(monkeypatch):
    """网络彻底不通：一个候选都没拿到真实响应 → 整次上抛（不是「搜过没有」）"""
    def boom(url, params):
        raise ConnectionError("network unreachable")

    client = _client(monkeypatch, boom)
    with pytest.raises(TmdbTransientError):
        client.search(NAME, 2013, "series")


def test_transient_failure_does_not_poison_l1(monkeypatch):
    """失败不落 L1：修复前空结果被缓存 300 秒，网络恢复后同批依旧搜不到"""
    def boom(url, params):
        raise ConnectionError("network unreachable")

    client = _client(monkeypatch, boom)
    with pytest.raises(TmdbTransientError):
        client.search(NAME, 2013, "series")
    first = len(client.session.calls)
    with pytest.raises(TmdbTransientError):
        client.search(NAME, 2013, "series")
    assert len(client.session.calls) > first, "第二次 search 必须真发请求（未被投毒）"


def test_search_returns_hit_when_later_candidate_transient(monkeypatch):
    """个别候选瞬态失败、别的候选命中 → 返回命中（部分失败不挡命中）"""
    assert len(list(tmdb_mod._search_candidates(NAME))) >= 3, "候选塌缩了测不出取舍"
    client = _client(monkeypatch, lambda u, p: _resp())
    calls = {"n": 0}

    def fake_search_raw(query, year, kind):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TmdbTransientError("boom")
        # 结果与查询同名 → 置信度必然命中
        return [{"id": 9, "name": query, "first_air_date": "2013-04-07"}]

    monkeypatch.setattr(client, "_search_raw", fake_search_raw)
    hit = client.search(NAME, 2013, "series")
    assert hit is not None and hit["id"] == 9


def test_search_none_when_all_candidates_answered_empty(monkeypatch):
    """全部候选正常返回但没命中 → 仍是 None（真搜不到，终态语义不变）"""
    client = _client(monkeypatch, lambda u, p: _resp(payload={"results": []}))
    assert client.search(NAME, 2013, "series") is None


def test_search_candidates_graceful_with_warning(monkeypatch, caplog):
    """求片中心契约：瞬态失败也不 500，返回空表但留下 WARNING"""
    def fake_search_raw(query, year, kind):
        raise TmdbTransientError("boom")

    client = _client(monkeypatch, lambda u, p: _resp())
    monkeypatch.setattr(client, "_search_raw", fake_search_raw)
    with caplog.at_level("WARNING", logger="backend.emby_server.tmdb"):
        assert client.search_candidates("黑鸟", "series") == []
    assert any("暂时不可用" in r.getMessage() for r in caplog.records)


# ---------- 单集补全：瞬态上抛、真没这集静默 ----------

def test_fetch_episode_reraises_transient(monkeypatch):
    """``_fetch_episode_tmdb``：瞬态 → 上抛（整条进重试队列）；其它异常保持静默"""
    from backend.emby_server import enrich_worker

    item = SimpleNamespace(season_number=1, episode_number=2)
    parent = {"tmdb_id": "123"}
    monkeypatch.setattr(
        TmdbClient, "find_episode",
        lambda self, *a, **k: (_ for _ in ()).throw(
            TmdbTransientError("TMDB 网络请求失败（重试耗尽）: /tv/123/season/1")))
    result: dict = {}
    with pytest.raises(TmdbTransientError):
        enrich_worker._fetch_episode_tmdb(item, parent, result)
    assert "episode_tmdb" not in result

    # 非瞬态（如接口报错/脏数据）→ 依旧静默，不影响纯继承主流程
    monkeypatch.setattr(
        TmdbClient, "find_episode",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    result2: dict = {}
    enrich_worker._fetch_episode_tmdb(item, parent, result2)
    assert "episode_tmdb" not in result2
