"""挂载体检冒烟测试（v2.6.18）

要解决的问题：同一条挂载会被 EM（面板：扫描/浏览/测试）与 EA（网关：播放出流）两个进程
各自解析，而 ``local`` / ``strm`` 的路径、rclone 的 RC 地址都是**主机相对**的配置。
后台「测试连接」跑在 EM 进程里，所以它通过并不代表那台 EA 能播。

覆盖：
- EA 的 ``GET /api/admin/mounts/health``：无密钥 / 错密钥一律 401，正确密钥才返回结果
- 体检结论如实：本机目录可读 → 可达；目录不存在 → 不可达；停用 → 跳过不体检
- 体检结果不泄露挂载密钥（Cookie / 密码等），失败文案里万一带了凭据也会被洗成 `***`
- EM 上**不存在**这条端点（它不是给公网/面板用的）
- EM 的面板体检（``POST /api/admin/emby/mounts/health``）会把结果写回挂载记录
- 真实起一个 EA（uvicorn + 真发 HTTP）后，EM 保存 EA 服务入口时会拉到 EA 视角的体检并落库，
  挂载列表能返回 ``ea_reachable`` / ``playback_node``，「被媒体库引用却 EA 不可达」可被判出来
"""
import os
import random
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("SECRET_KEY", "smoke-test-only-secret-key-not-for-production")

DB = tempfile.mktemp(suffix=".db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{DB}")

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import mount_health  # noqa: E402
from backend.main import app as em_app  # noqa: E402
from backend.security import hash_password  # noqa: E402
from emby_api import main as ea  # noqa: E402

init_db()

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


suf = str(random.randint(100000, 999999))
SECRET = os.environ["SECRET_KEY"]

# ==================== 数据准备 ====================

good_dir = tempfile.mkdtemp(prefix="mount_health_")
missing_dir = os.path.join(tempfile.mkdtemp(prefix="mount_health_"), "not-there")
SECRET_PASSWORD = f"dav-pass-{suf}"

db = SessionLocal()
try:
    staff = models.WebUser(username=f"mh_staff{suf}", password_hash=hash_password("pass12345"),
                           is_staff=True, is_active=True)
    db.add(staff)
    db.commit()

    good = em.StorageMount(name=f"本机可读{suf}", mount_type="local", path=good_dir, is_enabled=True)
    bad = em.StorageMount(name=f"目录不存在{suf}", mount_type="local", path=missing_dir, is_enabled=True)
    off = em.StorageMount(name=f"已停用{suf}", mount_type="local", path=good_dir, is_enabled=False)
    dav = em.StorageMount(name=f"WebDAV 不可达{suf}", mount_type="webdav",
                          path="", is_enabled=True,
                          config='{"url": "http://127.0.0.1:9/dav", "password": "%s"}' % SECRET_PASSWORD)
    db.add_all([good, bad, off, dav])
    db.commit()

    # 一个媒体库引用「不可达」的那条挂载：这是会「扫得到、播不了」的组合
    library = em.Library(guid=f"mounthealth{suf}", name=f"体检库{suf}", collection_type="movies",
                         paths="", mount_ids=str(bad.id), scrape_policy="missing_only")
    db.add(library)
    db.commit()

    good_id, bad_id, off_id, dav_id, library_id = good.id, bad.id, off.id, dav.id, library.id
    # session 关掉后属性会失效，先把要用的值取出来
    staff_username = staff.username
finally:
    db.close()


