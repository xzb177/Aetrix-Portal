# -*- coding: utf-8 -*-
"""有上限的外部进程 / 阻塞调用（探测链路专用，v2.53 探测 worker 重构）。

为什么需要：远程挂载（rclone/115/WebDAV 的 FUSE）挂死时，

- ``subprocess.run(timeout=…)`` 超时后只 ``kill()`` **直接子进程**，然后无限期
  ``wait()``。子进程卡在不可中断 IO（D 状态）时 SIGKILL 要等 IO 返回才生效，
  ``wait()`` 就陪着一起卡死；被包了一层（ionice/nice/sh）时孙进程还会变成孤儿；
- ``os.path.isfile / getsize`` 这类同步文件系统调用在挂死的 FUSE 上同样永不返回，
  而且发生在 Python 线程里，没有任何办法打断。

这里提供三件东西：

- :func:`bounded_run`：``subprocess.run`` 的替身。新会话（独立进程组）启动，超时
  ``killpg(SIGKILL)`` 整组；之后最多再等 ``KILL_GRACE_SEC``，还收不回就把进程交给
  后台收尸线程，**调用方立刻拿到 TimeoutExpired**，worker 槽位不被吃掉；
- :func:`deadline`：线程局部的「本条目总预算」。在它里面调用的 :func:`bounded_run`
  自动取 min(自己的 timeout, 剩余预算)，一条目串起的多跳探测（Range → 双 Range →
  自由 seek → MediaInfo）合计也不会超出预算；
- :func:`call_with_timeout`：把一个可能卡死的同步调用丢进守护线程，超时就放弃等待
  （线程留在后台，自生自灭），抛 :class:`CallTimeout`。
"""
from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: SIGKILL 之后最多再等多久收尸（秒）；收不回（D 状态）就交给后台线程
KILL_GRACE_SEC = 2.0

_local = threading.local()

# 被放弃的进程 / 线程计数（运维指标：持续上涨说明某个挂载在 D 状态里堆进程）
_abandoned_lock = threading.Lock()
_abandoned = {"procs": 0, "threads": 0}


def abandoned_counts() -> dict:
    with _abandoned_lock:
        return dict(_abandoned)


def _bump(key: str) -> None:
    with _abandoned_lock:
        _abandoned[key] += 1


@contextlib.contextmanager
def deadline(seconds: Optional[float]):
    """在当前线程上设一个总预算（秒）；嵌套时取更紧的那个。"""
    prev = getattr(_local, "deadline", None)
    if seconds is not None and seconds > 0:
        new = time.monotonic() + float(seconds)
        _local.deadline = new if prev is None else min(prev, new)
    try:
        yield
    finally:
        _local.deadline = prev


def remaining(default: Optional[float] = None) -> Optional[float]:
    """当前线程剩余预算（秒）；没设预算返回 ``default``。"""
    dl = getattr(_local, "deadline", None)
    if dl is None:
        return default
    return dl - time.monotonic()


def effective_timeout(timeout: Optional[float]) -> Optional[float]:
    rem = remaining()
    if rem is None:
        return timeout
    rem = max(0.05, rem)
    return rem if timeout is None else min(float(timeout), rem)


def timeout_count() -> int:
    """当前线程里 :func:`bounded_run` 累计超时次数（调用方前后相减判断「这次是不是超时」）。"""
    return int(getattr(_local, "timeouts", 0) or 0)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _reap_later(proc: subprocess.Popen) -> None:
    def _reap():
        try:
            proc.wait()
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_reap, name="proc-reaper", daemon=True).start()


def bounded_run(cmd, timeout: Optional[float] = None, text: bool = True,
                **_ignored) -> subprocess.CompletedProcess:
    """``subprocess.run(cmd, capture_output=True, text=…, timeout=…)`` 的有上限替身。

    超时抛 ``subprocess.TimeoutExpired``（与 ``subprocess.run`` 同口径，调用方的
    ``except TimeoutExpired`` 不用改）。保证调用方最多阻塞 timeout + KILL_GRACE_SEC。
    """
    timeout = effective_timeout(timeout)
    popen_kw = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                "stdin": subprocess.DEVNULL, "text": text}
    if os.name == "posix":
        popen_kw["start_new_session"] = True  # 独立进程组：超时整组杀（含 ionice/sh 包装）
    proc = subprocess.Popen(cmd, **popen_kw)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _local.timeouts = timeout_count() + 1
        _kill_group(proc)
        # 管道里可能还有数据；再给一个短宽限收尸
        try:
            proc.communicate(timeout=KILL_GRACE_SEC)
        except Exception:  # noqa: BLE001 — 收不回：多半是 D 状态，交给后台线程
            _bump("procs")
            logger.warning("子进程 %s 被 SIGKILL 后 %.0fs 仍未退出（挂载 D 状态？），已放弃等待",
                           proc.pid, KILL_GRACE_SEC)
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:  # noqa: BLE001
                    pass
            _reap_later(proc)
        raise subprocess.TimeoutExpired(cmd, timeout)
    except BaseException:
        _kill_group(proc)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


class CallTimeout(TimeoutError):
    """:func:`call_with_timeout` 超时（被调函数仍在后台线程里跑，结果被丢弃）。"""


def call_with_timeout(fn: Callable[..., Any], timeout: float, *args, **kwargs) -> Any:
    """在守护线程里跑 ``fn``，最多等 ``timeout`` 秒。

    超时抛 :class:`CallTimeout`；``fn`` 抛的异常原样抛给调用方。
    被放弃的线程不能被杀，只能让它自己结束——所以 ``fn`` 不能持有调用方的
    DB session 或锁（要用 DB 就在 ``fn`` 里自己开 session）。
    """
    box: dict = {}
    done = threading.Event()
    parent_deadline = getattr(_local, "deadline", None)

    def _run():
        _local.deadline = parent_deadline
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            done.set()

    t = threading.Thread(target=_run, name="bounded-call", daemon=True)
    t.start()
    if not done.wait(max(0.01, float(timeout))):
        _bump("threads")
        raise CallTimeout(f"{getattr(fn, '__name__', 'call')} 超过 {timeout:.0f}s 未返回")
    if "error" in box:
        raise box["error"]
    return box.get("result")
