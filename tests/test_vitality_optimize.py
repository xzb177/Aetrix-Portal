"""活力值优化：新配置项 / 每日获取上限 / 观影奖励 / 归档钳制 / 配置校验 / 原子增减。"""
import os
import sys

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend import vitality
from backend.integrations import store as _store


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    _store.invalidate(*list(vitality.VITALITY_DEFAULTS.keys()),
                      vitality.CONFIG_LAST_DEDUCT_DATE)
    yield s
    s.close()


def _mkuser(db, name, welfare=True, vitality_val=5):
    u = models.WebUser(username=name, password_hash="x",
                       is_welfare=welfare, vitality=vitality_val)
    db.add(u)
    db.commit()
    return u


def test_new_config_defaults(db):
    cfg = vitality.get_vitality_config(db)
    assert cfg["watch_reward"] == 1
    assert cfg["daily_gain_limit"] == 2
    assert cfg["archive_clamp"] == 3


def test_validate_config_ok(db):
    errors = vitality.validate_vitality_config({
        "vitality_max": "14", "vitality_daily_cost": "1",
        "vitality_limit_threshold": "3", "vitality_point_cost": "10",
        "vitality_watch_reward": "1", "vitality_daily_gain_limit": "2",
        "vitality_archive_clamp": "3",
    })
    assert errors == {}


def test_validate_config_rejects_bad_values(db):
    errors = vitality.validate_vitality_config({
        "vitality_max": "0", "vitality_daily_cost": "-1",
        "vitality_limit_threshold": "99", "vitality_point_cost": "0",
        "vitality_watch_reward": "-5", "vitality_daily_gain_limit": "-2",
        "vitality_archive_clamp": "999",
    })
    assert "vitality_max" in errors
    assert "vitality_daily_cost" in errors
    assert "vitality_limit_threshold" in errors  # 99 > max
    assert "vitality_point_cost" in errors
    assert "vitality_watch_reward" in errors
    assert "vitality_daily_gain_limit" in errors
    assert "vitality_archive_clamp" in errors  # 999 > max


def test_add_vitality_atomic_clamp(db):
    """单条 UPDATE 完成加减+钳制：上溢截断到 max，下溢截断到 0"""
    u = _mkuser(db, "u1", vitality_val=13)
    assert vitality._add_vitality(db, u.id, 5, "test") == 14  # 13+5 -> 14
    assert vitality._add_vitality(db, u.id, -20, "test") == 0  # 14-20 -> 0
    # 日志记录了钳制后的余额
    logs = db.query(models.VitalityLog).filter_by(user_id=u.id).order_by(models.VitalityLog.id).all()
    assert len(logs) == 2
    assert logs[0].balance_after == 14
    assert logs[1].balance_after == 0


def test_award_watch_reward_respects_daily_limit(db):
    """观影奖励受每日免费获取上限钳制"""
    u = _mkuser(db, "watcher", vitality_val=5)
    # 默认 watch_reward=1, daily_gain_limit=2
    assert vitality.award_watch_reward(db, u.id) == 1
    assert vitality.award_watch_reward(db, u.id) == 1  # 累计 2，达上限
    assert vitality.award_watch_reward(db, u.id) == 0  # 超上限，不再发放
    # vitality 从 5 -> 7（钳制在 max=14 内）
    db.refresh(u)
    assert u.vitality == 7


def test_award_watch_reward_disabled(db):
    db.add(models.SystemConfig(key="vitality_enabled", value="false"))
    db.commit()
    _store.invalidate("vitality_enabled")
    u = _mkuser(db, "watcher2", vitality_val=5)
    assert vitality.award_watch_reward(db, u.id) == 0


def test_award_watch_reward_non_welfare(db):
    u = _mkuser(db, "plain", welfare=False, vitality_val=5)
    assert vitality.award_watch_reward(db, u.id) == 0


def test_get_today_free_gain_counts_only_free_reasons(db):
    """只有 checkin/watch_reward 计入；recharge（付费）不计入"""
    u = _mkuser(db, "gainer", vitality_val=5)
    vitality._add_vitality(db, u.id, 1, "checkin")
    vitality._add_vitality(db, u.id, 1, "watch_reward")
    vitality._add_vitality(db, u.id, 5, "recharge")  # 付费，不计入
    db.commit()
    assert vitality.get_today_free_gain(db, u.id) == 2


def test_clamp_on_archive_only_decreases(db):
    """归档钳制只降不升"""
    rich = _mkuser(db, "rich", vitality_val=10)
    assert vitality.clamp_on_archive(db, rich.id) == 3  # 10 -> 3
    db.refresh(rich)
    assert rich.vitality == 3

    poor = _mkuser(db, "poor", vitality_val=2)
    assert vitality.clamp_on_archive(db, poor.id) == 2  # 2 < 3，不动
    db.refresh(poor)
    assert poor.vitality == 2


def test_daily_gain_limit_zero_means_unlimited(db):
    """daily_gain_limit=0 表示不限制"""
    db.add(models.SystemConfig(key="vitality_daily_gain_limit", value="0"))
    db.commit()
    _store.invalidate("vitality_daily_gain_limit")
    u = _mkuser(db, "unlimited", vitality_val=0)
    # 连续发放 5 次都不应被拦（max=14 钳制）
    total = sum(vitality.award_watch_reward(db, u.id) for _ in range(5))
    assert total == 5
