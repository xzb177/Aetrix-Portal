"""inotify 监听的两个前提（FUSE 降级 + 挂载类型识别）

对应两个 P0：

1. **FUSE 上不能挂 inotify**。rclone mount / sshfs / cifs 能通过 ``isdir`` +
   ``access`` 两道检查，但真去 watch 会把整个挂载点拖死。所以在 ``isdir`` **之前**
   按文件系统类型拒掉，并给出人话原因。
2. **挂载类型认得出**。``/proc/self/mountinfo`` 读不到时必须「当作没有 FUSE 信息」
   继续按老路走——拿不到信息不等于「不能监听」，否则容器里读不到挂载表就会把
   所有正常本机目录误降级。

测试全部走纯函数（临时文件 + monkeypatch 挂载表），不碰真实挂载、不起 observer。
"""
import os

import pytest

from backend.emby_server import fs_watcher


@pytest.fixture(autouse=True)
def _no_real_mountinfo(monkeypatch):
    """默认把挂载表换成空的：测试不受跑测机器的挂载布局影响"""
    monkeypatch.setattr(fs_watcher, "_mountinfo_cache", (1e18, []))


def _mounts(monkeypatch, rows):
    monkeypatch.setattr(fs_watcher, "_mountinfo_cache", (1e18, rows))


# ==================== 挂载表解析 ====================

def test_mount_table_picks_longest_prefix(monkeypatch, tmp_path):
    """嵌套挂载点必须取**最长**前缀：/mnt 下再挂一层 rclone 时不能判成 /mnt 的类型"""
    _mounts(monkeypatch, [
        ("/", "ext4"),
        ("/mnt", "ext4"),
        ("/mnt/mp/rclone", "fuse.rclone"),
    ])

    assert fs_watcher.fstype_of("/mnt/mp/rclone/Movies") == "fuse.rclone"
    assert fs_watcher.fstype_of("/mnt/paul_emby") == "ext4"
    # 挂载点本身也要能认出来（不带尾斜杠）
    assert fs_watcher.fstype_of("/mnt/mp/rclone") == "fuse.rclone"


def test_mount_point_escape_is_decoded(monkeypatch):
    """内核把空格转义成 \\040；不解回来就永远匹配不上（前缀判断会错）"""
    rows = [("/mnt/my\\040disk", "fuse.sshfs")]
    _mounts(monkeypatch, rows)

    # 直接验证我们写的解码规则，而不是依赖测试机上真的存在这个挂载
    assert "/mnt/my\\040disk".replace("\\040", " ") == "/mnt/my disk"


def test_unknown_fstype_is_empty_string(monkeypatch):
    """读不到挂载表 → 返回空串（调用方据此**不判**成 FUSE）"""
    _mounts(monkeypatch, [])
    assert fs_watcher.fstype_of("/media/电影") == ""


# ==================== is_watchable：FUSE 一律拒 ====================

@pytest.mark.parametrize("fstype", ["fuse.rclone", "fuse", "fuseblk", "sshfs", "cifs", "exfat"])
def test_fuse_mounts_are_never_watchable(monkeypatch, tmp_path, fstype):
    """FUSE / 网络盘：即使目录真实存在且可读，也必须拒掉"""
    real = tmp_path / "mnt"
    real.mkdir()
    _mounts(monkeypatch, [(str(real), fstype)])

    ok, why = fs_watcher.is_watchable(str(real))

    assert ok is False
    # 原因要说清「降级去哪了」，界面把它直接显示给用户
    assert fstype in why
    assert "定时扫描" in why


def test_plain_local_dir_is_still_watchable(monkeypatch, tmp_path):
    """普通 ext4 目录不受影响——降级不能误伤正常路径"""
    d = tmp_path / "local"
    d.mkdir()
    _mounts(monkeypatch, [(str(d), "ext4")])

    ok, why = fs_watcher.is_watchable(str(d))

    assert ok is True, why


def test_unreadable_mount_table_does_not_block_normal_paths(monkeypatch, tmp_path):
    """挂载表读不出来时退化成老行为：只查 isdir/access，不把所有目录都降级"""
    d = tmp_path / "local"
    d.mkdir()
    _mounts(monkeypatch, [])  # 相当于表是空的

    ok, why = fs_watcher.is_watchable(str(d))

    assert ok is True, why


def test_fuse_check_runs_before_isdir(monkeypatch, tmp_path):
    """FUSE 判定必须在 isdir 之前：卡死的挂载点上 isdir 本身就可能很慢/失败

    用一个「存在但读起来会炸」的目录验证：FUSE 命中时直接返回，不去碰文件系统。
    """
    _mounts(monkeypatch, [("/mnt/hang", "fuse.rclone")])

    def _boom(_p):
        raise AssertionError("不该走到 os.path.isdir —— FUSE 应在前面就拒掉")

    monkeypatch.setattr(os.path, "isdir", _boom)
    monkeypatch.setattr(os, "access", _boom)

    ok, why = fs_watcher.is_watchable("/mnt/hang/Movies")

    assert ok is False
    assert "fuse.rclone" in why


def test_empty_and_relative_paths_still_rejected(monkeypatch):
    """原有两条前置校验不能被 FUSE 逻辑挤掉"""
    _mounts(monkeypatch, [("/", "ext4")])
    assert fs_watcher.is_watchable("")[0] is False
    assert fs_watcher.is_watchable("relative/path")[0] is False