def set_config(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if row:
            row.value = value
        else:
            db.add(models.SystemConfig(key=key, value=value))
        db.commit()
    finally:
        db.close()


# ==================== 起一个真的 EA（真发 HTTP）====================

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


ea_port = free_port()
ea_url = f"http://127.0.0.1:{ea_port}"
server = uvicorn.Server(uvicorn.Config(ea.app, host="127.0.0.1", port=ea_port, log_level="warning"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()

ready = False
for _ in range(100):
    try:
        if httpx.get(f"{ea_url}/api/health", timeout=1).status_code == 200:
            ready = True
            break
    except Exception:  # noqa: BLE001 — 还没起来，继续等
        time.sleep(0.1)
check("EA 真的起来了（真 HTTP）", ready, ea_url)

try:
    # ==================== 1. EA 端点鉴权 ====================
    print("\n--- EA 挂载体检端点：鉴权 ---")
    r = httpx.get(f"{ea_url}/api/admin/mounts/health", timeout=30)
    check("不带 X-Panel-Key → 401", r.status_code == 401, f"HTTP {r.status_code}")

    r = httpx.get(f"{ea_url}/api/admin/mounts/health",
                  headers={mount_health.PANEL_KEY_HEADER: "wrong-key"}, timeout=30)
    check("密钥错误 → 401", r.status_code == 401, f"HTTP {r.status_code}")

    r = httpx.get(f"{ea_url}/api/admin/mounts/health",
                  headers={mount_health.PANEL_KEY_HEADER: SECRET}, timeout=60)
    check("共享 SECRET_KEY → 200", r.status_code == 200, f"HTTP {r.status_code}")
    health = r.json() if r.status_code == 200 else {}
    check("如实上报 service=ea", health.get("service") == "ea", str(health.get("service")))

    # ==================== 2. 体检结论 ====================
    print("\n--- EA 体检结论 ---")
    by_id = {m["id"]: m for m in health.get("mounts") or []}

    item = by_id.get(good_id) or {}
    check("本机目录可读 → 可达", item.get("ok") is True, str(item.get("message"))[:60])
    check("并报出路径存在", item.get("path_exists") is True, str(item.get("path_exists")))

    item = by_id.get(bad_id) or {}
    check("目录不存在 → 不可达", item.get("ok") is False, str(item.get("message"))[:60])
    check("不可达原因可读", "目录" in str(item.get("message")), str(item.get("message"))[:60])
    check("路径存在性为 False", item.get("path_exists") is False, str(item.get("path_exists")))
    check("并标出被媒体库引用", item.get("library_ids") == [library_id], str(item.get("library_ids")))

    item = by_id.get(off_id) or {}
    check("已停用的挂载跳过体检", item.get("ok") is None and item.get("skipped") is True,
          str(item.get("message")))

    item = by_id.get(dav_id) or {}
    check("WebDAV 连不上 → 不可达", item.get("ok") is False, str(item.get("message"))[:60])

    # 密钥绝不能随体检结果出来
    body_text = r.text
    check("体检结果不泄露挂载密钥",
          SECRET_PASSWORD not in body_text and "password" not in body_text,
          "响应里没有 password 字段")

    # 失败文案可能带着异常里的凭据（如 url 里内嵌的 user:pass）：必须洗掉
    dav_mount = db.query(em.StorageMount).filter(em.StorageMount.id == dav_id).first()
    raw = (f"连接失败: <urlopen error http://user:{SECRET_PASSWORD}@127.0.0.1:9/dav>")
    scrubbed = mount_health.redact(raw, dav_mount)
    check("告警文案里的密钥会被洗掉",
          SECRET_PASSWORD not in scrubbed and "***" in scrubbed,
          scrubbed[:80])

    # ==================== 3. 这条端点只在 EA 上 ====================
    print("\n--- 端点归属 ---")
    em_client = TestClient(em_app)
    r = em_client.get("/api/admin/mounts/health")
    check("EM 上不存在该端点（只给 EM→EA 内部调用）", r.status_code == 404, f"HTTP {r.status_code}")

    # ==================== 4. EM 侧：面板体检写回挂载 ====================
    print("\n--- EM 面板体检 ---")
    r = em_client.post("/api/user/auth/login",
                       json={"username": staff_username, "password": "pass12345"})
    token = r.json()["access_token"] if r.status_code == 200 else ""
    staff_h = {"Authorization": f"Bearer {token}"}
    check("管理员登录拿到令牌", bool(token), f"HTTP {r.status_code}")

    r = em_client.post("/api/admin/emby/mounts/health", headers=staff_h)
    check("POST /api/admin/emby/mounts/health → 200", r.status_code == 200, f"HTTP {r.status_code}")
    panel = r.json() if r.status_code == 200 else {}
    check("面板体检基于 EM 本机跑", panel.get("service") == "panel", str(panel.get("service")))
    panel_by_id = {m["id"]: m for m in panel.get("mounts") or []}
    check("面板体检结论与 EA 一致（同机时）",
          (panel_by_id.get(good_id) or {}).get("ok") is True
          and (panel_by_id.get(bad_id) or {}).get("ok") is False)

    db = SessionLocal()
    try:
        row = db.query(em.StorageMount).filter(em.StorageMount.id == bad_id).first()
        check("面板体检结果写回挂载记录", row.last_check_ok is False, str(row.last_check_ok))
    finally:
        db.close()

    # ==================== 5. EM 保存 EA 服务入口 → 拉 EA 体检并落库 ====================
    print("\n--- EM 保存 EA 服务入口 ---")
    r = em_client.put("/api/admin/emby/servers",
                      json={"mode": "managed_ea", "url": ea_url, "enabled": True},
                      headers=staff_h)
    check("保存 EA 服务入口 → 200", r.status_code == 200, f"HTTP {r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    check("EA 连接探测通过", (body.get("probe") or {}).get("ok") is True,
          str(body.get("probe"))[:80])
    mounts_health = body.get("mounts_health") or {}
    check("保存时顺带拉了 EA 视角的挂载体检", mounts_health.get("ok") is True,
          str(mounts_health)[:100])
    check("体检结果含「被库引用却 EA 不可达」清单",
          bad_id in (mounts_health.get("unreachable") or []),
          str(mounts_health.get("unreachable")))

    db = SessionLocal()
    try:
        saved = mount_health.read_ea_health(db)
        check("体检快照落库到 SystemConfig", bool(saved.get("checked_at")), str(saved.get("checked_at")))
        check("快照里确实有逐条结果", len(saved.get("mounts") or []) >= 4,
              str(len(saved.get("mounts") or [])))
    finally:
        db.close()

    # ==================== 6. 挂载列表把两个视角都摆出来 ====================
    print("\n--- 挂载列表（面板要展示的数据）---")
    r = em_client.get("/api/admin/emby/mounts", headers=staff_h)
    check("GET /api/admin/emby/mounts → 200", r.status_code == 200, f"HTTP {r.status_code}")
    data = r.json() if r.status_code == 200 else {}
    rows = {m["id"]: m for m in data.get("mounts") or []}
    check("当前播放节点是 EA（分离部署）", data.get("playback_node") == "ea",
          str(data.get("playback_node")))
    check("EA 体检摘要可见", (data.get("ea_health") or {}).get("ok") is True,
          str(data.get("ea_health"))[:80])
    check("每条挂载都带 em_reachable", rows.get(good_id, {}).get("em_reachable") is True,
          str(rows.get(good_id, {}).get("em_reachable")))
    check("每条挂载都带 ea_reachable", rows.get(good_id, {}).get("ea_reachable") is True,
          str(rows.get(good_id, {}).get("ea_reachable")))
    check("不可达的那条在 EA 侧也是 False", rows.get(bad_id, {}).get("ea_reachable") is False,
          str(rows.get(bad_id, {}).get("ea_reachable")))
    check("EA 侧带原因（前端 tooltip 用）", bool(rows.get(bad_id, {}).get("ea_message")),
          str(rows.get(bad_id, {}).get("ea_message"))[:60])

    # ==================== 7. 手动「EA 体检」按钮 ====================
    print("\n--- 手动刷新 EA 体检 ---")
    r = em_client.post("/api/admin/emby/servers/mounts/refresh", headers=staff_h)
    check("POST /servers/mounts/refresh → 成功", r.status_code == 200 and r.json().get("success") is True,
          f"HTTP {r.status_code}")

    # EA 不可达时要如实报告，而不是假装有结论
    set_config("emby_managed_url", "http://127.0.0.1:9")
    r = em_client.post("/api/admin/emby/servers/mounts/refresh", headers=staff_h)
    body = r.json() if r.status_code == 200 else {}
    check("EA 连不上时如实报错", r.status_code == 200 and body.get("success") is False,
          str(body.get("health"))[:80])
    db = SessionLocal()
    try:
        stale = mount_health.read_ea_health(db)
        check("失败时保留上一次逐条结果，只标记快照失效",
              bool(stale.get("error")) and len(stale.get("mounts") or []) >= 4,
              f"error={str(stale.get('error'))[:40]} mounts={len(stale.get('mounts') or [])}")
    finally:
        db.close()
finally:
    server.should_exit = True
    thread.join(timeout=10)
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass

print()
if failures:
    print(f"FAILED {len(failures)}/{checks}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"ALL PASS {checks}/{checks}")
