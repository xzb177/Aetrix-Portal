"""追新：必须覆盖远程（mount://）媒体源，并且不能靠整库递归硬扫。

生产实测全部库都是 ``mount://3/MoviePilot/...``（rclone RC），旧实现只查本机
目录，等于一个库都没检测——线程在跑、last_check 在更新，却永远发现不了新文件。

而「对整库递归列举」在生产也走不通：国产剧 1.4 万个文件，rclone RC 要几分钟，
超过任何合理超时（生产日志：库《动漫》远程挂载检查失败 timed out）。
所以必须先只列顶层（目录也带 ModTime），再对每个顶层目录列一层子目录
（季级），只递归最近变动的季级子目录。

**关键**：不能在顶层按 mtime 过滤——新出一集只改动 ``Season/`` 子目录的
mtime，顶层剧集目录 mtime 不变，"老剧出新集"会被漏掉（P0 回归测试覆盖）。
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


def _make_db():
    mount = SimpleNamespace(id=3, is_enabled=True,
                            config='{"mode":"rc","rc_url":"http://rclone:5572","fs":"MP:"}')

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return mount

    return SimpleNamespace(query=lambda *a, **k: _Q())


def test_two_phase_only_recurses_recent_season_dirs(monkeypatch):
    """只递归 ModTime 在窗口内的季级子目录；顶层目录不过滤（mtime 不可靠）"""
    now = datetime.now(timezone.utc).timestamp()
    fresh = now - 60
    old = now - 10 * 86400

    # 注意：顶层"新剧"的 mtime 是旧的——新集只改了 Season/ 的 mtime，
    # 即便如此也必须被检出（这正是 P0 bug 的场景）
    top = [
        {"Path": "新剧 (2026)", "Name": "新剧 (2026)", "IsDir": True, "ModTime": _iso(old)},
        {"Path": "老剧 (2019)", "Name": "老剧 (2019)", "IsDir": True, "ModTime": _iso(old)},
        {"Path": "根目录散片.mkv", "Name": "根目录散片.mkv", "IsDir": False, "ModTime": _iso(fresh)},
    ]
    # 第二级：Path 相对被列目录（rclone 真实语义）
    second = {
        "新剧 (2026)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True, "ModTime": _iso(fresh)},
            {"Path": "E00.mkv", "Name": "E00.mkv", "IsDir": False, "ModTime": _iso(old)},
        ],
        "老剧 (2019)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True, "ModTime": _iso(old)},
        ],
    }
    recursed = {
        ("新剧 (2026)", "Season 01"): [
            {"Path": "E01.mkv", "Name": "E01.mkv", "IsDir": False, "ModTime": _iso(fresh)},
            {"Path": "E02.mkv", "Name": "E02.mkv", "IsDir": False, "ModTime": _iso(old)},
        ],
    }
    calls = []

    def fake_rc(rc_url, path, payload, username="", password="", timeout=0):
        calls.append((payload["remote"], payload.get("opt", {})))
        remote = payload["remote"]
        if remote == "MoviePilot/电影/华语电影":
            return {"list": top}
        segs = remote.split("/")
        if len(segs) == 4:  # 季级：MoviePilot/电影/华语电影/<剧>
            return {"list": second.get(segs[-1], [])}
        if len(segs) == 5:  # 递归：.../<剧>/<季>
            return {"list": recursed.get((segs[-2], segs[-1]), [])}
        return {"list": []}

    monkeypatch.setattr("backend.emby_server.mount_rclone.rc_call", fake_rc)

    found = cw._find_new_videos_remote(_make_db(), 3, "/MoviePilot/电影/华语电影", now - 3600)

    remotes = [r for r, _ in calls]
    # 老剧的季目录是旧的：可以列第二级（便宜），但绝不能递归
    assert not any("老剧" in r and o.get("recurse") for r, o in calls), f"老剧不该被递归：{calls}"
    # 新剧的季目录被递归，且只递归一次
    assert sum(1 for r, o in calls if "新剧" in r and o.get("recurse")) == 1
    # 命中：顶层散片 + 新剧季目录里时间窗口内的 E01（E02/E00 太旧不算）
    assert len(found) == 2, found
    assert any("新剧 (2026)/Season 01/E01.mkv" in f for f in found), found
    assert any("根目录散片.mkv" in f for f in found)
    assert all(f.startswith("mount://3/") for f in found), found


def test_chase_new_detects_new_episode_in_old_show(monkeypatch):
    """P0 回归：老剧顶层目录 mtime 很旧，但 Season/ 子目录刚更新（新出一集）。

    旧实现在顶层按 mtime 过滤，直接把该剧筛掉 → 新集永远漏检。
    """
    now = datetime.now(timezone.utc).timestamp()
    fresh = now - 60
    old = now - 10 * 86400

    top = [
        # 顶层 mtime 很旧：新集只改了 Season/ 的 mtime，顶层不动
        {"Path": "老剧 (2019)", "Name": "老剧 (2019)", "IsDir": True, "ModTime": _iso(old)},
    ]
    second = {
        "老剧 (2019)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True, "ModTime": _iso(fresh)},
            {"Path": "Season 02", "Name": "Season 02", "IsDir": True, "ModTime": _iso(old)},
        ],
    }
    recursed = {
        ("老剧 (2019)", "Season 01"): [
            {"Path": "E99.mkv", "Name": "E99.mkv", "IsDir": False, "ModTime": _iso(fresh)},
            {"Path": "E98.mkv", "Name": "E98.mkv", "IsDir": False, "ModTime": _iso(old)},
        ],
    }

    def fake_rc(rc_url, path, payload, username="", password="", timeout=0):
        remote = payload["remote"]
        if remote == "MoviePilot/剧集/国产剧":
            return {"list": top}
        segs = remote.split("/")
        if len(segs) == 4:
            return {"list": second.get(segs[-1], [])}
        if len(segs) == 5:
            return {"list": recursed.get((segs[-2], segs[-1]), [])}
        return {"list": []}

    monkeypatch.setattr("backend.emby_server.mount_rclone.rc_call", fake_rc)

    found = cw._find_new_videos_remote(_make_db(), 3, "/MoviePilot/剧集/国产剧", now - 3600)

    # 必须检出新集 E99（E98 太旧不算；Season 02 没变动不递归）
    assert len(found) == 1, found
    assert found[0] == "mount://3/MoviePilot/剧集/国产剧/老剧 (2019)/Season 01/E99.mkv", found
