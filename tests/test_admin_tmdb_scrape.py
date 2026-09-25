"""管理后台 · 元数据与刮削

- TMDB Key 来源优先级：环境变量 > SystemConfig；保存后 refresh_keys 立即生效
- 密钥轮询：401 掉线后换下一个，耗尽返回 False
- 界面/日志不泄露原文（masked_keys 只露后 4 位）
- 条目级重刮幂等：重复调用无字段变更
"""
import threading
from types import SimpleNamespace

import pytest

from backend.api import admin_scrape
from backend.emby_server import tmdb as tmdb_mod
from backend.emby_server.tmdb import TmdbClient, _split_keys


@pytest.fixture(autouse=True)
def _clean_cache():
    TmdbClient._cache.clear()
    yield
    TmdbClient._cache.clear()


def _client_no_env(monkeypatch) -> TmdbClient:
    monkeypatch.delenv("TMDB_API_KEYS", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.setattr(tmdb_mod, "_read_config_value", lambda db: "")
    return TmdbClient()


# ---------- _split_keys ----------

def test_split_keys_multi_separators():
    assert _split_keys("a,b\nc d;e，f；g") == ["a", "b", "c", "d", "e", "f", "g"]


def test_split_keys_dedup_and_strip():
    assert _split_keys(" a , a ,\n b ") == ["a", "b"]


def test_split_keys_empty():
    assert _split_keys("") == []
    assert _split_keys(None) == []


# ---------- 来源优先级 ----------

def test_env_wins_over_db(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEYS", "env1,env2")
    monkeypatch.setattr(tmdb_mod, "_db_keys", lambda db=None: ["db1"])
    client = TmdbClient()
    assert client.key_source == "env"
    assert client.api_keys == ["env1", "env2"]
    assert client.configured


def test_db_fallback_when_env_empty(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEYS", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.setattr(tmdb_mod, "_read_config_value", lambda db: "db1\ndb2")
    client = TmdbClient()
    assert client.key_source == "db"
    assert client.api_keys == ["db1", "db2"]
    assert client.configured


def test_none_when_nothing_configured(monkeypatch):
    client = _client_no_env(monkeypatch)
    assert client.key_source == "none"
    assert client.api_keys == []
    assert not client.configured


def test_refresh_keys_hot_reload(monkeypatch):
    """保存即生效：先无 key，DB 有 key 后 refresh_keys() 直接生效，无需重启"""
    client = _client_no_env(monkeypatch)
    assert not client.configured
    monkeypatch.setattr(tmdb_mod, "_read_config_value", lambda db: "newkey")
    info = client.refresh_keys()
    assert info == {"source": "db", "count": 1}
    assert client.configured
    assert client.api_key == "newkey"


def test_masked_keys_never_leak_raw(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "supersecretkey123")
    client = TmdbClient()
    masked = client.masked_keys()
    assert masked == ["****y123"]
    assert "supersecretkey123" not in "".join(masked)


# ---------- 密钥轮询 ----------

def test_rotate_cycles_keys():
    client = TmdbClient.__new__(TmdbClient)  # 不走 __init__（无网络/DB 副作用）
    client._keys_lock = threading.Lock()
    client._set_keys(["k1", "k2"], "env")
    assert client._rotate() is True
    assert client.api_key == "k2"
    assert client._rotate() is True
    assert client.api_key == "k1"  # 循环


def test_get_skips_invalid_key(monkeypatch):
    """401 的 key 被跳过：_get 用下一个 key 重试并返回成功结果"""
    client = TmdbClient.__new__(TmdbClient)
    client._keys_lock = threading.Lock()
    client._set_keys(["bad", "good"], "env")
    calls = []

    def fake_get(url, params):
        calls.append(params["api_key"])
        if params["api_key"] == "bad":
            return SimpleNamespace(status_code=401, json=lambda: {})
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    client.session = SimpleNamespace(get=fake_get)
    monkeypatch.setattr(client, "_ensure_session", lambda: None)
    assert client._get("/configuration", {}) == {"ok": True}
    assert calls == ["bad", "good"]


def test_get_all_keys_bad_returns_none(monkeypatch):
    client = TmdbClient.__new__(TmdbClient)
    client._keys_lock = threading.Lock()
    client._set_keys(["only"], "env")
    client.session = SimpleNamespace(
        get=lambda url, params: SimpleNamespace(status_code=401, json=lambda: {}))
    monkeypatch.setattr(client, "_ensure_session", lambda: None)
    assert client._get("/configuration", {}) is None


# ---------- 条目级重刮幂等 ----------

NFO_DATA = {
    "title": "千与千寻",
    "originaltitle": "千と千尋の神隠し",
    "plot": "少女千寻误入神灵世界……",
    "year": 2001,
    "genres": ["动画"],
    "studios": ["吉卜力"],
    "tmdb_id": "129",
    "imdb_id": "tt0245429",
    "rating": 8.5,
    "mpaa": "PG",
}

DETAILS = {
    "poster_path": "/p.jpg",
    "backdrop_path": "/b.jpg",
    "external_ids": {"imdb_id": "tt0245429"},
    "alternative_titles": {"titles": [{"title": "Spirited Away"}]},
    "title": "千与千寻",
}


def _movie_item() -> SimpleNamespace:
    return SimpleNamespace(
        id=7, item_type="movie", name="旧名", original_title="", sort_name="",
        overview="", tagline="", production_year=None, community_rating=None,
        official_rating="", genres="", tags="", studios="", platforms="",
        tmdb_id="", imdb_id="", aliases="", file_path="/media/a.mkv",
        container="", poster_path="", backdrop_path="",
        primary_image_url="", backdrop_image_url="", last_scraped_at=None,
    )


def _fake_db() -> SimpleNamespace:
    return SimpleNamespace(commit=lambda: None)


def test_rescrape_item_idempotent(monkeypatch):
    """同一条目重刮两次：第一次有变更，第二次无字段变更（幂等）"""
    monkeypatch.setattr(admin_scrape, "_discover_nfo", lambda db, item: dict(NFO_DATA))
    monkeypatch.setattr(admin_scrape.tmdb_client, "details", lambda tid, kind: dict(DETAILS))
    # _set_image 会尝试本地化图片：测试里只落 URL，不下载
    monkeypatch.setattr(
        tmdb_mod, "_set_image",
        lambda item, kind, url: setattr(
            item, "backdrop_image_url" if kind == "Backdrop" else "primary_image_url", url),
    )
    monkeypatch.setattr(admin_scrape.tmdb_client, "api_keys", ["testkey"])

    db = _fake_db()
    item = _movie_item()

    first = admin_scrape._rescrape_one(db, item)
    assert first["nfo_found"] is True
    assert first["changed"], "首次重刮应该有字段变更"
    assert item.name == "千与千寻"
    assert item.tmdb_id == "129"

    second = admin_scrape._rescrape_one(db, item)
    assert second["changed"] == {}, f"重复调用应幂等，实际变更：{second['changed']}"


def test_rescrape_item_tmdb_only_fills_missing(monkeypatch):
    """B 方案：有 NFO tmdb_id 时跳过搜索，只取详情补缺失项；已有图/IMDb/别名时不再覆盖"""
    nfo_no_imdb = {k: v for k, v in NFO_DATA.items() if k != "imdb_id"}
    monkeypatch.setattr(admin_scrape, "_discover_nfo", lambda db, item: dict(nfo_no_imdb))
    searched = []
    monkeypatch.setattr(admin_scrape.tmdb_client, "search",
                        lambda name, year, kind: searched.append((name, year, kind)) or {"id": 1})
    monkeypatch.setattr(admin_scrape.tmdb_client, "details", lambda tid, kind: dict(DETAILS))
    monkeypatch.setattr(
        tmdb_mod, "_set_image",
        lambda item, kind, url: setattr(
            item, "backdrop_image_url" if kind == "Backdrop" else "primary_image_url", url),
    )
    monkeypatch.setattr(admin_scrape.tmdb_client, "api_keys", ["testkey"])

    item = _movie_item()
    item.imdb_id = "tt0000000"  # 已有：不该被覆盖
    item.aliases = "已有别名"
    item.primary_image_url = "https://example.com/old.jpg"  # 已有图：不该被覆盖
    admin_scrape._rescrape_one(_fake_db(), item)

    assert searched == [], "有 TMDB ID 时必须跳过搜索"
    assert item.imdb_id == "tt0000000"
    assert item.primary_image_url == "https://example.com/old.jpg"
