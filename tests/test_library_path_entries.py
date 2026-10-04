"""媒体库路径与存储后端分离（界面不再出现 ``mount://1/...``）

入库形态**一点没变**（``Library.paths`` 仍然是本机绝对路径 / ``mount://<id>/<子目录>`` /
``115:/`` / ``rclone:``），变的只是「界面怎么显示」与「界面怎么写回来」这一层：

    存 → assemble_library_path：裸路径 + 后端 + 挂载 id ⇒ mount://3/电影
    读 → library_path_entries：  mount://3/电影      ⇒ {path: /电影, backend: 115}

所以这里同时钉住三件事：
1. 简化形态能**往返**（界面写什么，存进去再读出来还是什么）；
2. **老数据**（只有 mount://、没有 storage_backends 列）回显成简化形态且不报错；
3. 扫描侧仍然只认入库形态（``library_sources`` 行为不变，不会因为多了后端列就多扫一次）。
"""
from types import SimpleNamespace

import pytest

from backend.emby_server import mounts as mnt
from backend.emby_server import portal
from backend.emby_server import portal_mount_routes as pmr
from fastapi import HTTPException


def _lib(paths: str, backends: str = "", mount_ids: str = "") -> SimpleNamespace:
    return SimpleNamespace(paths=paths, storage_backends=backends, mount_ids=mount_ids)


def _mount(mount_id: int, mount_type: str, name: str = "挂载", enabled: bool = True):
    return SimpleNamespace(id=mount_id, mount_type=mount_type, name=name, is_enabled=enabled)


# ==================== 展示：mount:// 隐藏成「挂载内路径 + 后端标签」 ====================

def test_mount_path_is_shown_without_prefix():
    lib = _lib("mount://3/video/剧集/国产剧")
    mounts = {3: _mount(3, "115", "115 影库")}

    (entry,) = mnt.library_path_entries(lib, mounts)

    assert entry["path"] == "/video/剧集/国产剧"
    assert entry["backend"] == "115"
    assert entry["backend_label"] == "115 网盘"
    assert entry["mount_id"] == 3
    assert entry["mount_name"] == "115 影库"
    assert entry["source"] == "mount"
    # 入库形态原样带出（改动对比 / 排障用，界面不显示）
    assert entry["raw"] == "mount://3/video/剧集/国产剧"


def test_legacy_library_without_backends_column_still_shows_backend():
    """老库没有 storage_backends 列：后端靠挂载类型现推，行为不变"""
    lib = _lib("mount://7/Movies,rclone:gdrive/Movies,/media/电影")

    entries = mnt.library_path_entries(lib, {7: _mount(7, "rclone", "谷歌云盘")})

    assert [e["backend"] for e in entries] == ["rclone", "rclone", "local"]
    assert [e["path"] for e in entries] == ["/Movies", "rclone:gdrive/Movies", "/media/电影"]
    assert [e["source"] for e in entries] == ["mount", "prefix", "local"]


def test_stored_backend_covers_deleted_mount():
    """挂载已删、但记得当时走的是哪种存储：回显不靠猜"""
    lib = _lib("mount://3/电影", backends="115")

    (entry,) = mnt.library_path_entries(lib, {})  # 挂载已经查不到

    assert entry["backend"] == "115"
    assert entry["backend_label"] == "115 网盘"
    assert entry["mount_name"] == ""


def test_mount_type_wins_over_stale_stored_backend():
    """挂载还在时以挂载类型为准：挂载被改成 rclone 后，旧库里的 115 不能继续显示着骗人"""
    lib = _lib("mount://3/电影", backends="115")

    (entry,) = mnt.library_path_entries(lib, {3: _mount(3, "rclone")})

    assert entry["backend"] == "rclone"


def test_deleted_mount_falls_back_to_unknown_instead_of_guessing():
    """挂载被删 + 没记过后端：宁可显示「未知来源」也不猜一个（猜错比空白更误导）"""
    (entry,) = mnt.library_path_entries(_lib("mount://99/电影"), {})

    assert entry["backend"] == ""
    assert entry["backend_label"] == "未知来源"


def test_entries_and_backends_stay_aligned():
    lib = _lib("mount://3/a,/media/b,mount://4/c", backends="115,local,rclone")

    entries = mnt.library_path_entries(lib, {3: _mount(3, "115"), 4: _mount(4, "rclone")})

    assert [e["backend"] for e in entries] == ["115", "local", "rclone"]


def test_split_library_paths_ignores_blank_and_duplicates():
    assert mnt.split_library_paths(" /media/a , ,/media/a,/media/b ") == [
        "/media/a", "/media/b",
    ]


# ==================== 组装：裸路径 + 后端 ⇒ mount:// 前缀 ====================

