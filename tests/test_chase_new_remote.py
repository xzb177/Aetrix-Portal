"""追新：必须覆盖远程（mount://）媒体源，走公共通道，且不能靠整库递归硬扫。

生产实测全部库都是 ``mount://3/MoviePilot/...``（rclone RC），旧实现只查本机
目录，等于一个库都没检测——线程在跑、last_check 在更新，却永远发现不了新文件。

而「对整库递归列举」在生产也走不通：国产剧 1.4 万个文件，rclone RC 要几分钟，
超过任何合理超时（生产日志：库《动漫》远程挂载检查失败 timed out）。
所以必须先只列顶层（目录也带 ModTime），再对每个顶层目录列一层子目录
（季级），只往下钻最近变动的季级子目录。

**关键**：不能在顶层按 mtime 过滤——新出一集只改动 ``Season/`` 子目录的
mtime，顶层剧集目录 mtime 不变，"老剧出新集"会被漏掉（P0 回归测试覆盖）。

2026-10：追新改走 ``mounts`` 公共通道（``build_provider`` + ``list_dir``），
不再直接调 ``rc_call``。旧旁路无上限地打 rclone，生产 24 小时 5.2 万条报错。
本文件除了行为回归，还钉住「确实走了公共通道」（缓存/限流/熔断可见）与
「追新占的是自己的小名额，不与扫描抢」。
"""
import os
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend.emby_server import change_watcher as cw
from backend.emby_server import mount_rclone
from backend.emby_server import mounts as mount_lib


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def test_library_mount_sources_parses_mount_paths():
    lib = SimpleNamespace(paths="mount://3/MoviePilot/电影/华语电影", mount_ids="")
    assert cw._library_mount_sources(lib, SimpleNamespace()) == [(3, "/MoviePilot/电影/华语电影")]


def test_library_mount_sources_skips_non_mount_paths():
    lib = SimpleNamespace(paths="/data/local/movies,/nonexistent", mount_ids="")
    assert cw._library_mount_sources(lib, SimpleNamespace()) == []


def _make_db(mount_type="rclone", mode="rc"):
    mount = SimpleNamespace(id=3, is_enabled=True, mount_type=mount_type,
                            config=('{"mode":"%s","rc_url":"http://rclone:5572","fs":"MP:"}' % mode))

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return mount

    return SimpleNamespace(query=lambda *a, **k: _Q())


@pytest.fixture(autouse=True)
def _clean_cache():
    mount_lib.invalidate_list_cache()
    yield
    mount_lib.invalidate_list_cache()


def _install_tree(monkeypatch, tree: dict, calls: list):
    """把远端目录树装到 rclone RC 上（key 是相对 fs 根的 remote 路径）"""

    def fake_rc(rc_url, path, payload, username="", password="", **kwargs):
        remote = payload["remote"]
        calls.append(remote)
        return {"list": tree.get(remote, [])}

    monkeypatch.setattr(mount_rclone, "rc_call", fake_rc)


def test_two_phase_only_recurses_recent_season_dirs(monkeypatch):
    """只往下钻 ModTime 在窗口内的季级子目录；顶层目录不过滤（mtime 不可靠）"""
    now = datetime.now(timezone.utc).timestamp()
    fresh = now - 60
    old = now - 10 * 86400

    # 注意：顶层"新剧"的 mtime 是旧的——新集只改了 Season/ 的 mtime，
    # 即便如此也必须被检出（这正是 P0 bug 的场景）
    tree = {
        "MoviePilot/电影/华语电影": [
            {"Path": "新剧 (2026)", "Name": "新剧 (2026)", "IsDir": True, "ModTime": _iso(old)},
            {"Path": "老剧 (2019)", "Name": "老剧 (2019)", "IsDir": True, "ModTime": _iso(old)},
            {"Path": "根目录散片.mkv", "Name": "根目录散片.mkv", "IsDir": False, "ModTime": _iso(fresh)},
        ],
        "MoviePilot/电影/华语电影/新剧 (2026)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True, "ModTime": _iso(fresh)},
            {"Path": "E00.mkv", "Name": "E00.mkv", "IsDir": False, "ModTime": _iso(old)},
        ],
        "MoviePilot/电影/华语电影/老剧 (2019)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True, "ModTime": _iso(old)},
        ],
        "MoviePilot/电影/华语电影/新剧 (2026)/Season 01": [
            {"Path": "E01.mkv", "Name": "E01.mkv", "IsDir": False, "ModTime": _iso(fresh)},
            {"Path": "E02.mkv", "Name": "E02.mkv", "IsDir": False, "ModTime": _iso(old)},
        ],
    }
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    found = cw._find_new_videos_remote(_make_db(), 3, "/MoviePilot/电影/华语电影", now - 3600)

    # 老剧的季目录是旧的：可以列第二级（便宜），但绝不能往下钻
    assert "MoviePilot/电影/华语电影/老剧 (2019)/Season 01" not in calls, calls
    # 新剧的季目录被钻，且只钻一次
    assert calls.count("MoviePilot/电影/华语电影/新剧 (2026)/Season 01") == 1, calls
    # 命中：顶层散片 + 新剧季目录里时间窗口内的 E01（E02/E00 太旧不算）
    assert len(found) == 2, found
    assert any("新剧 (2026)/Season 01/E01.mkv" in f for f in found), found
    assert any("根目录散片.mkv" in f for f in found), found
    assert all(f.startswith("mount://3/") for f in found), found


