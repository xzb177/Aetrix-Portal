import os
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.tg_bot import chat_points as cp


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_user(db, username, telegram_id=None, points=0):
    u = models.WebUser(username=username, password_hash="x", points=points, telegram_id=telegram_id)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _set_config(db, key, value):
    cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if cfg: cfg.value = str(value)
    else: db.add(models.SystemConfig(key=key, value=str(value)))
    db.commit()


def _make_update(tg_id=12345, chat_id=-100999, message_id=1, text="hello world"):
    return {"message": {"message_id": message_id, "from": {"id": tg_id, "is_bot": False},
            "chat": {"id": chat_id, "type": "supergroup"}, "text": text, "date": 1700000000}}


def _enable(db, chat_id=-100999):
    _set_config(db, "chat_points_enabled", "true")
    _set_config(db, "chat_points_group_ids", str(chat_id))


def _set_window(db, seconds):
    # 兼容两种可能的配置键名，确保分钟窗口被关闭
    _set_config(db, "minute_window", seconds)
    _set_config(db, "chat_points_minute_window", seconds)


def _set_cap(db, cap):
    # 兼容两种可能的配置键名
    _set_config(db, "daily_cap", cap)
    _set_config(db, "chat_points_daily_cap", cap)


def test_is_enabled(db):
    """is_enabled 随配置开关切换"""
    assert not cp.is_enabled(db)
    _set_config(db, "chat_points_enabled", "true")
    assert cp.is_enabled(db)


def test_disabled_by_default(db):
    """默认关闭：handle_group_message 返回 0 且不写日志"""
    assert not cp.is_enabled(db)
    assert cp.handle_group_message(db, _make_update()) == 0
    assert db.query(models.ChatPointsLog).count() == 0


def test_happy_path(db):
    """开启+目标群+已绑定+有效发言：返回 1，积分与日志各 +1"""
    _enable(db)
    u = _make_user(db, "alice", telegram_id=12345)
    assert cp.handle_group_message(db, _make_update()) == 1
    db.refresh(u)
    assert u.points == 1
    assert db.query(models.ChatPointsLog).count() == 1
    assert db.query(models.PointsLog).filter(models.PointsLog.type == "chat").count() == 1


def test_unbound_user_ignored(db):
    """未绑定 telegram_id 的用户发言不计分"""
    _enable(db)
    _make_user(db, "bob", telegram_id=None)
    assert cp.handle_group_message(db, _make_update()) == 0
    assert db.query(models.ChatPointsLog).count() == 0


def test_non_target_group_ignored(db):
    """非目标群发言不计分"""
    _enable(db, chat_id=-100999)
    _make_user(db, "carol", telegram_id=12345)
    assert cp.handle_group_message(db, _make_update(chat_id=-100888)) == 0
    assert db.query(models.ChatPointsLog).count() == 0


def test_command_not_counted(db):
    """命令文本（以 / 开头）不计分"""
    _enable(db)
    _make_user(db, "dave", telegram_id=12345)
    assert cp.handle_group_message(db, _make_update(text="/start")) == 0


def test_bot_message_ignored(db):
    """机器人发送的消息不计分"""
    _enable(db)
    _make_user(db, "erin", telegram_id=12345)
    upd = _make_update()
    upd["message"]["from"]["is_bot"] = True
    assert cp.handle_group_message(db, upd) == 0


def test_forward_ignored(db):
    """转发消息不计分"""
    _enable(db)
    _make_user(db, "frank", telegram_id=12345)
    upd = _make_update()
    upd["message"]["forward_origin"] = {"type": "user", "user": {"id": 999}}
    assert cp.handle_group_message(db, upd) == 0


def test_too_short_ignored(db):
    """长度低于 min_len 的发言不计分"""
    _enable(db)
    _make_user(db, "grace", telegram_id=12345)
    assert cp.handle_group_message(db, _make_update(text="好")) == 0


