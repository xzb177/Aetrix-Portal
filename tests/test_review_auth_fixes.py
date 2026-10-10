"""审查修复回归：P0 会话接口未鉴权、P1 首页排序未鉴权、P2 node_key 明文。"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend import models
from backend import servers as servers_mod
from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import api as emby_api

init_db()


def _guid():
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def seed():
    db = SessionLocal()
    for uname in ("review_alice", "review_bob"):
        old = db.query(models.WebUser).filter(models.WebUser.username == uname).first()
        if old:
            db.query(em.EmbyApiToken).filter(
                em.EmbyApiToken.user_id == old.id).delete(synchronize_session=False)
            db.query(em.PlaybackSession).filter(
                em.PlaybackSession.user_id == old.id).delete(synchronize_session=False)
            db.query(models.WebUser).filter(models.WebUser.id == old.id).delete()
    db.commit()
    alice = models.WebUser(username="review_alice", password_hash="x",
                           is_active=True, emby_username="review_alice",
                           emby_password="p")
    bob = models.WebUser(username="review_bob", password_hash="x",
                         is_active=True, emby_username="review_bob",
                         emby_password="p")
    db.add_all([alice, bob])
    db.flush()

    from backend.emby_server.auth import hash_emby_token
    tok_alice = "tok_" + _guid()
    tok_bob = "tok_" + _guid()
    db.add(em.EmbyApiToken(token=hash_emby_token(tok_alice), user_id=alice.id,
                           device_id="d1", app_name="t"))
    db.add(em.EmbyApiToken(token=hash_emby_token(tok_bob), user_id=bob.id,
                           device_id="d2", app_name="t"))
    sess = em.PlaybackSession(session_key="sess_" + _guid(), user_id=alice.id,
                              item_id=1, device_name="d1")
    db.add(sess)
    db.commit()
    yield {"alice": tok_alice, "bob": tok_bob, "sess_key": sess.session_key,
           "alice_id": alice.id, "bob_id": bob.id}
    db.query(em.EmbyApiToken).filter(
        em.EmbyApiToken.user_id.in_([alice.id, bob.id])).delete(synchronize_session=False)
    db.query(em.PlaybackSession).filter(
        em.PlaybackSession.user_id.in_([alice.id, bob.id])).delete(synchronize_session=False)
    db.query(models.WebUser).filter(
        models.WebUser.id.in_([alice.id, bob.id])).delete()
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def client():
    from backend.main import app
    return TestClient(app)


def test_get_sessions_requires_auth(client):
    r = client.get("/emby/Sessions")
    assert r.status_code == 401, f"未登录应 401，实际 {r.status_code}"


def test_get_sessions_scoped_to_self(client, seed):
    # bob 只能看到自己的会话（alice 的会话对 bob 不可见）
    r = client.get("/emby/Sessions", headers={"X-Emby-Token": seed["bob"]})
    assert r.status_code == 200
    keys = [s.get("Id") or s.get("SessionKey") for s in r.json()]
    assert seed["sess_key"] not in keys


def test_stop_session_requires_auth(client, seed):
    r = client.delete(f"/emby/Sessions/{seed['sess_key']}")
    assert r.status_code == 401, f"未登录应 401，实际 {r.status_code}"


def test_stop_session_forbidden_for_other_user(client, seed):
    # bob 不能停 alice 的会话
    r = client.delete(f"/emby/Sessions/{seed['sess_key']}",
                      headers={"X-Emby-Token": seed["bob"]})
    assert r.status_code == 403, f"跨用户应 403，实际 {r.status_code}"


def test_stop_session_own_ok(client, seed):
    r = client.delete(f"/emby/Sessions/{seed['sess_key']}",
                      headers={"X-Emby-Token": seed["alice"]})
    assert r.status_code == 200
    assert r.json().get("success") is True


def test_homepage_order_put_requires_admin():
    from backend.api.homepage_sections import router
    from fastapi.testclient import TestClient as TC
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    c = TC(app)
    r = c.put("/api/homepage/sections/order", json={"order": []})
    # 无鉴权头：应被 admin 鉴权拦下（401/403），绝不能 200
    assert r.status_code in (401, 403), f"匿名 PUT 应被拦，实际 {r.status_code}"


def test_serialize_masks_node_key():
    db = SessionLocal()
    try:
        srv = models.RemoteServer(name="review-srv", kind="ea",
                                  url="http://x", node_key="SECRET_NODE_KEY_123")  # secret-scan: allow —— 单元测试用的假密钥，非真实凭据
        out = servers_mod.serialize(db, srv)
        assert out["node_key"] != "SECRET_NODE_KEY_123", "node_key 明文泄露！"
        assert out["node_key_set"] is True
    finally:
        db.close()
