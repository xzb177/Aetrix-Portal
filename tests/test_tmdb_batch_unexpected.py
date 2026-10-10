"""TMDB 批量路径：非 TmdbTransientError 的意外异常不能当「搜不到」（会被终态化为 metadata_source='none'），
必须按瞬态处理（该条 ok=False 进退避重试，与逐条路径异常冒泡一致）。"""
from backend.emby_server.tmdb import TmdbClient


def _client(monkeypatch):
    c = TmdbClient.__new__(TmdbClient)

    def boom(*a, **k):
        raise KeyError("unexpected payload shape")

    monkeypatch.setattr(c, "search", boom, raising=False)
    monkeypatch.setattr(c, "details", boom, raising=False)
    return c


def test_batch_search_unexpected_error_is_transient(monkeypatch):
    c = _client(monkeypatch)
    results, transient = c.batch_search([("x", None, "movie")], return_transient=True)
    assert results[0] is None
    assert transient == {0}


def test_batch_details_unexpected_error_is_transient(monkeypatch):
    c = _client(monkeypatch)
    results, transient = c.batch_details([("1", "movie")], return_transient=True)
    assert results[0] is None
    assert transient == {0}


def test_run_tmdb_batch_marks_item_retryable(monkeypatch):
    from backend.emby_server import enrich_worker as ew
    from backend.emby_server import tmdb as tmdb_mod

    c = _client(monkeypatch)
    monkeypatch.setattr(tmdb_mod, "tmdb_client", c)
    plan = {"op": "search", "name": "x", "year": None, "kind": "movie"}
    out = ew._run_tmdb_batch([(0, plan)])
    assert out[0]["transient"] is True
    result = {"ok": True}
    ew._apply_tmdb_plan_result(result, type("I", (), {"name": "x"})(), plan, out[0], "movie")
    assert result["ok"] is False
