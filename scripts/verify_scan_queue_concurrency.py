"""扫描队列并发验证：四个媒体库同时点扫描（真 HTTP + 真 WebDAV + 真日志）

这不是又一份冒烟测试，而是把线上那次日志审计的现场**复现一遍**再对比：

    四个媒体库在几秒内依次点「扫描」→ 旧行为是四个扫描任务同时打同一个 WebDAV，
    远端目录被重复 PROPFIND（审计里那条「同一路径每 5 秒一次」），CPU 打满、进度
    长时间停在 item_count=0。v2.27.0 按「远程挂载串行化」后，引用同一挂载的库排队跑。

脚本起一个**真的 WebDAV 服务**（真 PROPFIND / 真 207 multistatus、真网络延迟，并记录
每个请求的时刻与在飞并发），再通过**真的管理端 HTTP 接口**连点四个库的扫描，然后一边
轮询队列快照 / 媒体库列表（面板看到的同一份数据）、一边记录：

- 每次 POST 的响应（已启动 / 排队第几位 / 在等哪个挂载）；
- 每秒时间线：每个库的排队位置、阶段、已发现 / 已处理、当前目录；
- 应用日志（扫描出入队 / 开始 / 结束、远程列举次数）——与线上审计用的同一批日志；
- WebDAV 服务端日志：每个 PROPFIND 的时刻、路径、当时在飞请求与峰值；
- 结果对照：并发峰值、同一路径被列了几次、四个库的条目数与总耗时。

两种模式各跑一遍（各自独立进程，保证模块级开关是干净的），默认对比输出：

    python3 scripts/verify_scan_queue_concurrency.py                 # 升级前 vs 现在
    python3 scripts/verify_scan_queue_concurrency.py --mode legacy    # 只跑「队列关闭」
    python3 scripts/verify_scan_queue_concurrency.py --mode queue     # 只跑「队列开启」

退出码：任一模式的关键断言不成立就非 0（可直接当护栏跑）。
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 现场规模（够看出并发差异，又不至于让验证跑几分钟）----
FILES_PER_DIR = 20
REMOTE_LATENCY = 0.05          # 每次 PROPFIND 的服务端延迟（模拟远程端点的真实延迟）
# 远端目录用 ASCII 名：WebDAV 的 href 是百分号编码的，而非 ASCII 目录名会撞上
# 「自己也被列成自己的子项」的存量口径问题（与扫描队列无关，单独一条线去看）
DIRS = ["/dav/tv", "/dav/movies", "/dav/concerts"]
POLL_SECONDS = 0.25
RUN_TIMEOUT = 180


# ==================== 假的 WebDAV 服务（真 HTTP） ====================

class _WebDavState:
    """服务端观测点：请求日志、在飞并发、同一路径被列了几次"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.inflight = 0
        self.peak_inflight = 0
        self.requests: list[dict] = []
        self.per_path: dict[str, int] = {}

    def enter(self, method: str, path: str) -> None:
        with self.lock:
            self.inflight += 1
            self.peak_inflight = max(self.peak_inflight, self.inflight)
            self.per_path[path] = self.per_path.get(path, 0) + 1
            self.requests.append({
                "t": round(time.monotonic() - self.started, 3),
                "method": method,
                "path": path,
                "inflight": self.inflight,
            })

    def leave(self) -> None:
        with self.lock:
            self.inflight = max(0, self.inflight - 1)


def _multistatus(self_path: str, children: list[tuple[str, bool, int]]) -> bytes:
    """按 DAV: 的格式造一份 PROPFIND 响应（与 WebDavMount._propfind 的解析口径对齐）"""
    parts = []

    def add(path: str, is_dir: bool, size: int) -> None:
        kind = "<D:resourcetype><D:collection/></D:resourcetype>" if is_dir else "<D:resourcetype/>"
        parts.append(
            "<D:response>"
            f"<D:href>{urllib.parse.quote(path)}</D:href>"
            "<D:propstat><D:prop>"
            f"{kind}<D:getcontentlength>{size}</D:getcontentlength>"
            "<D:getlastmodified>Wed, 01 Jan 2025 00:00:00 GMT</D:getlastmodified>"
            "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
            "</D:response>"
        )

    add(self_path, True, 0)
    for path, is_dir, size in children:
        add(path, is_dir, size)
    body = ('<?xml version="1.0" encoding="utf-8"?>'
            '<D:multistatus xmlns:D="DAV:">' + "".join(parts) + "</D:multistatus>")
    return body.encode("utf-8")


