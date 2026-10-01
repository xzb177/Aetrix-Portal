"""VPS 本地缓存（local_cache / local_cache_worker）单元测试

覆盖需求五条对应的实现面：

1. 配置：开关默认关、目录、配额（GB）、热门判定（N 天内播放 M 次）、限速；
2. 热门自动入队（只取远程挂载来源，本机文件不缓存）；
3. 播放命中读本机 / 未命中入队（播放线路分支见 tests/test_play_line.py）；
4. LRU 淘汰：超配额按最久未访问删除（连文件一起删）；
5. 占用 / 命中率统计与手动清理，以及 worker 的限速下载与播放让路。

全部用隔离的内存 SQLite，不碰网络、不碰生产库（下载的远端流由假 opener 注入）。
"""
import os
import time
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.emby_server import local_cache, local_cache_worker
from backend.emby_server import models as em
from backend.integrations import store


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # 配置热缓存是进程级的（key 不带库名）：进出都清一次，避免污染别的内存库测试
    store.invalidate()
    yield session
    store.invalidate()
    session.close()


def _write_config(db, **overrides):
    kwargs = dict(enabled=True, dir="", max_gb_value=500, hot_days_value=7,
                  hot_plays_value=3, rate_mbps_value=20)
    kwargs.update(overrides)
    return local_cache.write_config(db, **kwargs)


def _make_item(db, *, remote=True, size=1024, name="测试影片", file_path=None):
    lib = em.Library(guid=uuid.uuid4().hex, name="本地缓存库",
                     collection_type="movies", paths="")
    db.add(lib)
    db.flush()
    path = file_path or (f"mount://1/Movies/{name}.mkv" if remote else f"/local/{name}.mkv")
    item = em.MediaItem(
        guid=uuid.uuid4().hex, library_id=lib.id, item_type="movie",
        name=name, file_path=path, size=size,
    )
    db.add(item)
    db.commit()
    return item


def _make_user(db, username="viewer"):
    user = models.WebUser(username=username, password_hash="x")
    db.add(user)
    db.commit()
    return user


def _make_session(db, item, user, *, started=None, ended=None, key=None):
    row = em.PlaybackSession(
        session_key=key or uuid.uuid4().hex, user_id=user.id, item_id=item.id,
        start_time=started or datetime.now(), last_update_at=datetime.now(),
        ended_at=ended,
    )
    db.add(row)
    db.commit()
    return row


def _ready_entry(db, item, directory, *, content=b"x" * 1024,
                 accessed=None, state="ready"):
    """在 directory 里放一个「已缓存好的副本」并登记条目"""
    path = local_cache._dest_path(str(directory), item)
    with open(path, "wb") as f:
        f.write(content)
    entry = em.LocalCacheEntry(
        item_guid=item.guid, item_id=item.id, source_path=item.file_path,
        source_size=len(content), file_path=path, file_size=len(content),
        state=state, cached_at=datetime.now(),
        last_accessed_at=accessed or datetime.now(),
    )
    db.add(entry)
    db.commit()
    return entry


# ==================== 1. 配置 ====================

def test_config_defaults_disabled(db):
    payload = local_cache.config_payload(db)
    assert payload["enabled"] is False          # 默认关闭
    assert payload["dir"].endswith(local_cache._CACHE_SUBDIR)
    assert payload["max_gb"] == 500
    assert payload["hot_days"] == 7
    assert payload["hot_plays"] == 3
    assert payload["rate_mbps"] == 20
    assert payload["play_line"] == "cache"
    assert local_cache.enabled(db) is False


def test_write_config_roundtrip(db, tmp_path):
    state = _write_config(db, dir=str(tmp_path), max_gb_value=10,
                          hot_days_value=3, hot_plays_value=5, rate_mbps_value=8)
    assert state["enabled"] is True
    assert state["dir"] == str(tmp_path)
    assert state["max_gb"] == 10
    assert state["hot_days"] == 3
    assert state["hot_plays"] == 5
    assert state["rate_mbps"] == 8
    assert local_cache.max_bytes(db) == 10 * 1024 ** 3
    assert local_cache.enabled(db) is True
    # 保存即失效：读到的是刚写的值（不是热缓存里的旧值）
    assert local_cache.hot_plays(db) == 5