def test_assemble_adds_mount_prefix_for_remote_backend():
    assert mnt.assemble_library_path(
        {"path": "/电影", "backend": "115", "mount_id": 3}) == "mount://3/电影"


def test_assemble_normalizes_missing_leading_slash():
    assert mnt.assemble_library_path(
        {"path": "电影/2024", "backend": "rclone", "mount_id": 5}) == "mount://5/电影/2024"


def test_assemble_keeps_local_path_untouched():
    assert mnt.assemble_library_path(
        {"path": "/media/电影", "backend": "local"}) == "/media/电影"


def test_assemble_allows_prefix_path_without_mount():
    """不建挂载直连的老用法要继续能用（扫描器认得这两个前缀）"""
    assert mnt.assemble_library_path(
        {"path": "rclone:gdrive/Movies", "backend": "rclone"}) == "rclone:gdrive/Movies"
    assert mnt.assemble_library_path(
        {"path": "115:/0", "backend": "115"}) == "115:/0"


def test_assemble_rejects_remote_backend_without_mount():
    """选了 Rclone 又没挂载、路径也没前缀：直接报错，别存一个扫不出东西的来源"""
    with pytest.raises(mnt.MountError) as excinfo:
        mnt.assemble_library_path({"path": "/视频", "backend": "rclone"})

    assert "存储挂载" in str(excinfo.value)


def test_assemble_rejects_empty_remote_path():
    with pytest.raises(mnt.MountError):
        mnt.assemble_library_path({"path": "  ", "backend": "115"})


# ==================== 往返 ====================

@pytest.mark.parametrize("mount_type,backend", [("115", "115"), ("rclone", "rclone")])
def test_round_trip_keeps_path_and_backend(mount_type, backend):
    """界面写「/电影 + 选 Rclone」→ 存成 mount://5/电影 → 读回还是「/电影 + Rclone」"""
    raw = mnt.assemble_library_path({"path": "/电影", "backend": backend, "mount_id": 5})
    lib = _lib(raw, mnt.dump_storage_backends([backend]))

    (entry,) = mnt.library_path_entries(lib, {5: _mount(5, mount_type)})

    assert raw == f"mount://5/电影"
    assert (entry["path"], entry["backend"]) == ("/电影", backend)


def test_round_trip_local_untouched():
    raw = mnt.assemble_library_path({"path": "/media/电影", "backend": "local"})
    lib = _lib(raw, mnt.dump_storage_backends(["local"]))

    (entry,) = mnt.library_path_entries(lib, {})

    assert (entry["path"], entry["backend"], entry["source"]) == ("/media/电影", "local", "local")


# ==================== 后端归一与标签 ====================

@pytest.mark.parametrize("raw,expect", [
    ("LOCAL", "local"), ("Rclone", "rclone"), ("115", "115"),
    (" pan115 ", "115"), ("", ""), (None, ""), ("webdav", "webdav"),
])
def test_normalize_storage_backend(raw, expect):
    assert mnt.normalize_storage_backend(raw) == expect


def test_backend_label_falls_back_to_mount_type_label():
    """未进 STORAGE_BACKEND_LABELS 的扩展类型（webdav / alist）用挂载类型元数据里的名字；
    两者都没有才显示「未知来源」——不能空白，那看着像没取到值"""
    assert mnt.storage_backend_label("local") == "本地文件"
    assert mnt.storage_backend_label("rclone") == "Rclone"
    assert mnt.storage_backend_label("webdav") in ("WebDAV", "webdav")
    assert mnt.storage_backend_label("") == "未知来源"


def test_backend_matches_mount():
    assert mnt.backend_matches_mount("115", _mount(3, "115")) is True
    assert mnt.backend_matches_mount("rclone", _mount(3, "115")) is False
    assert mnt.backend_matches_mount("", _mount(3, "115")) is False


# ==================== 扫描侧不受影响 ====================

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *args, **kwargs):
        return _FakeQuery(self._rows)


def test_library_sources_still_reads_mount_prefix(tmp_path):
    """多一列 storage_backends 不影响扫描：来源照旧从 paths 里的前缀解析出来"""
    (tmp_path / "movies").mkdir()
    mnt.invalidate_list_cache()
    mount = SimpleNamespace(id=2, mount_type="local", name="本机媒体盘", is_enabled=True,
                            path=str(tmp_path), config=mnt.dump_config({}))
    lib = _lib(f"mount://2/movies,{tmp_path}", backends="local,local")

    sources, failed = mnt.library_sources(lib, _FakeDB([mount]))

    mnt.invalidate_list_cache()
    assert failed == []
    # library_sources 先收本机目录、再收挂载子目录（与改动无关的老顺序）
    assert [s.kind for s in sources] == ["local", "mount"]


