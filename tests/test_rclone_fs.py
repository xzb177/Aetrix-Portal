"""rclone 挂载的 remote 名漏冒号：错误翻译、自动纠正与保存拦截

真实起因：面板里 remote 填成 ``paul_emby``（漏冒号），rclone 把它当成**它自己的本机路径**，
输出的是两行原始信息：

    NOTICE: "paul_emby" refers to a local folder, use "paul_emby:" to refer to your remote
    ERROR : error listing: directory not found

看的人只会顺着「directory not found」去查目录、查权限，其实要补的是一个冒号。所以这里钉住
三件事：

- **错误翻译**：这种输出明确说成写法问题，并给出正确写法（不是含糊的「路径不存在」）；
- **自动纠正**：首段就是远端已配置的 remote 时补冒号（``paul_emby/电影`` → ``paul_emby:电影``），
  老配置不必先手改再重扫；
- **保存拦截**：查得到 remote 列表却没有这个名字时，保存就直接 400，不再等扫描时才炸。

不碰网络、不碰数据库：列 remote 的调用在本文件里被替换。
"""
import subprocess

import pytest
from fastapi import HTTPException

from backend.emby_server import models as em
from backend.emby_server import mount_rclone
from backend.emby_server import mounts as mnt
from backend.emby_server.mount_rclone import (
    MountAuthError,
    MountError,
    RcloneMount,
    _cli_error,
    fs_missing_colon_hint,
    fs_remote_name,
    normalize_fs,
    remote_name_list,
)
from backend.emby_server.portal_mount_routes import _fix_rclone_root

# rclone 的真实输出（NOTICE + ERROR 两行）
NOTICE = (
    'NOTICE: "paul_emby" refers to a local folder, use "paul_emby:" to refer to your remote\n'
    "ERROR : error listing: directory not found\n"
)


def _cli_failure(stderr: str) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(1, ["rclone", "lsjson", "paul_emby"], stderr=stderr.encode())


@pytest.fixture(autouse=True)
def _clean_list_cache():
    """每个用例都从空目录缓存开始

    ``cached_listing`` 用的是**模块级**缓存，键里带配置指纹；本文件里的挂载都是
    **未入库**的对象（id 都是 None）、配置又很像，不隔离就会互相命中对方的目录列表，
    于是有的用例根本不去问远端。
    """
    mnt.invalidate_list_cache()
    yield
    mnt.invalidate_list_cache()


def _mount(config: dict) -> em.StorageMount:
    return em.StorageMount(name="测试 rclone", mount_type="rclone", path="",
                           config=mnt.dump_config(config), is_enabled=True)


# ==================== 错误翻译 ====================

def test_local_folder_notice_is_reported_as_a_missing_colon():
    """NOTICE 才是原因：不能翻译成「路径不存在」，要把冒号写清楚"""
    error = _cli_error(_cli_failure(NOTICE))
    assert isinstance(error, MountError) and not isinstance(error, MountAuthError)
    text = str(error)
    assert "冒号" in text and "paul_emby:" in text
    assert "路径不存在" not in text


def test_plain_directory_not_found_still_means_the_path_is_gone():
    error = _cli_error(_cli_failure('ERROR : error listing: directory not found\n'))
    assert "路径不存在" in str(error)


def test_credentials_are_still_reported_as_auth_problems():
    error = _cli_error(_cli_failure("Failed to create file system: 401 Unauthorized\n"))
    assert isinstance(error, MountAuthError)


def test_unrelated_failures_keep_the_raw_message():
    error = _cli_error(_cli_failure("something exploded\n"))
    assert "something exploded" in str(error)


# ==================== 路径判定与纠正 ====================

@pytest.mark.parametrize(("value", "expected"), [
    ("gdrive:Movies", "gdrive"),
    ("gdrive:", "gdrive"),
    ("paul_emby/电影", ""),      # 没有冒号 → rclone 当本机路径
    ("paul_emby", ""),
    ("", ""),
])
def test_fs_remote_name(value, expected):
    assert fs_remote_name(value) == expected