def test_write_config_rejects_bad_values(db, tmp_path):
    with pytest.raises(ValueError):
        _write_config(db, dir="relative/path")          # 必须绝对路径
    with pytest.raises(ValueError):
        _write_config(db, hot_days_value=0)             # 窗口至少 1 天
    with pytest.raises(ValueError):
        _write_config(db, hot_days_value=9999)
    with pytest.raises(ValueError):
        _write_config(db, hot_plays_value=0)            # 次数至少 1
    with pytest.raises(ValueError):
        _write_config(db, max_gb_value=-1)              # 配额不能为负
    with pytest.raises(ValueError):
        _write_config(db, rate_mbps_value=999999)       # 限速上限
    # 校验失败不落库：仍是默认关闭状态
    assert local_cache.enabled(db) is False


def test_dirty_config_falls_back_to_defaults(db):
    db.add(models.SystemConfig(key=local_cache.CONFIG_MAX_GB, value="不是数字"))
    db.add(models.SystemConfig(key=local_cache.CONFIG_HOT_DAYS, value="0"))
    db.commit()
    store.invalidate()
    assert local_cache.max_gb(db) == local_cache.DEFAULT_MAX_GB   # 解不动 → 默认值
    assert local_cache.hot_days(db) == 1                          # 越界 → 夹到下限（窗口至少 1 天）


# ==================== 2. 热门判定与入队 ====================

def test_hot_item_ids_window_and_threshold(db):
    user = _make_user(db)
    hot = _make_item(db, name="热门片")
    cold = _make_item(db, name="冷门片")
    local_file = _make_item(db, remote=False, name="本机片")
    old = _make_item(db, name="过期窗口片")

    for i in range(4):                      # 达到阈值 3
        _make_session(db, hot, user, key=f"hot{i}")
    _make_session(db, cold, user, key="cold0")   # 只有 1 次
    for i in range(4):                      # 本机片再热也不缓存（没有副本的意义）
        _make_session(db, local_file, user, key=f"lf{i}")
    # 窗口外的 5 次不算数
    for i in range(5):
        _make_session(db, old, user, key=f"old{i}",
                      started=datetime.now() - timedelta(days=30))

    _write_config(db)
    ids = local_cache.hot_item_ids(db)
    assert hot.id in ids
    assert cold.id not in ids
    assert local_file.id not in ids
    assert old.id not in ids
    assert len(ids) == 1


def test_enqueue_creates_pending_and_skips_local(db):
    remote = _make_item(db, size=2048)
    local = _make_item(db, remote=False)

    # 默认关闭：不入队
    assert local_cache.enqueue(db, remote) is None
    assert db.query(em.LocalCacheEntry).count() == 0

    _write_config(db)
    entry = local_cache.enqueue(db, remote, priority=local_cache.PLAY_PRIORITY)
    assert entry is not None and entry.state == "pending"
    assert entry.priority == local_cache.PLAY_PRIORITY
    assert entry.source_size == 2048

    # 本机文件不入队
    assert local_cache.enqueue(db, local) is None

    # 重复入队不建重复行，只抬优先级
    again = local_cache.enqueue(db, remote, priority=local_cache.HOT_PRIORITY)
    assert again.id == entry.id
    assert again.priority == local_cache.PLAY_PRIORITY
    assert db.query(em.LocalCacheEntry).count() == 1


def test_enqueue_resets_ready_entry_when_source_changed(db, tmp_path):
    item = _make_item(db)
    _write_config(db, dir=str(tmp_path))
    entry = _ready_entry(db, item, tmp_path)
    assert entry.state == "ready"

    item.file_path = "mount://2/Movies/换源了.mkv"
    db.commit()
    refreshed = local_cache.enqueue(db, item, priority=local_cache.PLAY_PRIORITY)
    assert refreshed.state == "pending"          # 源变了：旧副本立刻失效


def test_enqueue_gives_failed_entry_another_chance(db):
    item = _make_item(db)
    _write_config(db)
    entry = em.LocalCacheEntry(item_guid=item.guid, item_id=item.id,
                               source_path=item.file_path, source_size=1,
                               state="failed", attempts=1, last_error="网络抖动")
    db.add(entry)
    db.commit()
    refreshed = local_cache.enqueue(db, item)
    assert refreshed.state == "pending"
    assert refreshed.last_error is None


# ==================== 3. 播放命中 ====================

