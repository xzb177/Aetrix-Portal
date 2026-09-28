"""蓝光/DVD 原盘目录过滤：BDMV 里的码流片段不能被当成电影。

生产事故：未解原盘 ``精武英雄 (1994)/BDMV/STREAM/00000.m2ts`` 被扫成一部叫
「00000」的电影，3966 条这样的碎片占了 movie 总数的 69%，既刮不出元数据也没有
封面，还把 worker 的 ffprobe 队列刷爆。
"""
from backend.emby_server import disc_filter
from backend.emby_server.mounts import MountEntry


class _FakeProvider:
    """最小可用的云盘遍历桩：只实现 walk_media 依赖的 list_dir"""

    def __init__(self, tree):
        self.tree = tree
        self._cid_cache: dict[str, str] = {}

    def list_dir(self, rel="/"):
        for name, is_dir, children in self.tree.get(rel, []):
            child_rel = f"{rel.rstrip('/')}/{name}" if rel != "/" else f"/{name}"
            yield MountEntry(name=name, rel=child_rel, is_dir=is_dir,
                             size=0, entry_id="")

    def _entries(self, rel):
        return list(self.list_dir(rel))

    def walk_media(self, root="/"):
        from backend.emby_server.mount_cloud import _CloudMount
        return _CloudMount.walk_media(self, root=root)


def _bd_tree():
    return {
        "/": [("MoviePilot", True, None), ("readme.txt", False, None)],
        "/MoviePilot": [("精武英雄 (1994)", True, None)],
        "/MoviePilot/精武英雄 (1994)": [
            ("BDMV", True, None), ("CERTIFICATE", True, None)],
        "/MoviePilot/精武英雄 (1994)/BDMV": [
            ("STREAM", True, None), ("index.bdmv", False, None)],
        "/MoviePilot/精武英雄 (1994)/BDMV/STREAM": [
            ("00000.m2ts", False, None), ("00001.m2ts", False, None)],
    }


def test_disc_subtree_files_are_not_yielded():
    found = [f.rel for f in _FakeProvider(_bd_tree()).walk_media("/")]
    assert found == [], f"原盘里的码流片段不该入库，实际产出：{found}"


def test_normal_movie_still_yielded():
    tree = {
        "/": [("电影", True, None)],
        "/电影": [("阿凡达 (2009)", True, None)],
        "/电影/阿凡达 (2009)": [("阿凡达.mkv", False, None)],
    }
    found = [f.rel for f in _FakeProvider(tree).walk_media("/")]
    assert found == ["/电影/阿凡达 (2009)/阿凡达.mkv"]


def test_dvd_structure_also_skipped():
    tree = {
        "/": [("老片 (1999)", True, None)],
        "/老片 (1999)": [("VIDEO_TS", True, None)],
        "/老片 (1999)/VIDEO_TS": [("VTS_01_1.VOB", False, None)],
    }
    assert [f.rel for f in _FakeProvider(tree).walk_media("/")] == []


def test_is_disc_subtree_dir():
    assert disc_filter.is_disc_subtree_dir("BDMV")
    assert disc_filter.is_disc_subtree_dir("bdmv")
    assert disc_filter.is_disc_subtree_dir("CERTIFICATE")
    assert not disc_filter.is_disc_subtree_dir("STREAM")
    assert not disc_filter.is_disc_subtree_dir("电影")


def test_is_disc_subtree_rel():
    assert disc_filter.is_disc_subtree_rel("/电影/精武英雄 (1994)/BDMV/STREAM/00000.m2ts")
    assert not disc_filter.is_disc_subtree_rel("/电影/阿凡达 (2009)/阿凡达.mkv")
    # 最后一段是文件名，不该被当成目录
    assert not disc_filter.is_disc_subtree_rel("/电影/BDMV.mkv")


def test_local_path_scan_skips_disc_subtree(tmp_path):
    """库直接配本机路径时走 scanner._local_dir_files，与挂载是另一条遍历，也要挡"""
    from backend.emby_server.scanner import _local_dir_files

    movie = tmp_path / "精武英雄 (1994)"
    (movie / "BDMV" / "STREAM").mkdir(parents=True)
    (movie / "CERTIFICATE").mkdir()
    (movie / "BDMV" / "STREAM" / "00000.m2ts").write_bytes(b"x")
    (movie / "BDMV" / "index.bdmv").write_bytes(b"x")
    (movie / "CERTIFICATE" / "id.bdmv").write_bytes(b"x")

    normal = tmp_path / "阿凡达 (2009)"
    normal.mkdir()
    (normal / "阿凡达.mkv").write_bytes(b"x")

    found = sorted(f.name for f in _local_dir_files(str(tmp_path), []))
    assert found == ["阿凡达.mkv"], f"本机路径同样不该产出原盘碎片，实际：{found}"
