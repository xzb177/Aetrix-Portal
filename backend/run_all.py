"""合并容器启动器：API + Worker + EA 三进程同容器。

设计：
- 三个子进程：serve.py（API:8000）、backend.worker（扫描）、emby_api.main（EA:8001）
- SIGTERM/SIGINT 转发给所有子进程，优雅退出
- 任一子进程异常退出则记录日志；API 或 EA 退出视为致命，整个容器退出（让 Docker 重启）
  worker 退出则尝试重启最多 3 次（扫描任务可恢复；超过则整容器退出让 Docker 重启）
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

# 分离架构的流节点角色（AETRIX_ROLE=stream）：只起 EA 出流进程，
# 不起 API / worker / 后台任务。无状态（只读主库 + 本地缓存），可横向扩展。
# 由 docker-compose.stream-node.yml / deploy-streaming-node.sh 使用。
ROLE_CHILDREN = {
    "stream": ["ea"],
}
ROLE_CRITICAL = {
    "stream": {"ea"},
}

# 各子进程的 AETRIX_ROLE（不在表里的子进程沿用容器环境变量）。
#
# api 必须显式声明。容器 env 是 AETRIX_ROLE=all，而 main.py 只把 "api" 认成 API 角色
# （_is_api_role = _role == "api"）：all 会被当成「单体模式」，于是 serve.py 这个子进程
# 也在 lifespan 里把 janitor / enrich_worker / reminders / auto_scan /
# db_backup / chase_new 整套后台任务起一遍 —— 而 backend.worker 子进程同样起一套。
# 结果是同一套后台任务跑两份：补全 worker 变成 2×ENRICH_WORKERS 线程、两个互不相通的
# TMDB 令牌桶互相打架（容器日志里「补全 worker 启动」出现两次），扫描队列也一直停在
# 单体模式的进程内队列上，v2.41 的 api/worker 拆分从未真正生效。
#
# 声明成 api 之后，两层行为都回到拆分的本意：
#   1) main.py 的 `if not _is_api_role` 分支全部跳过，后台任务只由 worker 进程承担
#      （worker.py 的启动清单与 main.py 逐条对应，另加 Redis 扫描队列消费）；
#   2) scan_queue 走 API 分支：enqueue 推 Redis 交给 worker 执行，而不是在 API 进程里
#      就地起扫描线程（进程内队列是单体模式的旧行为）。
#
# worker / ea 不覆盖：只有 "api" 会被特殊对待 —— worker 靠「AETRIX_ROLE != api」走
# 进程内队列，正是它需要的；ea（emby_api）整棵树不读这个变量。
CHILD_ROLE = {"api": "api"}

procs = {}


def log(msg):
    print("[run_all] " + str(msg), flush=True)


def start(name):
    cmd = CHILDREN[name]
    env = os.environ.copy()
    role = CHILD_ROLE.get(name)
    if role:
        env["AETRIX_ROLE"] = role
    # 有效角色打进日志：上一次「三个子进程共用一个 all」正是从日志上看不出来的
    log("start %s: %s (AETRIX_ROLE=%s)" % (
        name, " ".join(cmd), env.get("AETRIX_ROLE") or "<未设置>"))
    procs[name] = subprocess.Popen(cmd, cwd="/app", env=env)


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

    role = os.environ.get("AETRIX_ROLE", "")
    wanted = ROLE_CHILDREN.get(role, list(CHILDREN))
    critical = ROLE_CRITICAL.get(role, CRITICAL)
    if wanted != list(CHILDREN):
        log("role %r: only starting %s" % (role, ",".join(wanted)))
    for name in wanted:
        start(name)

    worker_restarts = 0
    while True:
        time.sleep(5)
        for name, p in list(procs.items()):
            rc = p.poll()
            if rc is not None:
                log("%s exited (rc=%s)" % (name, rc))
                if name in critical:
                    log("%s is critical, exiting container" % name)
                    stop_all()
                    sys.exit(1)
                if worker_restarts < 3:
                    worker_restarts += 1
                    log("restarting worker (%d/3)..." % worker_restarts)
                    start(name)
                else:
                    log("worker already restarted 3 times, exiting container")
                    stop_all()
                    sys.exit(1)


if __name__ == "__main__":
    main()
