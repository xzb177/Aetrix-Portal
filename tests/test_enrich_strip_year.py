"""enrich 写 name 时剥离年份后缀；年份进 production_year。

回归：刮削后名字是"马拉多纳：美好的梦想 (2021)"，年份没去掉。
要求：名字只留"马拉多纳：美好的梦想"，年份存 production_year。
"""
from types import SimpleNamespace

import pytest

from backend.emby_server import tmdb as tmdb_mod
from backend.emby_server.tmdb import (
    TmdbClient,
    _year_from_tmdb_date,
    strip_year_suffix,
)


def _fake_item(**kw):
    base = dict(
        tmdb_id=None,
        last_scraped_at=None,
        metadata_source=None,
        overview=None,
        community_rating=None,
        poster_path=None,
        primary_image_url=None,
        backdrop_path=None,
        backdrop_image_url=None,
        name="",
        aliases="",
        genres="",
        production_year=None,
        imdb_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestStripYearSuffix:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("马拉多纳：美好的梦想 (2021)", "马拉多纳：美好的梦想"),
            ("xxx（2021）", "xxx"),
            ("xxx (2021) ", "xxx"),
            ("xxx(1999)", "xxx"),
            ("2021 xxx", "2021 xxx"),  # 年份不在末尾，不动
            ("xxx (21)", "xxx (21)"),  # 两位数不是年份，不动
            ("xxx", "xxx"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_strip(self, raw, expected):
        assert strip_year_suffix(raw) == expected


class TestYearFromTmdbDate:
    def test_first_air_date(self):
        assert _year_from_tmdb_date({"first_air_date": "2021-05-01"}) == 2021

    def test_release_date(self):
        assert _year_from_tmdb_date({"release_date": "2019-12-20"}) == 2019

    def test_empty(self):
        assert _year_from_tmdb_date({}) is None
        assert _year_from_tmdb_date({"first_air_date": ""}) is None


class TestApplyStripsYear:
    def test_series_name_year_stripped_and_year_set(self):
        client = TmdbClient()
        item = _fake_item()
        hit = {
            "id": 197646,
            "name": "马拉多纳：美好的梦想 (2021)",
            "first_air_date": "2021-03-14",
        }
        client.apply(item, hit, "series")
        assert item.name == "马拉多纳：美好的梦想"
        assert "(2021)" not in item.name
        assert item.production_year == 2021

    def test_movie_title_year_stripped(self):
        client = TmdbClient()
        item = _fake_item()
        hit = {"id": 1, "title": "某个电影（2019）", "release_date": "2019-01-01"}
        client.apply(item, hit, "movie")
        assert item.name == "某个电影"
        assert item.production_year == 2019

    def test_existing_production_year_not_overwritten(self):
        client = TmdbClient()
        item = _fake_item(production_year=2020)
        hit = {"id": 1, "title": "xxx", "release_date": "2019-01-01"}
        client.apply(item, hit, "movie")
        assert item.production_year == 2020


    def test_year_only_name_keeps_original(self):
        """名字只剩年份时不写空名（防御）。"""
        client = TmdbClient()
        item = _fake_item(name="原名")
        hit = {"id": 1, "title": "(2021)", "release_date": "2021-01-01"}
        client.apply(item, hit, "movie")
        assert item.name == "原名"
        assert item.production_year == 2021


class TestApplyDetailsYear:
    def test_details_sets_year(self):
        client = TmdbClient()
        item = _fake_item()
        client.apply_details(item, {"release_date": "2018-07-20"})
        assert item.production_year == 2018

    def test_details_keeps_existing_year(self):
        client = TmdbClient()
        item = _fake_item(production_year=2017)
        client.apply_details(item, {"release_date": "2018-07-20"})
        assert item.production_year == 2017


class TestAltmetaStripsYear:
    def test_douban_title_year_stripped(self):
        from backend.emby_server import altmeta

        item = _fake_item()
        altmeta.apply(item, {"title": "某剧 (2022)", "year": 2022}, "douban")
        assert item.name == "某剧"
        assert item.production_year == 2022


class TestScannerFullwidthYear:
    def test_parse_fullwidth_year_parens(self):
        from backend.emby_server.scanner import parse_media_filename

        r = parse_media_filename("/mnt/x/马拉多纳：美好的梦想（2021）/S01E01.mkv", "tvshows")
        assert r["year"] == 2021
        assert "2021" not in r["name"]
        assert "（）" not in r["name"]