def test_chase_new_detects_new_episode_in_old_show(monkeypatch):
    """P0 回归：老剧顶层目录 mtime 很旧，但 Season/ 子目录刚更新（新出一集）。

    旧实现在顶层按 mtime 过滤，直接把该剧筛掉 → 新集永远漏检。
    """
    now = datetime.now(timezone.utc).timestamp()
    fresh = now - 60
    old = now - 10 * 86400

    tree = {
        "MoviePilot/剧集/国产剧": [
            # 顶层 mtime 很旧：新集只改了 Season/ 的 mtime，顶层不动
            {"Path": "老剧 (2019)", "Name": "老剧 (2019)", "IsDir": True, "ModTime": _iso(old)},
        ],
        "MoviePilot/剧集/国产剧/老剧 (2019)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True, "ModTime": _iso(fresh)},
            {"Path": "Season 02", "Name": "Season 02", "IsDir": True, "ModTime": _iso(old)},
        ],
        "MoviePilot/剧集/国产剧/老剧 (2019)/Season 01": [
            {"Path": "E99.mkv", "Name": "E99.mkv", "IsDir": False, "ModTime": _iso(fresh)},
            {"Path": "E98.mkv", "Name": "E98.mkv", "IsDir": False, "ModTime": _iso(old)},
        ],
    }
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    found = cw._find_new_videos_remote(_make_db(), 3, "/MoviePilot/剧集/国产剧", now - 3600)

    # 必须检出新集 E99（E98 太旧不算；Season 02 没变动不钻）
    assert found == ["mount://3/MoviePilot/剧集/国产剧/老剧 (2019)/Season 01/E99.mkv"], found
    assert "MoviePilot/剧集/国产剧/老剧 (2019)/Season 02" not in calls, calls


def test_chase_new_walks_nested_season_dirs(monkeypatch):
    """季目录里还有一层（特别篇 / 压制组）时也要能挖到，且不会无限往下钻"""
    now = datetime.now(timezone.utc).timestamp()
    fresh = now - 60
    tree = {
        "MP2": [
            {"Path": "剧 (2020)", "Name": "剧 (2020)", "IsDir": True, "ModTime": _iso(fresh)},
        ],
        "MP2/剧 (2020)": [
            {"Path": "Season 01", "Name": "Season 01", "IsDir": True, "ModTime": _iso(fresh)},
        ],
        "MP2/剧 (2020)/Season 01": [
            {"Path": "Specials", "Name": "Specials", "IsDir": True, "ModTime": _iso(fresh)},
        ],
        "MP2/剧 (2020)/Season 01/Specials": [
            {"Path": "SP01.mkv", "Name": "SP01.mkv", "IsDir": False, "ModTime": _iso(fresh)},
        ],
    }
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    found = cw._find_new_videos_remote(_make_db(), 3, "/MP2", now - 3600)

    assert found == ["mount://3/MP2/剧 (2020)/Season 01/Specials/SP01.mkv"], found
    # 深度上限之内就够了；不该无限延伸
    assert "MP2/剧 (2020)/Season 01/Specials/SP01.mkv" not in calls, calls