def test_minute_window(db):
    """同一用户在分钟窗口内的第二条发言不计分"""
    _enable(db)
    _make_user(db, "henry", telegram_id=12345)
    assert cp.handle_group_message(db, _make_update(message_id=1)) == 1
    assert cp.handle_group_message(db, _make_update(message_id=2)) == 0


def test_daily_cap(db):
    """达到每日上限后不再计分：前 3 次返回 1，第 4 次返回 0"""
    _enable(db)
    _set_cap(db, 3)
    _set_window(db, 0)
    u = _make_user(db, "ivan", telegram_id=12345)
    results = [cp.handle_group_message(db, _make_update(message_id=i)) for i in range(1, 5)]
    assert results == [1, 1, 1, 0]
    db.refresh(u)
    assert u.points == 3


def test_idempotent(db):
    """同一 (telegram_id, chat_id, message_id) 只计分一次"""
    _enable(db)
    _set_window(db, 0)
    u = _make_user(db, "jack", telegram_id=12345)
    upd = _make_update(message_id=7)
    assert cp.handle_group_message(db, upd) == 1
    assert cp.handle_group_message(db, upd) == 0
    db.refresh(u)
    assert u.points == 1
    assert db.query(models.ChatPointsLog).count() == 1


def test_chatpoints_disabled(db):
    """未开启时 handle_chatpoints 返回包含“未开启”"""
    text = cp.handle_chatpoints(db, _make_update()['message']['from'], -100999, '')
    assert "未开启" in text


def test_chatpoints_unbound(db):
    """开启但未绑定时返回包含“绑定”提示"""
    _enable(db)
    text = cp.handle_chatpoints(db, _make_update()['message']['from'], -100999, '')
    assert "绑定" in text


def test_chatpoints_summary(db):
    """绑定用户制造 2 条计分：文本含今日与本月统计"""
    _enable(db)
    _set_window(db, 0)
    _make_user(db, "kate", telegram_id=12345)
    cp.handle_group_message(db, _make_update(message_id=1))
    cp.handle_group_message(db, _make_update(message_id=2))
    text = cp.handle_chatpoints(db, _make_update()['message']['from'], -100999, '')
    assert "今日已得：<b>2</b> / 20 分" in text
    assert "本月累计：<b>2</b> 分" in text


def test_get_today_summary(db):
    """get_today_summary 返回今日与本月计分统计"""
    _enable(db)
    _set_window(db, 0)
    u = _make_user(db, "leo", telegram_id=12345)
    cp.handle_group_message(db, _make_update(message_id=1))
    cp.handle_group_message(db, _make_update(message_id=2))
    s = cp.get_today_summary(db, u)
    if isinstance(s, dict):
        assert s.get("today") == 2
        assert s.get("month") == 2
    else:
        assert "2" in str(s)


def test_parse_group_ids(db):
    """parse_group_ids 跳过非法片段，仅保留合法整数"""
    _set_config(db, "chat_points_group_ids", "abc, -1001, , 42")
    assert cp.parse_group_ids(db) == {-1001, 42}
    _set_config(db, "chat_points_group_ids", "-1001,-1002")
    assert cp.parse_group_ids(db) == {-1001, -1002}
    _set_config(db, "chat_points_group_ids", "")
    assert cp.parse_group_ids(db) == set()


@pytest.mark.parametrize("case,expected", [
    ("normal", True),
    ("boundary", True),
    ("command", False),
    ("short", False),
    ("empty", False),
    ("no_text", False),
    ("bot", False),
    ("forward", False),
])
def test_is_valid_message_cases(case, expected):
    """is_valid_message 各条件覆盖"""
    msg = _make_update()["message"]
    if case == "boundary":
        msg["text"] = "你好"
    elif case == "command":
        msg["text"] = "/start"
    elif case == "short":
        msg["text"] = "好"
    elif case == "empty":
        msg["text"] = ""
    elif case == "no_text":
        msg.pop("text", None)
    elif case == "bot":
        msg["from"]["is_bot"] = True
    elif case == "forward":
        msg["forward_origin"] = {"type": "user", "user": {"id": 999}}
    assert cp.is_valid_message(msg, min_len=2) == expected
