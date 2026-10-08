"""缺失集数单元测试（mock DB/缓存，无网络）。"""
import sys
sys.path.insert(0, "/opt/aetrix-portal")

from types import SimpleNamespace
from backend.emby_server import missing_episodes as me


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows
    def filter(self, *a, **k):
        return self
    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self._rows = rows
    def query(self, *a, **k):
        return FakeQuery(self._rows)


def _series(guid="abc", name="Test", tmdb_id="123"):
    return SimpleNamespace(id=1, guid=guid, name=name, tmdb_id=tmdb_id)


def test_no_tmdb_id_returns_none_source(monkeypatch):
    db = FakeDB([(1, 1), (1, 2)])
    out = me.compute_missing(db, _series(tmdb_id=""))
    assert out["Source"] == "none"
    assert out["TotalMissing"] == 0


def test_tmdb_cache_hit_computes_missing(monkeypatch):
    # 本地 S1 有 1,2,3；TMDB 说 S1 共 5 集 → 缺 4,5
    db = FakeDB([(1, 1), (1, 2), (1, 3)])
    fake_tv = {"seasons": [{"season_number": 1, "episode_count": 5}]}
    monkeypatch.setattr(me, "_tmdb_tv_seasons_from_cache", lambda tid: fake_tv)
    monkeypatch.setattr(me, "_episode_group_from_cache", lambda db, tid: None)
    out = me.compute_missing(db, _series())
    assert out["Source"] == "tmdb"
    assert out["Seasons"][0]["Missing"] == [4, 5]
    assert out["TotalMissing"] == 2


def test_no_cache_graceful(monkeypatch):
    db = FakeDB([(1, 1)])
    monkeypatch.setattr(me, "_tmdb_tv_seasons_from_cache", lambda tid: None)
    monkeypatch.setattr(me, "_episode_group_from_cache", lambda db, tid: None)
    out = me.compute_missing(db, _series())
    assert out["Source"] == "none"
    assert out["Seasons"] == []