def test_chase_new_skips_cli_mode_mounts(monkeypatch):
    """cli 模式不走这条实现（ModTime 口径不同），应当安静跳过而不是抛错"""
    def boom(*a, **k):  # noqa: ANN001
        raise AssertionError("cli 模式不该发起任何列举")

    monkeypatch.setattr(mount_rclone, "rc_call", boom)
    assert cw._find_new_videos_remote(_make_db(mode="cli"), 3, "/MP2", 0.0) == []


def test_chase_new_goes_through_public_channel(monkeypatch):
    """追新必须走公共通道：同一目录再问一次应当命中目录缓存（不再打网络）"""
    now = datetime.now(timezone.utc).timestamp()
    tree = {"MP2": [
        {"Path": "x.mkv", "Name": "x.mkv", "IsDir": False, "ModTime": _iso(now - 60)},
    ]}
    calls: list[str] = []
    _install_tree(monkeypatch, tree, calls)

    first = cw._find_new_videos_remote(_make_db(), 3, "/MP2", now - 3600)
    after_first = len(calls)
    second = cw._find_new_videos_remote(_make_db(), 3, "/MP2", now - 3600)

    assert first == second == ["mount://3/MP2/x.mkv"], (first, second)
    # 第二轮整个库一次网络请求都没多发——这就是走公共通道的直接证据
    assert len(calls) == after_first == 1, calls


def test_chase_new_uses_its_own_small_concurrency_quota(monkeypatch):
    """追新占的是自己的小名额：并发被 CHASE_REMOTE_CONCURRENCY 限制（默认 1）"""
    tree = {f"MP2/d{i}": [
        {"Path": f"{i}.mkv", "Name": f"{i}.mkv", "IsDir": False, "ModTime": _iso(0)},
    ] for i in range(6)}
    tree["MP2"] = [
        {"Path": f"d{i}", "Name": f"d{i}", "IsDir": True, "ModTime": _iso(0)}
        for i in range(6)
    ]
    tree["MP2/d0"] = [{"Path": "S", "Name": "S", "IsDir": True, "ModTime": _iso(0)}]
    tree["MP2/d0/S"] = [
        {"Path": f"e{j}.mkv", "Name": f"e{j}.mkv", "IsDir": False, "ModTime": _iso(0)}
        for j in range(6)
    ]

    lock = threading.Lock()
    inflight = 0
    peak = 0

    def fake_rc(rc_url, path, payload, username="", password="", **kwargs):
        nonlocal inflight, peak
        with lock:
            inflight += 1
            peak = max(peak, inflight)
        try:
            time.sleep(0.02)
            return {"list": tree.get(payload["remote"], [])}
        finally:
            with lock:
                inflight -= 1

    monkeypatch.setattr(mount_rclone, "rc_call", fake_rc)
    monkeypatch.setattr(mount_lib, "CHASE_REMOTE_CONCURRENCY", 1)
    monkeypatch.setattr(mount_lib, "_CHASE_SEM", None)
    monkeypatch.setattr(mount_lib, "_CHASE_SEM_SIZE", 0)
    mount_lib.invalidate_list_cache()

    # 3 个线程各查一个挂载，共享同一个 1 名额的追新信号量 → 峰值必须为 1
    threads = [threading.Thread(target=cw._find_new_videos_remote,
                                args=(_make_db(), 3, f"/MP2/d{i}", 0.0))
               for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak <= 1, f"追新并发峰值 {peak} 超过了 CHASE_REMOTE_CONCURRENCY=1"
    mount_lib._CHASE_SEM = None
    mount_lib._CHASE_SEM_SIZE = 0


def test_chase_new_goes_through_the_shared_channel(monkeypatch):
    """远端坏了：追新必须真打请求（熔断器已删），但走公共通道而不是自带旁路"""
    from backend.emby_server import mounts as ml

    calls = []
    lock = threading.Lock()

    def boom(rc_url, path, payload, username="", password="", **kwargs):
        with lock:
            calls.append(payload["remote"])
        raise ml.MountError("rclone: 模拟远端故障")

    monkeypatch.setattr(mount_rclone, "rc_call", boom)

    for _ in range(3):
        cw._find_new_videos_remote(_make_db(), 3, "/MP2", 0.0)

    # 熔断器删除后不再有「快速失败」这条捷径：每一次都真去问远端，错误如实抛出。
    # 这正是它跟 limit/缓存共用 _call_remote 的意义——请求量看得见、可限流。
    assert len(calls) == 3, calls
