"""Tests for backend/emby_server/strm_gen.py — .strm 生成器内置版。

覆盖：路径映射、视频判定、冲突解决、配置归一化、完整性校验。
不碰网络（Drive API 部分用 monkeypatch 隔离）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.emby_server import strm_gen as sg


class TestStrmRelpath:
    def test_strip_prefix(self):
        assert sg.strm_relpath("MoviePilot/剧集/xx.mkv", "MoviePilot/") == "剧集/xx.strm"

    def test_no_prefix(self):
        assert sg.strm_relpath("电影/xx.mp4", "") == "电影/xx.strm"

    def test_prefix_not_matched(self):
        # 前缀不匹配时保留原路径
        assert sg.strm_relpath("Other/xx.mkv", "MoviePilot/") == "Other/xx.strm"

    def test_nested(self):
        assert sg.strm_relpath(
            "MoviePilot/剧集/国产剧/惊枝 (2026)/Season 1/惊枝 - S01E01.mkv",
            "MoviePilot/",
        ) == "剧集/国产剧/惊枝 (2026)/Season 1/惊枝 - S01E01.strm"


class TestIsVideoPath:
    def test_video(self):
        assert sg.is_video_path("MoviePilot/剧集/xx.mkv")
        assert sg.is_video_path("MoviePilot/电影/xx.MP4")  # 大小写

    def test_not_video(self):
        assert not sg.is_video_path("MoviePilot/剧集/xx.nfo")
        assert not sg.is_video_path("MoviePilot/剧集/xx.jpg")

    def test_skip_hidden(self):
        assert not sg.is_video_path("MoviePilot/.hidden/xx.mkv")
        assert not sg.is_video_path("MoviePilot/剧集/.DS_Store.mkv")

    def test_skip_system_dirs(self):
        assert not sg.is_video_path("MoviePilot/剧集/@eaDir/xx.mkv")
        assert not sg.is_video_path("MoviePilot/剧集/#recycle/xx.mkv")

    def test_all_supported_exts(self):
        for ext in sg.VIDEO_EXTS:
            assert sg.is_video_path(f"a/b{ext}"), ext


class TestDriveUrl:
    def test_format(self):
        url = sg.drive_url("1QALUKEAwNgo1J8y2EipIDTcVDwIrpX_y")
        assert url == ("https://drive.google.com/uc?export=download"
                       "&id=1QALUKEAwNgo1J8y2EipIDTcVDwIrpX_y&confirm=t")


class TestResolveCollision:
    def test_no_collision(self):
        assert sg._resolve_collision("a/b.strm", set()) == "a/b.strm"

    def test_collision(self):
        used = {"a/b.strm"}
        assert sg._resolve_collision("a/b.strm", used) == "a/b-2.strm"

    def test_multiple(self):
        used = {"a/b.strm", "a/b-2.strm"}
        assert sg._resolve_collision("a/b.strm", used) == "a/b-3.strm"


class TestVerifyCompleteness:
    def _videos(self):
        # (rel, fid, size)
        return [
            ("MoviePilot/剧集/A/Season 1/A - S01E01.mkv", "f1", 100),
            ("MoviePilot/剧集/A/Season 1/A - S01E02.mkv", "f2", 100),
            ("MoviePilot/剧集/A/Season 1/A - S01E03.mkv", "f3", 100),
            ("MoviePilot/剧集/B/Season 1/B - S01E01.mkv", "f4", 100),
        ]

    def _make_state_on_disk(self, videos, tmp_path, skip=()):
        # state: {rel: (fid, size, spath)}，并在 tmp_path 下创建真实 .strm 文件
        import os
        state = {}
        for rel, fid, size in videos:
            if any(s in rel for s in skip):
                continue
            spath = rel.replace("MoviePilot/", "").replace(".mkv", ".strm")
            full = os.path.join(str(tmp_path), spath)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write("x")
            state[rel] = (fid, size, spath)
        return state

    def test_all_complete(self, tmp_path):
        videos = self._videos()
        state = self._make_state_on_disk(videos, tmp_path)
        result = sg._verify_completeness(videos, state, "MoviePilot/", str(tmp_path))
        assert result["total_series"] == 2  # A/Season 1, B/Season 1
        assert result["incomplete_series"] == 0

    def test_missing_detected(self, tmp_path):
        videos = self._videos()
        # state 缺了 A 的 E03
        state = self._make_state_on_disk(videos, tmp_path, skip=("E03",))
        result = sg._verify_completeness(videos, state, "MoviePilot/", str(tmp_path))
        assert result["incomplete_series"] == 1
        inc = result["incomplete"][0]
        assert inc["series"] == "剧集/A/Season 1"
        assert inc["missing_count"] == 1
        assert any("E03" in m for m in inc["missing_sample"])


    def test_missing_file_on_disk_counts_as_missing(self, tmp_path):
        # DB 有行但 .strm 文件不在磁盘 → 计为缺失（P3-2）
        videos = self._videos()
        state = self._make_state_on_disk(videos, tmp_path)
        # 删掉一个 .strm 文件
        import os
        gone = os.path.join(str(tmp_path), "剧集/A/Season 1/A - S01E01.strm")
        os.remove(gone)
        result = sg._verify_completeness(videos, state, "MoviePilot/", str(tmp_path))
        assert result["incomplete_series"] == 1
        inc = result["incomplete"][0]
        assert inc["series"] == "剧集/A/Season 1"
        assert inc["missing_count"] == 1


class TestSchedule:
    def test_valid(self):
        assert sg.schedule(_FakeDb({"strm_gen_schedule": "03:00"})) == "03:00"

    def test_invalid(self):
        assert sg.schedule(_FakeDb({"strm_gen_schedule": "25:00"})) == ""
        assert sg.schedule(_FakeDb({"strm_gen_schedule": "abc"})) == ""
        assert sg.schedule(_FakeDb({"strm_gen_schedule": ""})) == ""

    def test_source_dir(self):
        assert sg.source_dir(_FakeDb({"strm_gen_source_dir": "MoviePilot/"})) == "MoviePilot/"
        assert sg.source_dir(_FakeDb({"strm_gen_source_dir": ""})) == ""
        assert sg.source_dir(_FakeDb({})) == "MoviePilot/"  # 默认

    def test_enabled(self):
        assert sg.enabled(_FakeDb({"strm_gen_enabled": "true"}))
        assert not sg.enabled(_FakeDb({"strm_gen_enabled": "false"}))
        assert sg.enabled(_FakeDb({}))  # 默认 true


class _FakeDb:
    """最小 store.get_value 替身。"""

    def __init__(self, values: dict):
        self._values = values


# 给 _db_config 打桩：strm_gen._db_config(db, key, default)
@pytest.fixture(autouse=True)
def _patch_db_config(monkeypatch):
    def fake_db_config(db, key, default=""):
        if isinstance(db, _FakeDb):
            return db._values.get(key, default)
        return default
    monkeypatch.setattr(sg, "_db_config", fake_db_config)


class TestStrmGenModel:
    """P0-1：StrmGenFile 表必须存在（原来引用了但没建表，状态读写静默失败）。"""

    def test_table_exists(self):
        from backend.emby_server.models import StrmGenFile
        assert StrmGenFile.__tablename__ == "strm_gen_files"
        cols = {c.key for c in StrmGenFile.__table__.columns}
        assert {"remote_path", "file_id", "size", "strm_path", "updated_at"} <= cols

    def test_remote_path_is_pk(self):
        from backend.emby_server.models import StrmGenFile
        pks = [c.key for c in StrmGenFile.__table__.primary_key.columns]
        assert pks == ["remote_path"]


class TestRoutesRegistered:
    """P0-3：5 个 API 路由必须挂在 admin_emby_router 上（原来从未被 import）。"""

    def test_five_routes(self):
        import backend.api.admin_strm_gen  # noqa: F401  # 触发装饰器注册
        from backend.emby_server.portal import admin_emby_router
        by_path: dict[str, set[str]] = {}
        for r in admin_emby_router.routes:
            p = getattr(r, "path", "")
            if "strm-gen" in p:
                by_path.setdefault(p, set()).update(getattr(r, "methods", None) or set())
        assert by_path.get("/api/admin/emby/strm-gen/config", set()) >= {"GET", "PUT"}
        assert by_path.get("/api/admin/emby/strm-gen/trigger", set()) >= {"POST"}
        assert by_path.get("/api/admin/emby/strm-gen/progress", set()) >= {"GET"}
        assert by_path.get("/api/admin/emby/strm-gen/missing", set()) >= {"GET"}


class TestRunControl:
    """P3-6：运行权原子获取，不再有触发竞态。"""

    def test_try_acquire(self):
        sg._set_progress(running=False, phase="idle")
        try:
            assert sg.try_acquire() is True
            assert sg.try_acquire() is False  # 第二次拿不到
        finally:
            sg._set_progress(running=False, phase="idle")
        assert sg.try_acquire() is True
        sg._set_progress(running=False, phase="idle")

    def test_run_generation_rejects_when_running(self):
        sg._set_progress(running=True, phase="generating")
        try:
            res = sg.run_generation(None)
            assert res["ok"] is False
            assert "运行中" in res["error"]
        finally:
            sg._set_progress(running=False, phase="idle")

    def test_start_scheduler_idempotent(self, monkeypatch):
        # 不真正起线程：只验证幂等标记逻辑
        import threading
        monkeypatch.setattr(sg, "_scheduler_started", True)
        before = threading.active_count()
        assert sg.start_scheduler() is True
        assert threading.active_count() == before  # 没起新线程
        monkeypatch.setattr(sg, "_scheduler_started", False)


class TestSafeRelpath:
    """P3-7：输出路径防目录穿越。"""

    def test_dotdot_stripped(self):
        assert sg._safe_relpath("a/../../b") == "a/b"
        assert sg._safe_relpath("../x") == "x"

    def test_strm_relpath_sanitized(self):
        assert sg.strm_relpath("MoviePilot/../x.mkv", "MoviePilot/") == "x.strm"


class TestPageFetcher:
    """P1-1：列举中途 401 自动刷新 token 续跑。"""

    def test_refresh_on_401(self, monkeypatch):
        calls = []
        tokens = ["old", "new"]
        monkeypatch.setattr(sg, "_get_token", lambda: tokens.pop(0))
        def fake_list_page(token, drive_id, query, page_token):
            calls.append(token)
            if token == "old":
                raise PermissionError("Drive token 无效或过期")
            return ([{"id": "1"}], None)
        monkeypatch.setattr(sg, "_list_files_page", fake_list_page)
        fetch = sg._page_fetcher("d1")
        files, _ = fetch("q", None)
        assert files == [{"id": "1"}]
        assert calls == ["old", "new"]

    def test_reraise_when_refresh_fails(self, monkeypatch):
        monkeypatch.setattr(sg, "_get_token", lambda: "same")
        def fake_list_page(token, drive_id, query, page_token):
            raise PermissionError("Drive token 无效或过期")
        monkeypatch.setattr(sg, "_list_files_page", fake_list_page)
        fetch = sg._page_fetcher("d1")
        import pytest as _pytest
        with _pytest.raises(PermissionError):
            fetch("q", None)


class TestVerifyDisk:
    """P3-2：完整性校验同时验磁盘真实存在。"""

    def test_missing_on_disk_counts_as_incomplete(self, tmp_path):
        videos = [
            ("MoviePilot/剧集/A/Season 1/A - S01E01.mkv", "f1", 100),
            ("MoviePilot/剧集/A/Season 1/A - S01E02.mkv", "f2", 100),
        ]
        # DB 有行，但磁盘上一个文件都没有
        state = {rel: (fid, size, rel.replace(".mkv", ".strm").replace("MoviePilot/", ""))
                 for rel, fid, size in videos}
        result = sg._verify_completeness(videos, state, "MoviePilot/", strm_root=str(tmp_path))
        assert result["incomplete_series"] == 1
        assert result["incomplete"][0]["strm_count"] == 0

    def test_present_on_disk_counts_as_complete(self, tmp_path):
        videos = [("MoviePilot/剧集/A/Season 1/A - S01E01.mkv", "f1", 100)]
        spath = "剧集/A/Season 1/A - S01E01.strm"
        (tmp_path / "剧集/A/Season 1").mkdir(parents=True)
        (tmp_path / spath).write_text("x")
        state = {videos[0][0]: ("f1", 100, spath)}
        result = sg._verify_completeness(videos, state, "MoviePilot/", strm_root=str(tmp_path))
        assert result["incomplete_series"] == 0


class TestRunGenerationMocked:
    """核心流程 mock 测试（Drive/DB/落盘全部隔离）。"""

    def _patch_all(self, tmp_path, monkeypatch, videos, state=None, drives=None):
        monkeypatch.setattr(sg, "iter_drive_videos",
                            lambda drive_id, dir_path: iter(list(videos)))
        monkeypatch.setattr(sg, "_discover_drives",
                            lambda: drives if drives is not None else {"d1": ["sa1"]})
        monkeypatch.setattr(sg, "_container_strm_root", lambda db: str(tmp_path))
        monkeypatch.setattr(sg, "_load_state", lambda: dict(state or {}))
        saved: dict = {}
        monkeypatch.setattr(sg, "_save_state_rows",
                            lambda rows: saved.update({r[0]: r for r in rows}))
        deleted: list = []
        monkeypatch.setattr(sg, "_delete_state_rows", lambda rows: deleted.extend(rows))
        # _release_progress 里真实的 store.set_value 打桩掉
        import backend.integrations.store as _store
        monkeypatch.setattr(_store, "write_values", lambda *a, **k: 0)
        return saved, deleted

    def test_full_run_creates_strm(self, tmp_path, monkeypatch):
        videos = [
            ("MoviePilot/剧集/A/Season 1/A - S01E01.mkv", "fid1", 100),
            ("MoviePilot/剧集/A/Season 1/A - S01E02.mkv", "fid2", 200),
        ]
        self._patch_all(tmp_path, monkeypatch, videos)
        try:
            res = sg.run_generation(_FakeDb({}), full=False)
        finally:
            sg._set_progress(running=False, phase="idle")
        assert res["ok"] is True
        assert res["stats"]["generated"] == 2
        p = tmp_path / "剧集/A/Season 1/A - S01E01.strm"
        assert p.exists()
        assert "fid1" in p.read_text()

    def test_incremental_skips_unchanged(self, tmp_path, monkeypatch):
        videos = [("MoviePilot/剧集/A/Season 1/A - S01E01.mkv", "fid1", 100)]
        state = {"MoviePilot/剧集/A/Season 1/A - S01E01.mkv":
                 ("fid1", 100, "剧集/A/Season 1/A - S01E01.strm")}
        (tmp_path / "剧集/A/Season 1").mkdir(parents=True)
        (tmp_path / "剧集/A/Season 1/A - S01E01.strm").write_text("old")
        self._patch_all(tmp_path, monkeypatch, videos, state=state)
        try:
            res = sg.run_generation(_FakeDb({}), full=False)
        finally:
            sg._set_progress(running=False, phase="idle")
        assert res["stats"]["skipped"] == 1
        assert res["stats"]["generated"] == 0

    def test_size_change_rebuilds(self, tmp_path, monkeypatch):
        """P3-9：size 变化也触发重建（原来只比 file_id）。"""
        videos = [("MoviePilot/剧集/A/Season 1/A - S01E01.mkv", "fid1", 999)]
        state = {"MoviePilot/剧集/A/Season 1/A - S01E01.mkv":
                 ("fid1", 100, "剧集/A/Season 1/A - S01E01.strm")}
        (tmp_path / "剧集/A/Season 1").mkdir(parents=True)
        (tmp_path / "剧集/A/Season 1/A - S01E01.strm").write_text("old")
        self._patch_all(tmp_path, monkeypatch, videos, state=state)
        try:
            res = sg.run_generation(_FakeDb({}), full=False)
        finally:
            sg._set_progress(running=False, phase="idle")
        assert res["stats"]["generated"] == 1
        assert res["stats"]["skipped"] == 0

    def test_multi_drive(self, tmp_path, monkeypatch):
        """P1-2：不指定 drive 时遍历所有共享盘（原来只跑第一个）。"""
        def fake_iter(drive_id, dir_path):
            return iter([(f"MoviePilot/{drive_id}/a.mkv", f"fid-{drive_id}", 10)])
        monkeypatch.setattr(sg, "iter_drive_videos", fake_iter)
        monkeypatch.setattr(sg, "_discover_drives", lambda: {"d1": ["s"], "d2": ["s"]})
        monkeypatch.setattr(sg, "_container_strm_root", lambda db: str(tmp_path))
        monkeypatch.setattr(sg, "_load_state", lambda: {})
        monkeypatch.setattr(sg, "_save_state_rows", lambda rows: None)
        import backend.integrations.store as _store
        monkeypatch.setattr(_store, "write_values", lambda *a, **k: 0)
        try:
            res = sg.run_generation(_FakeDb({}), full=False)
        finally:
            sg._set_progress(running=False, phase="idle")
        assert res["ok"] is True
        assert res["stats"]["generated"] == 2
        assert (tmp_path / "d1/a.strm").exists()
        assert (tmp_path / "d2/a.strm").exists()

    def test_prune_removes_stale(self, tmp_path, monkeypatch):
        """P2-3：prune 开启时删除 Drive 已不存在的条目；默认关闭。"""
        videos = [("MoviePilot/剧集/A/a.mkv", "fid1", 100)]
        state = {
            "MoviePilot/剧集/A/a.mkv": ("fid1", 100, "剧集/A/a.strm"),
            "MoviePilot/剧集/OLD/old.mkv": ("fidOld", 100, "剧集/OLD/old.strm"),
        }
        (tmp_path / "剧集/A").mkdir(parents=True)
        (tmp_path / "剧集/A/a.strm").write_text("x")
        (tmp_path / "剧集/OLD").mkdir(parents=True)
        (tmp_path / "剧集/OLD/old.strm").write_text("x")
        _saved, deleted = self._patch_all(tmp_path, monkeypatch, videos, state=state)
        try:
            res = sg.run_generation(_FakeDb({"strm_gen_prune": "true"}), full=False)
        finally:
            sg._set_progress(running=False, phase="idle")
        assert res["ok"] is True
        assert res["stats"]["pruned"] == 1
        assert not (tmp_path / "剧集/OLD/old.strm").exists()
        assert (tmp_path / "剧集/A/a.strm").exists()
        assert deleted == ["MoviePilot/剧集/OLD/old.mkv"]

    def test_prune_off_by_default(self, tmp_path, monkeypatch):
        videos = [("MoviePilot/剧集/A/a.mkv", "fid1", 100)]
        state = {"MoviePilot/剧集/OLD/old.mkv": ("fidOld", 100, "剧集/OLD/old.strm")}
        (tmp_path / "剧集/OLD").mkdir(parents=True)
        (tmp_path / "剧集/OLD/old.strm").write_text("x")
        _saved, deleted = self._patch_all(tmp_path, monkeypatch, videos, state=state)
        try:
            res = sg.run_generation(_FakeDb({}), full=False)
        finally:
            sg._set_progress(running=False, phase="idle")
        assert res["stats"]["pruned"] == 0
        assert (tmp_path / "剧集/OLD/old.strm").exists()
        assert deleted == []


class TestSelectDrive:
    """P1-2：多盘选择逻辑。"""

    def test_explicit_param_wins(self):
        did, info = sg._select_drive_id(_FakeDb({}), drive_id="dd")
        assert did == "dd"
        assert info["drives_found"] == 0

    def test_config_wins_over_auto(self, monkeypatch):
        monkeypatch.setattr(sg, "_discover_drives",
                            lambda: {"b": ["r"], "a": ["r"]})
        did, info = sg._select_drive_id(
            _FakeDb({"strm_gen_drive_id": "b"}), drive_id=None)
        assert did == "b"

    def test_auto_picks_first_sorted_and_notes(self, monkeypatch):
        monkeypatch.setattr(sg, "_discover_drives",
                            lambda: {"zz": ["r1"], "aa": ["r2"]})
        did, info = sg._select_drive_id(_FakeDb({}), drive_id=None)
        assert did == "aa"
        assert info["auto_selected"] is True
        assert info["drives_found"] == 2
        assert "aa" in info["drive_note"] and "zz" in info["drive_note"]

    def test_no_drives(self, monkeypatch):
        monkeypatch.setattr(sg, "_discover_drives", lambda: {})
        did, info = sg._select_drive_id(_FakeDb({}), drive_id=None)
        assert did is None

    def test_list_drives_sorted(self, monkeypatch):
        monkeypatch.setattr(sg, "_discover_drives",
                            lambda: {"zz": ["r1"], "aa": ["r2"]})

        class FakeDc:
            @staticmethod
            def _is_personal_drive_key(did):
                return did.startswith("myDrive:")

        monkeypatch.setattr(sg, "_drive_modules", lambda: FakeDc())
        drives = sg.list_drives()
        assert [d["drive_id"] for d in drives] == ["aa", "zz"]


class TestSafeName:
    """P3-7：文件名清理。"""

    def test_strips_dotdot(self):
        assert sg._safe_name("..") == ""
        assert sg._safe_name("../a") == "a"


class TestResolveDirIdPagination:
    """P2-1：_resolve_dir_id 应翻页查找（fetch 闭包版）。"""

    def test_finds_on_second_page(self):
        calls = {"n": 0}

        def fetch(query, page_token=None):
            calls["n"] += 1
            # 第一页没命中但有下一页；目标在第二页
            if page_token is None:
                return ([], "p2")
            return ([{"id": "dir123", "name": "MoviePilot", "trashed": False}], None)

        got = sg._resolve_dir_id(fetch, "d1", "MoviePilot/")
        assert got == "dir123"
        assert calls["n"] == 2

    def test_returns_none_when_not_found(self):
        def fetch(query, page_token=None):
            return ([], None)

        assert sg._resolve_dir_id(fetch, "d1", "不存在的目录/") is None
