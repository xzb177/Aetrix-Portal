"""三重门抽奖守卫体系测试。

身份门：参赛者必须在 TG 群里（sender.get_chat_member）
资格门：黑名单 / 新号限制 / 参与频率限流（lottery.check_eligibility）
公信门：drand 公开随机信标混入种子（lottery.fetch_drand_beacon / mix_seed_with_drand）
"""
import hashlib
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base  # noqa: F401
from backend import models
from backend import lottery


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    models.WebUser.__table__.create(engine, checkfirst=True)
    models.SystemConfig.__table__.create(engine, checkfirst=True)
    models.LotteryRound.__table__.create(engine, checkfirst=True)
    models.LotteryRoundPrize.__table__.create(engine, checkfirst=True)
    models.LotteryRoundEntry.__table__.create(engine, checkfirst=True)
    models.LotteryRoundWinner.__table__.create(engine, checkfirst=True)
    models.LotteryBlacklist.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_user(db, username, tg_id, created_at=None):
    user = models.WebUser(username=username, password_hash="", telegram_id=tg_id)
    if created_at is not None:
        user.created_at = created_at
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_round(db, title="三重门测试", chat_id=999):
    return lottery.create_round(
        db, title=title, chat_id=chat_id,
        prizes=[{"name": "积分奖", "type": "points", "value": 100, "quantity": 1}],
    )


def _set_config(db, key, value):
    cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if cfg:
        cfg.value = value
    else:
        db.add(models.SystemConfig(key=key, value=value))
    db.commit()


# ==================== 资格门 ====================

class TestEligibilityGate:
    def test_blacklisted_user_rejected(self, db):
        """黑名单用户无法参加。"""
        user = _make_user(db, "badguy", 111)
        rnd = _make_round(db)
        db.add(models.LotteryBlacklist(user_id=user.id, reason="薅奖"))
        db.commit()
        result = lottery.join_round(db, rnd, user, 111)
        assert result["ok"] is False
        assert result["reason"] == "blacklisted"

    def test_non_blacklisted_user_ok(self, db):
        """非黑名单用户正常参加。"""
        user = _make_user(db, "goodguy", 222)
        rnd = _make_round(db)
        result = lottery.join_round(db, rnd, user, 222)
        assert result["ok"] is True

    def test_too_new_user_rejected(self, db):
        """新号限制：注册不满 N 天拒绝。"""
        _set_config(db, "lottery_min_account_age_days", "7")
        user = _make_user(db, "newbie", 333, created_at=datetime.now() - timedelta(days=2))
        rnd = _make_round(db)
        result = lottery.join_round(db, rnd, user, 333)
        assert result["ok"] is False
        assert result["reason"] == "too_new"

    def test_old_enough_user_ok(self, db):
        """注册满 N 天正常参加。"""
        _set_config(db, "lottery_min_account_age_days", "7")
        user = _make_user(db, "oldman", 444, created_at=datetime.now() - timedelta(days=10))
        rnd = _make_round(db)
        result = lottery.join_round(db, rnd, user, 444)
        assert result["ok"] is True

    def test_rate_limited_user_rejected(self, db):
        """频率限流：24 小时内参加超限拒绝。"""
        _set_config(db, "lottery_max_joins_per_day", "1")
        user = _make_user(db, "frequent", 555)
        rnd1 = _make_round(db, title="第一轮")
        rnd2 = _make_round(db, title="第二轮")
        r1 = lottery.join_round(db, rnd1, user, 555)
        assert r1["ok"] is True
        r2 = lottery.join_round(db, rnd2, user, 555)
        assert r2["ok"] is False
        assert r2["reason"] == "rate_limited"

    def test_limits_disabled_by_default(self, db):
        """默认不限制（向后兼容）。"""
        # 不设置任何配置
        user = _make_user(db, "free", 666, created_at=datetime.now())
        rnd = _make_round(db)
        result = lottery.join_round(db, rnd, user, 666)
        assert result["ok"] is True

    def test_blacklist_crud(self, db):
        """黑名单增删查。"""
        user = _make_user(db, "temp", 777)
        assert lottery.is_blacklisted(db, user.id) is None
        db.add(models.LotteryBlacklist(user_id=user.id, reason="test"))
        db.commit()
        rec = lottery.is_blacklisted(db, user.id)
        assert rec is not None
        assert rec.reason == "test"


# ==================== 公信门 ====================

