"""防共享两件套（backend/share_guard.py）单元测试

三组约束，每一条都对应一个「错了会误伤正常用户」的事故：

1. **默认关闭**：``off`` 档下不判定、不写库、不通知——升级上来的老部署
   行为必须与升级前**逐字一致**（这是防共享这类功能最容易踩的坑）。
2. **不误判**：没配地理能力 / 城市查不到时，绝不把「未知」当成「换了城市」；
   管理员自己（排障时会故意从多地登录）不受判定；同一城市在窗口内反复上报
   只写一行（客户端每 10 秒一次心跳，不节流表会写满）。
3. **enforce 只由管理员显式开启**才处置（停用账号 / 拦下多余会话）。

外加同播检测的边界：上限 N = 允许 N 路，第 N+1 路才算；「停止」上报
（``ended=True``）不参与判定。

全部用隔离的内存 SQLite，不碰网络（geoip 用 monkeypatch 假掉）、不碰生产库。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models, share_guard
from backend.emby_server import models as em
from backend.integrations import store


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # 配置热缓存与告警节流都是进程级的（key 不带库名）：进出都清一次，
    # 否则内存库里各自从 1 开始的 user_id 会互相吃掉节流窗口
    store.invalidate()
    share_guard._notified_at.clear()
    yield session
    store.invalidate()
    share_guard._notified_at.clear()
    session.close()


@pytest.fixture(autouse=True)
def _fake_geo(monkeypatch):
    """城市固定可控：默认可控成「查不到」，需要真实实现的测试自己装回去"""
    def fake_city_of(db, ip):
        return fake_city_of.value(ip)

    fake_city_of.value = lambda ip: ""
    monkeypatch.setattr(share_guard, "city_of", fake_city_of)
    return fake_city_of


#: 真实实现（下面测 city_of 本身的用例会装回去）
_REAL_CITY_OF = share_guard.city_of


def _user(db, username="alice", **kw):
    row = models.WebUser(username=username, password_hash="x", **kw)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _policy(db, **overrides):
    values = {
        share_guard.CONFIG_TRAVEL_ACTION: "off",
        share_guard.CONFIG_TRAVEL_WINDOW: "30",
        share_guard.CONFIG_CONCURRENT_ACTION: "off",
        share_guard.CONFIG_CONCURRENT_LIMIT: "2",
    }
    values.update(overrides)
    share_guard.write_policy(db, values)
    db.commit()
    return values


def _events(db, user_id=None, kind=None):
    query = db.query(models.ShareGuardEvent)
    if user_id is not None:
        query = query.filter(models.ShareGuardEvent.user_id == user_id)
    if kind is not None:
        query = query.filter(models.ShareGuardEvent.kind == kind)
    return query.order_by(models.ShareGuardEvent.id.asc()).all()


def _live_session(db, user_id, key, client="Infuse", ip="1.1.1.1"):
    row = em.PlaybackSession(
        session_key=key, user_id=user_id, item_id=1,
        client_name=client, remote_addr=ip,
    )
    db.add(row)
    db.commit()
    return row


# ==================== 1. 默认关闭 ====================


def test_defaults_are_off(db):
    """出厂默认两档都是 off —— 这是整个功能的地基"""
    assert share_guard.DEFAULTS[share_guard.CONFIG_TRAVEL_ACTION] == "off"
    assert share_guard.DEFAULTS[share_guard.CONFIG_CONCURRENT_ACTION] == "off"
    # 不写任何配置行时，读出来也必须是 off（自愈补行前的裸库同样安全）
    assert share_guard.travel_action(db) == "off"
    assert share_guard.concurrent_action(db) == "off"


def test_off_writes_nothing(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_travel_action="record", share_concurrent_action="record")
    share_guard.write_policy(db, {share_guard.CONFIG_TRAVEL_ACTION: "off",
                                 share_guard.CONFIG_CONCURRENT_ACTION: "off"})
    db.commit()
    user = _user(db)

    assert share_guard.note_activity(db, user, "1.2.3.4") is None
    assert share_guard.note_session(db, user, "s1", "1.2.3.4") is None
    assert _events(db) == []


@pytest.mark.parametrize("raw", ["", "未知", "Unknown", "-", None])
def test_unknown_region_reads_as_not_a_city(db, monkeypatch, raw):
    """地理库未配置 / 查不到时返回各种占位，必须一律读成「不知道」

    而不是「换了个地方」——否则没配地理库的所有用户都会被报成跨城市。
    """
    from backend.integrations import geoip

    monkeypatch.setattr(share_guard, "city_of", _REAL_CITY_OF)
    monkeypatch.setattr(geoip, "region_of", lambda db, ip: raw or "")
    assert share_guard.city_of(db, "1.2.3.4") == ""


def test_known_region_passes_through(db, monkeypatch):
    from backend.integrations import geoip

    monkeypatch.setattr(share_guard, "city_of", _REAL_CITY_OF)
    monkeypatch.setattr(geoip, "region_of", lambda db, ip: "广东 深圳 南山区")
    assert share_guard.city_of(db, "1.2.3.4") == "广东 深圳 南山区"


def test_geo_failure_is_swallowed(db, monkeypatch):
    """地理查询报错不能把登录拖挂"""
    from backend.integrations import geoip

    def boom(db, ip):
        raise RuntimeError("geoip down")

    monkeypatch.setattr(share_guard, "city_of", _REAL_CITY_OF)
    monkeypatch.setattr(geoip, "region_of", boom)
    assert share_guard.city_of(db, "1.2.3.4") == ""


def test_empty_ip_is_never_looked_up(db, monkeypatch):
    """没有 IP 时连地理库都不问（省一次外部请求）"""
    from backend.integrations import geoip

    def boom(db, ip):
        raise AssertionError("空 IP 不该去查地理库")

    monkeypatch.setattr(share_guard, "city_of", _REAL_CITY_OF)
    monkeypatch.setattr(geoip, "region_of", boom)
    assert share_guard.city_of(db, None) == ""


def test_no_geo_no_judgement(db, _fake_geo):
    """城市查不到 → 不写轨迹、不判定。配了 record 也一样。"""
    _fake_geo.value = lambda ip: ""
    _policy(db, share_travel_action="enforce")
    user = _user(db)

    assert share_guard.note_activity(db, user, "1.2.3.4") is None
    assert _events(db) == []
    assert user.is_active is True, "查不到城市就停用账号 = 把整个站点误伤"


# ==================== 2. 跨城市轨迹 ====================


def test_travel_first_seen_writes_baseline(db, _fake_geo):
    """首次出现只写一行**基线**（标记当前位置，不是异常）

    基线行是判定算法自己的记忆（记住上一次在哪个城市），后台事件页按
    ``is_baseline`` 把它滤掉 —— 否则列表里全是「用户还在原地」。
    """
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_travel_action="record")
    user = _user(db)

    assert share_guard.note_activity(db, user, "1.1.1.1") is None
    rows = _events(db, kind=share_guard.KIND_TRAVEL)
    assert len(rows) == 1 and rows[0].region == "广东 深圳"
    assert rows[0].is_baseline is True, "首次出现的行必须标成基线，否则会混进事件流水"
    assert rows[0].prev_region is None, "基线没有「上一个城市」"
    assert share_guard.event_dto(rows[0])["is_baseline"] is True


def test_travel_same_city_in_window_is_throttled(db, _fake_geo):
    """同一城市在窗口内反复上报只写一行（客户端每 10 秒一次心跳）"""
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_travel_action="record")
    user = _user(db)

    share_guard.note_activity(db, user, "1.1.1.1")
    for _ in range(20):
        assert share_guard.note_activity(db, user, "1.1.1.1") is None
    assert len(_events(db, kind=share_guard.KIND_TRAVEL)) == 1


def test_travel_detects_city_switch(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳" if ip == "1.1.1.1" else "四川 成都"
    _policy(db, share_travel_action="record")
    user = _user(db)

    share_guard.note_activity(db, user, "1.1.1.1")
    verdict = share_guard.note_activity(db, user, "2.2.2.2")

    assert verdict is not None
    assert verdict["kind"] == share_guard.KIND_TRAVEL
    assert verdict["prev_region"] == "广东 深圳"
    assert verdict["region"] == "四川 成都"
    assert verdict["blocked"] is False, "record 档不处置"
    assert user.is_active is True
    rows = _events(db, kind=share_guard.KIND_TRAVEL)
    assert len(rows) == 2
    assert rows[0].is_baseline is True, "第一行是基线"
    assert rows[1].is_baseline is False, "判定行绝不能标成基线，否则事件流水里看不到它"


def test_travel_outside_window_is_not_flagged(db, _fake_geo):
    """窗口外的城市变化不算异常（出差 / 回家 / 换网络都是正常的）"""
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_travel_action="enforce", share_travel_window_minutes="30")
    user = _user(db)

    share_guard.note_activity(db, user, "1.1.1.1")
    # 把上一条挪到窗口之外
    old = _events(db, kind=share_guard.KIND_TRAVEL)[0]
    old.created_at = datetime.now() - timedelta(minutes=31)
    old.region = "四川 成都"
    db.commit()

    _fake_geo.value = lambda ip: "广东 深圳"
    assert share_guard.note_activity(db, user, "1.1.1.1") is None
    assert user.is_active is True


def test_travel_alert_notifies_staff(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳" if ip == "1.1.1.1" else "四川 成都"
    _policy(db, share_travel_action="alert")
    staff = _user(db, "boss", is_staff=True)
    user = _user(db)

    share_guard.note_activity(db, user, "1.1.1.1")
    share_guard.note_activity(db, user, "2.2.2.2")

    msgs = db.query(models.StationMessage).filter(
        models.StationMessage.to_user_id == staff.id
    ).all()
    assert len(msgs) == 1
    assert msgs[0].message_type == "share_guard"
    assert user.is_active is True, "alert 档只通知，不停用"


def test_travel_enforce_disables_account(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳" if ip == "1.1.1.1" else "四川 成都"
    _policy(db, share_travel_action="enforce")
    user = _user(db)

    share_guard.note_activity(db, user, "1.1.1.1")
    verdict = share_guard.note_activity(db, user, "2.2.2.2")

    assert verdict["blocked"] is True
    db.refresh(user)
    assert user.is_active is False
    # 停用也要留安全日志：「为什么这个号突然登不上」的答案
    reasons = [r.reason for r in db.query(models.LoginLog).all()]
    assert "share_guard" in reasons


def test_travel_never_flags_staff(db, _fake_geo):
    """管理员排障时会故意从多地登录，不能因此被自己停用"""
    _fake_geo.value = lambda ip: "广东 深圳" if ip == "1.1.1.1" else "四川 成都"
    _policy(db, share_travel_action="enforce")
    boss = _user(db, "boss", is_staff=True)

    assert share_guard.note_activity(db, boss, "1.1.1.1") is None
    assert share_guard.note_activity(db, boss, "2.2.2.2") is None
    assert boss.is_active is True
    assert _events(db) == []


# ==================== 3. 同播检测 ====================


def test_concurrent_under_limit_is_fine(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_concurrent_action="enforce", share_concurrent_limit="2")
    user = _user(db)
    _live_session(db, user.id, "s1")

    # 只有 1 条既有会话 → 本条是第 2 路 = 上限，不算超
    assert share_guard.note_session(db, user, "s2", "1.1.1.1") is None


def test_concurrent_over_limit_is_flagged(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_concurrent_action="record", share_concurrent_limit="2")
    user = _user(db)
    _live_session(db, user.id, "s1", client="Infuse")
    _live_session(db, user.id, "s2", client="SenPlayer")

    verdict = share_guard.note_session(db, user, "s3", "1.1.1.1")

    assert verdict is not None
    assert verdict["sessions"] == 3
    assert verdict["blocked"] is False
    rows = _events(db, kind=share_guard.KIND_CONCURRENT)
    assert len(rows) == 1 and rows[0].sessions == 3


def test_concurrent_enforce_blocks_extra_session(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_concurrent_action="enforce", share_concurrent_limit="1")
    user = _user(db)
    _live_session(db, user.id, "s1")

    verdict = share_guard.note_session(db, user, "s2", "1.1.1.1")
    assert verdict["blocked"] is True
    # 被拦下的会话不应该出现在会话表里（调用方拿到 None 后不会建会话）
    keys = [s.session_key for s in db.query(em.PlaybackSession).all()]
    assert "s2" not in keys


def test_concurrent_ignores_own_session(db, _fake_geo):
    """进度上报会反复命中同一条会话，不能把自己算成「另一路」"""
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_concurrent_action="enforce", share_concurrent_limit="1")
    user = _user(db)
    _live_session(db, user.id, "s1")

    assert share_guard.note_session(db, user, "s1", "1.1.1.1") is None


def test_concurrent_ignores_ended_sessions(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_concurrent_action="enforce", share_concurrent_limit="1")
    user = _user(db)
    old = _live_session(db, user.id, "s1")
    old.ended_at = datetime.now()
    db.commit()

    assert share_guard.note_session(db, user, "s2", "1.1.1.1") is None


def test_concurrent_never_flags_staff(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_concurrent_action="enforce", share_concurrent_limit="1")
    boss = _user(db, "boss", is_staff=True)
    _live_session(db, boss.id, "s1")

    assert share_guard.note_session(db, boss, "s2", "1.1.1.1") is None


# ==================== 4. 策略读写与清理 ====================


def test_write_policy_rejects_unknown_and_bad_values(db):
    applied = share_guard.write_policy(db, {
        "share_travel_action": "不存在的档位",     # 非法枚举 → 不写
        "share_travel_window_minutes": "abc",     # 非数字 → 不写
        "share_concurrent_limit": "999",          # 超上限 → 夹到上限
        "随便一个键": "x",                          # 不在白名单 → 不写
    })
    db.commit()

    assert "share_travel_action" not in applied
    assert "share_travel_window_minutes" not in applied
    assert "随便一个键" not in applied
    assert share_guard.concurrent_limit(db) == share_guard.LIMIT_MAX


def test_policy_roundtrip(db):
    share_guard.write_policy(db, {
        share_guard.CONFIG_TRAVEL_ACTION: "enforce",
        share_guard.CONFIG_CONCURRENT_ACTION: "alert",
        share_guard.CONFIG_TRAVEL_WINDOW: "15",
        share_guard.CONFIG_CONCURRENT_LIMIT: "5",
    })
    db.commit()
    payload = share_guard.policy_payload(db)
    assert payload["travel_action"] == "enforce"
    assert payload["concurrent_action"] == "alert"
    assert payload["travel_window_minutes"] == 15
    assert payload["concurrent_limit"] == 5


def test_alert_notification_is_throttled(db, _fake_geo):
    """站内信节流：狂刷会话的客户端不该把管理员邮箱刷爆

    事件行照旧每次都记（那是事实），只有通知被节流。
    """
    from backend import authlog

    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_concurrent_action="alert", share_concurrent_limit="1")
    staff = _user(db, "boss", is_staff=True)
    user = _user(db)

    for index in range(5):
        _live_session(db, user.id, f"s{index}")
        share_guard.note_session(db, user, f"new{index}", "1.1.1.1")

    messages = db.query(models.StationMessage).filter(
        models.StationMessage.to_user_id == staff.id,
        models.StationMessage.message_type == "share_guard",
    ).count()
    assert messages == 1, "同一个号同类异常，10 分钟内只提醒一次"
    assert len(_events(db, kind=share_guard.KIND_CONCURRENT)) == 5, "事件行一条不能少"
    # 防共享停用会写登录日志，登录日志里必须有可读的中文原因
    assert authlog.REASONS.get("share_guard"), "share_guard 缺登录日志原因标签"


def test_purge_respects_retention(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_travel_action="record")
    user = _user(db)
    share_guard.note_activity(db, user, "1.1.1.1")
    old = _events(db)[0]
    old.created_at = datetime.now() - timedelta(days=100)
    db.commit()

    assert share_guard.purge_old(db, 90) == 1
    assert _events(db) == []


def test_purge_zero_means_disabled(db, _fake_geo):
    """保留天数 = 0 表示「不自动清理」，不是「清空」"""
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_travel_action="record")
    user = _user(db)
    share_guard.note_activity(db, user, "1.1.1.1")

    assert share_guard.purge_old(db, 0) == 0
    assert len(_events(db)) == 1


def test_event_dto_has_labels(db, _fake_geo):
    _fake_geo.value = lambda ip: "广东 深圳"
    _policy(db, share_travel_action="record")
    user = _user(db)
    share_guard.note_activity(db, user, "1.1.1.1")

    dto = share_guard.event_dto(_events(db)[0])
    assert dto["kind_label"] == "跨城市轨迹"
    assert dto["action_label"] == "只记录"


# ==================== 6. 后台事件页只列判定 ====================


def test_admin_event_list_hides_baselines(db, _fake_geo):
    """基线行留在库里（判定要靠它），但不进后台事件页

    否则运营看到的列表里绝大多数是「用户还在原地」，概览数字也被它冲高到
    没有意义 —— 判定记录页只应该回答「判出来过什么」。
    """
    from backend.api import admin_ops

    _fake_geo.value = lambda ip: "广东 深圳" if ip == "1.1.1.1" else "四川 成都"
    _policy(db, share_travel_action="record")
    admin = _user(db, "boss", is_staff=True)
    user = _user(db)

    share_guard.note_activity(db, user, "1.1.1.1")   # 基线
    share_guard.note_activity(db, user, "2.2.2.2")   # 判定

    payload = admin_ops.get_share_guard(current_admin=admin, db=db)
    assert len(_events(db)) == 2, "库里两条都在（判定离不开基线）"
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["travel_24h"] == 1
    assert len(payload["events"]) == 1
    assert payload["events"][0]["prev_region"] == "广东 深圳"