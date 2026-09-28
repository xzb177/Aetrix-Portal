"""追新：必须覆盖远程（mount://）媒体源。

生产实测全部库都是 ``mount://3/MoviePilot/...``（rclone RC），旧实现只查本机
目录，等于一个库都没检测——线程在跑、last_check 在更新，却永远发现不了新文件。
"""
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend.emby_server import change_watcher as cw


def test_library_mount_sources_parses_mount_paths():
    lib = SimpleNamespace(paths="mount://3/MoviePilot/电影/华语电影", mount_ids="")
    assert cw._library_mount_sources(lib, SimpleNamespace()) == [(3, "/MoviePilot/电影/华语电影")]


def test_library_mount_sources_skips_non_mount_paths():
    lib = SimpleNamespace(paths="/data/local/movies,/nonexistent", mount_ids="")
    assert cw._library_mount_sources(lib, SimpleNamespace()) == []


def test_find_new_videos_remote_filters_by_modtime(monkeypatch):
    now = datetime.now(timezone.utc)
    fresh = (now.timestamp() - 60)
    old = (now.timestamp() - 10 * 86400)
    items = [
        {"Path": "A/新片.mkv", "Name": "新片.mkv", "IsDir": False,
         "ModTime": datetime.fromtimestamp(fresh, tz=timezone.utc).isoformat().replace("+00:00", "Z")},
        {"Path": "A/老片.mkv", "Name": "老片.mkv", "IsDir": False,
         "ModTime": datetime.fromtimestamp(old, tz=timezone.utc).isoformat().replace("+00:00", "Z")},
        {"Path": "A/说明.txt", "Name": "说明.txt", "IsDir": False,
         "ModTime": datetime.fromtimestamp(fresh, tz=timezone.utc).isoformat().replace("+00:00", "Z")},
        {"Path": "A/子目录", "Name": "子目录", "IsDir": True, "ModTime": None},
    ]

    class _Mount:
        id = 3
        is_enabled = True

        class _Config:
            pass

    mount = _Mount()
    mount.config = '{"mode":"rc","rc_url":"http://rclone:5572","fs":"MP:"}'

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return mount

    db = SimpleNamespace(query=lambda *a, **k: _Q())

    def fake_rc(rc_url, path, payload, username="", password=""):
        assert path == "/operations/list"
        assert payload["opt"]["recurse"] is True
        return {"list": items}

    monkeypatch.setattr("backend.emby_server.mount_rclone.rc_call", fake_rc)

    found = cw._find_new_videos_remote(db, 3, "/MoviePilot/电影/华语电影", now.timestamp() - 3600)
    assert len(found) == 1
    assert "新片.mkv" in found[0]
    assert found[0].startswith("mount://3/")
