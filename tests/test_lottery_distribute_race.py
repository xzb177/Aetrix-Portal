"""群抽奖发奖并发回归：两个开奖者（管理员手动 + 自动调度）同时 distribute 同一轮，
各自读到 distributed=False 时不能双倍发奖。"""
import hashlib
import sys

sys.path.insert(0, ".")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend import lottery


def test_concurrent_distribute_pays_once(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lot.db'}")
    for t in (models.WebUser, models.SystemConfig, models.LotteryRound, models.LotteryRoundPrize,
              models.LotteryRoundEntry, models.LotteryRoundWinner, models.LotteryBlacklist,
              models.PointsLog, models.WelfareGrantLog):
        t.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    a, b = Session(), Session()

    user = models.WebUser(username="w", password_hash="", telegram_id=1, points=0)
    a.add(user)
    a.commit()
    rnd = lottery.create_round(a, title="t", chat_id=1,
                               prizes=[{"name": "积分", "type": "points", "value": 100, "quantity": 1}])
    rnd.seed = "s"
    rnd.seed_hash = hashlib.sha256(b"s").hexdigest()
    a.commit()
    lottery.join_round(a, rnd, user, 1)
    lottery.draw_round(a, rnd.id)
    rid, uid = rnd.id, user.id

    # 开奖者 A 已读到中奖行（distributed=False）……
    stale = a.query(models.LotteryRoundWinner).filter_by(round_id=rid).all()
    assert stale and not stale[0].distributed
    # ……与此同时开奖者 B 完整发完并提交
    assert lottery.distribute_round(b, rid)["distributed"] == 1
    # A 继续用身份映射里的旧对象发奖：不能再发一次
    res = lottery.distribute_round(a, rid)
    assert res["distributed"] == 0

    b.expire_all()
    assert b.query(models.WebUser.points).filter_by(id=uid).scalar() == 100
    assert b.query(models.PointsLog).filter_by(user_id=uid, type="lottery_win").count() == 1
    a.close()
    b.close()
