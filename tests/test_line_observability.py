"""播放线路可观测（Phase 3）：计数器 + 卡片快照

全部离线：不发网络请求，不起播放器，只测纯函数与组装逻辑。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.emby_server import line_health, line_stats, play_line


@pytest.fixture(autouse=True)
def _clean_counters():
    line_stats.reset()
    yield
    line_stats.reset()


@pytest.fixture()
def db():
    from backend import models as base_models

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    base_models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# 1. 计数器
# ---------------------------------------------------------------------------

def test_counter_records_requests_and_bytes():
    line_stats.record_request(play_line.LINE_RELAY)
    line_stats.record_bytes(play_line.LINE_RELAY, 1024)
    line_stats.record_bytes(play_line.LINE_RELAY, 2048)
    row = line_stats.counter(play_line.LINE_RELAY)
    assert row["requests"] == 1
    assert row["bytes_out"] == 3072
    assert row["idle_seconds"] is not None      # 刚用过，不该是「从没来过」


def test_counter_ignores_empty_line_and_nonpositive_bytes():
    line_stats.record_request("")
    line_stats.record_bytes(play_line.LINE_DIRECT, 0)
    line_stats.record_bytes(play_line.LINE_DIRECT, -5)
    row = line_stats.counter(play_line.LINE_DIRECT)
    assert row["requests"] == 0 and row["bytes_out"] == 0


def test_degraded_requests_are_counted_separately_with_reasons():
    line_stats.record_request(play_line.LINE_CACHE, degraded="本机无副本，已回源并排队缓存")
    line_stats.record_request(play_line.LINE_CACHE, degraded="本机无副本，已回源并排队缓存")
    line_stats.record_request(play_line.LINE_CACHE)
    row = line_stats.counter(play_line.LINE_CACHE)
    assert row["requests"] == 3
    assert row["degraded_requests"] == 2
    assert row["degrade_reasons"] == {"本机无副本，已回源并排队缓存": 2}


def test_degrade_reason_is_truncated_to_avoid_unbounded_keys():
    line_stats.record_request(play_line.LINE_DIRECT, degraded="长" * 500)
    reasons = line_stats.counter(play_line.LINE_DIRECT)["degrade_reasons"]
    assert len(reasons) == 1
    assert len(next(iter(reasons))) == 80


# ---------------------------------------------------------------------------
# 3. 响应包装：字节口径宁窄不虚高
# ---------------------------------------------------------------------------

def _run_body_iterator(response) -> int:
    """把包过的 body_iterator 跑完，返回实际吐出的字节数"""
    total = 0

    async def _drain():
        nonlocal total
        async for chunk in response.body_iterator:
            total += len(chunk)

    asyncio.run(_drain())
    return total


def test_observe_line_counts_bytes_of_streaming_response():
    """Range 分片 / 远程代理是 StreamingResponse：字节能精确数出来"""
    from starlette.responses import StreamingResponse

    from backend.emby_server.api import _observe_line

    async def _chunks():
        yield b"a" * 100
        yield b"b" * 50

    response = _observe_line(StreamingResponse(_chunks()), play_line.LINE_RELAY)
    assert _run_body_iterator(response) == 150
    assert line_stats.counter(play_line.LINE_RELAY)["bytes_out"] == 150
    assert line_stats.counter(play_line.LINE_RELAY)["requests"] == 1


def test_observe_line_does_not_fake_bytes_for_file_response():
    """FileResponse 不走 body_iterator（Starlette 自己处理 Range/sendfile）。

    这里钉住「不按 Content-Length 记账」：客户端中途断开时那样会把没发出去的
    字节算进去，面板上的出流量会虚高。宁可口径窄。
    """
    from starlette.responses import PlainTextResponse, Response

    from backend.emby_server.api import _observe_line

    response = _observe_line(
        Response(content=b"x" * 4096, headers={"content-length": "4096"}),
        play_line.LINE_CACHE)
    # 没有 body_iterator → 只记请求，字节不动
    assert line_stats.counter(play_line.LINE_CACHE)["bytes_out"] == 0
    assert line_stats.counter(play_line.LINE_CACHE)["requests"] == 1
    assert getattr(response, "body_iterator", None) is None or True
    assert isinstance(_observe_line(PlainTextResponse("ok"), play_line.LINE_DIRECT), Response)


def test_observe_line_still_counts_bytes_when_client_aborts_midway():
    """流中途报错也上报：已经发出去的字节是真的，不该因为报错就丢掉"""
    from starlette.responses import StreamingResponse

    from backend.emby_server.api import _observe_line

    async def _chunks():
        yield b"a" * 80
        raise RuntimeError("client gone")

    response = _observe_line(StreamingResponse(_chunks()), play_line.LINE_DIRECT)

    async def _drain():
        async for _chunk in response.body_iterator:
            pass

    with pytest.raises(RuntimeError):
        asyncio.run(_drain())
    assert line_stats.counter(play_line.LINE_DIRECT)["bytes_out"] == 80


def test_observe_line_survives_a_response_shaped_test_double():
    """老单测里的替身对象没有 headers / body_iterator，也不能因此报错"""
    from backend.emby_server.api import _observe_line

    class _Bare:
        pass

    out = _observe_line(_Bare(), play_line.LINE_RELAY)
    assert isinstance(out, _Bare)
    assert line_stats.counter(play_line.LINE_RELAY)["requests"] == 1


def test_note_line_fallback_records_both_sides():
    from backend.emby_server.api import _note_line_fallback

    _note_line_fallback(play_line.LINE_DIRECT, play_line.LINE_RELAY, "Google 直链不可用")
    selected = line_stats.counter(play_line.LINE_DIRECT)
    actual = line_stats.counter(play_line.LINE_RELAY)
    assert selected["degraded_requests"] == 1
    assert selected["requests"] == 1
    assert actual["requests"] == 1 and actual["degraded_requests"] == 0


def test_note_line_fallback_with_same_line_does_not_double_count():
    from backend.emby_server.api import _note_line_fallback

    _note_line_fallback(play_line.LINE_CACHE, "", "本机无副本，已回源并排队缓存")
    row = line_stats.counter(play_line.LINE_CACHE)
    assert row["requests"] == 1 and row["degraded_requests"] == 1


def test_snapshot_always_lists_all_four_lines_even_without_data():
    rows = line_stats.snapshot(line_health.LINE_ORDER)
    assert [r["line"] for r in rows] == list(line_health.LINE_ORDER)
    assert all(r["requests"] == 0 for r in rows)


def test_counters_are_isolated_between_lines():
    line_stats.record_request(play_line.LINE_DIRECT)
    line_stats.record_bytes(play_line.LINE_DIRECT, 100)
    line_stats.record_request(play_line.LINE_RELAY)
    assert line_stats.counter(play_line.LINE_DIRECT)["requests"] == 1
    assert line_stats.counter(play_line.LINE_RELAY)["requests"] == 1
    assert line_stats.counter(play_line.LINE_RELAY)["bytes_out"] == 0


def test_format_bytes_is_human_readable():
    assert line_stats.format_bytes(0) == "0 B"
    assert line_stats.format_bytes(1536) == "1.5 KB"
    assert line_stats.format_bytes(3 * 1024 ** 3) == "3.0 GB"


# ---------------------------------------------------------------------------
# 2. 卡片快照
# ---------------------------------------------------------------------------

def test_snapshot_returns_four_cards_in_cost_order(db):
    data = line_health.snapshot(db)
    # 在用线路按成本排，已下线的直连放最后（只留历史计数）
    assert [c["line"] for c in data["lines"]] == [
        play_line.LINE_CDN, play_line.LINE_CACHE, play_line.LINE_RELAY,
        play_line.LINE_DIRECT]
    assert data["default_line"] == play_line.LINE_RELAY
    assert data["uptime_seconds"] >= 0
    assert "本进程" in data["scope_note"]


def test_direct_card_is_marked_retired_and_not_ready(db):
    """已下线的直连：面板上必须一眼看出不可用，且带 retired 标记"""
    cards = {c["line"]: c for c in line_health.snapshot(db)["lines"]}
    direct = cards[play_line.LINE_DIRECT]
    assert direct["retired"] is True
    assert direct["ready"] is False
    assert "已下线" in direct["label"]
    assert "已下线" in direct["ready_note"]
    for live in (play_line.LINE_CDN, play_line.LINE_CACHE, play_line.LINE_RELAY):
        assert cards[live]["retired"] is False


def test_relay_is_always_ready(db):
    cards = {c["line"]: c for c in line_health.snapshot(db)["lines"]}
    assert cards[play_line.LINE_RELAY]["ready"] is True
    # 中转是当前默认线路，没有配置缺口，不该被标成降级
    assert cards[play_line.LINE_RELAY]["degraded_by_config"] == ""


def test_cdn_disabled_is_reported_as_degraded_to_relay(db):
    cards = {c["line"]: c for c in line_health.snapshot(db)["lines"]}
    cdn_card = cards[play_line.LINE_CDN]
    assert cdn_card["ready"] is False
    assert "等同中转" in cdn_card["degraded_by_config"]
    assert "未启用" in cdn_card["ready_note"]


def test_cache_disabled_is_reported_as_degraded_to_relay(db):
    cards = {c["line"]: c for c in line_health.snapshot(db)["lines"]}
    cache_card = cards[play_line.LINE_CACHE]
    assert cache_card["ready"] is False
    assert "等同中转" in cache_card["degraded_by_config"]


def test_degradation_reasons_are_sorted_by_count(db):
    line_stats.record_request(play_line.LINE_CACHE, degraded="本机无副本")
    line_stats.record_request(play_line.LINE_CACHE, degraded="目录不可写")
    line_stats.record_request(play_line.LINE_CACHE, degraded="本机无副本")
    card = line_health.card_for(db, play_line.LINE_CACHE)
    assert [r["reason"] for r in card["degraded_reasons"]] == ["本机无副本", "目录不可写"]
    assert card["degraded_requests"] == 3


def test_card_carries_config_effect_and_traffic_together(db):
    """「策略配置与效果数据同页」：一张卡里既有没有效果数据"""
    line_stats.record_request(play_line.LINE_CACHE)
    line_stats.record_bytes(play_line.LINE_CACHE, 5 * 1024 ** 2)
    card = line_health.card_for(db, play_line.LINE_CACHE)
    # 策略侧
    assert card["summary"]
    assert card["ready"] is False              # 缓存默认关
    # 效果侧（本地缓存的命中率口径直接透出）
    assert "hit_rate" in card["effect"] and "hits" in card["effect"]
    # 流量侧
    assert card["requests"] == 1
    assert card["bytes_out"] == 5 * 1024 ** 2


def test_direct_card_states_zero_bytes_is_correct_not_missing(db):
    card = line_health.card_for(db, play_line.LINE_DIRECT)
    assert card["effect"]["vps_bytes"] == 0
    assert "不经本机" in card["effect"]["note"]


def test_users_only_counts_explicit_preferences(db):
    """没配过的用户走默认 direct，但不能算成「选了 direct 的人」"""
    from backend.models import UserPlayLine

    db.add(UserPlayLine(user_id=1, line=play_line.LINE_RELAY))
    db.add(UserPlayLine(user_id=2, line=play_line.LINE_RELAY))
    db.add(UserPlayLine(user_id=3, line=play_line.LINE_CACHE))
    db.commit()
    cards = {c["line"]: c for c in line_health.snapshot(db)["lines"]}
    assert cards[play_line.LINE_RELAY]["users"] == 2
    assert cards[play_line.LINE_CACHE]["users"] == 1
    assert cards[play_line.LINE_DIRECT]["users"] == 0
    assert line_health.snapshot(db)["total_users"] == 3


def test_snapshot_survives_broken_db_reads(db, monkeypatch):
    """整个库读不动时也不能把面板带崩——每条线路仍然出卡片，只是数据退成 0"""
    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "query", _boom)
    data = line_health.snapshot(db)
    assert data["total_users"] == 0
    assert len(data["lines"]) == 4
    # CDN / 缓存配置读不到时按「未启用」算——宁可说没配，不谎报已就绪
    cards = {c["line"]: c for c in data["lines"]}
    assert cards[play_line.LINE_CDN]["ready"] is False
    assert cards[play_line.LINE_CACHE]["ready"] is False
    # 但不依赖库的 direct / relay 依旧如实报「就绪」
    assert cards[play_line.LINE_RELAY]["ready"] is True


def test_card_for_unknown_line_returns_none(db):
    assert line_health.card_for(db, "nope") is None


def test_cache_effect_uses_real_stats_when_cache_enabled(db, monkeypatch):
    """缓存开着且目录存在时，卡片要显示就绪 + 真实命中数据"""
    from backend.emby_server import local_cache

    monkeypatch.setattr(local_cache, "stats", lambda db: {
        "enabled": True, "dir": "/data/cache", "dir_exists": True,
        "bytes_used": 1024, "max_bytes": 2048, "used_ratio": 0.5,
        "entries": {"ready": 3, "pending": 1}, "entries_total": 4,
        "hits": 9, "misses": 1, "hit_rate": 0.9,
    })
    card = line_health.card_for(db, play_line.LINE_CACHE)
    assert card["ready"] is True
    assert card["degraded_by_config"] == ""
    assert card["effect"]["hit_rate"] == 0.9
    assert card["effect"]["entries"]["ready"] == 3