"""探测缓存 + 同文件任务合并（v2.48.0）

真正贵的那一步是 ffprobe：要么起进程，要么向网盘发 Range 请求。同一份文件被反复
排队时（重试撞上复制、同一份文件挂在两个库下），这些成本是**同一份字节的同一次**。
所以：

- **缓存**：键 = path + size + mtime。文件一改键就变，命中的一定是同一份字节；
  只缓存干净结果——缓存一个 404 等于把这个文件永久判死。
- **合并**：同一批里指向同一个文件的条目只探一次，结果镜像给其余条目（连内封轨道
  一起），没探成的时候退回 pending 而不是停在 probing 上。

不碰网络、不起 ffprobe：``probe_metadata`` 全程打桩。
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import models as em
from backend.emby_server import probe_worker as pw
from backend.integrations import store


class _SessionProxy:
    """worker 自己 close 会话；测试共用一条连接，让它别把用例的后半段带走"""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    store.invalidate()
    yield session
    store.invalidate()
    session.close()


@pytest.fixture()
def probe_env(db, monkeypatch, tmp_path):
    """探测器环境：ffprobe 打桩、单线程跑、缓存干净、熔断器不参与"""
    calls = []

    def fake_probe(path, headers=None, size=0, container=""):
        calls.append(path)
        return {
            "duration_ticks": 12_345, "size": size or 4096, "bitrate": 8_000,
            "width": 1920, "height": 1080, "video_codec": "h264", "audio_codec": "aac",
            "audio_languages": "chi", "subtitle_languages": "",
            "streams": [{"stream_index": 0, "stream_type": "video", "codec": "h264"}],
        }

    monkeypatch.setattr(pw, "SessionLocal", lambda: _SessionProxy(db))
    monkeypatch.setattr(pw, "PROBE_WORKERS", 1)
    monkeypatch.setattr(pw, "probe_metadata", fake_probe)
    monkeypatch.setattr(pw, "needs_probe", lambda *a, **k: True)
    monkeypatch.setattr(pw, "breaker_is_tripped", lambda: False)
    monkeypatch.setattr(pw, "breaker_record_success", lambda: None)
    monkeypatch.setattr(pw, "breaker_record_quota_error", lambda: None)
    monkeypatch.setattr(pw, "resolve_play_target",
                        lambda path, _db: type("T", (), {"value": path,
                                                        "headers": {}})())
    pw.clear_probe_cache()
    yield db, calls
    pw.clear_probe_cache()


def _lib(db, guid, name):
    row = em.Library(guid=guid, name=name, collection_type="movies")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _item(db, lib, guid, path, size=4096, status="pending"):
    row = em.MediaItem(guid=guid, library_id=lib.id, item_type="movie", name=guid,
                       file_path=path, size=size, probe_status=status)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _video(tmp_path, name="a.mkv", size=4096):
    path = tmp_path / name
    path.write_bytes(b"0" * size)
    return str(path)


# ==================== 缓存键：path + size + mtime ====================

def test_same_file_yields_the_same_key(tmp_path):
    path = _video(tmp_path)
    assert pw.probe_cache_key(path, 4096) == pw.probe_cache_key(path, 4096)


def test_changed_file_yields_a_new_key(tmp_path):
    """mtime/size 变了就是另一份字节 → 必须重新探，不能拿旧结果糊弄"""
    path = _video(tmp_path)
    before = pw.probe_cache_key(path, 4096)
    time.sleep(0.01)
    _video(tmp_path, size=8192)
    os.utime(path, (time.time() + 5, time.time() + 5))

    assert pw.probe_cache_key(path, 8192) != before


def test_key_differs_by_path(tmp_path):
    a, b = _video(tmp_path, "a.mkv"), _video(tmp_path, "b.mkv")
    assert pw.probe_cache_key(a, 4096) != pw.probe_cache_key(b, 4096)


def test_remote_paths_key_on_size_only():
    """远程挂载拿不到 mtime，只能退化到 path+size（那边唯一的文件标识）"""
    assert pw.probe_cache_key("mount://1/movie.mkv", 10) == \
        pw.probe_cache_key("mount://1/movie.mkv", 10)
    assert pw.probe_cache_key("mount://1/movie.mkv", 10) != \
        pw.probe_cache_key("mount://1/movie.mkv", 11)


# ==================== 缓存内容：只留干净结果，且返回副本 ====================

def test_errors_are_never_cached():
    key = "path|1|2"
    pw.probe_cache_put(key, {"_error": "http_404", "_error_detail": "没找到"})

    assert pw.probe_cache_get(key) is None


def test_cached_info_is_copied_not_shared():
    """返回副本：调用方后续改 info（比如填 streams）不能把缓存里的改掉"""
    key = "path|1|3"
    original = {"duration_ticks": 10, "streams": []}
    pw.probe_cache_put(key, original)

    first = pw.probe_cache_get(key)
    first["duration_ticks"] = 999
    first["streams"].append("x")

    again = pw.probe_cache_get(key)
    assert again["duration_ticks"] == 10
    assert again["streams"] == []


def test_cache_respects_ttl(monkeypatch):
    monkeypatch.setattr(pw, "PROBE_CACHE_TTL_SEC", 0.05)
    key = "path|1|4"
    pw.probe_cache_put(key, {"duration_ticks": 10})

    time.sleep(0.12)

    assert pw.probe_cache_get(key) is None


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(pw, "PROBE_CACHE_MAX", 16)
    for i in range(64):
        pw.probe_cache_put(f"path|{i}|0", {"duration_ticks": i})

    with pw._probe_cache_lock:
        size = len(pw._probe_cache)
    assert size == 16
    # 最早的被挤掉了——LRU 语义，不是「谁最后写谁留下」
    assert pw.probe_cache_get("path|0|0") is None
    assert pw.probe_cache_get("path|63|0") is not None


# ==================== 缓存真的省掉一次 ffprobe ====================

def test_second_round_on_the_same_file_hits_the_cache(probe_env, tmp_path):
    db, calls = probe_env
    lib = _lib(db, "g1", "电影库")
    path = _video(tmp_path)
    first = _item(db, lib, "m1", path)
    second = _item(db, lib, "m2", path)

    pw.run_once(db=db, limit=10)
    assert len(calls) == 1
    db.expire_all()
    db.refresh(first)
    db.refresh(second)
    assert first.probe_status == "done" and second.probe_status == "done"

    # 第二轮：文件一个字节没变 → 直接复用，不再调 ffprobe
    second.probe_status = "pending"
    db.commit()
    counts = pw.run_once(db=db, limit=10)

    assert counts["claimed"] == 1
    assert counts["merged"] == 0, "同一批里已经合并过了，这一轮只该有一个待探条目"
    assert len(calls) == 1, "同一份字节不该再探一次"
    db.expire_all()
    db.refresh(second)
    assert second.probe_status == "done"
    assert second.duration_ticks == 12_345


def test_cache_does_not_survive_a_file_change(probe_env, tmp_path):
    """文件被替换（新 mtime）→ 缓存失效，重新探"""
    db, calls = probe_env
    lib = _lib(db, "g1", "电影库")
    path = _video(tmp_path)
    item = _item(db, lib, "m1", path)

    pw.run_once(db=db, limit=10)
    assert len(calls) == 1

    _video(tmp_path, size=9000)
    os.utime(path, (time.time() + 10, time.time() + 10))
    item.probe_status = "pending"
    db.commit()

    pw.run_once(db=db, limit=10)

    assert len(calls) == 2, "文件换过内容，必须重新探而不是拿缓存里的旧时长"


# ==================== 同文件任务合并 ====================

def test_duplicate_paths_are_probed_once_and_mirrored(probe_env, tmp_path):
    """同一份文件挂在两个库下 → 一次 ffprobe，两个条目都拿到时长和轨道"""
    db, calls = probe_env
    lib_a = _lib(db, "g1", "片库")
    lib_b = _lib(db, "g2", "备份库")
    path = _video(tmp_path)
    first = _item(db, lib_a, "m1", path)
    second = _item(db, lib_b, "m2", path)

    counts = pw.run_once(db=db, limit=10)

    assert len(calls) == 1, "同一个文件只该探一次"
    assert counts["claimed"] == 2
    assert counts["merged"] == 1
    db.expire_all()
    db.refresh(first)
    db.refresh(second)
    assert (first.probe_status, second.probe_status) == ("done", "done")
    assert first.duration_ticks == second.duration_ticks == 12_345
    # 内封轨道也要跟着镜像过去，否则「媒体信息」页在第二个库下是空的
    for row in (first, second):
        streams = db.query(em.MediaStream).filter(em.MediaStream.item_id == row.id).all()
        assert [s.codec for s in streams] == ["h264"]


def test_different_sizes_are_not_merged(probe_env, tmp_path):
    """同名但大小不同 = 不是同一份字节，各探各的"""
    db, calls = probe_env
    lib = _lib(db, "g1", "电影库")
    path = _video(tmp_path)
    _item(db, lib, "m1", path, size=4096)
    _item(db, lib, "m2", path, size=4097)

    counts = pw.run_once(db=db, limit=10)

    assert counts["merged"] == 0
    assert len(calls) == 2


def test_mirror_without_a_result_returns_shadows_to_pending(probe_env, tmp_path):
    """代表条目没探成（被抢走 / 熔断）时不能镜像，影子条目退回 pending

    停在 ``probing`` 上就等于永久卡死：既不会被下一轮抢到（它只捞 pending），
    也没人会再动它。
    """
    db, _calls = probe_env
    lib = _lib(db, "g1", "电影库")
    path = _video(tmp_path)
    primary = _item(db, lib, "m1", path)
    shadow = _item(db, lib, "m2", path)

    pw._mirror_probe_result(primary.id, [shadow.id], "skipped")

    db.expire_all()
    db.refresh(shadow)
    assert shadow.probe_status == "pending"


def test_merge_keeps_claim_order(probe_env, tmp_path):
    """合并不能打乱抢单顺序：新片（高优先级）必须仍然先被真正探测"""
    db, calls = probe_env
    lib = _lib(db, "g1", "电影库")
    path = _video(tmp_path)
    _item(db, lib, "m1", path)
    high = _item(db, lib, "m2", _video(tmp_path, "b.mkv"))
    high.probe_priority = pw.BOOST_PRIORITY
    db.commit()

    counts = pw.run_once(db=db, limit=10)

    assert counts["merged"] == 0
    assert calls and calls[0].endswith("b.mkv"), "插队的条目应该第一个探"

# ==================== 环境变量：写错不能把 worker 打死 ====================

def test_env_int_falls_back_and_keeps_a_floor(monkeypatch):
    """环境变量写成非法值时回落默认，而不是让整个 worker 导入失败

    这些常量是模块级的：``int("abc")`` 会直接抛，整个 Phase 2 探测就此不再启动。
    """
    monkeypatch.setenv("PW_T", "abc")
    assert pw._env_int("PW_T", 60, 10) == 60
    monkeypatch.setenv("PW_T", "")
    assert pw._env_int("PW_T", 60, 10) == 60
    monkeypatch.setenv("PW_T", "5")
    assert pw._env_int("PW_T", 60, 10) == 10, "下限要压住（重试间隔不能是 0）"
    monkeypatch.setenv("PW_T", "120")
    assert pw._env_int("PW_T", 60, 10) == 120
    monkeypatch.delenv("PW_T")
    assert pw._env_int("PW_T", 60, 10) == 60


def test_tuning_defaults_match_the_documented_values():
    assert pw.STABILITY_RECENT_SEC == 60
    assert pw.STABILITY_RETRY_SEC == 60
    assert pw.PROBE_CACHE_TTL_SEC == 900
    assert pw.PROBE_CACHE_MAX == 512
