"""首页「继续观看」不该出现单集（episode）。

起因：主人 iOS 首页出现了「第 1 集」这类单集卡片。查下来 ``/Items/Resume``
只过滤了「有播放进度 + 未播完」，**没按 item_type 过滤**——任何一条有进度的
单集都会作为独立条目混进首页。而 ``/Items/Latest`` 同一处一直有
``item_type.in_(["movie", "series"])``，两条口径不一致。

这里只验证查询构造：给定的过滤条件必须把 episode 排除在结果之外。
"""
import inspect

from backend.emby_server import api as emby_api


def _resume_filter_source() -> str:
    src = inspect.getsource(emby_api.get_resume)
    return src


def test_resume_filters_by_item_type():
    """Resume 端点必须按 item_type 过滤，且保留 movie/series"""
    src = _resume_filter_source()
    assert 'item_type.in_(["movie", "series"])' in src, (
        "Resume 缺少 item_type 过滤：单集会混进首页（/Items/Latest 有，这里没有）"
    )


def test_resume_excludes_hidden_items():
    """Resume 应过滤 is_hidden（与 Latest 一致）"""
    src = _resume_filter_source()
    assert "is_hidden" in src


def test_resume_still_filters_progress_and_played():
    """不能因为加了类型过滤，丢掉「有进度 / 未播完」这两个原条件"""
    src = _resume_filter_source()
    assert "playback_position_ticks > 0" in src
    assert "played ==" in src  # noqa: E712 — SQLAlchemy 写法


def test_latest_keeps_same_type_scope():
    """Latest 仍应只给 movie/series（防止修 Resume 时误改）"""
    src = inspect.getsource(emby_api.get_latest)
    assert 'item_type.in_(["movie", "series"])' in src
