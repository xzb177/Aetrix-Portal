"""追新：必须覆盖远程（mount://）媒体源，并且不能靠整库递归硬扫。

生产实测全部库都是 ``mount://3/MoviePilot/...``（rclone RC），旧实现只查本机
目录，等于一个库都没检测——线程在跑、last_check 在更新，却永远发现不了新文件。

而「对整库递归列举」在生产也走不通：国产剧 1.4 万个文件，rclone RC 要几分钟，
超过任何合理超时（生产日志：库《动漫》远程挂载检查失败 timed out）。
所以必须先只列顶层（目录也带 ModTime），只递归最近变动的子目录。
"""
import os
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend.emby_server import change_watcher as cw


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def test_library_mount_sources_parses_mount_paths():
    lib = SimpleNamespace(paths="mount://3/MoviePilot/电影/华语电影", mount_ids="")
    assert cw._library_mount_sources(lib, SimpleNamespace()) == [(3, "/MoviePilot/电影/华语电影")]


def test_library_mount_sources_skips_non_mount_paths():
    lib = SimpleNamespace(paths="/data/local/movies,/nonexistent", mount_ids="")
    assert cw._library_mount_sources(lib, SimpleNamespace()) == []


def test_two_phase_only_recurses_recent_dirs(monkeypatch):
    """只递归 ModTime 在窗口内的子目录；旧目录不产生任何递归请求"""
    now = datetime.now(timezone.utc).timestamp()
    fresh = now - 60
    old = now - 10 * 86400

    top = [
        {"Path": "新剧 (2026)", "Name": "新剧 (2026)", "IsDir": True, "ModTime": _iso(fresh)},
        {"Path": "老剧 (2019)", "Name": "老剧 (2019)", "IsDir": True, "ModTime": _iso(old)},
        {"Path": "根目录散片.mkv", "Name": "根目录散片.mkv", "IsDir": False, "ModTime": _iso(fresh)},
    ]
    per_dir = {
        "新剧 (2026)": [
            {"Path": "新剧/E01.mkv", "Name": "E01.mkv", "IsDir": False, "ModTime": _iso(fresh)},
            {"Path": "新剧/E02.mkv", "Name": "E02.mkv", "IsDir": False, "ModTime": _iso(old)},
        ],
    }
    calls = []

    def fake_rc(rc_url, path, payload, username="", password="", timeout=0):
        calls.append((payload["remote"], payload.get("opt", {})))
        if payload["remote"] == "MoviePilot/电影/华语电影":
            return {"list": top}
        key = payload["remote"].rsplit("/", 1)[-1]
        return {"list": per_dir.get(key, [])}

    monkeypatch.setattr("backend.emby_server.mount_rclone.rc_call", fake_rc)

    mount = SimpleNamespace(id=3, is_enabled=True,
                            config='{"mode":"rc","rc_url":"http://rclone:5572","fs":"MP:"}')

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return mount

    db = SimpleNamespace(query=lambda *a, **k: _Q())

    found = cw._find_new_videos_remote(db, 3, "/MoviePilot/电影/华语电影", now - 3600)

    # 旧目录不得被递归
    remotes = [r for r, _ in calls]
    assert not any("老剧" in r for r in remotes), f"旧目录不该递归：{remotes}"
    # 新目录被递归，且只递归一次
    assert sum(1 for r in remotes if "新剧" in r) == 1
    # 命中：顶层散片 + 新目录里时间窗口内的 E01（E02 太旧不算）
    assert len(found) == 2, found
    assert any("E01.mkv" in f for f in found)
    assert any("根目录散片.mkv" in f for f in found)
    assert all(f.startswith("mount://3/") for f in found), found