def test_remote_names_are_compared_without_the_trailing_colon():
    assert remote_name_list(["gdrive:", "s3", "gdrive:", ""]) == ["gdrive", "s3"]


def test_normalize_adds_the_colon_for_a_configured_remote():
    assert normalize_fs("paul_emby", ["paul_emby:"]) == "paul_emby:"
    assert normalize_fs("paul_emby/电影/2024", ["paul_emby:"]) == "paul_emby:电影/2024"


def test_normalize_leaves_correct_or_unknown_values_alone():
    assert normalize_fs("gdrive:Movies", ["gdrive:"]) == "gdrive:Movies"   # 本来就对
    assert normalize_fs("Movies", ["gdrive:"]) == "Movies"                 # 不在 remote 列表里
    assert normalize_fs("paul_emby", []) == "paul_emby"                    # 列表拿不到就不猜


@pytest.mark.parametrize("value", ["gdrive:Movies", "/media/movies", "./media", "~/media", ""])
def test_missing_colon_hint_ignores_valid_or_explicitly_local_values(value):
    assert fs_missing_colon_hint(value, ["gdrive:"]) == ""


def test_missing_colon_hint_tells_the_exact_fix():
    hint = fs_missing_colon_hint("paul_emby", ["paul_emby:", "gdrive:"])
    assert "冒号" in hint and "paul_emby:" in hint and "paul_emby:子目录" in hint
    assert "gdrive" in hint          # 顺带把可用的 remote 列出来


# ==================== 保存时纠正 / 拦截 ====================

def test_save_fixes_the_missing_colon_when_the_remote_exists(monkeypatch):
    monkeypatch.setattr(mount_rclone, "list_remotes", lambda *a, **k: ["paul_emby:", "gdrive:"])
    config = {"fs": "paul_emby/电影", "mode": "cli"}
    _fix_rclone_root("rclone", config)
    assert config["fs"] == "paul_emby:电影"


def test_save_rejects_a_remote_name_that_does_not_exist(monkeypatch):
    monkeypatch.setattr(mount_rclone, "list_remotes", lambda *a, **k: ["gdrive:"])
    with pytest.raises(HTTPException) as exc:
        _fix_rclone_root("rclone", {"fs": "paul_emby"})
    assert exc.value.status_code == 400
    assert "冒号" in str(exc.value.detail) and "gdrive" in str(exc.value.detail)


def test_save_still_blocks_the_typo_when_the_remote_list_is_unavailable(monkeypatch):
    """EM 这台机器没有 rclone / RC 连不上：查不到列表也要把明显的漏冒号拦下"""
    def boom(*_args, **_kwargs):
        raise MountError("找不到 rclone 可执行文件")

    monkeypatch.setattr(mount_rclone, "list_remotes", boom)
    with pytest.raises(HTTPException) as exc:
        _fix_rclone_root("rclone", {"fs": "paul_emby"})
    assert exc.value.status_code == 400 and "冒号" in str(exc.value.detail)