class _WebDavHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FakeWebDav/1.0"

    # 服务端日志由脚本自己记，标准输出保持干净
    def log_message(self, fmt, *args) -> None:  # noqa: A003
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PROPFIND(self) -> None:  # noqa: N802 — HTTP 方法名
        state: _WebDavState = self.server.dav_state  # type: ignore[attr-defined]
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path).rstrip("/") or "/dav"
        state.enter("PROPFIND", path)
        try:
            time.sleep(REMOTE_LATENCY)
            tree: dict = self.server.tree  # type: ignore[attr-defined]
            children = tree.get(path)
            if children is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send(207, _multistatus(path, children), "application/xml; charset=utf-8")
        finally:
            state.leave()

    def do_GET(self) -> None:  # noqa: N802 — 播放 / 读 .strm 才会用到
        state: _WebDavState = self.server.dav_state  # type: ignore[attr-defined]
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        state.enter("GET", path)
        try:
            payload = b"fake-media-bytes" * 32
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            state.leave()


def _build_tree() -> dict[str, list[tuple[str, bool, int]]]:
    tree: dict[str, list[tuple[str, bool, int]]] = {"/dav": [(d, True, 0) for d in DIRS]}
    for directory in DIRS:
        children = []
        leaf = directory.rsplit("/", 1)[-1]
        for index in range(FILES_PER_DIR):
            if leaf == "tv":
                name = f"Show.Name.S01E{index + 1:02d}.1080p.WEB-DL.mkv"
            elif leaf == "movies":
                name = f"Movie.Name.{2000 + index}.1080p.BluRay.mkv"
            else:
                name = f"Concert.Name.2024.Part{index + 1:02d}.1080p.mkv"
            children.append((f"{directory}/{name}", False, 1024 * 1024))
        tree[directory] = children
    return tree


class _WebDavServer:
    def __init__(self) -> None:
        self.state = _WebDavState()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _WebDavHandler)
        self.httpd.tree = _build_tree()          # type: ignore[attr-defined]
        self.httpd.dav_state = self.state        # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/dav"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# ==================== 日志捕获 ====================

