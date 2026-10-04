"""ffprobe 跑完但没读出时长：**不是失败，是「时长未知但能播」

对应线上症状：2.6 万个文件（93% 在 MoviePilot 目录）探测失败，报错全是
「ffprobe 未返回有效时长」，重试 5 轮后集体 failed，用户端显示
「网络错误或者当前媒体库不存在该项目」——而文件其实存在且可访问。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.emby_server import probe_worker
from backend.emby_server import scanner


# ---------- 只有「文件真的不在了」才算永久失败 ----------

@pytest.mark.parametrize("code", ["not_found", "http_404", "http_410"])
def test_missing_file_is_the_only_permanent_failure(code):
    assert probe_worker._classify_failure(code) == probe_worker.KIND_PERMANENT


@pytest.mark.parametrize("code", ["http_400", "http_405", "http_415", "http_416",
                                  "http_401", "quota", "", None, "weird_new_code"])
def test_ambiguous_errors_must_not_kill_a_playable_file(code):
    """签名 URL 过期 / 网关回 415 / Range 被中间层改写，都会落到这些码。

    原来它们在 PERMANENT_ERRORS 里 = 第一次就判死。现在必须是 transient。
    """
    assert probe_worker._classify_failure(code) == probe_worker.KIND_TRANSIENT


def test_permanent_set_is_exactly_missing_file():
    assert probe_worker.PERMANENT_ERRORS == {"not_found", "http_404", "http_410"}


# ---------- 无时长 = 终态但不失败，且不进重试 ----------

class _Item:
    """够用的替身：_probe_one 只碰这几个字段"""

    def __init__(self, **kw):
        self.id = 1
        self.file_path = "/mnt/movie.mkv"
        self.library = None
        self.size = 0
        self.duration_ticks = None
        self.probe_status = "probing"
        self.probe_attempts = 0
        self.probe_priority = 0
        self.probe_next_retry_at = None
        self.last_probed_at = None
        self.__dict__.update(kw)


class _DB:
    def __init__(self, item):
        self._item = item
        self.commits = 0

    def query(self, *_a, **_k):
        return self

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return self._item

    def commit(self):
        self.commits += 1

    def delete(self, *_a, **_k):
        """_apply_probe_result 会先删掉旧的内封轨道再重建"""

    def add(self, *_a, **_k):
        pass

    def rollback(self):
        pass

    def flush(self):
        pass

    def close(self):
        pass


def _run_one(monkeypatch, info):
    item = _Item()
    db = _DB(item)
    monkeypatch.setattr(probe_worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(probe_worker, "needs_probe", lambda *a, **k: True)
    monkeypatch.setattr(probe_worker, "breaker_is_tripped", lambda: False)
    monkeypatch.setattr(probe_worker, "breaker_record_success", lambda: None)
    monkeypatch.setattr(probe_worker, "breaker_record_quota_error", lambda: None)
    monkeypatch.setattr(probe_worker, "resolve_play_target",
                        lambda *a, **k: type("T", (), {"value": "https://x/v.mkv",
                                                        "headers": {}})())
    monkeypatch.setattr(probe_worker, "probe_metadata", lambda *a, **k: info)
    result = probe_worker._probe_one(item.id)
    return item, result


def test_probe_ok_but_no_duration_is_not_failed(monkeypatch):
    """ffprobe 跑完了，只是没给出时长 → 记 probed_no_duration，不进重试"""
    item, result = _run_one(monkeypatch, {"size": 999, "streams": []})

    assert result == probe_worker.STATUS_NO_DURATION
    assert item.probe_status == probe_worker.STATUS_NO_DURATION
    # 关键：不计失败、不排重试——否则它会反复占满 worker 名额
    assert item.probe_attempts == 0
    assert item.probe_next_retry_at is None
    # 已探测过（避免每轮扫描重新排队），并保留探测到的文件大小
    assert item.last_probed_at is not None
    assert item.size == 999


def test_probe_with_duration_still_done(monkeypatch):
    # _apply_probe_result 会读这些键，给一份完整的（字段名与 scanner.probe_metadata 一致）
    full = {
        "size": 10, "duration_ticks": 1_000, "bitrate": 800, "width": 1920,
        "height": 1080, "video_codec": "HEVC", "audio_codec": "AAC",
        "audio_languages": [], "subtitle_languages": [], "streams": [],
    }
    item, result = _run_one(monkeypatch, full)
    assert result == "done"
    assert item.probe_status == "done"


def test_real_error_still_goes_through_fail_path(monkeypatch):
    """有 _error 的仍然走失败分类（404 永久、配额退避）"""
    item, result = _run_one(
        monkeypatch, {"_error": "http_404", "_error_detail": "文件不存在"})
    assert result == "failed"
    assert item.probe_status == "failed"


# ---------- 别让这批条目在每轮扫描里重新排队 ----------

def test_no_duration_status_is_not_requeued_every_scan():
    item = _Item(probe_status=probe_worker.STATUS_NO_DURATION,
                 last_probed_at=datetime.now(), size=500)
    # 同大小：已探过，不再探
    assert scanner.needs_probe(item, "/mnt/movie.mkv", 500) is False
    # 换源（大小变了）：重新排队
    assert scanner.needs_probe(item, "/mnt/movie.mkv", 900) is True


def test_explicit_boost_requeues_no_duration(monkeypatch):
    """用户点播放 = 「我要知道能不能放」：此时必须真的重新入队

    ``_claim_batch`` 只取 pending，所以只改优先级不改状态等于没插队。
    """
    class _Q:
        def __init__(self, items):
            self._items = items

        def filter(self, *a, **k):
            return self

        def all(self):
            return self._items

    item = _Item(probe_status=probe_worker.STATUS_NO_DURATION)
    db = _DB(item)
    assert probe_worker.boost_probe(db, item) is True
    assert item.probe_status == "pending"
    assert item.probe_attempts == 0


def test_boost_leaves_done_untouched():
    item = _Item(probe_status="done")
    db = _DB(item)
    assert probe_worker.boost_probe(db, item) is False
    assert item.probe_status == "done"


# ---------- 关键：这些条目必须**还能播**（需求 3） ----------

@pytest.fixture()
def db():
    """真会话（隔离的内存 SQLite）：``_item_dto`` 要查库，桩撑不住"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend import models as web_models
    from backend.emby_server import models as em

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    web_models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(em.Library(guid="lib-1", name="电影"))
    session.commit()
    yield session
    session.close()