def test_save_does_not_touch_other_types_or_correct_values(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("写法没问题时不该去问远端 remote 列表")

    monkeypatch.setattr(mount_rclone, "list_remotes", unexpected)
    _fix_rclone_root("rclone", {"fs": "gdrive:Movies"})        # 已带冒号
    _fix_rclone_root("webdav", {"fs": "paul_emby"})            # 不是 rclone 类型
    _fix_rclone_root("rclone", {"fs": "/media/movies"})        # 明确的本地路径
    _fix_rclone_root("rclone", {})                             # 没填 remote（必填校验会报）


# ==================== 列目录 / 测试时自愈 ====================

def test_listing_heals_an_old_config_and_says_so(monkeypatch):
    """老配置里存着漏冒号的值：先按远端 remote 补上，再列目录（不必先手改配置）"""
    monkeypatch.setattr(mount_rclone, "list_remotes", lambda *a, **k: ["paul_emby:"], raising=False)
    calls: list[dict] = []

    def fake_rc_call(rc_url, path, payload=None, **_kwargs):  # noqa: ANN001
        calls.append({"path": path, "payload": payload or {}})
        return {"list": [{"Path": "电影", "Name": "电影", "Size": 0, "IsDir": True}]}

    monkeypatch.setattr(mount_rclone, "rc_call", fake_rc_call)
    provider = RcloneMount(_mount({"mode": "rc", "fs": "paul_emby"}))
    entries = provider.list_dir("/")
    assert provider.fs == "paul_emby:" and provider.healed_from == "paul_emby"
    assert [e.rel for e in entries] == ["/电影"]
    assert calls[0]["payload"]["fs"] == "paul_emby:"


def test_rc_listing_failure_also_explains_the_missing_colon(monkeypatch):
    """rc 模式只拿得到一句 directory not found（没有 NOTICE），也要能看懂"""
    def no_remotes(*_args, **_kwargs):
        raise MountError("找不到 rclone 可执行文件")

    def boom(*_args, **_kwargs):
        raise MountError("rclone: directory not found")

    monkeypatch.setattr(mount_rclone, "list_remotes", no_remotes)
    monkeypatch.setattr(mount_rclone, "rc_call", boom)
    with pytest.raises(MountError) as exc:
        RcloneMount(_mount({"mode": "rc", "fs": "paul_emby"})).list_dir("/")
    assert "冒号" in str(exc.value) and "directory not found" in str(exc.value)


def test_rc_listing_failure_keeps_the_original_message_for_a_valid_fs(monkeypatch):
    """remote 写法没问题时，原来的报错不能被改写成「漏冒号」"""
    def boom(*_args, **_kwargs):
        raise MountError("rclone: RC 返回 HTTP 500")

    monkeypatch.setattr(mount_rclone, "rc_call", boom)
    with pytest.raises(MountError) as exc:
        RcloneMount(_mount({"mode": "rc", "fs": "gdrive:Movies"})).list_dir("/")
    assert str(exc.value) == "rclone: RC 返回 HTTP 500"


def test_listing_does_not_heal_values_that_are_already_correct(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("写法没问题时不该去问远端 remote 列表")

    monkeypatch.setattr(mount_rclone, "list_remotes", unexpected)
    monkeypatch.setattr(mount_rclone, "rc_call",
                        lambda *a, **k: {"list": [{"Path": "a.mkv", "Name": "a.mkv",
                                                  "Size": 1, "IsDir": False}]})
    provider = RcloneMount(_mount({"mode": "rc", "fs": "gdrive:Movies"}))
    provider.list_dir("/")
    assert provider.fs == "gdrive:Movies" and provider.healed_from == ""


def test_self_healed_config_is_flagged_in_the_connection_test(monkeypatch):
    monkeypatch.setattr(mount_rclone, "list_remotes", lambda *a, **k: ["paul_emby:"])
    monkeypatch.setattr(mount_rclone, "rc_call", lambda *a, **k: {"list": []})
    monkeypatch.setattr(RcloneMount, "_request", lambda *a, **k: type("R", (), {"status_code": 200})())
    result = RcloneMount(_mount({"mode": "rc", "fs": "paul_emby"})).test()
    assert result["ok"] is True
    assert "paul_emby:" in result["message"] and "漏冒号" in result["message"]


def test_a_missing_rc_serve_does_not_hide_the_missing_colon_notice(monkeypatch):
    """两个问题同时存在时要都能看见

    漏冒号是「去改配置」，rc-serve 未开是「播放会 404」。后者不能把前者顶掉，
    否则管理员只看到 rc-serve 的提示，改完照旧播不了。
    """
    monkeypatch.setattr(mount_rclone, "list_remotes", lambda *a, **k: ["paul_emby:"])
    monkeypatch.setattr(mount_rclone, "rc_call", lambda *a, **k: {"list": []})
    monkeypatch.setattr(RcloneMount, "_request", lambda *a, **k: type("R", (), {"status_code": 404})())
    result = RcloneMount(_mount({"mode": "rc", "fs": "paul_emby"})).test()
    assert "漏冒号" in result["message"]
    assert "rc-serve" in result["message"]