def test_lookup_hit_increments_and_records_stat(db, tmp_path):
    item = _make_item(db, size=1024)
    _write_config(db, dir=str(tmp_path))
    entry = _ready_entry(db, item, tmp_path, content=b"x" * 1024)

    path = local_cache.lookup(db, item)
    assert path == entry.file_path
    assert os.path.isfile(path)
    db.refresh(entry)
    assert entry.hits == 1
    assert entry.last_accessed_at is not None
    assert local_cache.stat_counts(db) == (1, 0)

    assert local_cache.lookup(db, item) == path
    assert local_cache.stat_counts(db) == (2, 0)


def test_lookup_miss_when_disabled_or_not_cacheable(db, tmp_path):
    item = _make_item(db, size=1024)
    local = _make_item(db, remote=False, size=1024)
    _write_config(db, dir=str(tmp_path))
    _ready_entry(db, item, tmp_path, content=b"x" * 1024)

    # 关掉缓存：既不给副本，也不计入命中率（不是「没命中」，是「没这个功能」）
    _write_config(db, enabled=False, dir=str(tmp_path))
    assert local_cache.lookup(db, item) is None
    assert local_cache.stat_counts(db) == (0, 0)
    # 本机条目永远不需要缓存线路的副本
    _write_config(db, dir=str(tmp_path))
    assert local_cache.lookup(db, local) is None
    assert local_cache.stat_counts(db) == (0, 0)


def test_lookup_miss_when_source_changed(db, tmp_path):
    item = _make_item(db, size=1024)
    _write_config(db, dir=str(tmp_path))
    entry = _ready_entry(db, item, tmp_path, content=b"x" * 1024)

    # 换源（大小变了）：不算命中，副本打回队列重新缓存
    item.size = 4096
    db.commit()
    assert local_cache.lookup(db, item) is None
    db.refresh(entry)
    assert entry.state == "pending"
    assert entry.last_error and "源文件" in entry.last_error
    assert local_cache.stat_counts(db) == (0, 1)


def test_lookup_miss_when_file_gone(db, tmp_path):
    item = _make_item(db, size=1024)
    _write_config(db, dir=str(tmp_path))
    entry = _ready_entry(db, item, tmp_path, content=b"x" * 1024)

    os.remove(entry.file_path)                 # 副本被手工删了 / 磁盘被清了
    assert local_cache.lookup(db, item) is None
    db.refresh(entry)
    assert entry.state == "pending"            # 打回队列，等 worker 重新缓存
    assert local_cache.stat_counts(db) == (0, 1)


def test_lookup_survives_broken_db(db, tmp_path):
    """缓存只是加速：db 异常时按未命中返回，不能把播放打挂"""
    item = _make_item(db, size=1024)
    _write_config(db, dir=str(tmp_path))

    class BrokenDB:
        def query(self, *a, **k):
            raise RuntimeError("db down")

        def rollback(self):
            pass

    assert local_cache.lookup(BrokenDB(), item) is None


# ==================== 4. LRU 淘汰 ====================

def test_evict_removes_least_recently_used_first(db, tmp_path, monkeypatch):
    monkeypatch.setattr(local_cache, "max_bytes", lambda _db: 1500)
    item_a = _make_item(db, name="最久没看")
    item_b = _make_item(db, name="次久没看")
    item_c = _make_item(db, name="刚看过")
    now = datetime.now()
    entry_a = _ready_entry(db, item_a, tmp_path, content=b"a" * 1000,
                           accessed=now - timedelta(days=3))
    entry_b = _ready_entry(db, item_b, tmp_path, content=b"b" * 1000,
                           accessed=now - timedelta(days=1))
    entry_c = _ready_entry(db, item_c, tmp_path, content=b"c" * 1000, accessed=now)

    counts = local_cache.evict(db)
    # 3000 > 1500：先删最久没访问的两条，直到降到配额以内
    assert counts["removed"] == 2
    assert counts["freed_bytes"] == 2000
    remaining = db.query(em.LocalCacheEntry).all()
    assert [e.id for e in remaining] == [entry_c.id]
    assert not os_path_isfile(entry_a.file_path)
    assert not os_path_isfile(entry_b.file_path)
    assert os_path_isfile(entry_c.file_path)
    assert local_cache.ready_bytes(db) == 1000


