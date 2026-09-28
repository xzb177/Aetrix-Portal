"""容器条目（series / season）没有 file_path 也必须能刮 TMDB。

生产事故：3117 个剧集 TMDB 命中 0。查日志全是
``err=无 file_path，无法重建 ScanFile``，attempts 打到 8 次后锁死 failed。

根因：``_enrich_fetch`` 一进来就要求能重建 ScanFile，没有 file_path 直接判失败。
但 series / season 是目录聚合出来的容器条目，文件在 episode 上，它们天生没有
file_path——而 TMDB 匹配只需要 ``name`` + ``production_year``，压根用不到它。

所以之前所有剧集/季都卡在第 0 行，一步都走不出去。

**本文件不碰数据库**：``_enrich_fetch`` 里的 side / NFO / TMDB 全部走 mock，
条目用 SimpleNamespace 构造。刻意不设 DATABASE_URL、不重建 engine ——
``backend.database.engine`` 是模块级单例，后导入的测试文件若重建它，
会污染同批次其他模块（``test_enrich_worker::test_get_progress`` 会读到空表）。

**并且不在 import 期导入 enrich_worker**：``enrich_worker`` 顶部是
``from backend.database import SessionLocal``，import 那一刻就把引用绑死了。
本文件在字母序上排在 test_enrich_worker 之前，若此时 import，它拿到的是
``test_enrich_worker`` 建库之前的那份 SessionLocal，后面 test_get_progress
就会读到空表（表现为 ``assert 0 == 2``）。改成运行期才导入即可两不耽误。
"""
from types import SimpleNamespace
from unittest import mock

from backend.emby_server import enrich_worker


def _ew():
    return enrich_worker


def _item(item_type, name, year=2020, file_path=None):
    return SimpleNamespace(
        id=1, item_type=item_type, name=name, production_year=year,
        file_path=file_path, size=0, container="", library_id=1,
        tmdb_id=None, poster_path=None, primary_image_url=None,
        imdb_id=None, aliases=None, repair_requested_at=None,
    )


def test_series_without_file_path_still_queries_tmdb():
    """核心回归：series 没有 file_path 也必须走到 TMDB，且不能判失败"""
    item = _item("series", "1000磅姐妹", 2020, file_path=None)
    with mock.patch.object(_ew(), "_scanfile_from_item", return_value=None), \
         mock.patch("backend.emby_server.scanner._tmdb_work",
                    return_value=({"id": 98410}, {"id": 98410})) as m_tmdb, \
         mock.patch("backend.emby_server.tmdb.tmdb_client") as m_client:
        m_client.configured = True
        res = _ew()._enrich_fetch(item)

    assert res["ok"] is True, f"容器条目不该被判失败：{res}"
    assert res["error"] is None
    assert m_tmdb.called, "没有 file_path 也必须调用 TMDB"
    assert res["tmdb_hit"] == {"id": 98410}


def test_season_without_file_path_is_not_a_failure():
    """season 刻意不单独搜 TMDB（图片走剧集），但也不能被判失败"""
    item = _item("season", "第一季", 2020, file_path=None)
    with mock.patch.object(_ew(), "_scanfile_from_item", return_value=None), \
         mock.patch("backend.emby_server.scanner._tmdb_work",
                    return_value=({"id": 1}, {})) as m_tmdb, \
         mock.patch("backend.emby_server.tmdb.tmdb_client") as m_client:
        m_client.configured = True
        res = _ew()._enrich_fetch(item)
    assert res["ok"] is True
    assert not m_tmdb.called


def test_episode_without_file_path_is_still_a_failure():
    """episode 必须有本地文件，没有就该判失败退避重试"""
    item = _item("episode", "第 1 集", 2020, file_path=None)
    with mock.patch.object(_ew(), "_scanfile_from_item", return_value=None):
        res = _ew()._enrich_fetch(item)
    assert res["ok"] is False
    assert "file_path" in (res["error"] or "")


def test_movie_without_file_path_is_still_a_failure():
    item = _item("movie", "阿凡达", 2009, file_path=None)
    with mock.patch.object(_ew(), "_scanfile_from_item", return_value=None):
        res = _ew()._enrich_fetch(item)
    assert res["ok"] is False


def test_series_with_file_path_still_reads_nfo_and_side():
    """有 file_path 时行为不变：side + NFO 都照跑"""
    item = _item("series", "剧名", 2020, file_path="mount://3/剧名/tvshow.nfo")
    fake_sf = SimpleNamespace(name="tvshow.nfo")
    with mock.patch.object(_ew(), "_scanfile_from_item", return_value=fake_sf), \
         mock.patch("backend.emby_server.scanner._side_info",
                    return_value=("/p.jpg", "/f.jpg", [])) as m_side, \
         mock.patch("backend.emby_server.scanner._nfo_work",
                    return_value=({"tmdb_id": "42"}, None, None)) as m_nfo, \
         mock.patch("backend.emby_server.scanner._tmdb_work") as m_tmdb, \
         mock.patch("backend.emby_server.tmdb.tmdb_client") as m_client:
        m_client.configured = True
        res = _ew()._enrich_fetch(item)

    assert m_side.called, "有 file_path 时 side 必须照跑"
    assert m_nfo.called, "有 file_path 时 NFO 必须照跑"
    assert res["poster"] == "/p.jpg"
    # NFO 里有 tmdb_id 时走详情分支，不再做名称搜索
    assert res["tmdb_id"] == "42"
    assert m_tmdb.called
    assert m_tmdb.call_args[0][0] is False, "有 tmdb_id 时不该再做名称搜索"
