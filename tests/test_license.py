"""授权自动分发测试（v2.50.0）

覆盖 grant / revoke / expire 三个流程，GitHub API 全部 mock，
不发真实请求。
"""
import os
import tempfile
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
_fd, _p = tempfile.mkstemp(suffix=".db"); os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_p}"
from backend import database as _dbmod
from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker as _sm
_dbmod.engine = _ce(os.environ["DATABASE_URL"])
_dbmod.configure_session_local(_sm(bind=_dbmod.engine))

from datetime import datetime, timedelta
from unittest import mock

import pytest

from backend.database import SessionLocal, init_db
from backend.emby_server import license_github, license_worker
from backend.emby_server import models as em


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield
    # 清理授权表
    db = SessionLocal()
    db.query(em.License).delete()
    db.commit()
    db.close()


def _mock_token(*args, **kwargs):
    return "fake-token"


def test_grant_package_access_success():
    """grant 调对 GitHub API，失败抛异常"""
    with mock.patch.object(
        license_github, "_api_request", return_value={}
    ) as m:
        license_github.grant_package_access("someuser", "aetrix-web", "tok")
        assert m.called
        url = m.call_args[0][1]
        assert "someuser" in url
        assert "aetrix-web" in url
        assert m.call_args[0][0] == "PUT"


def test_grant_rejects_bad_username():
    """非法用户名直接拒绝，不调 API"""
    with mock.patch.object(license_github, "_api_request") as m:
        with pytest.raises(license_github.GitHubPackageError):
            license_github.grant_package_access("a/b", "aetrix-web", "tok")
        assert not m.called


def test_revoke_package_access_success():
    """revoke 用 DELETE 方法"""
    with mock.patch.object(
        license_github, "_api_request", return_value={}
    ) as m:
        license_github.revoke_package_access("someuser", "aetrix-web", "tok")
        assert m.call_args[0][0] == "DELETE"


def test_token_missing_gives_clear_error():
    """token 未配置时给清晰的错误提示"""
    db = SessionLocal()
    try:
        with mock.patch(
            "backend.integrations.store.get_value", return_value=""
        ):
            with pytest.raises(license_github.GitHubPackageError) as e:
                license_github.get_token_from_db(db)
            assert "github_package_token" in str(e.value)
    finally:
        db.close()


def test_api_401_gives_clear_error():
    """GitHub 返回 401 时提示 token 无效"""
    import urllib.error
    err = urllib.error.HTTPError(
        url="https://api.github.com/x", code=401, msg="Unauthorized",
        hdrs={}, fp=None,
    )
    with mock.patch(
        "urllib.request.urlopen", side_effect=err
    ):
        with pytest.raises(license_github.GitHubPackageError) as e:
            license_github._api_request(
                "PUT", "https://api.github.com/x", "bad-token"
            )
        assert "无效或已过期" in str(e.value)


def test_api_403_gives_clear_error():
    """GitHub 返回 403 时提示权限不足"""
    import urllib.error
    err = urllib.error.HTTPError(
        url="https://api.github.com/x", code=403, msg="Forbidden",
        hdrs={}, fp=None,
    )
    with mock.patch(
        "urllib.request.urlopen", side_effect=err
    ):
        with pytest.raises(license_github.GitHubPackageError) as e:
            license_github._api_request(
                "PUT", "https://api.github.com/x", "token"
            )
        assert "权限不足" in str(e.value)


def test_expire_reclaimer_revokes_and_marks():
    """过期回收：调 GitHub API + 状态变 expired"""
    db = SessionLocal()
    try:
        lic = em.License(
            github_username="expireduser",
            package_name="aetrix-web",
            granted_at=datetime.now() - timedelta(days=400),
            expires_at=datetime.now() - timedelta(days=1),
            status="active",
        )
        db.add(lic)
        db.commit()

        with mock.patch.object(
            license_github, "get_token_from_db", side_effect=_mock_token
        ), mock.patch.object(
            license_github, "revoke_package_access"
        ) as mock_revoke:
            n = license_worker._reclaim_expired_once()
            assert n == 1
            assert mock_revoke.called

        db.refresh(lic)
        assert lic.status == "expired"
    finally:
        db.close()


def test_expire_reclaimer_skips_not_expired():
    """没到期的不回收"""
    db = SessionLocal()
    try:
        lic = em.License(
            github_username="activeuser",
            package_name="aetrix-web",
            granted_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=100),
            status="active",
        )
        db.add(lic)
        db.commit()

        with mock.patch.object(
            license_github, "revoke_package_access"
        ) as mock_revoke:
            n = license_worker._reclaim_expired_once()
            assert n == 0
            assert not mock_revoke.called

        db.refresh(lic)
        assert lic.status == "active"
    finally:
        db.close()


def test_expire_reclaimer_single_failure_does_not_block_others():
    """单个回收失败不影响其它（下一轮重试）"""
    db = SessionLocal()
    try:
        for u in ("user1", "user2"):
            db.add(em.License(
                github_username=u,
                package_name="aetrix-web",
                granted_at=datetime.now() - timedelta(days=400),
                expires_at=datetime.now() - timedelta(days=1),
                status="active",
            ))
        db.commit()

        def _fail_once(username, package, token):
            if username == "user1":
                raise license_github.GitHubPackageError("模拟失败")

        with mock.patch.object(
            license_github, "get_token_from_db", side_effect=_mock_token
        ), mock.patch.object(
            license_github, "revoke_package_access", side_effect=_fail_once
        ):
            n = license_worker._reclaim_expired_once()
            assert n == 1  # user2 成功

        statuses = {
            r.github_username: r.status
            for r in db.query(em.License).all()
        }
        assert statuses["user1"] == "active"   # 下一轮再试
        assert statuses["user2"] == "expired"
    finally:
        db.close()
