"""群抽奖 G1 核心服务（backend.lottery）隔离测试。"""
import hashlib
import sys

sys.path.insert(0, ".")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base  # noqa: F401 保持与其它测试相同的导入习惯
from backend import models
from backend import lottery


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    # 只建需要的表
    models.WebUser.__table__.create(engine, checkfirst=True)
    models.SystemConfig.__table__.create(engine, checkfirst=True)
    models.LotteryRound.__table__.create(engine, checkfirst=True)
    models.LotteryRoundPrize.__table__.create(engine, checkfirst=True)
    models.LotteryRoundEntry.__table__.create(engine, checkfirst=True)
    models.LotteryRoundWinner.__table__.create(engine, checkfirst=True)
    models.PointsLog.__table__.create(engine, checkfirst=True)
    models.WelfareGrantLog.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


DEFAULT_PRIZES = [
    {"name": "积分奖", "type": "points", "value": 100, "quantity": 1},
    {"name": "天数奖", "type": "days", "value": 30, "quantity": 1},
]


def _make_user(db, username, tg_id):
    user = models.WebUser(username=username, password_hash="", telegram_id=tg_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_round(db, title="测试抽奖", chat_id=999, prizes=None, max_participants=0):
    if prizes is None:
        prizes = [dict(p) for p in DEFAULT_PRIZES]
    return lottery.create_round(
        db, title=title, chat_id=chat_id, prizes=prizes,
        max_participants=max_participants,
    )


def _fix_seed(db, rnd, seed="fixed-seed-for-test"):
    rnd.seed = seed
    rnd.seed_hash = hashlib.sha256(seed.encode()).hexdigest()
    db.commit()
    return rnd


def test_create_round(db):
    rnd = _make_round(db, title="创建轮次")
    assert len(rnd.seed) == 64
    assert rnd.seed_hash == hashlib.sha256(rnd.seed.encode()).hexdigest()
    assert rnd.status == "open"

    rows = (
        db.query(models.LotteryRoundPrize)
        .filter_by(round_id=rnd.id)
        .order_by(models.LotteryRoundPrize.sort)
        .all()
    )
    assert [p.name for p in rows] == ["积分奖", "天数奖"]
    assert [p.sort for p in rows] == [0, 1]

    with pytest.raises(ValueError):
        lottery.create_round(db, title="空奖品", chat_id=1, prizes=[])
    with pytest.raises(ValueError):
        lottery.create_round(
            db, title="未知类型", chat_id=1,
            prizes=[{"name": "x", "type": "unknown", "value": 1, "quantity": 1}],
        )
    with pytest.raises(ValueError):
        lottery.create_round(db, title="   ", chat_id=1, prizes=[dict(DEFAULT_PRIZES[0])])


def test_is_enabled_and_group_ids(db):
    # 无配置时默认开启
    assert lottery.is_enabled(db) is True

    db.add(models.SystemConfig(key="lottery_enabled", value="0"))
    db.commit()
    assert lottery.is_enabled(db) is False

    cfg = db.query(models.SystemConfig).filter_by(key="lottery_enabled").first()
    cfg.value = "false"
    db.commit()
    assert lottery.is_enabled(db) is False

    cfg.value = "TRUE"
    db.commit()
    assert lottery.is_enabled(db) is True

    # 无配置 -> 空集合（不限制）
    assert lottery.allowed_group_ids(db) == set()

    db.add(models.SystemConfig(key="lottery_group_ids", value="100, abc ,200,,300"))
    db.commit()
    assert lottery.allowed_group_ids(db) == {100, 200, 300}


def test_get_round(db):
    assert lottery.get_round(db, 999999) is None
    rnd = _make_round(db)
    got = lottery.get_round(db, rnd.id)
    assert got is not None and got.id == rnd.id and got.title == "测试抽奖"


def test_join_success(db):
    rnd = _make_round(db)
    u1 = _make_user(db, "u1", 910001)
    u2 = _make_user(db, "u2", 910002)
    r1 = lottery.join_round(db, rnd, u1, 910001)
    r2 = lottery.join_round(db, rnd, u2, 910002)
    assert r1["ok"] is True and r1["entry"].user_id == u1.id
    assert r2["ok"] is True and r2["entry"].user_id == u2.id


def test_join_duplicate_rejected(db):
    rnd = _make_round(db)
    u1 = _make_user(db, "u1", 910001)
    assert lottery.join_round(db, rnd, u1, 910001)["ok"] is True
    r = lottery.join_round(db, rnd, u1, 910001)
    assert r == {"ok": False, "reason": "already"}
    # 失败后 session 仍可用
    assert db.query(models.LotteryRoundEntry).filter_by(round_id=rnd.id).count() == 1


def test_join_full_rejected(db):
    rnd = _make_round(db, max_participants=1)
    u1 = _make_user(db, "u1", 910001)
    u2 = _make_user(db, "u2", 910002)
    assert lottery.join_round(db, rnd, u1, 910001)["ok"] is True
    r = lottery.join_round(db, rnd, u2, 910002)
    assert r == {"ok": False, "reason": "full"}


def test_join_closed_round_rejected(db):
    rnd = _make_round(db)
    u1 = _make_user(db, "u1", 910001)
    lottery.draw_round(db, rnd.id)  # 开奖后 status=done
    db.refresh(rnd)
    r = lottery.join_round(db, rnd, u1, 910001)
    assert r == {"ok": False, "reason": "closed"}


def test_join_disabled_rejected(db):
    rnd = _make_round(db)
    u1 = _make_user(db, "u1", 910001)
    db.add(models.SystemConfig(key="lottery_enabled", value="0"))
    db.commit()
    r = lottery.join_round(db, rnd, u1, 910001)
    assert r == {"ok": False, "reason": "disabled"}


def test_get_active_round(db):
    rnd = _make_round(db, chat_id=123)
    assert lottery.get_active_round(db, 123).id == rnd.id
    assert lottery.get_active_round(db, 456) is None
    lottery.draw_round(db, rnd.id)
    assert lottery.get_active_round(db, 123) is None


def _join_five(db, rnd):
    users = [_make_user(db, f"u{i}", 910000 + i) for i in range(1, 6)]
    for u in users:
        res = lottery.join_round(db, rnd, u, u.telegram_id)
        assert res["ok"] is True
    return users


def test_draw_deterministic(db):
    prizes = [
        {"name": "一等奖", "type": "points", "value": 50, "quantity": 2},
        {"name": "二等奖", "type": "days", "value": 7, "quantity": 1},
    ]
    rnd = _make_round(db, prizes=prizes)
    _fix_seed(db, rnd)
    _join_five(db, rnd)

    winners = lottery.draw_round(db, rnd.id)
    assert len(winners) == 3
    entry_ids = [w.entry_id for w in winners]
    assert len(set(entry_ids)) == 3  # 一人至多中一次

    # 独立用纯函数复算，结果与落库一致
    all_entry_ids = [
        e.id for e in db.query(models.LotteryRoundEntry)
        .filter_by(round_id=rnd.id).order_by(models.LotteryRoundEntry.id).all()
    ]
    prize_rows = (
        db.query(models.LotteryRoundPrize).filter_by(round_id=rnd.id)
        .order_by(models.LotteryRoundPrize.sort).all()
    )
    expected = lottery.compute_winners(
        "fixed-seed-for-test", all_entry_ids,
        [{"id": p.id, "quantity": p.quantity} for p in prize_rows],
    )
    actual = {}
    for w in winners:
        actual.setdefault(w.prize_id, []).append(w.entry_id)
    for pid, eids in expected.items():
        assert sorted(actual[pid]) == sorted(eids)

    # 同一输入再算一次，结果完全相同（确定性）
    again = lottery.compute_winners(
        "fixed-seed-for-test", all_entry_ids,
        [{"id": p.id, "quantity": p.quantity} for p in prize_rows],
    )
    assert again == expected


def test_draw_idempotent(db):
    rnd = _make_round(db)
    _fix_seed(db, rnd)
    _join_five(db, rnd)
    first = lottery.draw_round(db, rnd.id)
    second = lottery.draw_round(db, rnd.id)
    assert len(first) == len(second) == 2
    assert {w.id for w in first} == {w.id for w in second}


def test_draw_empty_entries(db):
    rnd = _make_round(db)
    winners = lottery.draw_round(db, rnd.id)
    assert winners == []
    db.refresh(rnd)
    assert rnd.status == "done"
    assert rnd.drawn_at is not None


def _winner_user_ids_by_prize_type(db, rnd, prize_type):
    """返回 {prize_type: [user_id]}，顺带 prize 名映射。"""
    prize_rows = db.query(models.LotteryRoundPrize).filter_by(round_id=rnd.id).all()
    pid_to_type = {p.id: p.type for p in prize_rows}
    entry_to_user = {
        e.id: e.user_id
        for e in db.query(models.LotteryRoundEntry).filter_by(round_id=rnd.id).all()
    }
    winners = db.query(models.LotteryRoundWinner).filter_by(round_id=rnd.id).all()
    out = {}
    for w in winners:
        out.setdefault(pid_to_type[w.prize_id], []).append(entry_to_user[w.entry_id])
    return out


def test_distribute_points_and_days(db):
    from datetime import datetime, timedelta

    rnd = _make_round(db)
    _fix_seed(db, rnd)
    users = _join_five(db, rnd)
    # 预置已过期的公益资格，覆盖"续期从当前时间起算"路径
    # （注：grant_welfare 对从未开通的用户发放 days>0 时 expires_at 保持 None，
    #  与其 docstring"从未开通时从当前时间开始计算"不符，疑似现有原语 bug，已上报，
    #  G1 不动该文件，这里用过期资格避开该分支）
    for u in users:
        u.welfare_expires_at = datetime.now() - timedelta(days=1)
        u.is_welfare = True
    db.commit()
    lottery.draw_round(db, rnd.id)

    result = lottery.distribute_round(db, rnd.id)
    assert result["total"] == 2
    assert result["distributed"] == 2
    assert result["skipped"] == 0
    assert result["errors"] == []

    by_type = _winner_user_ids_by_prize_type(db, rnd, None)
    points_uid = by_type["points"][0]
    days_uid = by_type["days"][0]

    u_points = db.query(models.WebUser).filter_by(id=points_uid).first()
    assert u_points.points == 100
    log = (
        db.query(models.PointsLog)
        .filter_by(user_id=points_uid, type="lottery_win")
        .first()
    )
    assert log is not None and log.amount == 100
    assert log.ref_id == f"lottery:{rnd.id}"

    u_days = db.query(models.WebUser).filter_by(id=days_uid).first()
    assert u_days.is_welfare is True
    assert u_days.welfare_expires_at is not None

    winners = db.query(models.LotteryRoundWinner).filter_by(round_id=rnd.id).all()
    assert all(w.distributed is True and w.distributed_at is not None for w in winners)
    # 没中奖的人积分不动
    for u in users:
        if u.id not in (points_uid, days_uid):
            assert db.query(models.WebUser).filter_by(id=u.id).first().points == 0


def test_distribute_whitelist(db):
    rnd = _make_round(
        db, prizes=[{"name": "永久白名单", "type": "whitelist", "value": 0, "quantity": 1}]
    )
    _fix_seed(db, rnd)
    users = _join_five(db, rnd)
    lottery.draw_round(db, rnd.id)
    result = lottery.distribute_round(db, rnd.id)
    assert result["distributed"] == 1 and result["errors"] == []

    winner = db.query(models.LotteryRoundWinner).filter_by(round_id=rnd.id).first()
    entry = db.query(models.LotteryRoundEntry).filter_by(id=winner.entry_id).first()
    u = db.query(models.WebUser).filter_by(id=entry.user_id).first()
    assert u.is_welfare is True
    assert u.welfare_expires_at is None  # 永久


def test_distribute_idempotent(db):
    rnd = _make_round(db)
    _fix_seed(db, rnd)
    users = _join_five(db, rnd)
    lottery.draw_round(db, rnd.id)

    first = lottery.distribute_round(db, rnd.id)
    assert first["distributed"] == 2
    points_before = {
        u.id: db.query(models.WebUser).filter_by(id=u.id).first().points for u in users
    }

    second = lottery.distribute_round(db, rnd.id)
    assert second["distributed"] == 0
    assert second["skipped"] == first["total"] == 2
    assert second["errors"] == []
    for u in users:
        assert db.query(models.WebUser).filter_by(id=u.id).first().points == points_before[u.id]


def test_verify_round(db):
    rnd = _make_round(db, title="核验轮")
    _fix_seed(db, rnd)
    _join_five(db, rnd)
    lottery.draw_round(db, rnd.id)

    v = lottery.verify_round(db, rnd.id)
    assert v["round_id"] == rnd.id
    assert v["title"] == "核验轮"
    assert v["status"] == "done"
    assert v["seed"] == "fixed-seed-for-test"
    assert v["seed_hash"] == hashlib.sha256(b"fixed-seed-for-test").hexdigest()
    assert v["algorithm"] == "sha256(seed:entry_id)升序"

    assert len(v["entries"]) == 5
    for e in v["entries"]:
        assert set(e.keys()) == {"entry_id", "user_id", "telegram_id_masked"}
        # telegram_id 只留后 4 位
        assert e["telegram_id_masked"].startswith("****")
        assert len(e["telegram_id_masked"]) == 8

    assert len(v["winners"]) == 2
    for w in v["winners"]:
        assert set(w.keys()) == {"entry_id", "prize_name", "score"}
        assert w["score"] == hashlib.sha256(
            f"fixed-seed-for-test:{w['entry_id']}".encode()
        ).hexdigest()

    with pytest.raises(ValueError):
        lottery.verify_round(db, 999999)
