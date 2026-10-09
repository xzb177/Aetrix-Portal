# -*- coding: utf-8 -*-
"""Hark 6链路第4项：后台侦测优化——复现测试。

4 个问题（Hark 报告）：
1. ffprobe 没设 -probesize / -analyzeduration → 探测慢
2. 播放时探测并发不降 → 抢播放链路资源（用户红线）
3. 空队列固定间隔轮询 → 没有退避休眠
4. 每次提交强制等 0.5s（PROBE_MIN_INTERVAL_SEC）→ 吞吐硬上限

约定：
- 测试环境 SQLite，os.environ 必须在 import backend 之前设置（照抄下面头部）。
- init_db() + module 级 fixture 建表（全量跑时不受执行顺序影响）。
- 修复后应新增的 API（测试先行，实现后补）：
  - probe_worker.idle_backoff_sleep(consecutive_idle, base=None, cap=None) -> float
    空队列退避：base * 2**consecutive_idle，上限 cap；默认取
    PROBE_IDLE_SLEEP_SEC / PROBE_IDLE_MAX_SLEEP_SEC。
  - probe_worker.has_active_playback(db=None) -> bool
    是否有未结束的播放会话（PlaybackSession.ended_at IS NULL）。
  - probe_worker.effective_workers(playback_active, base=None, playback_workers=None) -> int
    有播放时降为 min(playback_workers, base)，否则 base；默认取
    PROBE_WORKERS / PROBE_PLAYBACK_WORKERS。
  - probe_worker.SubmitPacer(min_interval, burst)：批量提交节流器
    .wait_seconds(now) -> float；.mark_submitted(now)；.mark_waited()
    语义：每 burst 次提交内不等待；burst 用完后按 min_interval 间隔；
    调用 mark_waited() 后 burst 计数清零（即等待一次后又可以连发 burst 个）。
  - scanner._ffprobe 的命令里必须含 "-probesize" 和 "-analyzeduration"。
"""

import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import types
import uuid
from datetime import datetime

import pytest

from backend.database import SessionLocal, init_db
from backend.emby_server import probe_worker
from backend.emby_server import scanner
from backend.emby_server import models as em

init_db()


def _guid():
    return uuid.uuid4().hex


@pytest.fixture(autouse=True, scope="module")
def _tables():
    from backend.database import Base
    from backend import models as _base_models  # noqa: F401
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()
    yield


