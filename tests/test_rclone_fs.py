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
from types import SimpleNamespace

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


def _mount(config: dict, path: str = "") -> em.StorageMount:
    return em.StorageMount(name="测试 rclone", mount_type="rclone", path=path,
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

#: rclone.conf 里配了哪些 remote（保存时读它，而不是问远端）
CONF_TEXT = "[paul_emby]\ntype = webdav\nurl = https://dav.example.com\n\n[gdrive]\ntype = drive\n"


@pytest.fixture()
def _conf(monkeypatch):
    monkeypatch.setattr(mount_rclone, "read_rclone_conf", lambda path="": CONF_TEXT)


def test_save_fixes_the_missing_colon_when_the_remote_exists(monkeypatch, _conf):
    assert _fix_rclone_root("rclone", "rclone:paul_emby/电影", {}) == "rclone:paul_emby:电影"


def test_save_rejects_a_remote_name_that_does_not_exist(monkeypatch):
    monkeypatch.setattr(mount_rclone, "read_rclone_conf", lambda path="": "[gdrive]\ntype = drive\n")
    with pytest.raises(HTTPException) as exc:
        _fix_rclone_root("rclone", "rclone:paul_emby", {})
    assert exc.value.status_code == 400
    assert "冒号" in str(exc.value.detail) and "gdrive" in str(exc.value.detail)


def test_save_still_blocks_the_typo_when_the_conf_is_missing(monkeypatch):
    """还没粘 rclone.conf：查不到列表也要把明显的漏冒号拦下"""
    monkeypatch.setattr(mount_rclone, "read_rclone_conf", lambda path="": "")
    with pytest.raises(HTTPException) as exc:
        _fix_rclone_root("rclone", "rclone:paul_emby", {})
    assert exc.value.status_code == 400 and "冒号" in str(exc.value.detail)


def test_save_does_not_touch_other_types_or_correct_values(monkeypatch, _conf):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("写法没问题时不该去读 rclone.conf")

    monkeypatch.setattr(mount_rclone, "read_rclone_conf", unexpected)
    assert _fix_rclone_root("rclone", "rclone:gdrive:Movies", {}) == "rclone:gdrive:Movies"
    assert _fix_rclone_root("115", "115:/0", {}) == "115:/0"          # 不是 rclone 类型
    assert _fix_rclone_root("local", "/media/movies", {}) == "/media/movies"
    assert _fix_rclone_root("rclone", "rclone:/media/movies", {}) == "rclone:/media/movies"


# ==================== 类型由路径前缀决定 ====================


@pytest.mark.parametrize("path,expected", [
    ("115:/0", "115"),
    ("115:/12345/电影", "115"),
    ("rclone:gdrive/Movies", "rclone"),
    ("rclone:", "rclone"),
    ("/media/movies", "local"),
    ("/media", "local"),
])
def test_detect_mount_type_from_path_prefix(path, expected):
    assert mnt.detect_mount_type(path) == expected


@pytest.mark.parametrize("path", ["", "s3://bucket/x", "gdrive:Movies", "media/movies"])
def test_detect_mount_type_rejects_unknown_prefixes(path):
    """认不出来的前缀必须返回空串，让调用方明确报错而不是猜一个类型"""
    assert mnt.detect_mount_type(path) == ""


# ==================== rclone.conf 由用户粘贴 ====================


def test_pasted_conf_is_written_atomically_with_600(tmp_path, monkeypatch):
    target = tmp_path / "rclone" / "rclone.conf"
    written = mount_rclone.write_rclone_conf(CONF_TEXT, str(target))
    assert written == str(target)
    assert target.read_text(encoding="utf-8") == CONF_TEXT
    assert oct(target.stat().st_mode)[-3:] == "600"
    assert not list(tmp_path.rglob("*.tmp")), "临时文件应该已经改名为正式文件"


def test_conf_parsing_rejects_broken_ini():
    with pytest.raises(MountError) as exc:
        mount_rclone.parse_rclone_conf("这不是 INI\n[未闭合\ntype = drive\n")
    assert "INI" in str(exc.value)


def test_conf_without_type_is_rejected(tmp_path):
    with pytest.raises(MountError) as exc:
        mount_rclone.write_rclone_conf("[gdrive]\nclient_id = x\n", str(tmp_path / "c.conf"))
    assert "type" in str(exc.value)


def test_conf_with_no_remote_at_all_is_rejected(tmp_path):
    with pytest.raises(MountError):
        mount_rclone.write_rclone_conf("# 只有注释\n", str(tmp_path / "c.conf"))


def test_conf_remote_names_ignore_surrounding_whitespace():
    assert mount_rclone.conf_remote_names(CONF_TEXT) == ["paul_emby:", "gdrive:"]


def test_read_conf_of_a_missing_file_is_empty(tmp_path):
    assert mount_rclone.read_rclone_conf(str(tmp_path / "nope.conf")) == ""


def test_cli_mode_passes_the_pasted_conf_to_rclone(monkeypatch, tmp_path):
    """cli 模式不填 rclone_config 时，跑的每条 rclone 命令都带 --config=<粘贴的那份>

    这是「rclone.conf 由用户自理」能不能成立的那一步：配置文件落在磁盘上没用，
    命令行不指过去 rclone 就还是去读它自己的 ~/.config/rclone/rclone.conf。
    """
    conf = tmp_path / "rclone.conf"
    conf.write_text(CONF_TEXT, encoding="utf-8")
    monkeypatch.setattr(mount_rclone, "CONF_PATH", str(conf))
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"")

    monkeypatch.setattr(mount_rclone.subprocess, "run", fake_run)
    monkeypatch.setattr(mount_rclone.shutil, "which", lambda _b: "/usr/bin/rclone")
    RcloneMount(_mount({"mode": "cli"}, path="rclone:gdrive/Movies")).list_dir("/")
    assert commands and commands[0][:2] == ["rclone", "lsjson"]
    assert f"--config={conf}" in commands[0], commands[0]