def _install_log_capture():
    """把 backend.* 的日志收一份（与线上审计看到的是同一批日志行）

    只接在 ``backend`` 这一层：子 logger 会向上传，接两层会把每行收成两份。
    """
    import logging

    records: list[dict] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                message = record.getMessage()
            except Exception:  # noqa: BLE001 — 格式化失败不该影响被测进程
                return
            records.append({
                "t": round(record.created - _T0_WALL, 3),
                "level": record.levelname,
                "logger": record.name,
                "thread": record.threadName,
                "message": message,
            })

    handler = Handler(level=logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("backend")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return records


_T0 = time.monotonic()      # 场景开始的单调钟（各事件的相对时间用它）
_T0_WALL = time.time()      # 同一时刻的墙上钟（日志记录用的是 time.time()）


# ==================== 一个场景（一种模式） ====================

def run_scenario(mode: str) -> dict:
    """跑一遍「四个库同时点扫描」，返回这次现场的全部观测数据"""
    import logging

    from fastapi.testclient import TestClient

    from backend import models
    from backend.database import SessionLocal, init_db
    from backend.emby_server import models as em
    from backend.emby_server import mounts as mnt
    from backend.emby_server import scan_queue
    from backend.main import app
    from backend.security import create_access_token, hash_password

    global _T0, _T0_WALL
    _T0 = time.monotonic()
    _T0_WALL = time.time()
    log_records = _install_log_capture()

    init_db()
    client = TestClient(app)

    with SessionLocal() as db:
        admin = models.WebUser(username=f"verify_{mode}", password_hash=hash_password("verify12345"),
                               is_active=True, is_staff=True)
        db.add(admin)
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    server = _WebDavServer()
    local_dir = tempfile.mkdtemp(prefix="verify-queue-local-")
    for index in range(8):
        with open(os.path.join(local_dir, f"Local.Movie.{index}.2024.1080p.mp4"), "wb") as handle:
            handle.write(b"\x00" * 4096)

    try:
        # 三条来源指向同一个远程挂载（审计里的 MP媒体库），第四条只读本机目录
        with SessionLocal() as db:
            mount = em.StorageMount(name="MP媒体库", mount_type="webdav", path="",
                                    config=json.dumps({"url": server.url, "username": "", "password": ""}),
                                    is_enabled=True)
            db.add(mount)
            db.commit()
            libraries = [
                em.Library(guid=f"verify-{mode}-{name}", name=name, collection_type="movies",
                           paths=path, mount_ids="" if not mount_id else str(mount.id),
                           scrape_policy="missing_only", is_enabled=True)
                for name, path, mount_id in (
                    ("剧集", "", mount.id), ("电影", "", mount.id),
                    ("演唱会", "", mount.id), ("音乐片", local_dir, None),
                )
            ]
            db.add_all(libraries)
            db.commit()
            library_rows = [(lib.id, lib.name, bool(str(lib.mount_ids or "").strip())) for lib in libraries]
            mount_id = mount.id

        # ---- 四个库连点扫描（同一分钟里的那次操作）----
        responses = []
        for lib_id, name, uses_mount in library_rows:
            started_at = time.monotonic() - _T0
            resp = client.post(f"/api/admin/emby/libraries/{lib_id}/scan", headers=headers)
            body = resp.json()
            responses.append({
                "library_id": lib_id, "name": name, "uses_mount": uses_mount,
                "at": round(started_at, 3), "http": resp.status_code,
                "state": (body.get("task") or {}).get("state"),
                "already": body.get("already"), "started": body.get("started"),
                "position": (body.get("task") or {}).get("position"),
                "waiting_for": (body.get("task") or {}).get("waiting_for"),
                "message": body.get("message"),
            })

        # ---- 一边轮询（面板口径），一边等四个库都跑完 ----
        timeline: list[dict] = []
        persisted_samples: list[dict] = []
        done_seen: set[int] = set()
        deadline = time.monotonic() + RUN_TIMEOUT
        while time.monotonic() < deadline:
            now = round(time.monotonic() - _T0, 3)
            snapshot = client.get("/api/admin/emby/scan-queue", headers=headers).json()
            libs = client.get("/api/admin/emby/libraries", headers=headers).json()["libraries"]
            row = {"t": now, "running": len(snapshot["running"]), "waiting": len(snapshot["waiting"]),
                   "mount_owners": snapshot.get("mount_owners"), "remote": snapshot.get("remote"),
                   "libs": {}}
            for item in libs:
                live = item.get("scan_live") or {}
                progress = live.get("progress") or {}
                row["libs"][item["name"]] = {
                    "state": live.get("state"),
                    "source": live.get("source"),
                    "position": live.get("position"),
                    "waiting_for": live.get("waiting_for"),
                    "phase": progress.get("phase_label"),
                    "enumerated": progress.get("enumerated"),
                    "processed": progress.get("processed"),
                    "current": progress.get("current"),
                    "elapsed_ms": progress.get("elapsed_ms"),
                }
            timeline.append(row)

            # 落库的进度快照（刷新页面 / 另一个进程看到的那份）
            with SessionLocal() as db:
                for lib_id, name, _ in library_rows:
                    record = db.query(em.Library).filter(em.Library.id == lib_id).first()
                    if record is not None and record.scan_progress:
                        persisted_samples.append({
                            "t": now, "name": name,
                            "raw": json.loads(record.scan_progress),
                        })

            history = {task["library_id"]: task for task in snapshot["history"]}
            for lib_id, _, _ in library_rows:
                if lib_id in history:
                    done_seen.add(lib_id)
            if len(done_seen) == len(library_rows):
                break
            time.sleep(POLL_SECONDS)

        # ---- 收尾：每个库的最终状态与条目数 ----
        finals = []
        with SessionLocal() as db:
            for lib_id, name, uses_mount in library_rows:
                record = db.query(em.Library).filter(em.Library.id == lib_id).first()
                stats_payload = json.loads(record.scan_stats) if record.scan_stats else None
                sources = (stats_payload or {}).get("sources") or []
                finals.append({
                    "library_id": lib_id, "name": name, "uses_mount": uses_mount,
                    "scan_status": record.scan_status, "item_count": record.item_count or 0,
                    "scan_error": record.scan_error,
                    "source_files": sum(int(s.get("files") or 0) for s in sources),
                    "source_labels": [s.get("label") for s in sources],
                    "last_scan": {
                        "status": (stats_payload or {}).get("status"),
                        "added": (stats_payload or {}).get("added"),
                        "sources": sources,
                    } if stats_payload else None,
                    "progress_cleared": record.scan_progress is None,
                })
        for task in client.get("/api/admin/emby/scan-queue", headers=headers).json()["history"]:
            for item in finals:
                if item["library_id"] == task["library_id"]:
                    item["task"] = {k: task[k] for k in
                                    ("state", "result", "queued_ms", "duration_ms", "remote_lists",
                                     "remote_reused", "request_count", "trigger")}
        queue_final = client.get("/api/admin/emby/scan-queue", headers=headers).json()

        return {
            "mode": mode,
            "queue_enabled": bool(scan_queue.SCAN_QUEUE_ENABLED),
            "max_parallel": scan_queue.SCAN_MAX_PARALLEL,
            "mount_serial": bool(scan_queue.SCAN_MOUNT_SERIAL),
            "remote_concurrency": mnt.MOUNT_REMOTE_CONCURRENCY,
            "mount_id": mount_id,
            "webdav_url": server.url,
            "responses": responses,
            "timeline": timeline,
            "persisted_progress": persisted_samples,
            "finals": finals,
            "webdav": {
                "requests": server.state.requests,
                "peak_inflight": server.state.peak_inflight,
                "per_path": server.state.per_path,
                "total": len(server.state.requests),
            },
            "queue_remote": queue_final.get("remote"),
            "logs": log_records,
            "wall_seconds": round(time.monotonic() - _T0, 3),
        }
    finally:
        server.stop()
        logging.getLogger("backend").handlers.clear()
        logging.getLogger("backend.emby_server").handlers.clear()


# ==================== 指标与断言 ====================

def metrics(result: dict) -> dict:
    """从原始观测里算出「这次现场到底发生了什么」"""
    libs = {item["name"]: item for item in result["finals"]}
    responses = result["responses"]
    timeline = result["timeline"]

    # 每个库「开始扫描 → 结束扫描」的时间窗（从时间线里取状态变化）
    windows: dict[str, list[float]] = {name: [] for name in libs}
    for row in timeline:
        for name, state in row["libs"].items():
            entry = windows.setdefault(name, [])
            if state.get("state") == "running":
                entry.append(row["t"])

    def window_of(name: str) -> tuple[float, float] | None:
        stamps = windows.get(name) or []
        if not stamps:
            return None
        return (stamps[0], stamps[-1])

    # 同一挂载的三个库彼此重叠了多久（>0 = 并发打同一个远程端点）
    shared = [name for name, item in libs.items() if item["uses_mount"]]
    overlap = 0.0
    for index, first in enumerate(shared):
        for second in shared[index + 1:]:
            a, b = window_of(first), window_of(second)
            if not a or not b:
                continue
            overlap = max(overlap, min(a[1], b[1]) - max(a[0], b[0]))

    peak_scans = max((row["running"] for row in timeline), default=0)
    # 应用日志里「同时 N 个在跑」的最大值：轮询可能错过一瞬间，日志不会
    log_peak = 0
    for row in result["logs"]:
        match = re.search(r"同时 (\d+) 个在跑", row["message"])
        if match:
            log_peak = max(log_peak, int(match.group(1)))
    finished = [item for item in result["finals"] if item.get("task")]
    return {
        "peak_concurrent_scans": peak_scans,
        "log_peak_simultaneous": log_peak,
        "peak_webdav_inflight": result["webdav"]["peak_inflight"],
        "webdav_requests": result["webdav"]["total"],
        "webdav_max_same_path": max(result["webdav"]["per_path"].values(), default=0),
        "shared_mount_overlap_seconds": round(overlap, 2),
        "shared_mount_libs": shared,
        "all_four_running_at_once": any(
            sum(1 for s in row["libs"].values() if s.get("state") == "running") >= 4
            for row in timeline
        ),
        "queued_libs": sorted({r["name"] for r in responses
                               if r.get("started") is False or r.get("state") == "queued"}),
        "items": {name: item["item_count"] for name, item in libs.items()},
        "statuses": {name: item["scan_status"] for name, item in libs.items()},
        "durations_ms": {item["name"]: (item.get("task") or {}).get("duration_ms") for item in finished},
        "queued_ms": {item["name"]: (item.get("task") or {}).get("queued_ms") for item in finished},
        "wall_seconds": result["wall_seconds"],
        "progress_cleared": all(item["progress_cleared"] for item in result["finals"]),
        "remote_lists_per_lib": {item["name"]: (item.get("task") or {}).get("remote_lists")
                                 for item in finished},
        # 每条来源实际**发现**了多少文件：证明枚举真的走完了整个挂载（不是半路放弃）
        "source_files": {name: item["source_files"] for name, item in libs.items()},
        "failed": [name for name, item in libs.items() if item["scan_status"] == "failed"],
        "indexed_items": sum(item["item_count"] for name, item in libs.items()
                             if item["uses_mount"]),
    }


def assertions(result: dict, stats: dict) -> list[tuple[str, bool, str]]:
    """关键断言：两种模式各自应该成立的事实"""
    mode = result["mode"]
    checks: list[tuple[str, bool, str]] = []
    total_files = FILES_PER_DIR * len(DIRS)

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    add("四个库都触发了扫描（HTTP 200）",
        len(result["responses"]) == 4 and all(r["http"] == 200 for r in result["responses"]),
        str([(r["name"], r["http"]) for r in result["responses"]]))
    add("四个库都真的扫完了（有终态）",
        len([item for item in result["finals"] if item.get("task")]) == 4,
        str([(item["name"], item.get("task", {}).get("state")) for item in result["finals"]]))
    add("本机目录的库不受远程串行化影响（自己跑完了）",
        stats["statuses"].get("音乐片") == "success" and stats["items"].get("音乐片", 0) > 0,
        f"{stats['statuses'].get('音乐片')} / {stats['items'].get('音乐片')} 条")

    if mode == "queue":
        add("同时最多 2 个扫描在跑（并发上限）",
            stats["peak_concurrent_scans"] <= result["max_parallel"],
            f"peak={stats['peak_concurrent_scans']} 上限={result['max_parallel']}")
        add("同一远程挂载的三个库**没有**并发重叠",
            stats["shared_mount_overlap_seconds"] <= 0.3,
            f"最长重叠 {stats['shared_mount_overlap_seconds']}s")
        add("有库被明确告知「在等挂载」而不是硬上",
            len(stats["queued_libs"]) >= 1, str(stats["queued_libs"]))
        add("WebDAV 端点的并发请求数不超过远程上限",
            stats["peak_webdav_inflight"] <= result["remote_concurrency"],
            f"peak={stats['peak_webdav_inflight']} 上限={result['remote_concurrency']}")
        add("扫描开始的日志里同时最多 2 个在跑（日志口径与快照一致）",
            stats["log_peak_simultaneous"] <= result["max_parallel"],
            f"日志 peak={stats['log_peak_simultaneous']} 上限={result['max_parallel']}")
        add("四个库的扫描都没有失败（串行化后不再互相踩踏）",
            not stats["failed"], str(stats["failed"]))
        add("每个远程库都枚举完整个挂载（发现 60 个文件）",
            all(stats["source_files"].get(name) == total_files
                for name in stats["shared_mount_libs"]),
            f"应为 {total_files}：{ {k: v for k, v in stats['source_files'].items()} }")
        add("挂载内容确实入库（条目落在最先跑的那个库里）",
            stats["indexed_items"] > 0, f"挂载库条目合计 {stats['indexed_items']}")
    else:
        add("（升级前）四个库确实同时在跑——这就是那次审计的现场",
            stats["peak_concurrent_scans"] >= 4 and stats["log_peak_simultaneous"] >= 4,
            f"队列快照 peak={stats['peak_concurrent_scans']}；日志 peak={stats['log_peak_simultaneous']}")
        add("（升级前）同一远程挂载上叠着多个扫描任务",
            stats["shared_mount_overlap_seconds"] > 0,
            f"最长重叠 {stats['shared_mount_overlap_seconds']}s")
        add("（升级前）没有排队这回事：四个库都直接“已启动”，没有位置与等待原因",
            not stats["queued_libs"] and all(r.get("started") for r in result["responses"]),
            str([(r["name"], r.get("started"), r.get("position")) for r in result["responses"]]))

    add("扫描结束后进度快照被清空（面板不会显示陈旧的「扫描中」）",
        stats["progress_cleared"] is True)
    return checks


# ==================== 输出 ====================

def _bar(value: float, scale: float, width: int = 28) -> str:
    if scale <= 0:
        return ""
    filled = int(round(width * min(1.0, value / scale)))
    return "█" * filled + "·" * (width - filled)


def print_scenario(result: dict, stats: dict, checks: list[tuple[str, bool, str]]) -> None:
    label = "队列开启（v2.27.0）" if result["mode"] == "queue" else "队列关闭（升级前行为）"
    print(f"\n{'=' * 78}\n【{label}】\n{'=' * 78}")
    print(f"WebDAV: {result['webdav_url']}（同一挂载 id={result['mount_id']}，每次 PROPFIND 延迟 "
          f"{int(REMOTE_LATENCY * 1000)}ms）")
    print(f"场景：剧集 / 电影 / 演唱会 → 同一个远程挂载；音乐片 → 本机目录（不吃远程串行化）")

    print("\n-- 四个库连点扫描的响应（面板看到的）--")
    for item in result["responses"]:
        print(f"  t+{item['at']:6.2f}s  {item['name']:<4} HTTP {item['http']}  "
              f"state={item['state']}  started={item['started']}  "
              f"position={item['position']}  waiting_for={item['waiting_for']}")
        print(f"                 → {item['message']}")

    print("\n-- 应用日志（扫描出入队 / 开始 / 结束；与线上审计同一批）--")
    interesting = [row for row in result["logs"]
                   if any(key in row["message"] for key in
                          ("扫描入队", "扫描开始", "扫描结束", "取消排队", "清空扫描进度"))]
    for row in interesting:
        print(f"  t+{row['t']:6.2f}s [{row['thread']:<12}] {row['level']:<5} {row['message']}")
    if not interesting:
        print("  （没有队列相关日志：升级前是直接起线程，没有入队/排队这一步）")

    print("\n-- WebDAV 服务端日志（每个请求的时刻与在飞并发）--")
    for row in result["webdav"]["requests"]:
        print(f"  t+{row['t']:6.2f}s {row['method']:<8} {urllib.parse.unquote(row['path']):<44} "
              f"inflight={row['inflight']}")
    print(f"  → 共 {result['webdav']['total']} 次请求，在飞峰值 {result['webdav']['peak_inflight']}")

    print("\n-- 每个库的最终结果 --")
    for item in result["finals"]:
        task = item.get("task") or {}
        print(f"  {item['name']:<4} 状态={item['scan_status']:<8} 条目={item['item_count']:<4} "
              f"本来源发现={item['source_files']:<4} "
              f"耗时={(task.get('duration_ms') or 0) / 1000:5.2f}s 排队={(task.get('queued_ms') or 0) / 1000:5.2f}s "
              f"本轮远程列举={task.get('remote_lists')}（复用 {task.get('remote_reused')}）"
              f"{'  ⚠ ' + str(item['scan_error'])[:90] if item['scan_error'] else ''}")

    print("\n-- 进度时间线（面板口径：状态 / 阶段 / 已处理 / 已发现）--")
    names = [item["name"] for item in result["finals"]]
    print("    t      " + "".join(f"{name:<22}" for name in names))
    for row in result["timeline"]:
        cells = []
        for name in names:
            state = row["libs"].get(name) or {}
            if state.get("state") == "running":
                text = f"扫描 {state.get('phase') or ''} {state.get('processed')}/{state.get('enumerated')}"
            elif state.get("state") == "queued":
                text = f"排队(第{state.get('position')}位)"
            else:
                text = "—"
            cells.append(f"{text:<22}")
        print(f"  +{row['t']:6.2f}s " + "".join(cells))

    if result["persisted_progress"]:
        print("\n-- 落库的进度快照样本（刷新页面 / 另一个进程看到的那份）--")
        for sample in result["persisted_progress"][:6]:
            raw = sample["raw"]
            print(f"  t+{sample['t']:6.2f}s {sample['name']:<4} phase={raw.get('phase_label')} "
                  f"enumerated={raw.get('enumerated')} processed={raw.get('processed')} "
                  f"当前={raw.get('current')}")

    print("\n-- 汇总 --")
    print(f"  同时最多几个扫描在跑 : {stats['peak_concurrent_scans']}（扫描开始日志：{stats['log_peak_simultaneous']}）")
    print(f"  同一挂载的最长重叠   : {stats['shared_mount_overlap_seconds']}s")
    print(f"  WebDAV 在飞峰值      : {stats['peak_webdav_inflight']}")
    print(f"  WebDAV 总请求        : {stats['webdav_requests']}"
          f"（同一路径最多 {stats['webdav_max_same_path']} 次）")
    print(f"  入口到全部跑完       : {stats['wall_seconds']}s")
    if result["mode"] == "queue":
        print(f"  被排队的库           : {stats['queued_libs']}")

    print("\n-- 断言 --")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")


def print_comparison(results: dict[str, dict], stats: dict[str, dict]) -> None:
    legacy, queue = results["legacy"], results["queue"]
    old, new = stats["legacy"], stats["queue"]

    def row(label: str, before, after, unit: str = "") -> None:
        print(f"  {label:<26} {str(before) + unit:>12}   →   {str(after) + unit}")

    print(f"\n{'=' * 78}\n对照：四个库同时点扫描，一次线上日志审计的现场\n{'=' * 78}")
    row("同时在跑的扫描", old["peak_concurrent_scans"], new["peak_concurrent_scans"], " 个")
    row("同一挂载的最长并发重叠", old["shared_mount_overlap_seconds"], new["shared_mount_overlap_seconds"], " s")
    row("WebDAV 在飞请求峰值", old["peak_webdav_inflight"], new["peak_webdav_inflight"])
    row("WebDAV 总请求数", old["webdav_requests"], new["webdav_requests"])
    row("四个库全部跑完（墙上时间）", old["wall_seconds"], new["wall_seconds"], " s")
    row("排队等待的库数", len(old["queued_libs"]), len(new["queued_libs"]))
    print(f"  {'扫描失败（并发写库互踩）':<26} {len(old['failed'])} 个 {old['failed']}  →  "
          f"{len(new['failed'])} 个 {new['failed']}")
    print(f"  {'条目数（四个库）':<26} {old['items']}  →  {new['items']}")
    print(f"  {'每条来源发现（远程库）':<26} {old['source_files']}  →  {new['source_files']}")
    print(f"  {'扫描状态':<26} {old['statuses']}  →  {new['statuses']}")
    print(f"  {'画面对比':<26} 四个库都显示「扫描中」，看不出谁在等什么"
          f"  →  " + ("能看出谁在排队、第几位、在等哪个挂载" if new["queued_libs"] else "—"))
    print("\n  图表（同时有几个扫描在跑，横轴 = 峰值）：")
    scale = max(old["peak_concurrent_scans"], new["peak_concurrent_scans"], 1)
    print(f"    升级前 {_bar(old['peak_concurrent_scans'], scale)} {old['peak_concurrent_scans']}")
    print(f"    现在   {_bar(new['peak_concurrent_scans'], scale)} {new['peak_concurrent_scans']}")


# ==================== 入口 ====================

def _prepare_child_env(mode: str) -> None:
    """子进程的环境：干净的临时库 + 这一模式的开关（模块常量在 import 时读取，所以要先设）"""
    os.environ["DATABASE_TYPE"] = "sqlite"
    os.environ["REDIS_ENABLED"] = "false"
    os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ.setdefault("SECRET_KEY", "verify-scan-queue-only-secret-not-for-production")
    os.environ["EMBY_SCAN_QUEUE"] = "0" if mode == "legacy" else "1"
    os.environ["EMBY_SCAN_MAX_PARALLEL"] = "2"
    os.environ["EMBY_SCAN_MOUNT_SERIAL"] = "1"
    os.environ["EMBY_SCAN_PROGRESS_FLUSH"] = "1"
    os.environ["MOUNT_REMOTE_CONCURRENCY"] = "2"
    os.environ["MOUNT_LIST_CACHE_SECONDS"] = "5"
    os.environ.setdefault("LOG_LEVEL", "warning")


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描队列并发验证（真 WebDAV + 真管理端接口）")
    parser.add_argument("--mode", choices=("legacy", "queue"), help="只跑一种模式（默认两种都跑并对照）")
    parser.add_argument("--json", help="把原始观测写到这个文件")
    args = parser.parse_args()

    if args.mode:
        _prepare_child_env(args.mode)
        result = run_scenario(args.mode)
        stats = metrics(result)
        checks = assertions(result, stats)
        print_scenario(result, stats, checks)
        if args.json:
            with open(args.json, "w", encoding="utf-8") as handle:
                json.dump({"result": result, "stats": stats,
                           "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]},
                          handle, ensure_ascii=False, indent=2)
        failed = [name for name, ok, _ in checks if not ok]
        if failed:
            print("\n❌ 未通过：" + "；".join(failed))
            return 1
        print("\n✅ 本次场景全部通过")
        return 0

    # 父进程：两种模式各起一个干净的子进程（模块级开关在 import 时读取）
    results: dict[str, dict] = {}
    stats: dict[str, dict] = {}
    all_checks: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="verify-queue-") as workdir:
        for mode in ("legacy", "queue"):
            out = os.path.join(workdir, f"{mode}.json")
            proc = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--mode", mode, "--json", out],
                capture_output=True, text=True, timeout=RUN_TIMEOUT + 120,
            )
            print(proc.stdout, end="")
            if proc.returncode != 0:
                print(proc.stderr[-2000:], file=sys.stderr)
            with open(out, encoding="utf-8") as handle:
                payload = json.load(handle)
            results[mode] = payload["result"]
            stats[mode] = payload["stats"]
            all_checks.extend((f"[{mode}] {c['name']}", c["ok"], c["detail"]) for c in payload["checks"])

    print_comparison(results, stats)
    failed = [name for name, ok, _ in all_checks if not ok]
    print(f"\n{'=' * 78}")
    print(f"断言通过 {len(all_checks) - len(failed)}/{len(all_checks)}")
    if failed:
        print("❌ 未通过：")
        for name in failed:
            print(f"  - {name}")
        return 1
    print("✅ 扫描队列验证通过：四个库同时点扫描时，同一远程挂载串行化、进度可查、结果正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
