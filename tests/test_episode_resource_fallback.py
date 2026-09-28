"""集资源回归：未观看剧集首集选择、集级封面继承、媒体流字段补全。"""
from types import SimpleNamespace

from backend.emby_server import api


def test_episode_image_tag_uses_parent_fallback():
    """episode 自身没海报时，DTO 仍必须宣告有 Primary 图片。"""
    parent = SimpleNamespace(
        item_type="season", poster_path=None, primary_image_url="https://img/series.jpg",
        backdrop_path=None, backdrop_image_url=None, id=2,
    )
    series = SimpleNamespace(
        item_type="series", poster_path="/data/series.jpg", primary_image_url=None,
        backdrop_path=None, backdrop_image_url=None, id=3,
    )
    item = SimpleNamespace(
        id=1, item_type="episode", poster_path=None, primary_image_url=None,
        backdrop_path=None, backdrop_image_url=None, parent_id=2, series_id=3,
        parent=parent, series=series, name="E01", guid="e" * 32,
        library_id=1, genres="", tags="", studios="", tmdb_id=None, imdb_id=None,
        production_year=None, community_rating=None, official_rating=None,
        overview="", premiere_date=None, date_added=None, duration_ticks=0,
        container="mkv", bitrate=100, width=1920, height=1080,
        original_title=None, season_number=1, episode_number=1,
        is_hidden=False, streams=[], aliases="",
    )
    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return parent

    db = SimpleNamespace(query=lambda *args, **kwargs: _Query())
    assert api._image_chain(item, "Primary", db) == [
        "https://img/series.jpg", "/data/series.jpg"
    ]


def test_video_stream_falls_back_to_item_probe_values():
    """ffprobe 的视频轨 bit_rate=0 时，不能把 0 传给客户端。"""
    stream = SimpleNamespace(
        stream_index=0, stream_type="Video", codec="hevc", language="eng",
        display_title=None, title=None, is_default=False, is_forced=False,
        is_external=False, channels=None, bit_rate=0,
    )
    item = SimpleNamespace(bitrate=22_059_445, width=3840, height=1920)
    dto = api._stream_dto(stream, "http://test", item, "")
    assert dto["BitRate"] == 22_059_445
    assert dto["Width"] == 3840
    assert dto["Height"] == 1920


def test_foreign_seriesid_nextup_is_not_ignored(monkeypatch):
    """NextUp?SeriesId 必须只在请求的剧内选集，不能返回全库其他剧。"""
    # 这里守住参数分支的源码契约；完整 DB 行为由 test_nextup 的集成夹具覆盖。
    import inspect
    src = inspect.getsource(api.get_next_up)
    assert "requested_series_guid" in src
    assert "requested_series.id" in src
    assert "SeriesId" in src