class TestTrustGate:
    def test_mix_seed_with_drand(self):
        """混合种子 = sha256(db_seed:drand_randomness)。"""
        mixed = lottery.mix_seed_with_drand("abc", "def")
        assert mixed == hashlib.sha256(b"abc:def").hexdigest()

    def test_mix_seed_no_drand_fallback(self):
        """drand 为空时返回原 seed（降级）。"""
        assert lottery.mix_seed_with_drand("abc", None) == "abc"
        assert lottery.mix_seed_with_drand("abc", "") == "abc"

    def test_draw_uses_drand_when_available(self, db):
        """开奖时抓取到信标则混入种子并落库。"""
        user = _make_user(db, "winner", 888)
        rnd = _make_round(db)
        lottery.join_round(db, rnd, user, 888)
        fake_beacon = {"round": 12345, "randomness": "aabbcc"}
        with patch.object(lottery, "fetch_drand_beacon", return_value=fake_beacon):
            lottery.draw_round(db, rnd.id)
        db.refresh(rnd)
        assert rnd.drand_round == 12345
        assert rnd.drand_randomness == "aabbcc"
        # 中奖者用混合种子算出
        winners = db.query(models.LotteryRoundWinner).filter(
            models.LotteryRoundWinner.round_id == rnd.id).all()
        assert len(winners) == 1

    def test_draw_fallback_when_drand_fails(self, db):
        """drand 抓取失败时降级为纯 seed 开奖。"""
        user = _make_user(db, "winner2", 999)
        rnd = _make_round(db)
        lottery.join_round(db, rnd, user, 999)
        with patch.object(lottery, "fetch_drand_beacon", return_value=None):
            lottery.draw_round(db, rnd.id)
        db.refresh(rnd)
        assert rnd.drand_round is None
        assert rnd.drand_randomness is None
        winners = db.query(models.LotteryRoundWinner).filter(
            models.LotteryRoundWinner.round_id == rnd.id).all()
        assert len(winners) == 1

    def test_verify_round_includes_drand(self, db):
        """核验报告包含 drand 信息。"""
        user = _make_user(db, "vuser", 1010)
        rnd = _make_round(db)
        lottery.join_round(db, rnd, user, 1010)
        fake_beacon = {"round": 99999, "randomness": "ddeeff"}
        with patch.object(lottery, "fetch_drand_beacon", return_value=fake_beacon):
            lottery.draw_round(db, rnd.id)
        report = lottery.verify_round(db, rnd.id)
        assert report["drand_round"] == 99999
        assert report["drand_randomness"] == "ddeeff"
        assert report["drand_verified"] is True


# ==================== 身份门 ====================

class TestIdentityGate:
    def test_get_chat_member_in_group(self, db):
        """在群里的成员返回 True。"""
        from backend.tg_bot import sender
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"ok": True, "result": {"status": "member"}}
        with patch("httpx.post", return_value=fake_resp):
            with patch("backend.integrations.telegram.token", return_value="fake-token"):
                is_member, status = sender.get_chat_member(db, -100123, 456)
        assert is_member is True
        assert status == "member"

    def test_get_chat_member_not_in_group(self, db):
        """不在群里返回 False。"""
        from backend.tg_bot import sender
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"ok": True, "result": {"status": "left"}}
        with patch("httpx.post", return_value=fake_resp):
            with patch("backend.integrations.telegram.token", return_value="fake-token"):
                is_member, status = sender.get_chat_member(db, -100123, 456)
        assert is_member is False
        assert status == "left"

    def test_get_chat_member_api_error_fail_open(self, db):
        """API 失败返回 None（调用方 fail-open）。"""
        from backend.tg_bot import sender
        with patch("httpx.post", side_effect=Exception("network down")):
            with patch("backend.integrations.telegram.token", return_value="fake-token"):
                is_member, status = sender.get_chat_member(db, -100123, 456)
        assert is_member is None
        assert status == "api_error"

    def test_get_chat_member_admin_counts_as_member(self, db):
        """管理员/创建者也算成员。"""
        from backend.tg_bot import sender
        for st in ("creator", "administrator", "restricted"):
            fake_resp = MagicMock()
            fake_resp.json.return_value = {"ok": True, "result": {"status": st}}
            with patch("httpx.post", return_value=fake_resp):
                with patch("backend.integrations.telegram.token", return_value="fake-token"):
                    is_member, _ = sender.get_chat_member(db, -100123, 456)
            assert is_member is True, f"status={st} 应该算成员"

    def test_require_group_member_default_on(self, db):
        """身份门默认开启。"""
        assert lottery.require_group_member(db) is True

    def test_require_group_member_can_disable(self, db):
        """身份门可关闭。"""
        _set_config(db, "lottery_require_group_member", "0")
        assert lottery.require_group_member(db) is False
