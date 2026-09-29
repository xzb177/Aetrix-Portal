"""合并容器启动器：API + Worker + EA 三进程同容器。

设计：
- 三个子进程：serve.py（API:8000）、backend.worker（扫描）、emby_api.main（EA:8001）
- SIGTERM/SIGINT 转发给所有子进程，优雅退出
- 任一子进程异常退出则记录日志；API 或 EA 退出视为致命，整个容器退出（让 Docker 重启）
  worker 退出则尝试重启一次（扫描任务可恢复）
"""
import os
import signal
import subprocess
import sys
import time

CHILDREN = {
    "api": [sys.executable, "serve.py"],
    "worker": [sys.executable, "-m", "backend.worker"],
    "ea": [sys.executable, "-m", "emby_api.main"],
}

# 致命进程：退出则整个容器退出
CRITICAL = {"api", "ea"}

procs = {}


def log(msg):
    print("[run_all] " + str(msg), flush=True)


def start(name):
    cmd = CHILDREN[name]
    log("start %s: %s" % (name, " ".join(cmd)))
    procs[name] = subprocess.Popen(cmd, cwd="/app", env=os.environ.copy())


def stop_all():
    log("stopping all children")
    for name, p in procs.items():
        if p.poll() is None:
            log("  -> %s (pid=%s) SIGTERM" % (name, p.pid))
            try:
                p.terminate()
            except Exception as e:
                log("  -> %s terminate failed: %s" % (name, e))
    deadline = time.time() + 15
    for name, p in procs.items():
        try:
            remaining = max(0, deadline - time.time())
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            log("  -> %s timeout, SIGKILL" % name)
            p.kill()


def main():
    def _handler(signum, frame):
        stop_all()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)

    for name in CHILDREN:
        start(name)

    worker_restarts = 0
    while True:
        time.sleep(5)
        for name, p in list(procs.items()):
            rc = p.poll()
            if rc is not None:
                log("%s exited (rc=%s)" % (name, rc))
                if name in CRITICAL:
                    log("%s is critical, exiting container" % name)
                    stop_all()
                    sys.exit(1)
                if worker_restarts < 1:
                    worker_restarts += 1
                    log("restarting worker...")
                    start(name)
                else:
                    log("worker already restarted once, exiting container")
                    stop_all()
                    sys.exit(1)


if __name__ == "__main__":
    main()