def test_evict_disabled_when_quota_is_zero(db, tmp_path, monkeypatch):
    monkeypatch.setattr(local_cache, "max_bytes", lambda _db: 0)
    item = _make_item(db)
    entry = _ready_entry(db, item, tmp_path, content=b"x" * 1000)
    counts = local_cache.evict(db)
    assert counts["removed"] == 0
    assert os_path_isfile(entry.file_path)


def test_evict_ignores_pending_and_downloading(db, tmp_path, monkeypatch):
    """半成品不算占用：淘汰绝不碰正在写的记录"""
    monkeypatch.setattr(local_cache, "max_bytes", lambda _db: 1)
    ready_item = _make_item(db, name="已缓存")
    other = _make_item(db, name="下载中")
    ready = _ready_entry(db, ready_item, tmp_path, content=b"x" * 100,
                         accessed=datetime.now() - timedelta(days=1))
    downloading = em.LocalCacheEntry(
        item_guid=other.guid, item_id=other.id, source_path=other.file_path,
        file_path=str(tmp_path) + "/half.mkv", file_size=999, state="downloading",
    )
    db.add(downloading)
    db.commit()
    local_cache.evict(db)
    db.refresh(downloading)
    assert downloading.state == "downloading"     # 正在写的绝不碰
    # 配额只有 1 字节：ready 那条被正常淘汰（淘汰本身还在工作）
    assert db.query(em.LocalCacheEntry).filter_by(id=ready.id).count() == 0


def test_evict_protects_recently_accessed_copy(db, tmp_path, monkeypatch):
    """刚访问过的副本不参与淘汰：避免命中与删除之间的毫秒竞态断掉正在播的片子"""
    monkeypatch.setattr(local_cache, "max_bytes", lambda _db: 1)
    item = _make_item(db)
    entry = _ready_entry(db, item, tmp_path, content=b"x" * 100)  # accessed = 刚刚
    counts = local_cache.evict(db)
    assert counts["removed"] == 0
    db.refresh(entry)
    assert entry.state == "ready"
    assert os.path.isfile(entry.file_path)


# ==================== 5. 统计与手动清理 ====================

def test_stats_reports_usage_and_hit_rate(db, tmp_path):
    item = _make_item(db, size=2048)
    _write_config(db, dir=str(tmp_path))
    stats0 = local_cache.stats(db)
    assert stats0["enabled"] is True
    assert stats0["bytes_used"] == 0
    assert stats0["hit_rate"] is None           # 还没有任何取用
    assert stats0["dir"] == str(tmp_path)
    assert stats0["max_bytes"] == 500 * 1024 ** 3

    _ready_entry(db, item, tmp_path, content=b"x" * 2048)
    local_cache.lookup(db, item)               # 1 命中
    local_cache.lookup(db, _make_item(db))     # 1 未命中

    stats1 = local_cache.stats(db)
    assert stats1["bytes_used"] == 2048
    assert stats1["entries"].get("ready") == 1
    assert stats1["hits"] == 1 and stats1["misses"] == 1
    assert stats1["hit_rate"] == 0.5
    listed = local_cache.entry_list(db)
    assert len(listed) == 1
    assert listed[0]["state"] == "ready"
    assert listed[0]["hits"] == 1


def test_clean_modes(db, tmp_path):
    ready_item = _make_item(db, name="可清理")
    failed_item = _make_item(db, name="失败记录")
    pending_item = _make_item(db, name="排队中")
    busy_item = _make_item(db, name="正在下载")
    ready = _ready_entry(db, ready_item, tmp_path, content=b"x" * 100)
    failed = em.LocalCacheEntry(item_guid=failed_item.guid, item_id=failed_item.id,
                                source_path=failed_item.file_path, state="failed",
                                attempts=9, last_error="源站 404")
    pending = em.LocalCacheEntry(item_guid=pending_item.guid, item_id=pending_item.id,
                                 source_path=pending_item.file_path, state="pending")
    downloading = em.LocalCacheEntry(item_guid=busy_item.guid, item_id=busy_item.id,
                                     source_path=busy_item.file_path, state="downloading")
    db.add_all([failed, pending, downloading])
    db.commit()

    counts = local_cache.clean(db, "ready")
    assert counts["removed"] == 1 and counts["freed_bytes"] == 100
    assert not os_path_isfile(ready.file_path)
    assert db.query(em.LocalCacheEntry).filter_by(id=ready.id).count() == 0

    counts = local_cache.clean(db, "all")
    # ready/failed/pending 都清；downloading 留给 worker 收尾
    assert counts["removed"] == 2
    states = [e.state for e in db.query(em.LocalCacheEntry).all()]
    assert states == ["downloading"]

    with pytest.raises(ValueError):
        local_cache.clean(db, "手滑模式")

    local_cache.reset_stats(db)
    assert local_cache.stat_counts(db) == (0, 0)


