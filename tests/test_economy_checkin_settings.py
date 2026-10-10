"""签到随机基础分/惩罚配置：economy._checkin_rules 读取的键必须能在后台保存，且有校验。"""
import os
import sys

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.api import admin_economy, economy


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    admin = models.WebUser(username="admin", password_hash="x", is_staff=True)
    s.add(admin)
    s.commit()
    yield s, admin
    s.close()


def _save(db, admin, settings):
    return admin_economy.economy_update_settings(
        admin_economy.EconomySettingsRequest(settings=settings), current_admin=admin, db=db)


def test_checkin_random_and_penalty_keys_saveable(db):
    s, admin = db
    res = _save(s, admin, {"checkin_base_min": "3", "checkin_base_max": "8",
                           "checkin_penalty_pct": "10", "checkin_penalty_min": "1",
                           "checkin_penalty_max": "4"})
    assert set(res["changed"]) >= {"checkin_base_min", "checkin_base_max", "checkin_penalty_pct",
                                   "checkin_penalty_min", "checkin_penalty_max"}
    rules = economy._checkin_rules(s)
    assert (rules["base_min"], rules["base_max"]) == (3, 8)
    assert (rules["penalty_pct"], rules["penalty_min"], rules["penalty_max"]) == (10, 1, 4)
    got = admin_economy.economy_get_settings(current_admin=admin, db=s)["settings"]
    assert got["checkin_base_min"] == "3" and got["checkin_penalty_pct"] == "10"


@pytest.mark.parametrize("bad", [
    {"checkin_penalty_pct": "150"},
    {"checkin_base_min": "-1"},
    {"checkin_base_max": "abc"},
    {"checkin_base_min": "9", "checkin_base_max": "2"},
    {"checkin_penalty_min": "5", "checkin_penalty_max": "1"},
])
def test_checkin_settings_validation(db, bad):
    s, admin = db
    with pytest.raises(HTTPException) as ei:
        _save(s, admin, bad)
    assert ei.value.status_code == 400
    assert s.query(models.SystemConfig).filter(models.SystemConfig.key.in_(list(bad))).count() == 0


def test_checkin_min_vs_existing_max(db):
    """只改下限时，对比库里已存的上限"""
    s, admin = db
    _save(s, admin, {"checkin_base_max": "5"})
    with pytest.raises(HTTPException):
        _save(s, admin, {"checkin_base_min": "6"})


def test_checkin_empty_means_unset(db):
    s, admin = db
    _save(s, admin, {"checkin_base_min": "", "checkin_base_max": ""})
    rules = economy._checkin_rules(s)
    assert rules["base_min"] == rules["base_max"] == rules["base_points"]