# ==================== 接口层：path_entries ⇒ paths + storage_backends ====================

class _MountTable:
    """按 id 查挂载的最小桩（portal._resolve_entry_mounts 只用到 filter/first）

    filter 的入参是 ``StorageMount.id == <id>``，取它的右值当过滤条件；
    不做这个过滤的话，不同 mount_id 会全部命中第一行，测出来的东西是假的。
    """

    def __init__(self, rows):
        self._rows = rows
        self._want = None

    def filter(self, clause, *args, **kwargs):
        self._want = getattr(getattr(clause, "right", None), "value", None)
        return self

    def all(self):
        if self._want is None:
            return list(self._rows)
        return [r for r in self._rows if r.id == self._want]

    def first(self):
        rows = self.all()
        return rows[0] if rows else None


class _MountDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *args, **kwargs):
        return _MountTable(self._rows)


def _entry(path: str, backend: str = "local", mount_id: int | None = None):
    return portal.LibraryPathEntry(path=path, backend=backend, mount_id=mount_id)


def test_payload_assembles_prefix_and_keeps_backends_aligned():
    db = _MountDB([_mount(3, "115"), _mount(4, "rclone")])

    paths, backends = portal._library_path_payload(db, [
        _entry("/video/剧集", "115", 3),
        _entry("/media/电影"),
        _entry("Movies", "rclone", 4),
    ])

    assert paths == "mount://3/video/剧集,/media/电影,mount://4/Movies"
    assert backends == "115,local,rclone"


def test_payload_drops_duplicate_paths_without_shifting_backends():
    """重复条目去重后，后端列跟着重排，否则会对错位置（第二个条目被标成错误的后端）"""
    db = _MountDB([_mount(3, "115")])

    paths, backends = portal._library_path_payload(db, [
        _entry("/电影", "115", 3),
        _entry("/media/剧集"),
        _entry("/电影", "115", 3),
    ])

    assert paths == "mount://3/电影,/media/剧集"
    assert backends == "115,local"


def test_payload_accepts_local_path_without_mount():
    db = _MountDB([])

    paths, backends = portal._library_path_payload(db, [_entry("/media/电影")])

    assert paths == "/media/电影"
    assert backends == "local"


def test_payload_rejects_backend_mount_mismatch():
    """选了 115、却选了 rclone 挂载：直接拒，不让自相矛盾的来源入库"""
    db = _MountDB([_mount(4, "rclone")])

    with pytest.raises(HTTPException) as excinfo:
        portal._library_path_payload(db, [_entry("/电影", "115", 4)])

    assert excinfo.value.status_code == 400
    assert "115 网盘" in excinfo.value.detail and "Rclone" in excinfo.value.detail


def test_payload_rejects_missing_mount():
    db = _MountDB([])

    with pytest.raises(HTTPException) as excinfo:
        portal._library_path_payload(db, [_entry("/电影", "rclone", 9)])

    assert excinfo.value.status_code == 400
    assert "不存在" in excinfo.value.detail


def test_payload_rejects_disabled_mount():
    db = _MountDB([_mount(3, "115", "115 影库", enabled=False)])

    with pytest.raises(HTTPException) as excinfo:
        portal._library_path_payload(db, [_entry("/电影", "115", 3)])

    assert "已停用" in excinfo.value.detail


def test_payload_rejects_empty_path():
    db = _MountDB([])

    with pytest.raises(HTTPException):
        portal._library_path_payload(db, [_entry("   ")])


# ==================== 本机目录浏览（与挂载浏览返回同一套结构） ====================

def test_local_dirs_lists_subdirectories_only(tmp_path):
    (tmp_path / "电影").mkdir()
    (tmp_path / "剧集").mkdir()
    (tmp_path / "说明.txt").write_text("x")

    dirs, truncated = pmr._list_local_dirs(str(tmp_path))

    assert truncated is False
    # 只列目录，按名称排序（文件不进列表）
    assert [d["name"] for d in dirs] == ["剧集", "电影"]
    assert dirs[0]["path"] == f"{tmp_path}/剧集"


def test_local_dirs_returns_none_for_missing_path(tmp_path):
    assert pmr._list_local_dirs(str(tmp_path / "nope")) is None


def test_local_dirs_reports_file_as_not_a_directory(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("x")

    assert pmr._list_local_dirs(str(target)) == "不是目录"


def test_local_dirs_truncates_huge_directories(tmp_path, monkeypatch):
    for i in range(5):
        (tmp_path / f"d{i}").mkdir()
    monkeypatch.setattr(pmr, "_LOCAL_BROWSE_MAX", 2)

    dirs, truncated = pmr._list_local_dirs(str(tmp_path))

    assert len(dirs) == 2
    assert truncated is True