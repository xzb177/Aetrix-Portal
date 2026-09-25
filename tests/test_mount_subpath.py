"""媒体库支持 ``mount://<挂载 id>/<子目录>``：只扫描挂载下的子目录

起因：动漫剧库的 paths 里写着 ``mount://2/video/剧集/动漫剧``，但老代码把 paths
逐项当本机目录检查（``os.path.isdir``），每次扫描都报「目录不存在或不可读」，
而库真正扫的是整个挂载（mount_ids=2）——动漫库把全盘都扫了进去。

不碰网络、不碰数据库：用本机目录挂载（local）做提供者，db 用桩。
"""
from types import SimpleNamespace

import pytest

from backend.emby_server import models as em
from backend.emby_server import mounts as mnt


@pytest.fixture(autouse=True)
def _clean_list_cache():
    mnt.invalidate_list_cache()
    yield
    mnt.invalidate_list_cache()


class _FakeQuery:
    def __init__(self, mounts):
        self._mounts = mounts

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._mounts

    def first(self):
        return self._mounts[0] if self._mounts else None


class _FakeDB:
    def __init__(self, mounts):
        self._mounts = mounts

    def query(self, *args, **kwargs):
        return _FakeQuery(self._mounts)


def _local_mount(mount_id: int, path: str, enabled: bool = True) -> em.StorageMount:
    m = em.StorageMount(name=f"测试挂载{mount_id}", mount_type="local", path=path,
                        config=mnt.dump_config({}), is_enabled=enabled)
    m.id = mount_id
    return m


def _tree(tmp_path) -> None:
    (tmp_path / "video" / "剧集" / "动漫剧").mkdir(parents=True)
    (tmp_path / "video" / "剧集" / "动漫剧" / "a.mkv").write_bytes(b"x")
    (tmp_path / "video" / "影库").mkdir(parents=True)
    (tmp_path / "video" / "影库" / "b.mkv").write_bytes(b"x")


def test_mount_subpath_becomes_a_mount_source(tmp_path):
    """paths 里的 mount:// 条目变成带 subpath 的挂载来源"""
    _tree(tmp_path)
    mount = _local_mount(2, str(tmp_path))
    lib = SimpleNamespace(paths="mount://2/video/剧集/动漫剧", mount_ids="")

    sources, failed = mnt.library_sources(lib, _FakeDB([mount]))

    assert failed == []
    assert len(sources) == 1
    src = sources[0]
    assert src.kind == "mount"
    assert src.subpath == "/video/剧集/动漫剧"
    assert src.label == "mount://2/video/剧集/动漫剧"


def test_walk_media_with_root_only_yields_subdir_files(tmp_path):
    """walk_media(root=子目录) 只产出该子目录下的文件，rel 仍是挂载根相对路径"""
    _tree(tmp_path)
    mount = _local_mount(2, str(tmp_path))
    lib = SimpleNamespace(paths="mount://2/video/剧集/动漫剧", mount_ids="")
    sources, failed = mnt.library_sources(lib, _FakeDB([mount]))
    assert failed == []

    files = list(sources[0].provider.walk_media(root=sources[0].subpath))
    assert [f.rel for f in files] == ["/video/剧集/动漫剧/a.mkv"]
    # 入库路径保持 mount://2/... 格式（播放时照常解析）
    assert mnt.mount_path(2, files[0].rel) == "mount://2/video/剧集/动漫剧/a.mkv"


def test_missing_subdir_is_reported_unavailable(tmp_path):
    """子目录不存在 → 不可用来源（扫描器据此跳过清理，不会误删条目）"""
    _tree(tmp_path)
    mount = _local_mount(2, str(tmp_path))
    lib = SimpleNamespace(paths="mount://2/video/不存在的目录", mount_ids="")

    sources, failed = mnt.library_sources(lib, _FakeDB([mount]))

    assert sources == []
    assert len(failed) == 1
    assert failed[0]["label"] == "mount://2/video/不存在的目录"
    assert "子目录" in failed[0]["reason"]


def test_missing_mount_is_reported_unavailable(tmp_path):
    """mount:// 引用的挂载不存在 → 不可用来源"""
    lib = SimpleNamespace(paths="mount://99/video", mount_ids="")

    sources, failed = mnt.library_sources(lib, _FakeDB([]))

    assert sources == []
    assert len(failed) == 1
    assert "99" in failed[0]["reason"]


def test_disabled_mount_is_reported_unavailable(tmp_path):
    """mount:// 引用的挂载已停用 → 不可用来源"""
    _tree(tmp_path)
    mount = _local_mount(2, str(tmp_path), enabled=False)
    lib = SimpleNamespace(paths="mount://2/video/剧集/动漫剧", mount_ids="")

    sources, failed = mnt.library_sources(lib, _FakeDB([mount]))

    assert sources == []
    assert "停用" in failed[0]["reason"]


def test_plain_local_paths_still_work(tmp_path):
    """普通本机目录不受影响；不存在的本机目录仍报不可用"""
    _tree(tmp_path)
    lib = SimpleNamespace(paths=f"{tmp_path}/video/影库,/definitely/not/here", mount_ids="")

    sources, failed = mnt.library_sources(lib, _FakeDB([]))

    assert [s.kind for s in sources] == ["local"]
    assert len(failed) == 1 and "不可读" in failed[0]["reason"]


def test_whole_mount_source_keeps_subpath_root(tmp_path):
    """mount_ids（整挂载）的来源 subpath 仍是 /，行为不变"""
    _tree(tmp_path)
    mount = _local_mount(2, str(tmp_path))
    lib = SimpleNamespace(paths="", mount_ids="2")

    sources, failed = mnt.library_sources(lib, _FakeDB([mount]))

    assert failed == []
    assert sources[0].subpath == "/"
    rels = sorted(f.rel for f in sources[0].provider.walk_media(root=sources[0].subpath))
    assert rels == ["/video/剧集/动漫剧/a.mkv", "/video/影库/b.mkv"]


def test_check_mount_subpath(tmp_path):
    """后台保存校验：挂载不存在/子目录不存在时抛 MountError"""
    _tree(tmp_path)
    mount = _local_mount(2, str(tmp_path))
    db = _FakeDB([mount])

    mnt.check_mount_subpath(db, 2, "/video/剧集/动漫剧")  # 合法：静默通过
    with pytest.raises(mnt.MountError):
        mnt.check_mount_subpath(db, 2, "/video/不存在的目录")
    with pytest.raises(mnt.MountError):
        mnt.check_mount_subpath(_FakeDB([]), 99, "/video")