# ==================== 6. 下载：限速、让路、重试 ====================

def _fake_opener_factory(chunks, total=None, seen=None):
    def _fake_open(url, headers, offset):
        if seen is not None:
            seen.append(offset)
        start = offset if offset else 0
        payload = b"".join(chunks)
        body = payload[start:] if start else payload
        return iter([body]), (total if total is not None else len(payload)), (start if offset else 0)
    return _fake_open


def test_download_entry_marks_ready(db, tmp_path, monkeypatch):
    from backend.emby_server.mounts import PlayTarget

    payload = b"y" * 4096
    item = _make_item(db, size=len(payload))
    _write_config(db, dir=str(tmp_path))
    entry = local_cache.enqueue(db, item, priority=local_cache.PLAY_PRIORITY)
    monkeypatch.setattr(local_cache.mount_lib, "resolve_play_target",
                        lambda path, _db, library=None: PlayTarget("url", "https://fake/x.mkv", {}))
    monkeypatch.setattr(local_cache, "_open_remote_stream",
                        _fake_opener_factory([payload]))

    assert local_cache.download_entry(db, entry.id) == "ready"
    db.refresh(entry)
    assert entry.state == "ready"
    assert entry.file_size == len(payload)
    assert os_path_isfile(entry.file_path)
    assert not os_path_isfile(entry.file_path + local_cache._PART_SUFFIX)
    assert entry.cached_at is not None


def test_download_entry_resumes_from_part_file(db, tmp_path, monkeypatch):
    from backend.emby_server.mounts import PlayTarget

    payload = b"z" * 4096
    item = _make_item(db, size=len(payload))
    _write_config(db, dir=str(tmp_path))
    entry = local_cache.enqueue(db, item)
    part = local_cache._dest_path(str(tmp_path), item) + local_cache._PART_SUFFIX
    with open(part, "wb") as f:
        f.write(payload[:1000])                  # 断点：已下 1000 字节
    monkeypatch.setattr(local_cache.mount_lib, "resolve_play_target",
                        lambda path, _db, library=None: PlayTarget("url", "https://fake/x.mkv", {}))
    seen = []
    monkeypatch.setattr(local_cache, "_open_remote_stream",
                        _fake_opener_factory([payload], seen=seen))

    assert local_cache.download_entry(db, entry.id) == "ready"
    assert seen == [1000]                        # 续传时带上了 offset
    db.refresh(entry)
    assert entry.file_size == len(payload)       # 不是 1000+4096（追加而不是覆盖）


def test_download_entry_retries_then_fails(db, tmp_path, monkeypatch):
    from backend.emby_server.mounts import PlayTarget

    item = _make_item(db)
    _write_config(db, dir=str(tmp_path))
    entry = local_cache.enqueue(db, item)
    monkeypatch.setattr(local_cache.mount_lib, "resolve_play_target",
                        lambda path, _db, library=None: PlayTarget("url", "https://fake/x.mkv", {}))

    def _boom(url, headers, offset):
        raise local_cache._RemoteError("源站返回 404")

    monkeypatch.setattr(local_cache, "_open_remote_stream", _boom)
    for attempt in (1, 2):                      # 额度内：回到 pending 继续排队
        assert local_cache.download_entry(db, entry.id) == "failed"
        db.refresh(entry)
        assert entry.state == "pending"
        assert "404" in entry.last_error
    assert local_cache.download_entry(db, entry.id) == "failed"
    db.refresh(entry)
    assert entry.state == "failed"              # 超过 MAX_ATTEMPTS：放弃


