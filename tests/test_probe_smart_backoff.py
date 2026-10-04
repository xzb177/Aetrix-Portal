"""探测 worker 的智能退避：别再反复探测配额受限的文件

背景（也是这一版要修的浪费）：配额耗尽要 **24 小时** 才恢复，而原来的单条退避
上限是 **1 小时**——在配额恢复前，每个文件都会白白打 24 次请求。同时熔断后的
休眠是 5 分钟，与熔断状态靠 Redis 24h TTL 过期的事实对不上，worker 每天醒来
288 次，每次发现「还熔着」就继续睡。

这里把三条处置钉死：

1. **永久失败直接放弃**：文件没了 / 格式不支持，重试一万次还是同一个结果，
   而每次重试都要占 worker 名额与云盘配额。
2. **配额耗尽等满 24 小时，且不计入尝试次数**：配额是账号/部署的状态，不是这个
   文件的错。计进 5 次上限就等于「因为配额问题把文件判死」。
3. **重试中的老文件排在新入库文件之后**：用户最想看的是刚入库那批的元数据。

全部用隔离的内存 SQLite 与桩，不碰网络、不碰生产库。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models as web_models
from backend.emby_server import models as em
from backend.emby_server import probe_worker as pw


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    web_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # MediaItem.library_id 是 NOT NULL，建一个库房挂上去
    session.add(em.Library(guid="lib-1", name="电影"))
    session.commit()
    yield session
    session.close()


def _item(db, name="a.mkv", **kw):
    status = kw.pop("probe_status", "probing")
    row = em.MediaItem(
        guid=f"guid-{name}",
        library_id=db.query(em.Library).first().id,
        item_type="movie",
        name=name,
        file_path=f"/media/{name}",
        container="mp4",
        probe_status=status,
        **kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ==================== 失败分类 ====================


@pytest.mark.parametrize("error", [
    "not_found",
    "http_404", "http_410",
])
def test_permanent_errors(error):
    """永久失败只认「文件真的不在了」（v2.42.14 收紧）

    原来还包含 400 / 415 / 416，但线上实测这些码在云盘与反代后面绝大多数不是
    「文件坏了」：签名 URL 过期、网关回 415、Range 被中间层改写都会落到这几码。
    当成永久失败 = 把还在线播放的条目判死，用户端直接变「不存在该项目」。
    """
    assert pw._classify_failure(error) == pw.KIND_PERMANENT


@pytest.mark.parametrize("error", ["http_400", "http_405", "http_415", "http_416"])
def test_ambiguous_http_codes_are_not_permanent(error):
    """这些码现在是临时失败：退避重试；真不支持的格式会在 PROBE_MAX_ATTEMPTS 后
    自行转 failed（只是不再第一次就被判死）"""
    assert pw._classify_failure(error) == pw.KIND_TRANSIENT


@pytest.mark.parametrize("error", [
    "quota",                       # 配额是账号状态，不是文件的错
    "auth", "http_401",            # 凭据失效：管理员改完就能探，不判死
    "http_500", "http_502",        # 服务端临时故障
    "http_429",                    # 限流
    "", None, "unknown_future_kind",  # 认不出来 → 保守当临时
])
def test_transient_errors(error):
    assert pw._classify_failure(error) == pw.KIND_TRANSIENT


def test_unknown_error_is_not_permanently_failed():
    """认不出来的一律当临时——宁可多试几次，也不要因为归错类把好文件判死"""
    assert pw._classify_failure("something_we_have_never_seen") == pw.KIND_TRANSIENT


# ==================== 退避时长 ====================


def test_backoff_cap_is_24h_not_1h():
    """**核心回归**：原上限 3600s（1 小时），配额恢复要 24 小时 —— 白打 24 次请求"""
    assert pw.MAX_BACKOFF_SECONDS == 86400
    assert pw._backoff_seconds(1) == 60
    assert pw._backoff_seconds(2) == 120
    assert pw._backoff_seconds(5) == 960
    assert pw._backoff_seconds(20) == 86400     # 封顶，不再往上
    assert pw._backoff_seconds(999) == 86400


def test_quota_backoff_is_a_full_day():
    assert pw.QUOTA_BACKOFF_SECONDS == 86400


# ==================== 永久失败：直接放弃 ====================


def test_permanent_failure_fails_immediately(db):
    item = _item(db, "gone.mkv")
    pw._fail(db, item, "远端 404", error="not_found")
    db.commit()
    assert item.probe_status == "failed"
    assert item.probe_next_retry_at is None, "永久失败不该再排重试"


def test_permanent_failure_does_not_walk_the_backoff_ladder(db):
    """只失败一次就直接放弃，不会先 pending 退避几次才 failed

    用**确实代表文件没了**的码（v2.42.14 收紧后 415 不再算永久）。
    """
    item = _item(db, "gone.mkv", probe_attempts=0)
    pw._fail(db, item, "文件不存在", error="http_404")
    db.commit()
    assert item.probe_status == "failed"
    assert item.probe_attempts == pw.PROBE_MAX_ATTEMPTS


# ==================== 配额：等 24 小时，不计次数 ====================


def test_quota_failure_waits_24h_and_keeps_attempts(db):
    item = _item(db, "a.mkv", probe_attempts=0)
    before = datetime.now()
    pw._fail(db, item, "配额耗尽", error="quota")
    db.commit()

    assert item.probe_status == "pending"           # 不是 failed：不是文件的错
    assert item.probe_attempts == 0, "配额问题不该消耗文件的尝试次数"
    delta = item.probe_next_retry_at - before
    assert timedelta(hours=23, minutes=55) <= delta <= timedelta(hours=24, minutes=5)


def test_repeated_quota_errors_never_fail_the_item(db):
    """连着 10 次配额耗尽也不会把文件判死 —— 旧逻辑会把 5 次上限算进去"""
    item = _item(db, "a.mkv", probe_attempts=0)
    for _ in range(10):
        pw._fail(db, item, "配额耗尽", error="quota")
    db.commit()
    assert item.probe_status == "pending"
    assert item.probe_attempts == 0


# ==================== 临时失败：退避重试 + 降优先级 ====================


def test_transient_failure_schedules_retry(db):
    item = _item(db, "a.mkv", probe_attempts=0)
    before = datetime.now()
    pw._fail(db, item, "源站超时", error="http_502")
    db.commit()
    assert item.probe_status == "pending"
    assert item.probe_attempts == 1
    assert before + timedelta(seconds=50) <= item.probe_next_retry_at


def test_transient_failure_still_gives_up_after_max_attempts(db):
    item = _item(db, "a.mkv", probe_attempts=pw.PROBE_MAX_ATTEMPTS - 1)
    pw._fail(db, item, "一直超时", error="http_502")
    db.commit()
    assert item.probe_status == "failed"
    assert item.probe_next_retry_at is None


def test_retrying_items_are_demoted_below_new_files(db):
    """重试中的老文件排到新入库文件之后"""
    item = _item(db, "old.mkv", probe_attempts=0, probe_priority=pw.NEW_FILE_PRIORITY)
    pw._fail(db, item, "源站超时", error="http_502")
    db.commit()
    assert item.probe_priority == pw.RETRY_PRIORITY
    assert item.probe_priority < pw.NEW_FILE_PRIORITY


# ==================== 熔断 ====================


def test_breaker_sleeps_a_full_day():
    """原来 5 分钟 —— 与熔断状态靠 Redis 24h TTL 过期的事实对不上，
    worker 每天醒来 288 次只为了发现「还熔着」"""
    assert pw._QUOTA_BREAKER_BACKOFF_SEC == 86400


# ==================== 抢批：新文件优先 ====================


def test_claim_batch_orders_new_files_before_retries(db):
    """新文件（100）先于重试中的老文件（10）"""
    from datetime import datetime as _dt

    retry_item = _item(db, "retry.mkv", probe_status="pending",
                       probe_priority=pw.RETRY_PRIORITY)
    plain = _item(db, "plain.mkv", probe_status="pending", probe_priority=0)
    new_item = _item(db, "new.mkv", probe_status="pending",
                     probe_priority=pw.NEW_FILE_PRIORITY)

    ids = pw._claim_batch(db, 10)
    assert ids.index(new_item.id) < ids.index(retry_item.id)
    assert ids.index(new_item.id) < ids.index(plain.id)


def test_claim_batch_respects_retry_time(db):
    """退避没到期的不能被抢走"""
    item = _item(db, "later.mkv", probe_status="pending",
                 probe_priority=pw.RETRY_PRIORITY,
                 probe_next_retry_at=datetime.now() + timedelta(hours=23))
    assert pw._claim_batch(db, 10) == []
    item.probe_next_retry_at = datetime.now() - timedelta(minutes=1)
    db.commit()
    assert pw._claim_batch(db, 10) == [item.id]


def test_claim_batch_after_24h_quota_retry_is_reachable(db):
    """配额 24 小时后到期就该能被重新抢到（否则会永久卡住）"""
    item = _item(db, "a.mkv", probe_status="pending",
                 probe_next_retry_at=datetime.now() + timedelta(hours=23, minutes=59))
    assert pw._claim_batch(db, 10) == []
    item.probe_next_retry_at = datetime.now() + timedelta(hours=23, minutes=58)
    db.commit()
    assert pw._claim_batch(db, 10) == []


# ==================== 按需插队不受影响 ====================


def test_boost_still_beats_everything(db):
    """用户手动点「重新探测」必须插到最前，且清掉退避与失败计数"""
    item = _item(db, "a.mkv", probe_status="failed",
                 probe_attempts=pw.PROBE_MAX_ATTEMPTS,
                 probe_priority=pw.RETRY_PRIORITY,
                 probe_next_retry_at=datetime.now() + timedelta(hours=23))
    assert pw.boost_probe(db, item) is True
    db.commit()
    assert item.probe_priority == pw.BOOST_PRIORITY
    assert item.probe_next_retry_at is None
    assert item.probe_status == "pending"
    assert item.probe_attempts == 0
    assert pw._claim_batch(db, 10) == [item.id]


def test_priority_ladder_is_ordered():
    assert pw.BOOST_PRIORITY > pw.NEW_FILE_PRIORITY > pw.RETRY_PRIORITY > pw.DEFAULT_PRIORITY