@pytest.fixture()
def user():
    from backend import models as base_models
    db = SessionLocal()
    u = base_models.WebUser(username=f"p4_{_guid()[:12]}", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    uid = u.id
    db.close()
    yield uid
    db = SessionLocal()
    db.query(em.PlaybackSession).filter(em.PlaybackSession.user_id == uid).delete(
        synchronize_session=False)
    db.query(base_models.WebUser).filter(base_models.WebUser.id == uid).delete()
    db.commit()
    db.close()


class TestFfprobeFlags:
    """问题 1：ffprobe 必须带 -probesize / -analyzeduration。"""

    def test_ffprobe_cmd_has_probesize_and_analyzeduration(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(scanner, "shutil_which", lambda cmd: "/usr/bin/ffprobe")

        def fake_run(cmd, timeout):
            captured["cmd"] = list(cmd)
            return types.SimpleNamespace(stdout="{}", stderr="")

        monkeypatch.setattr(scanner, "_run_probe_cmd", fake_run)
        scanner._ffprobe("/tmp/p4_test.mkv")
        cmd = captured["cmd"]
        assert "-probesize" in cmd, f"ffprobe 命令缺 -probesize: {cmd}"
        assert "-analyzeduration" in cmd, f"ffprobe 命令缺 -analyzeduration: {cmd}"
        # 值必须紧跟在 flag 后面且为正数
        ps = cmd[cmd.index("-probesize") + 1]
        ad = cmd[cmd.index("-analyzeduration") + 1]
        assert int(ps) > 0 and int(ad) > 0


class TestIdleBackoff:
    """问题 3：空队列退避休眠（指数退避 + 上限）。"""

    def test_exponential_growth(self):
        assert probe_worker.idle_backoff_sleep(0, base=5.0, cap=300.0) == 5.0
        assert probe_worker.idle_backoff_sleep(1, base=5.0, cap=300.0) == 10.0
        assert probe_worker.idle_backoff_sleep(2, base=5.0, cap=300.0) == 20.0
        assert probe_worker.idle_backoff_sleep(3, base=5.0, cap=300.0) == 40.0

    def test_capped(self):
        assert probe_worker.idle_backoff_sleep(100, base=5.0, cap=300.0) == 300.0
        assert probe_worker.idle_backoff_sleep(10, base=5.0, cap=60.0) == 60.0

    def test_uses_config_defaults(self):
        assert probe_worker.idle_backoff_sleep(0) == probe_worker.PROBE_IDLE_SLEEP_SEC
        assert probe_worker.idle_backoff_sleep(10 ** 6) == probe_worker.PROBE_IDLE_MAX_SLEEP_SEC


class TestPlaybackAwareConcurrency:
    """问题 2：有播放时降低探测并发（用户红线：后台不能抢播放链路）。"""

    def test_no_playback_keeps_base(self):
        assert probe_worker.effective_workers(False, base=4, playback_workers=1) == 4

    def test_playback_reduces_concurrency(self):
        assert probe_worker.effective_workers(True, base=4, playback_workers=1) == 1

    def test_playback_workers_never_exceeds_base(self):
        assert probe_worker.effective_workers(True, base=2, playback_workers=8) == 2

    def test_uses_config_defaults(self):
        assert probe_worker.effective_workers(False) == probe_worker.PROBE_WORKERS
        assert probe_worker.effective_workers(True) == min(
            probe_worker.PROBE_PLAYBACK_WORKERS, probe_worker.PROBE_WORKERS)

    def test_has_active_playback(self, user):
        # 测试库是共享 SQLite 文件，其他测试模块可能残留 PlaybackSession 行，
        # 所以不断言初始为空，只验证「创建→True / 结束→恢复原值」的跃迁
        db = SessionLocal()
        try:
            before = probe_worker.has_active_playback(db)
            ps = em.PlaybackSession(session_key=_guid(), user_id=user,
                                    device_name="d", client_name="c")
            db.add(ps)
            db.commit()
            assert probe_worker.has_active_playback(db) is True
            ps.ended_at = datetime.now()
            db.commit()
            assert probe_worker.has_active_playback(db) is before
        finally:
            db.close()


class TestSubmitPacer:
    """问题 4：批量提交节流——解除「每提交必等 0.5s」的硬上限。"""

    def test_burst_submits_do_not_wait(self):
        p = probe_worker.SubmitPacer(min_interval=0.5, burst=4)
        now = 1000.0
        for _ in range(4):
            assert p.wait_seconds(now) == 0.0
            p.mark_submitted(now)

    def test_wait_after_burst_exhausted(self):
        p = probe_worker.SubmitPacer(min_interval=0.5, burst=4)
        now = 1000.0
        for _ in range(4):
            p.mark_submitted(now)
        assert p.wait_seconds(now) == pytest.approx(0.5)

    def test_wait_resets_burst(self):
        p = probe_worker.SubmitPacer(min_interval=0.5, burst=2)
        now = 1000.0
        p.mark_submitted(now)
        p.mark_submitted(now)
        assert p.wait_seconds(now) == pytest.approx(0.5)
        p.mark_waited()
        assert p.wait_seconds(now + 0.5) == 0.0
        p.mark_submitted(now + 0.5)
        assert p.wait_seconds(now + 0.5) == 0.0
        p.mark_submitted(now + 0.5)
        assert p.wait_seconds(now + 0.5) == pytest.approx(0.5)

    def test_zero_interval_never_waits(self):
        p = probe_worker.SubmitPacer(min_interval=0.0, burst=1)
        now = 1000.0
        for _ in range(5):
            assert p.wait_seconds(now) == 0.0
            p.mark_submitted(now)
