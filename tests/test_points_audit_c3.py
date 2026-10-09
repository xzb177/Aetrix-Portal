"""C3 积分流水 hash 审计测试。

- 审计开启时 _add_points 写入 prev_hash/record_hash，且链条可逐条核验通过；
- 篡改某条记录后核验能定位到断裂点；
- 审计关闭时不写 hash（两列 NULL），行为与原来一致；
- 审计开启前的历史记录（NULL hash）跳过校验、计入 legacy。
"""

import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.api.economy import _add_points, verify_points_chain, _points_record_hash


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user(db, name="alice"):
    u = models.WebUser(username=name, password_hash="x")
    db.add(u)
    db.commit()
    return u


def _set_config(db, key, value):
    db.add(models.SystemConfig(key=key, value=value))
    db.commit()


def test_add_points_writes_hash_chain(db):
    """审计开启（默认）时，三笔流水形成可核验的链。"""
    u = _user(db)
    _add_points(db, u, 100, "checkin", "签到")
    _add_points(db, u, -30, "exchange", "兑换")
    _add_points(db, u, 50, "rebate", "返利")
    db.commit()

    logs = db.query(models.PointsLog).filter_by(user_id=u.id).order_by(models.PointsLog.id).all()
    assert len(logs) == 3
    assert all(l.record_hash and len(l.record_hash) == 64 for l in logs)
    assert logs[0].prev_hash == ""
    assert logs[1].prev_hash == logs[0].record_hash
    assert logs[2].prev_hash == logs[1].record_hash

    result = verify_points_chain(db, u.id)
    assert result["ok"] is True
    assert result["verified"] == 3
    assert result["legacy_skipped"] == 0
    assert result["broken_at"] is None


def test_verify_detects_tamper(db):
    """篡改中间一条的 amount 后，核验定位到该记录。"""
    u = _user(db)
    _add_points(db, u, 100, "checkin", "签到")
    _add_points(db, u, 200, "rebate", "返利")
    db.commit()

    victim = db.query(models.PointsLog).filter_by(user_id=u.id).order_by(models.PointsLog.id).all()[0]
    victim.amount = 99999  # 模拟篡改
    db.commit()

    result = verify_points_chain(db, u.id)
    assert result["ok"] is False
    assert result["broken_at"] == victim.id
    assert "篡改" in result["broken_reason"]


def test_verify_detects_broken_link(db):
    """删除中间一条后，后续记录的 prev_hash 对不上。"""
    u = _user(db)
    _add_points(db, u, 100, "checkin", "签到")
    _add_points(db, u, 200, "rebate", "返利")
    _add_points(db, u, 300, "invite", "邀请")
    db.commit()

    logs = db.query(models.PointsLog).filter_by(user_id=u.id).order_by(models.PointsLog.id).all()
    db.delete(logs[1])
    db.commit()

    result = verify_points_chain(db, u.id)
    assert result["ok"] is False
    assert result["broken_at"] == logs[2].id
    assert "断裂" in result["broken_reason"]


def test_audit_disabled_writes_no_hash(db):
    """审计关闭时不写 hash，余额逻辑不变。"""
    _set_config(db, "points_audit_enabled", "false")
    u = _user(db)
    balance = _add_points(db, u, 100, "checkin", "签到")
    db.commit()
    assert balance == 100

    log = db.query(models.PointsLog).filter_by(user_id=u.id).one()
    assert log.prev_hash is None
    assert log.record_hash is None


def test_legacy_records_skipped(db):
    """审计开启前的历史记录跳过校验，之后的新链从空起头。"""
    _set_config(db, "points_audit_enabled", "false")
    u = _user(db)
    _add_points(db, u, 100, "checkin", "签到")
    db.commit()

    db.query(models.SystemConfig).filter_by(key="points_audit_enabled").delete()
    db.commit()
    _add_points(db, u, 50, "rebate", "返利")
    db.commit()

    logs = db.query(models.PointsLog).filter_by(user_id=u.id).order_by(models.PointsLog.id).all()
    assert logs[0].record_hash is None
    assert logs[1].record_hash is not None
    assert logs[1].prev_hash == ""  # 历史缺口后链条重新起头

    result = verify_points_chain(db, u.id)
    assert result["ok"] is True
    assert result["verified"] == 1
    assert result["legacy_skipped"] == 1


def test_verify_windowed_with_anchor(db):
    """记录数超过 limit 时，只验最近的，锚点链接正确。"""
    u = _user(db)
    for i in range(5):
        _add_points(db, u, 10, "checkin", f"第{i}笔")
    db.commit()

    result = verify_points_chain(db, u.id, limit=3)
    assert result["ok"] is True
    assert result["total"] == 3
    assert result["verified"] == 3


def test_verify_windowed_detects_tamper_in_window(db):
    """窗口内的篡改能被发现（即使断裂点不在窗口头部）。"""
    u = _user(db)
    for i in range(5):
        _add_points(db, u, 10, "checkin", f"第{i}笔")
    db.commit()

    logs = db.query(models.PointsLog).filter_by(user_id=u.id).order_by(models.PointsLog.id).all()
    logs[3].amount = 777  # 篡改窗口内（最近3条中的）记录
    db.commit()

    result = verify_points_chain(db, u.id, limit=3)
    assert result["ok"] is False
    assert result["broken_at"] == logs[3].id


def test_record_hash_deterministic():
    """同一输入永远算出同一 hash。"""
    from datetime import datetime
    ts = datetime(2026, 10, 10, 12, 0, 0)
    h1 = _points_record_hash("abc", 1, 100, 100, "checkin", "签到", None, ts)
    h2 = _points_record_hash("abc", 1, 100, 100, "checkin", "签到", None, ts)
    assert h1 == h2 and len(h1) == 64
    h3 = _points_record_hash("abc", 1, 101, 101, "checkin", "签到", None, ts)
    assert h3 != h1