def test_explicit_rclone_config_overrides_the_default(monkeypatch, tmp_path):
    conf = tmp_path / "rclone.conf"
    conf.write_text(CONF_TEXT, encoding="utf-8")
    monkeypatch.setattr(mount_rclone, "CONF_PATH", str(tmp_path / "default.conf"))
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"")

    monkeypatch.setattr(mount_rclone.subprocess, "run", fake_run)
    monkeypatch.setattr(mount_rclone.shutil, "which", lambda _b: "/usr/bin/rclone")
    mount = _mount({"mode": "cli", "rclone_config": str(conf)}, path="rclone:gdrive/M")
    RcloneMount(mount).list_dir("/")
    assert f"--config={conf}" in commands[0], commands[0]


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


# ==================== rc-serve 出流 URL ====================
#
# rclone 的 rc-serve 根目录页面上给出的链接是 ``./[paul_emby:]/``：remote 名要用
# **方括号**包起来，才能和普通目录区分。写成 ``/paul_emby:/x.mkv`` 会被当成一个叫
# ``paul_emby:`` 的本机目录而 404 —— 而列目录走 ``/operations/list`` 完全正常，
# 于是「能浏览、不能播」，很容易被误判成 rc-serve 没开。


def _rc_mount(config: dict) -> RcloneMount:
    return RcloneMount(_mount(config))


def test_play_url_wraps_remote_in_brackets():
    m = _rc_mount({"mode": "rc", "fs": "paul_emby:", "rc_url": "http://rclone:5572"})
    assert m._rc_play_url("/") == "http://rclone:5572/[paul_emby:]/"
    assert m._rc_play_url("video/影库") == "http://rclone:5572/[paul_emby:]/video/%E5%BD%B1%E5%BA%93"


def test_play_url_keeps_subpath_inside_remote():
    m = _rc_mount({"mode": "rc", "fs": "gdrive:Movies", "rc_url": "http://127.0.0.1:5572"})
    assert m._rc_play_url("2024/a.mkv") == "http://127.0.0.1:5572/[gdrive:Movies]/2024/a.mkv"


def test_play_url_never_leaves_a_bare_colon_path():
    """回归钉住：URL 路径里不允许出现裸的 ``remote:``（那会被 rclone 当本机目录）"""
    m = _rc_mount({"mode": "rc", "fs": "paul_emby:", "rc_url": "http://rclone:5572"})
    url = m._rc_play_url("video/a.mkv")
    assert "/paul_emby:/" not in url
    assert url.startswith("http://rclone:5572/[paul_emby:]/")


def test_play_url_percent_encodes_each_segment():
    m = _rc_mount({"mode": "rc", "fs": "paul_emby:", "rc_url": "http://rclone:5572"})
    url = m._rc_play_url("剧集/某 片 (2024).mkv")
    # 斜杠分段编码，空格与中文不裸露
    assert url == "http://rclone:5572/[paul_emby:]/%E5%89%A7%E9%9B%86/%E6%9F%90%20%E7%89%87%20%282024%29.mkv"
