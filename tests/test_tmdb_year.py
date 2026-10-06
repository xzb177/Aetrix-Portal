"""Series 年份 / 首播日期回填（P0-1）：apply() 与 apply_details() 的日期落库口径。

背景：2026-10 之前刮进库的 series 97% 没有年份——``apply()`` /
``apply_details()`` 从不写 ``production_year`` / ``premiere_date``。
修完之后两条路必须都写，且都只补缺项（NFO / 用户整理的值不覆盖）。

全部纯逻辑，不碰网络、不碰数据库；``image_base`` 打桩避免读配置库。
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from backend.emby_server import tmdb as tmdb_mod
from backend.emby_server.tmdb import TmdbClient, extract_air_dates


@pytest.fixture(autouse=True)
def _no_config_db(monkeypatch):
    """apply() 拼图片 URL 会读 image_base（配置库）：测试里不需要，打桩掉"""
    monkeypatch.setattr(tmdb_mod, "image_base", lambda: "https://img.example")


def _item(**kw):
    base = dict(
        tmdb_id=None, last_scraped_at=None, metadata_source=None,
        overview=None, community_rating=None, imdb_id=None,
        name=None, aliases=None, genres=None,
        production_year=None, premiere_date=None,
        poster_path=None, primary_image_url=None,
        backdrop_path=None, backdrop_image_url=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


_CLIENT: TmdbClient | None = None


def _client() -> TmdbClient:
    """裸客户端：只用 apply / apply_details，不发请求。

    懒初始化：import 期不碰密钥/会话配置，避免测试收集期产生副作用。
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = TmdbClient()
    return _CLIENT


# ---------------- extract_air_dates：纯函数 ----------------

def test_extract_tv_first_air_date():
    year, premiere = extract_air_dates({"first_air_date": "2021-03-05"})
    assert year == 2021
    assert premiere == datetime(2021, 3, 5)


def test_extract_movie_release_date():
    year, premiere = extract_air_dates({"release_date": "1999-12-31"})
    assert year == 1999
    assert premiere == datetime(1999, 12, 31)


def test_extract_year_only_gives_year_without_premiere():
    year, premiere = extract_air_dates({"first_air_date": "2020"})
    assert year == 2020
    assert premiere is None


def test_extract_dirty_date_keeps_year_drops_premiere():
    year, premiere = extract_air_dates({"first_air_date": "2021-13-99"})
    assert year == 2021
    assert premiere is None


def test_extract_empty_payload():
    assert extract_air_dates({}) == (None, None)
    assert extract_air_dates({"first_air_date": ""}) == (None, None)
    assert extract_air_dates(None) == (None, None)


# ---------------- apply()：搜索命中 ----------------

def test_apply_series_hit_writes_year_and_premiere():
    item = _item()
    hit = {"id": 123, "name": "测试剧", "first_air_date": "2021-03-05",
           "vote_average": 8.1}
    _client().apply(item, hit, "series")
    assert item.production_year == 2021
    assert item.premiere_date == datetime(2021, 3, 5)


def test_apply_movie_hit_writes_year_and_premiere():
    item = _item()
    hit = {"id": 456, "title": "测试电影", "release_date": "2019-07-20"}
    _client().apply(item, hit, "movie")
    assert item.production_year == 2019
    assert item.premiere_date == datetime(2019, 7, 20)


def test_apply_does_not_overwrite_existing_year():
    item = _item(production_year=2018, premiere_date=datetime(2018, 1, 1))
    hit = {"id": 123, "name": "测试剧", "first_air_date": "2021-03-05"}
    _client().apply(item, hit, "series")
    assert item.production_year == 2018
    assert item.premiere_date == datetime(2018, 1, 1)


def test_apply_hit_without_date_is_noop_for_year():
    item = _item()
    hit = {"id": 123, "name": "测试剧"}  # 老缓存的 hit 可能没日期字段
    _client().apply(item, hit, "series")
    assert item.production_year is None
    assert item.premiere_date is None
    assert item.name == "测试剧"  # 其它字段照常落


# ---------------- apply_details()：详情 ----------------

def test_apply_details_writes_year_and_premiere():
    item = _item()
    data = {"name": "测试剧", "first_air_date": "2022-11-30",
            "vote_average": 7.5, "overview": "简介"}
    _client().apply_details(item, data)
    assert item.production_year == 2022
    assert item.premiere_date == datetime(2022, 11, 30)


def test_apply_details_does_not_overwrite_existing():
    item = _item(production_year=2020)  # 只有年份：年份不动，日期照补
    data = {"first_air_date": "2022-11-30"}
    _client().apply_details(item, data)
    assert item.production_year == 2020
    assert item.premiere_date == datetime(2022, 11, 30)


def test_apply_details_without_date_is_noop_for_year():
    item = _item()
    _client().apply_details(item, {"name": "测试剧", "overview": "简介"})
    assert item.production_year is None
    assert item.premiere_date is None
    assert item.overview == "简介"  # 其它字段照常落


def test_apply_details_empty_data_is_noop():
    item = _item()
    _client().apply_details(item, {})
    _client().apply_details(item, None)
    assert item.production_year is None
    assert item.premiere_date is None
