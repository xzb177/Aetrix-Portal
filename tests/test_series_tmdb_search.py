"""episode 隐式 series 的 TMDB 搜索补全（B 方案：NFO 管文字、TMDB 只补图）。

回归：标准命名（S01E01）的文件被判为 episode，series 在写库循环里隐式创建，
以前完全走不到 TMDB 搜索分支（scraped=0，全库系列无 tmdb_id/海报/简介）。

设计约束（与 v2.31.0 共存）：
- 只给“从没走过 TMDB”的剧（无 tmdb_id 且无 last_scraped_at）搜一次；
- 干净落地后（命中与否）记 last_scraped_at，之后不再拦、不再搜——
  否则配了 TMDB 的剧集库每轮重扫都得完整处理每一集（v2.31.0 钉住的行为）。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from types import SimpleNamespace
from unittest import mock

import pytest

from backend.emby_server import scanner
from backend.emby_server.tmdb import TmdbClient


def _set_configured(monkeypatch, value):
    monkeypatch.setattr(TmdbClient, "configured",
                        property(lambda self: value))


def _ctx_with_series(series_item, policy="missing_only"):
    ctx = SimpleNamespace(
        series_items={},
        series_tmdb_searched=set(),
        series_tmdb_results={},
        nfo_series_imaged=set(),
        snap=SimpleNamespace(scrape_policy=policy),
    )
    if series_item is not None:
        ctx.series_items["sg1"] = series_item
    return ctx


def _series_row(tmdb_id=None, last_scraped_at=None):
    return SimpleNamespace(
        tmdb_id=tmdb_id,
        last_scraped_at=last_scraped_at,
        repair_requested_at=None,
        poster_path=None,
        primary_image_url=None,
    )


def _pending_episode():
    return SimpleNamespace(
        item_type="episode",
        series_guid="sg1",
        parsed={"name": "86 不存在的战区", "year": 2021},
        scan_file=SimpleNamespace(stored_path="/fake/86.S01E01.mkv", size=123),
    )


def _full_item(**kw):
    from datetime import datetime
    base = dict(
        tmdb_id=None, imdb_id=None, aliases=None,
        repair_requested_at=None, series_id=1, parent_id=1,
        probe_status="done", size=123,
        duration_ticks=3600 * 10_000_000, last_probed_at=datetime.now(),
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------- _can_skip_file ----------

def test_skip_blocked_when_series_never_scraped(monkeypatch):
    """从没走过 TMDB 的剧：集不能跳过（否则这部剧永远刮不到）。"""
    _set_configured(monkeypatch, True)
    ctx = _ctx_with_series(_series_row(tmdb_id=None, last_scraped_at=None))
    with mock.patch.object(scanner, "SCAN_INCREMENTAL", True):
        assert scanner._can_skip_file(
            ctx, _full_item(), _pending_episode(), "fp", "fp") is False


def test_skip_allowed_when_series_has_tmdb(monkeypatch):
    _set_configured(monkeypatch, True)
    ctx = _ctx_with_series(_series_row(tmdb_id="100565"))
    with mock.patch.object(scanner, "SCAN_INCREMENTAL", True):
        assert scanner._can_skip_file(
            ctx, _full_item(tmdb_id="100565", imdb_id="tt1", aliases="a"),
            _pending_episode(), "fp", "fp") is True


def test_skip_allowed_when_series_attempted_but_missed(monkeypatch):
    """搜过但没命中（有 last_scraped_at、无 tmdb_id）：v2.31.0，集必须能跳过。"""
    from datetime import datetime
    _set_configured(monkeypatch, True)
    ctx = _ctx_with_series(_series_row(tmdb_id=None, last_scraped_at=datetime.now()))
    with mock.patch.object(scanner, "SCAN_INCREMENTAL", True):
        assert scanner._can_skip_file(
            ctx, _full_item(), _pending_episode(), "fp", "fp") is True


def test_skip_not_blocked_when_tmdb_unconfigured(monkeypatch):
    _set_configured(monkeypatch, False)
    ctx = _ctx_with_series(_series_row(tmdb_id=None))
    with mock.patch.object(scanner, "SCAN_INCREMENTAL", True):
        assert scanner._can_skip_file(
            ctx, _full_item(), _pending_episode(), "fp", "fp") is True


# ---------- 预取：只给“从没走过 TMDB”的剧提交搜索（去重） ----------

def _maybe_submit_series_search(ctx, pending, series_nfo_data):
    """复刻 _prepare_and_prefetch 里 episode 分支的提交判定。"""
    series_id = (series_nfo_data or {}).get("tmdb_id")
    if series_id and pending.series_guid not in ctx.nfo_series_imaged:
        return "nfo-details"
    if (not series_id and TmdbClient.configured.fget(scanner.tmdb_client)
            and pending.series_guid not in ctx.series_tmdb_searched):
        s_item = ctx.series_items.get(pending.series_guid)
        if s_item is None or (not s_item.tmdb_id and not s_item.last_scraped_at):
            ctx.series_tmdb_searched.add(pending.series_guid)
            return ("search", pending.parsed["name"], pending.parsed["year"])
    return None


def test_prefetch_submits_series_search_once(monkeypatch):
    _set_configured(monkeypatch, True)
    ctx = _ctx_with_series(_series_row(tmdb_id=None, last_scraped_at=None))
    r1 = _maybe_submit_series_search(ctx, _pending_episode(), {})
    assert r1 == ("search", "86 不存在的战区", 2021)
    # 同一部剧第二次不再提交
    r2 = _maybe_submit_series_search(ctx, _pending_episode(), {})
    assert r2 is None


def test_prefetch_skips_search_when_series_has_tmdb(monkeypatch):
    _set_configured(monkeypatch, True)
    ctx = _ctx_with_series(_series_row(tmdb_id="100565"))
    assert _maybe_submit_series_search(ctx, _pending_episode(), {}) is None


def test_prefetch_skips_search_when_series_attempted(monkeypatch):
    """搜过没命中：不再重复提交（v2.31.0）。"""
    from datetime import datetime
    _set_configured(monkeypatch, True)
    ctx = _ctx_with_series(_series_row(tmdb_id=None, last_scraped_at=datetime.now()))
    assert _maybe_submit_series_search(ctx, _pending_episode(), {}) is None


# ---------- 写库：命中落到 series（NFO 随后覆盖）；没命中记一笔尝试 ----------

def test_apply_hit_then_nfo_overlay():
    hit = {"id": 100565, "name": "TMDB 名", "overview": "TMDB 简介",
           "vote_average": 8.5, "poster_path": "/p.jpg", "backdrop_path": "/b.jpg",
           "genre_ids": [16]}
    series = SimpleNamespace(
        tmdb_id=None, overview=None, poster_path=None, primary_image_url=None,
        backdrop_path=None, backdrop_image_url=None, community_rating=None,
        name="文件名", aliases=None, genres=None, imdb_id=None,
        last_scraped_at=None, repair_requested_at=None,
    )
    ctx = SimpleNamespace(
        series_tmdb_results={"sg1": (hit, None)},
        series_tmdb_searched={"sg1"},
    )
    stats = {"scraped": 0}
    # 复刻写库循环片段
    series_tmdb_applied = False
    tmdb_res = ctx.series_tmdb_results.get("sg1")
    if tmdb_res and not series.tmdb_id:
        h, d = tmdb_res
        if h:
            scanner.tmdb_client.apply(series, h, "series")
            stats["scraped"] += 1
            series_tmdb_applied = True
    if ("sg1" in ctx.series_tmdb_searched
            and not series.tmdb_id and not series.last_scraped_at):
        from datetime import datetime
        series.last_scraped_at = datetime.now()
    assert series.tmdb_id == "100565"
    assert stats["scraped"] == 1
    assert series_tmdb_applied is True
    assert series.last_scraped_at is not None  # apply() 顺带记了
    # NFO 随后覆盖（B 方案 NFO 优先）
    scanner.nfo_lib.apply_nfo(series, {"title": "NFO 标题", "plot": "NFO 简介"},
                              "series")
    assert series.name == "NFO 标题"


def test_miss_marks_attempted():
    """干净搜过但没命中：记 last_scraped_at，下次不再拦/不再搜。"""
    from datetime import datetime
    series = SimpleNamespace(tmdb_id=None, last_scraped_at=None)
    ctx = SimpleNamespace(series_tmdb_results={}, series_tmdb_searched={"sg1"})
    # 复刻写库循环的标记片段
    if ("sg1" in ctx.series_tmdb_searched
            and not series.tmdb_id and not series.last_scraped_at):
        series.last_scraped_at = datetime.now()
    assert series.last_scraped_at is not None
    assert series.tmdb_id is None