def test_download_entry_skips_when_disabled_or_local_source(db, tmp_path, monkeypatch):
    from backend.emby_server.mounts import PlayTarget

    item = _make_item(db)
    _write_config(db, dir=str(tmp_path))
    entry = local_cache.enqueue(db, item)

    _write_config(db, enabled=False, dir=str(tmp_path))
    assert local_cache.download_entry(db, entry.id) == "disabled"
    db.refresh(entry)
    assert entry.state == "pending"             # 只是没启用，不算失败

    _write_config(db, dir=str(tmp_path))
    monkeypatch.setattr(local_cache.mount_lib, "resolve_play_target",
                        lambda path, _db, library=None: PlayTarget("local", "/local/a.mkv", {}))
    assert local_cache.download_entry(db, entry.id) == "skipped"


def test_claim_next_orders_by_priority(db):
    a = _make_item(db, name="先入队但优先级低")
    b = _make_item(db, name="点播的")
    _write_config(db)
    entry_a = local_cache.enqueue(db, a, priority=local_cache.HOT_PRIORITY)
    entry_b = local_cache.enqueue(db, b, priority=local_cache.PLAY_PRIORITY)
    assert local_cache.claim_next(db) == entry_b.id   # 点播的先下


def test_playback_busy_window(db):
    user = _make_user(db)
    item = _make_item(db)
    assert local_cache.playback_busy(db) is False
    _make_session(db, item, user)                    # 正在播（未结束、刚上报过）
    assert local_cache.playback_busy(db) is True
    row = db.query(em.PlaybackSession).first()
    row.ended_at = datetime.now()
    db.commit()
    assert local_cache.playback_busy(db) is False    # 已结束
    row.ended_at = None
    row.last_update_at = datetime.now() - timedelta(seconds=9999)
    db.commit()
    assert local_cache.playback_busy(db) is False    # 陈旧会话（客户端异常退出）不算


def test_byte_limiter_paces_but_never_blocks_unlimited(db):
    unlimited = local_cache._ByteLimiter(0)          # 0 = 不限速
    start = time.monotonic()
    unlimited.take(100 * 1024 * 1024)
    assert time.monotonic() - start < 0.5

    limited = local_cache._ByteLimiter(8192)         # 8KB/s
    start = time.monotonic()
    limited.take(8192 + 4096)                        # 超出初始额度：要睡够 ~0.5s
    assert 0.3 < time.monotonic() - start < 5
    limited.set_rate(0)                              # 播放结束后可以放开
    start = time.monotonic()
    limited.take(100 * 1024 * 1024)
    assert time.monotonic() - start < 0.5


# ==================== 7. worker 轮次 ====================

def test_worker_run_once_disabled_is_noop(db):
    counts = local_cache_worker.run_once(db=db)
    assert counts["enabled"] is False
    assert counts["claimed"] == 0
    assert counts["queued"] == 0


def test_worker_run_once_enqueues_hot_and_downloads(db, tmp_path, monkeypatch):
    from backend.emby_server.mounts import PlayTarget

    user = _make_user(db)
    payload = b"w" * 2048
    hot = _make_item(db, size=len(payload))
    for i in range(4):
        _make_session(db, hot, user, key=f"h{i}")
    _write_config(db, dir=str(tmp_path))
    monkeypatch.setattr(local_cache.mount_lib, "resolve_play_target",
                        lambda path, _db, library=None: PlayTarget("url", "https://fake/x.mkv", {}))
    monkeypatch.setattr(local_cache, "_open_remote_stream",
                        _fake_opener_factory([payload]))

    counts = local_cache_worker.run_once(db=db, hot_batch=5)
    assert counts["enabled"] is True
    assert counts["hot"] == 1 and counts["queued"] == 1
    assert counts["claimed"] == 1 and counts["ready"] == 1
    entry = db.query(em.LocalCacheEntry).one()
    assert entry.state == "ready"
    assert os_path_isfile(entry.file_path)
    # 第二轮：已缓存，不再入队、无活可干
    counts2 = local_cache_worker.run_once(db=db, hot_batch=5)
    assert counts2["claimed"] == 0 and counts2["queued"] == 0


def test_worker_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(local_cache_worker, "run_once", lambda *a, **k: {"enabled": False})
    try:
        assert local_cache_worker.start_local_cache_worker() is True
        assert local_cache_worker.start_local_cache_worker() is True  # 幂等
    finally:
        local_cache_worker.stop_local_cache_worker()
    assert local_cache_worker._worker_thread is None


# ==================== 辅助断言 ====================

def os_path_isfile(path) -> bool:
    return bool(path) and os.path.isfile(path)
