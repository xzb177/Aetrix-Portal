import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import models
from backend.models import Base
from backend.api.economy import _get_quick_amounts

DEFAULT_AMOUNTS = [10, 30, 50, 100, 200]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()


def set_cfg(db, key, value):
    db.add(models.SystemConfig(key=key, value=value))
    db.commit()


def test_missing_key_returns_default(db):
    assert _get_quick_amounts(db) == DEFAULT_AMOUNTS


def test_custom_amounts(db):
    set_cfg(db, "recharge_quick_amounts", "5,20,100")
    assert _get_quick_amounts(db) == [5, 20, 100]


def test_unsorted_and_duplicates(db):
    set_cfg(db, "recharge_quick_amounts", "100,10,100,30")
    assert _get_quick_amounts(db) == [10, 30, 100]


def test_invalid_value_falls_back_to_default(db):
    set_cfg(db, "recharge_quick_amounts", "abc")
    assert _get_quick_amounts(db) == DEFAULT_AMOUNTS


def test_empty_string_falls_back_to_default(db):
    set_cfg(db, "recharge_quick_amounts", "")
    assert _get_quick_amounts(db) == DEFAULT_AMOUNTS


def test_more_than_eight_truncated(db):
    raw = ",".join(str(v) for v in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50])
    set_cfg(db, "recharge_quick_amounts", raw)
    result = _get_quick_amounts(db)
    assert len(result) == 8
    assert result == sorted(result)
    assert result == [5, 10, 15, 20, 25, 30, 35, 40]


def test_out_of_range_values_filtered(db):
    set_cfg(db, "recharge_quick_amounts", "0,10,-5,200000,30")
    assert _get_quick_amounts(db) == [10, 30]


def test_whitespace_is_stripped(db):
    set_cfg(db, "recharge_quick_amounts", " 10 , 20 ")
    assert _get_quick_amounts(db) == [10, 20]


def test_all_invalid_after_filter_falls_back_to_default(db):
    set_cfg(db, "recharge_quick_amounts", "0,-1,999999")
    assert _get_quick_amounts(db) == DEFAULT_AMOUNTS

