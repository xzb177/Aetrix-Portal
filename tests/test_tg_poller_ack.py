"""poller offset 必须在 update 处理完之后才推进（at-least-once），队列满时阻塞而不是丢弃。"""
from __future__ import annotations

import os
import queue
import sys
import threading

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
sys.path.insert(0, ".")

from backend.tg_bot import poller, router


def test_offset_saved_only_after_all_dispatched(monkeypatch):
    dispatched = []
    saved_when = []
    monkeypatch.setattr(poller, "_UPDATE_QUEUE", queue.Queue(maxsize=1))

    class _S:
        def close(self):
            pass

    import backend.database as dbmod
    monkeypatch.setattr(dbmod, "SessionLocal", lambda: _S())

    def slow_dispatch(db, u):
        threading.Event().wait(0.05)
        dispatched.append(u["update_id"])

    monkeypatch.setattr(router, "dispatch", slow_dispatch)
    t = threading.Thread(target=poller._worker_loop, daemon=True)
    t.start()
    updates = [{"update_id": i} for i in (10, 11, 12)]
    new_offset = poller._process_updates(
        updates, 10, save=lambda off: saved_when.append((off, list(dispatched))))
    poller._UPDATE_QUEUE.put(None)
    t.join(timeout=5)
    assert new_offset == 13
    assert sorted(dispatched) == [10, 11, 12], "队列满时不能丢 update"
    assert saved_when == [(13, sorted(dispatched))] or (
        saved_when[0][0] == 13 and sorted(saved_when[0][1]) == [10, 11, 12]
    ), "offset 必须在全部处理完之后才保存"
