"""审查修复回归（第二批）：lottery seed 门控、签名头、转码缓存 LRU。"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-for-review")

import json
import tempfile
import time
from datetime import datetime, timedelta

from backend.database import SessionLocal, init_db
from backend import models

init_db()


def test_lottery_seed_gated_before_draw():
    """开奖前 verify_round 不得返回 seed 明文，只给 seed_hash。"""
    from backend import lottery
    db = SessionLocal()
    try:
        r = models.LotteryRound(title="review-seed-test", status="open", chat_id=-100123,
                                seed="SECRET_SEED_123", seed_hash="hash_abc")
        db.add(r)
        db.commit()
        out = lottery.verify_round(db, r.id)
        assert out["seed"] is None, "开奖前 seed 明文泄露！"
        assert out["seed_hash"] == "hash_abc"
    finally:
        db.query(models.LotteryRound).filter(
            models.LotteryRound.title == "review-seed-test").delete()
        db.commit()
        db.close()


def test_lottery_seed_visible_after_draw():
    """开奖后 seed 明文可公开（供外部复算验证）。"""
    from backend import lottery
    db = SessionLocal()
    try:
        r = models.LotteryRound(title="review-seed-test2", status="done", chat_id=-100124,
                                seed="SECRET_SEED_456", seed_hash="hash_def")
        db.add(r)
        db.commit()
        out = lottery.verify_round(db, r.id)
        assert out["seed"] == "SECRET_SEED_456"
    finally:
        db.query(models.LotteryRound).filter(
            models.LotteryRound.title == "review-seed-test2").delete()
        db.commit()
        db.close()


def test_verify_signed_headers_accepts_valid():
    """合法 HMAC 签名头通过。"""
    import secrets as pysecrets
    from backend import node_auth
    key = node_auth.node_shared_secret()
    assert key, "测试需要 SECRET_KEY"
    ts = str(int(time.time()))
    nonce = pysecrets.token_hex(16)
    sig = node_auth._sign(key, ts, nonce, "GET", "/api/admin/stream-nodes/bundle")
    headers = {"X-Panel-Ts": ts, "X-Panel-Nonce": nonce, "X-Panel-Sign": sig}
    assert node_auth.verify_signed_headers(
        headers, "GET", "/api/admin/stream-nodes/bundle") is True


def test_verify_signed_headers_rejects_static_key():
    """静态 X-Panel-Key 必须被拒绝（bundle 不再接受）。"""
    from backend import node_auth
    key = node_auth.node_shared_secret()
    assert node_auth.verify_signed_headers(
        {"X-Panel-Key": key}, "GET", "/api/admin/stream-nodes/bundle") is False


def test_verify_signed_headers_rejects_stale_ts():
    """过期时间戳被拒绝。"""
    import secrets as pysecrets
    from backend import node_auth
    key = node_auth.node_shared_secret()
    ts = str(int(time.time()) - 3600)  # 1 小时前
    nonce = pysecrets.token_hex(16)
    sig = node_auth._sign(key, ts, nonce, "GET", "/api/admin/stream-nodes/bundle")
    headers = {"X-Panel-Ts": ts, "X-Panel-Nonce": nonce, "X-Panel-Sign": sig}
    assert node_auth.verify_signed_headers(
        headers, "GET", "/api/admin/stream-nodes/bundle") is False


def test_transcode_cache_lru_evicts_oldest():
    """转码缓存超限时淘汰最旧目录，保留刚落盘的。"""
    from backend.emby_server import transcode as t
    base = tempfile.mkdtemp()
    orig = t.cache_dir
    t.cache_dir = lambda: base
    os.environ["EMBY_TRANSCODE_CACHE_MAX_GB"] = "0.00001"  # ~10KB，强制触发
    try:
        for name, age in (("old_a", 300), ("old_b", 200), ("new_c", 100)):
            d = os.path.join(base, name)
            os.makedirs(d)
            with open(os.path.join(d, "data.bin"), "wb") as f:
                f.write(b"x" * 5000)
            with open(os.path.join(d, "cache.json"), "w") as f:
                json.dump({"completed_at": (
                    datetime.now() - timedelta(seconds=age)).isoformat()}, f)
        t._enforce_cache_capacity(os.path.join(base, "new_c"))
        remain = os.listdir(base)
        assert "new_c" in remain, "刚落盘的目录不应被删"
        assert len(remain) < 3, "超限时应淘汰最旧的目录"
    finally:
        t.cache_dir = orig
        os.environ.pop("EMBY_TRANSCODE_CACHE_MAX_GB", None)
        import shutil
        shutil.rmtree(base, ignore_errors=True)
