"""活力值每日扣减：分页不漏扣 + 多进程同日只扣一次。"""
import os
import sys

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models, vitality
from backend.integrations import store as _store


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    # 配置有进程内 TTL 热缓存：别的测试关掉过的开关不能串进来
    _store.invalidate("vitality_enabled", "vitality_daily_cost", "vitality_max",
                      vitality.CONFIG_LAST_DEDUCT_DATE)
    yield s
    s.close()


def test_daily_deduct_pagination_does_not_skip(db):
    """本批扣到 0 的用户会离开 vitality>0 结果集，offset 分页会跳过后面的用户（批大小 500）"""
    n = 1200
    db.bulk_save_objects([
        models.WebUser(username=f"u{i}", password_hash="x", is_welfare=True, vitality=1)
        for i in range(n)
    ])
    db.add(models.SystemConfig(key="vitality_daily_cost", value="1"))
    db.commit()
    res = vitality.daily_deduct(db)
    assert res["deducted"] == n
    assert db.query(models.WebUser).filter(models.WebUser.vitality > 0).count() == 0


def test_claim_daily_deduct_once_per_day(db):
    assert vitality.claim_daily_deduct(db, "2026-10-10") is True
    assert vitality.claim_daily_deduct(db, "2026-10-10") is False
    assert vitality.claim_daily_deduct(db, "2026-10-11") is True
    assert vitality.claim_daily_deduct(db, "2026-10-11") is False
