"""红包过期退款调度 + 抢红包并发锁测试

全部用隔离的临时 SQLite，不碰生产库。
"""
import os
import threading

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from backend import models
from backend import welfare_redpacket as rp


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_user(db, username, points=10000, is_staff=False):
    u = models.WebUser(
        username=username, password_hash="x", points=points, is_staff=is_staff)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _set_config(db, key, value):
    cfg = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == key).first()
    if cfg:
        cfg.value = str(value)
    else:
        db.add(models.SystemConfig(key=key, value=str(value)))
    db.commit()


def _expire(packet_id, db):
    """把红包设为已过期"""
    from datetime import datetime, timedelta
    p = db.query(models.RedPacket).filter(
        models.RedPacket.id == packet_id).first()
    p.expires_at = datetime.now() - timedelta(hours=1)
    db.commit()


# ---------- 过期退款 ----------

def test_refund_expired_refunds_and_zeroes(db):
    """过期红包：剩余退回发送者，remaining 清零"""
    sender = _make_user(db, "sender_refund1")
    packet = rp.send_packet(db, sender, 100, 2)
    _expire(packet.id, db)
    db.refresh(sender)
    before = int(sender.points or 0)  # 10000 - 105（100 本金 + 5 手续费）

    n = rp.refund_expired(db)
    assert n == 1

    db.refresh(sender)
    assert int(sender.points) == before + 100
    p = db.query(models.RedPacket).filter(
        models.RedPacket.id == packet.id).first()
    assert p.remaining_amount == 0
    assert p.remaining_count == 0


def test_refund_expired_idempotent(db):
    """退款幂等：第二次调用返回 0，余额不再变化"""
    sender = _make_user(db, "sender_refund2")
    packet = rp.send_packet(db, sender, 100, 2)
    _expire(packet.id, db)
    assert rp.refund_expired(db) == 1
    db.refresh(sender)
    after_first = int(sender.points)
    assert rp.refund_expired(db) == 0
    db.refresh(sender)
    assert int(sender.points) == after_first


def test_refund_expired_skips_active_and_empty(db):
    """未过期 / 已抢完的包不退款"""
    sender = _make_user(db, "sender_refund3")
    active = rp.send_packet(db, sender, 100, 2)  # 未过期
    full = rp.send_packet(db, sender, 50, 1)
    u = _make_user(db, "claimer_refund3")
    rp.claim_packet(db, u, full.id)  # 抢完
    _expire(full.id, db)
    db.refresh(sender)
    before = int(sender.points)

    assert rp.refund_expired(db) == 0
    db.refresh(sender)
    assert int(sender.points) == before
    p = db.query(models.RedPacket).filter(
        models.RedPacket.id == active.id).first()
    assert p.remaining_amount == 100


def test_refund_scheduler_start_guard():
    """调度器单启动守卫：第一次 True，第二次 False"""
    assert rp.start_redpacket_refund_scheduler() is True
    assert rp.start_redpacket_refund_scheduler() is False


# ---------- 并发锁 ----------

def _file_db(path):
    """多线程并发测试用文件库（内存库无法跨连接共享）"""
    if os.path.exists(path):
        os.remove(path)
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    return engine


def _claim_with_retry(Session, user_id, packet_id, barrier, results, idx,
                      max_retries=40):
    """线程入口：带重试的抢红包（SQLite 写锁冲突时重试）"""
    barrier.wait()
    for _ in range(max_retries):
        s = Session()
        try:
            user = s.query(models.WebUser).filter(
                models.WebUser.id == user_id).first()
            out = rp.claim_packet(s, user, packet_id)
            results[idx] = ("ok", out["amount"])
            return
        except OperationalError:
            s.rollback()
        except ValueError as e:
            results[idx] = ("value_error", str(e))
            return
        finally:
            s.close()
        import time
        time.sleep(0.05)
    results[idx] = ("gave_up", "")


def test_claim_dup_race_single_winner():
    """并发重复领取：同一用户两线程同时抢，恰好一个成功"""
    path = "/tmp/test_rp_dup.db"
    engine = _file_db(path)
    Session = sessionmaker(bind=engine)
    s = Session()
    sender = _make_user(s, "sender_dup")
    user = _make_user(s, "racer_dup")
    packet = rp.send_packet(s, sender, 100, 5)
    packet_id, user_id = packet.id, user.id
    s.close()

    barrier = threading.Barrier(2)
    results = [None, None]
    threads = [
        threading.Thread(target=_claim_with_retry,
                         args=(Session, user_id, packet_id, barrier, results, i))
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = [r for r in results if r and r[0] == "ok"]
    dup = [r for r in results if r and r[0] == "value_error"
           and "已经领过" in r[1]]
    assert len(ok) == 1, f"必须恰好一个成功: {results}"
    assert len(dup) == 1, f"另一个必须报重复领取: {results}"

    s = Session()
    try:
        cnt = s.query(models.RedPacketClaim).filter(
            models.RedPacketClaim.packet_id == packet_id,
            models.RedPacketClaim.user_id == user_id).count()
        assert cnt == 1
    finally:
        s.close()
        engine.dispose()
        os.remove(path)


def test_claim_exact_accounting_sequential(db):
    """顺序领取：5 人分 100，金额总和恒等于 100"""
    sender = _make_user(db, "sender_seq")
    packet = rp.send_packet(db, sender, 100, 5)
    total = 0
    for i in range(5):
        u = _make_user(db, f"seq_user_{i}")
        out = rp.claim_packet(db, u, packet.id)
        total += out["amount"]
    assert total == 100
    p = db.query(models.RedPacket).filter(
        models.RedPacket.id == packet.id).first()
    assert p.remaining_amount == 0
    assert p.remaining_count == 0


@pytest.mark.skipif(
    os.environ.get("DATABASE_TYPE") != "postgresql"
    or not os.environ.get("DATABASE_URL"),
    reason="needs postgres (DATABASE_TYPE=postgresql + DATABASE_URL)",
)
def test_claim_no_overissue_pg():
    """PG 真并发：20 线程抢 10 个名额，精确记账不超发

    需要 DATABASE_URL 指向隔离的临时 PG（行锁 FOR UPDATE 在 PG 生效，
    SQLite 下是 no-op 故跳过）。
    """
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    sender = _make_user(s, "sender_pg")
    users = [_make_user(s, f"pg_user_{i}") for i in range(20)]
    user_ids = [u.id for u in users]
    packet = rp.send_packet(s, sender, 100, 10)
    packet_id = packet.id
    s.close()

    n = 20
    barrier = threading.Barrier(n)
    results = [None] * n
    threads = [
        threading.Thread(target=_claim_with_retry,
                         args=(Session, user_ids[i], packet_id, barrier, results, i))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = [r for r in results if r and r[0] == "ok"]
    assert len(ok) == 10, f"必须恰好 10 人抢到: {results}"
    assert sum(r[1] for r in ok) == 100, "金额总和必须等于红包总额"
    s = Session()
    try:
        p = s.query(models.RedPacket).filter(
            models.RedPacket.id == packet_id).first()
        assert p.remaining_amount == 0
        assert p.remaining_count == 0
    finally:
        s.close()
        engine.dispose()