def test_no_duration_item_is_still_playable(db):
    """时长未知 ≠ 不可播：媒体信息缺失不许影响播放地址的发放

    这是本次改动最容易漏掉的一条。探测状态只管媒体信息，管播放的是
    ``file_path``：PlaybackInfo 只在**没有 file_path** 时才发空 MediaSources
    （Emby 客户端的「无可播放源」）。时长读不出来时必须照样发地址，
    否则「不判死」这个修复只做了一半，用户照样点不开。
    """
    from backend.emby_server import api as emby_api
    from backend.emby_server import models as em

    row = em.MediaItem(
        guid="g-nodur", library_id=db.query(em.Library).first().id,
        item_type="movie", name="NoDuration.mkv", container="mkv",
        file_path="/media/NoDuration.mkv",
        probe_status=probe_worker.STATUS_NO_DURATION, last_probed_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    dto = emby_api._item_dto(row, "http://ea.test", None, db, full=True)
    sources = dto.get("MediaSources") or []
    assert len(sources) == 1, "时长未知也必须发得出播放源"
    assert sources[0]["Path"] == "/media/NoDuration.mkv"
    # 时长确实没有——``_strip_nulls`` 会把空值整键去掉，所以用户端看到的是
    # 「没有这个字段」而不是 0（0 会被当成「时长 0 秒」）。
    # 这不影响可播：播放地址照发。
    assert sources[0].get("RunTimeTicks") in (None, 0)
    assert dto.get("MediaSourceCount") == 1
