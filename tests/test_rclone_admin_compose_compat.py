"""rclone 集中管理面板与「拆分 Compose 部署」的兼容性回归。

这组测试锁住两个真实缺陷（都是先在生产容器里只读核实、再修的）：

1. **上传服务账号会静默失效**：旧代码写死 ``SA_DIR = "/sa-accounts"``，那是
   *rclone 容器视角*的挂载点。API 容器里没有这个目录，于是 ``makedirs`` 在
   容器可写层建出同名目录并写进去，接口返回 success——但 rclone 容器挂的是
   宿主 ``/root/sa-accounts``，那是**另一份文件**。面板显示成功、remote 用不了，
   容器一重建文件就没了。现在目录不存在/只读时直接报错，绝不新建。

2. **一键生成配置失败得毫无指向**：本地路径不可写时退回 ``docker exec``，
   而 API 容器里通常没有 docker CLI，异常被笼统吞成「写入异常」。现在
   FileNotFoundError 单独处理，给出该改哪里的提示。
"""
import os
import tempfile

import pytest
from fastapi import HTTPException

from backend.emby_server import rclone_admin


# ---------------- 服务账号目录 ----------------

def test_sa_dir_follows_env(monkeypatch):
    monkeypatch.setenv("RCLONE_SA_DIR", "/custom/sa")
    assert rclone_admin._sa_dir() == "/custom/sa"


def test_sa_dir_defaults_to_compose_mount(monkeypatch):
    """默认值必须落在 compose 实际挂载的路径上，而不是 rclone 容器视角的 /sa-accounts"""
    monkeypatch.delenv("RCLONE_SA_DIR", raising=False)
    assert rclone_admin._sa_dir() == "/root/sa-accounts"


def test_missing_sa_dir_fails_loudly(monkeypatch):
    """目录不存在时必须报错，且绝不能顺手建一个黑洞目录"""
    with tempfile.TemporaryDirectory() as tmp:
        absent = os.path.join(tmp, "sa-accounts")
        monkeypatch.setenv("RCLONE_SA_DIR", absent)
        with pytest.raises(HTTPException) as exc:
            rclone_admin.upload_service_account.__wrapped__ if False else _raise_upload(monkeypatch, absent)
        assert exc.value.status_code == 500
        assert "不存在" in str(exc.value.detail)
        assert not os.path.exists(absent), "不允许为了通过而在容器本地新建黑洞目录"


def test_readonly_sa_dir_fails_loudly(monkeypatch):
    """只读目录必须报错并指出 :ro，而不是把文件写进临时层"""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("RCLONE_SA_DIR", tmp)
        monkeypatch.setattr(os, "access", lambda path, mode: False)
        with pytest.raises(HTTPException) as exc:
            _raise_upload(monkeypatch, tmp)
        assert exc.value.status_code == 500
        assert "只读" in str(exc.value.detail)


def _raise_upload(monkeypatch, sa_dir):
    """构造一个只用到目录检查那几步的上传调用。

    端点签名带 UploadFile / DB 依赖，直接调会牵扯整条链；这里用足够真实的
    替身，让它走到「目录存在吗 / 可写吗」的判断就抛出。
    """
    import types

    remote = types.SimpleNamespace(id=1, name="mp_drive", sa_file_id=None)
    db = types.SimpleNamespace(
        query=lambda *a, **k: types.SimpleNamespace(
            filter=lambda *a, **k: types.SimpleNamespace(first=lambda: remote)
        )
    )
    upload = types.SimpleNamespace(file=types.SimpleNamespace(
        read=lambda: b'{"type": "service_account", "client_email": "a@b", "project_id": "p"}'
    ))
    return rclone_admin.upload_service_account(1, upload, remote, db)


# ---------------- 写配置失败提示 ----------------

def test_no_docker_cli_gives_actionable_message(monkeypatch):
    """没有可写目录、又没有 docker CLI 时，提示要指向 compose 挂载。

    必须**同时**把 ``docker`` 从 PATH 里摘掉并让 subprocess 抛 FileNotFoundError：
    只 monkeypatch ``shutil.which`` 是不够的——``_write_conf_to_target`` 是直接
    调 ``subprocess.run(["docker", ...])`` 的，PATH 里真有 docker 时（CI 机器上就有）
    它会真的去执行，连不上容器时报的是「No such container」，
    于是这条测试在本地过、到 CI 挂——它测的其实是 docker 守护进程的状态。
    """
    monkeypatch.setattr(rclone_admin.shutil, "which", lambda _n: None)
    monkeypatch.setattr(
        rclone_admin.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("docker")),
    )
    with tempfile.TemporaryDirectory() as tmp:
        conf = os.path.join(tmp, "no-such-dir", "rclone.conf")
        result = rclone_admin._write_conf_to_target("[x]\ntype = drive\n", conf)
    assert result["success"] is False
    assert "docker" in result["message"]
    assert "RCLONE_CONFIG_DIR" in result["message"], "提示要指明改哪个挂载"


def test_writable_local_path_wins_over_docker(monkeypatch):
    """本地目录可写时直接写盘，不去碰 docker"""
    calls = []
    monkeypatch.setattr(rclone_admin.subprocess, "run", lambda *a, **k: calls.append(a))
    with tempfile.TemporaryDirectory() as tmp:
        conf = os.path.join(tmp, "rclone.conf")
        result = rclone_admin._write_conf_to_target("[mp]\ntype = drive\n", conf)
        assert result["success"] is True
        assert "[mp]" in open(conf).read()
        assert oct(os.stat(conf).st_mode)[-3:] == "600"
    assert not calls, "本地可写时不该调用 docker"


def test_reload_without_docker_does_not_claim_success(monkeypatch):
    """没有 docker CLI 时，重启必须报失败——不能显示「已生效」而实际还是旧配置"""
    monkeypatch.setattr(rclone_admin.shutil, "which", lambda _n: None)
    # 同上：_reload_rclone 也走 subprocess.run，必须一并堵住
    monkeypatch.setattr(
        rclone_admin.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("docker")),
    )
    result = rclone_admin._reload_rclone()
    assert result["success"] is False
    assert "手动重启" in result["message"]
