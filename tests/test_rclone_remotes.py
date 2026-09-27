"""rclone remote 管理的单元测试。

全部用内存 SQLite + mock，不碰真实 rclone、不碰真实 Google API、
不写任何真实密码或 token。
"""
import json
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.emby_server import models as em
from backend.emby_server import rclone_manager


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_remote(db, name="test_drive", **kw):
    defaults = dict(
        name=name,
        remote_type="drive",
        client_id="",
        client_secret="",
        token_json="",
        scope="drive",
        sa_file_id=None,
        team_drive="",
        chunk_size="64M",
        is_enabled=True,
        is_probe_remote=False,
        remark="",
    )
    defaults.update(kw)
    r = em.RcloneRemote(**defaults)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ---------------- generate_rclone_conf ----------------

def test_conf_personal_drive_oauth(db):
    _make_remote(
        db, name="my_drive",
        client_id="cid123", client_secret="sec456",
        token_json='{"access_token":"at","refresh_token":"rt","expiry":"2026-01-01"}',
    )
    conf = rclone_manager.generate_rclone_conf(db)
    assert "[my_drive]" in conf
    assert "type = drive" in conf
    assert "client_id = cid123" in conf
    assert "client_secret = sec456" in conf
    assert "token = " in conf
    assert "team_drive" not in conf


def test_conf_service_account_team_drive(db):
    sa = em.ServiceAccountFile(
        filename="my_sa.json",
        stored_path="/sa-accounts/my_sa.json",
        client_email="sa@test.iam.gserviceaccount.com",
    )
    db.add(sa)
    db.commit()
    db.refresh(sa)
    _make_remote(db, name="team_drive", sa_file_id=sa.id, team_drive="0ABC123")
    conf = rclone_manager.generate_rclone_conf(db)
    assert "[team_drive]" in conf
    assert "service_account_file = /sa-accounts/my_sa.json" in conf
    assert "team_drive = 0ABC123" in conf
    # 服务账号模式不应该有 client_id
    assert "client_id" not in conf


def test_conf_disabled_excluded(db):
    _make_remote(db, name="enabled_one")
    _make_remote(db, name="disabled_one", is_enabled=False)
    conf = rclone_manager.generate_rclone_conf(db)
    assert "[enabled_one]" in conf
    assert "[disabled_one]" not in conf
    assert "disabled_one" not in conf


def test_conf_empty_when_no_enabled(db):
    _make_remote(db, name="off", is_enabled=False)
    conf = rclone_manager.generate_rclone_conf(db)
    assert conf.strip() == ""


def test_conf_multiple_remotes_sorted(db):
    _make_remote(db, name="zebra")
    _make_remote(db, name="alpha")
    conf = rclone_manager.generate_rclone_conf(db)
    assert conf.index("[alpha]") < conf.index("[zebra]")


# ---------------- probe remote ----------------

def test_get_probe_remote_none(db):
    _make_remote(db, name="a")
    assert rclone_manager.get_probe_remote(db) is None


def test_set_and_get_probe_remote(db):
    r1 = _make_remote(db, name="r1")
    r2 = _make_remote(db, name="r2")
    assert rclone_manager.set_probe_remote(db, r1.id) is True
    assert rclone_manager.get_probe_remote(db) == "r1"
    # 切换到 r2，r1 自动取消
    assert rclone_manager.set_probe_remote(db, r2.id) is True
    assert rclone_manager.get_probe_remote(db) == "r2"
    db.refresh(r1)
    assert r1.is_probe_remote is False


def test_set_probe_remote_not_found(db):
    assert rclone_manager.set_probe_remote(db, 99999) is False


def test_get_probe_remote_ignores_disabled(db):
    r = _make_remote(db, name="prober", is_probe_remote=True, is_enabled=False)
    assert rclone_manager.get_probe_remote(db) is None


# ---------------- write_rclone_conf 备份 ----------------

def test_write_conf_creates_backup(db):
    _make_remote(db, name="backup_test", client_id="x")
    with tempfile.TemporaryDirectory() as tmpdir:
        conf_path = os.path.join(tmpdir, "rclone.conf")
        # 先写一个旧文件
        with open(conf_path, "w") as f:
            f.write("[old]\ntype = drive\n")
        result_path = rclone_manager.write_rclone_conf(db, conf_path)
        assert result_path == conf_path
        # 备份存在
        assert os.path.exists(conf_path + ".bak")
        with open(conf_path + ".bak") as f:
            assert "[old]" in f.read()
        # 新内容写入
        with open(conf_path) as f:
            assert "[backup_test]" in f.read()
        # 权限 600
        assert oct(os.stat(conf_path).st_mode)[-3:] == "600"


def test_write_conf_no_existing_no_backup(db):
    _make_remote(db, name="fresh")
    with tempfile.TemporaryDirectory() as tmpdir:
        conf_path = os.path.join(tmpdir, "sub", "rclone.conf")
        rclone_manager.write_rclone_conf(db, conf_path)
        assert os.path.exists(conf_path)
        assert not os.path.exists(conf_path + ".bak")
