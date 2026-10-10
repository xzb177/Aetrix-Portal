"""SA 轮换只改 rclone.conf，SA 在挂载/rcd 启动时加载——不重挂不生效。

代码库没有应用内的重挂/重载 rclone 挂载的能力（rcd 重启是宿主机脚本
scripts/restart_rclone_rcd.sh，FUSE 挂载由 scripts/rclone_vfs_mount.sh 在宿主机起），
所以不发明基础设施：结果里明确标 needs_remount，接口和后台把它说出来。
"""

from unittest import mock

from backend.emby_server import playback_tune as pt


def _conf(tmp_path):
    conf = tmp_path / "rclone.conf"
    conf.write_text("[gd]\ntype = drive\nservice_account_file = /old.json\n", encoding="utf-8")
    sa = tmp_path / "sa"
    sa.mkdir()
    (sa / "a.json").write_text("{}", encoding="utf-8")
    (sa / "b.json").write_text("{}", encoding="utf-8")
    return conf, sa


def test_rotation_result_flags_needs_remount(tmp_path):
    conf, sa = _conf(tmp_path)
    r = pt.ensure_sa_rotation(conf, sa, state_path=tmp_path / "s.json")
    assert r["changed"] is True
    assert r["needs_remount"] is True


def test_rotation_no_change_no_remount(tmp_path):
    conf = tmp_path / "rclone.conf"
    conf.write_text("[gd]\ntype = drive\ntoken = x\n", encoding="utf-8")
    sa = tmp_path / "sa"
    sa.mkdir()
    (sa / "a.json").write_text("{}", encoding="utf-8")
    r = pt.ensure_sa_rotation(conf, sa, state_path=tmp_path / "s.json")
    assert r["changed"] is False
    assert r["needs_remount"] is False


def test_endpoint_surfaces_needs_remount():
    from backend.api import admin as admin_api
    with mock.patch.object(pt, "ensure_sa_rotation", autospec=True,
                           return_value={"sa_file": "/x/a.json", "mode": "rotated",
                                         "changed": True, "needs_remount": True}), \
            mock.patch("pathlib.Path.exists", return_value=True), \
            mock.patch.object(admin_api, "_audit"):
        out = admin_api.gdrive_sa_rotate(current_admin=mock.MagicMock(), db=mock.MagicMock())
    assert out["needs_remount"] is True
    assert "重新挂载" in out["remount_hint"]
