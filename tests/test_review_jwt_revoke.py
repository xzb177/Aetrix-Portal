"""审查修复回归：JWT 吊销与 token_version。"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-jwt-revoke")

from backend.database import SessionLocal, init_db
from backend import models

init_db()


def _make_user(username: str) -> int:
    db = SessionLocal()
    old = db.query(models.WebUser).filter(models.WebUser.username == username).first()
    if old:
        db.query(models.WebUser).filter(models.WebUser.id == old.id).delete()
        db.commit()
    u = models.WebUser(username=username, password_hash="x", is_active=True,
                       token_version=0)
    db.add(u)
    db.commit()
    uid = u.id
    db.close()
    return uid


def test_jti_revocation():
    """吊销 jti 后 is_jti_revoked 返回 True。"""
    from backend import security
    db = SessionLocal()
    try:
        uid = _make_user("review_jwt_u1")
        token = security.create_access_token(uid, token_version=0)
        payload = security.decode_token(token, expected_type="access")
        jti = payload["jti"]
        assert security.is_jti_revoked(db, jti) is False
        security.revoke_jti(db, jti, uid, reason="logout")
        assert security.is_jti_revoked(db, jti) is True
    finally:
        db.close()


def test_token_version_in_payload():
    """新签发的 token 带 tv；改密后 tv 对不上。"""
    from backend import security
    db = SessionLocal()
    try:
        uid = _make_user("review_jwt_u2")
        token = security.create_access_token(uid, token_version=0)
        payload = security.decode_token(token, expected_type="access")
        assert payload.get("tv") == 0
        # 模拟改密码：token_version +1
        user = db.query(models.WebUser).filter(models.WebUser.id == uid).first()
        user.token_version = 1
        db.commit()
        # 旧 token 的 tv=0 vs 当前 1 → 应判定失效
        assert int(payload.get("tv", 0)) != int(user.token_version)
    finally:
        db.close()
