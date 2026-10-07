"""流节点 join token 自助接入的回归测试。

钉住：token 生成（随机/过期时间）、核销（一次性/过期/不存在）、
作废、join 注册节点 + 返回 bundle、用过的 token 不能再 join。

用隔离的内存 SQLite，不碰生产库。
"""
import time

import pytest


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend import models
    from backend.integrations import store

    store.invalidate()
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        store.invalidate()


NODE = "https://stream.example.com"


def _create(db, **kw):
    from backend.emby_server import stream_nodes
    kw.setdefault("name", "n1")
    return stream_nodes.create_join_token(db, **kw)


# ---------- 生成 ----------

def test_create_token_fields(db):
    info = _create(db, node_url=NODE)
    assert info["token"] and len(info["token"]) >= 32
    assert info["expires_at"] > time.time()
    assert info["used"] is False
    assert info["node_url"] == NODE


def test_create_token_random(db):
    a = _create(db)["token"]
    b = _create(db)["token"]
    assert a != b


def test_create_token_rejects_private_url(db):
    from backend.emby_server import stream_nodes
    with pytest.raises(ValueError):
        _create(db, node_url="http://192.168.1.10:8001")


def test_create_token_allows_empty_url(db):
    # URL 可后补（join 时上报）
    info = _create(db)
    assert info["node_url"] == ""


# ---------- 核销 ----------

def test_consume_ok(db):
    from backend.emby_server import stream_nodes
    tok = _create(db, node_url=NODE)["token"]
    info = stream_nodes.consume_join_token(db, tok)
    assert info["node_url"] == NODE


def test_consume_reported_url(db):
    from backend.emby_server import stream_nodes
    tok = _create(db)["token"]  # 建时没填 URL
    info = stream_nodes.consume_join_token(db, tok, reported_url=NODE)
    assert info["node_url"] == NODE


def test_consume_missing_url_fails(db):
    from backend.emby_server import stream_nodes
    tok = _create(db)["token"]
    with pytest.raises(ValueError):
        stream_nodes.consume_join_token(db, tok)


def test_consume_twice_fails(db):
    from backend.emby_server import stream_nodes
    tok = _create(db, node_url=NODE)["token"]
    stream_nodes.consume_join_token(db, tok)
    with pytest.raises(ValueError, match="已使用"):
        stream_nodes.consume_join_token(db, tok)


def test_consume_unknown_fails(db):
    from backend.emby_server import stream_nodes
    with pytest.raises(ValueError):
        stream_nodes.consume_join_token(db, "no-such-token")


def test_consume_expired_fails(db):
    from backend.emby_server import stream_nodes
    tok = _create(db, node_url=NODE, ttl_seconds=60)["token"]
    # 把过期时间拨到过去
    tokens = stream_nodes._raw_tokens(db)
    tokens[tok]["expires_at"] = time.time() - 1
    stream_nodes._save_tokens(db, tokens)
    with pytest.raises(ValueError, match="过期"):
        stream_nodes.consume_join_token(db, tok)


# ---------- 列表 / 作废 ----------

def test_list_tokens_status(db):
    from backend.emby_server import stream_nodes
    t1 = _create(db, node_url=NODE)["token"]
    t2 = _create(db, node_url=NODE)["token"]
    stream_nodes.consume_join_token(db, t1)
    by_tok = {t["token"]: t["status"] for t in stream_nodes.list_join_tokens(db)}
    assert by_tok[t1] == "used"
    assert by_tok[t2] == "pending"


def test_revoke_pending(db):
    from backend.emby_server import stream_nodes
    tok = _create(db, node_url=NODE)["token"]
    assert stream_nodes.revoke_join_token(db, tok) is True
    with pytest.raises(ValueError):
        stream_nodes.consume_join_token(db, tok)


def test_revoke_used_fails(db):
    from backend.emby_server import stream_nodes
    tok = _create(db, node_url=NODE)["token"]
    stream_nodes.consume_join_token(db, tok)
    assert stream_nodes.revoke_join_token(db, tok) is False


# ---------- join 即注册 ----------

def test_join_registers_node(db):
    from backend.emby_server import stream_nodes
    tok = _create(db, name="n9", node_url=NODE, weight=50)["token"]
    info = stream_nodes.consume_join_token(db, tok)
    node = stream_nodes.register_node(db, info["node_url"], info["name"], info["weight"])
    assert node["url"] == NODE
    assert node["name"] == "n9"
    assert node["weight"] == 50
    urls = [n.get("url") for n in stream_nodes._raw_nodes(db)]
    assert NODE in urls
