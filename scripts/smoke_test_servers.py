"""服务器清单与求片转交冒烟测试（v2.6.19）

要解决的问题：面板以前只能填**一台** EA 和**一台**外部 Emby，MoviePilot / qBittorrent
连入口都没有，所以「求片」批了之后没有任何办法真的把片子弄进来。这一版把服务器变成一份
可增删改的清单，并让求片能转交给它们。

本脚本真的起三个 HTTP 服务（不是打桩）：
1. **假 MoviePilot**：`/api/v1/subscribe/list?token=`（API_TOKEN 校验）、
   `/api/v1/login/access-token`（用户名密码换 JWT）、`POST /api/v1/subscribe/`（要 Bearer）；
2. **假 qBittorrent**：`/api/v2/auth/login`（错密码回 "Fails."）、`/api/v2/app/version`、
   `/api/v2/torrents/add`（要 SID Cookie）；
3. **真 EA**（`emby_api.main`），验证「设为当前使用」会真的把旧配置键换过去并拉挂载体检。

覆盖：
- 类型元数据（四类、字段与密钥声明）、匿名访问被拒
- 新增即体检；连不上 / 凭据不对时如实报错（不假装成功）
- 连不上的服务器**不能**被设为当前使用，旧配置不会被切走
- EA 激活 → 旧页面（`GET /api/admin/emby/servers`）看到同一台；旧页面保存 → 清单里出现同一台
- 删除当前使用的 EA → 收回旧配置，回到「面板自己出流」
- 密钥永不出接口（API_TOKEN / 密码都不在响应里）
- 求片推送：MoviePilot 收到 name/year/type；qB 没链接时明确拒绝、有磁力时真的加种；
  失败原因落库到求片记录；没有可用服务时提示去「服务器」页
"""
import os
import random
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "smoke-test-only-secret-key-not-for-production")

# **强制**用自己的库（不是 setdefault）：本脚本断言的是全局状态——「清单初始为空」
# 以及「被拒时旧配置没被切走」。CI 里所有冒烟脚本共用一个 DATABASE_URL（ci-smoke.db），
# 前面某个脚本（如 Emby 服务入口 / 挂载体检）留下的配置会把这些断言弄脏。
DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Form, HTTPException, Request  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
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
STAFF_PASSWORD = "pass12345"
MP_TOKEN = f"mp-api-token-{suf}"
MP_USER, MP_PASS = f"mp-{suf}", "mp-pass-1234"
QB_USER, QB_PASS = f"qb-{suf}", "qb-pass-1234"
# 这两个字符串绝不能出现在任何接口响应里
MP_PASSWORD = MP_PASS
QB_PASSWORD = QB_PASS


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, path: str = "/api/health") -> bool:
    for _ in range(100):
        try:
            if httpx.get(f"{url}{path}", timeout=1).status_code < 500:
                return True
        except Exception:  # noqa: BLE001 — 还没起来就继续等
            time.sleep(0.1)
    return False


# ==================== 1. 假 MoviePilot + 假 qBittorrent ====================

CALLS: dict = {"subscribe": [], "torrents": [], "mp_logins": 0, "qb_logins": 0}
fake = FastAPI()


@fake.get("/api/v1/subscribe/list")
async def mp_list(request: Request):
    token = request.query_params.get("token") or request.headers.get("X-Api-Key")
    if token != MP_TOKEN:
        raise HTTPException(401, "token校验不通过")
    return [{"id": 1, "name": "已有的订阅"}]


@fake.post("/api/v1/login/access-token")
async def mp_login(username: str = Form(...), password: str = Form(...)):
    CALLS["mp_logins"] += 1
    if (username, password) != (MP_USER, MP_PASS):
        raise HTTPException(400, "用户名或密码错误")
    return {"access_token": "fake-jwt", "token_type": "bearer"}


@fake.post("/api/v1/subscribe/")
async def mp_subscribe(payload: dict, request: Request):
    if request.headers.get("Authorization") != "Bearer fake-jwt":
        raise HTTPException(401, "token校验不通过")
    CALLS["subscribe"].append(payload)
    return {"success": True, "message": "订阅已添加", "data": {"id": 42}}


# 外部 Emby 的协议面：旧页面（Emby 服务入口）的「已有 Emby 服」探测打这里
@fake.get("/System/Info/Public")
async def emby_public():
    return {"ServerName": f"假 Emby {suf}", "Version": "4.8.0.0", "Id": f"fake-emby-{suf}"}


@fake.post("/api/v2/auth/login")
async def qb_login(username: str = Form(...), password: str = Form(...)):
    CALLS["qb_logins"] += 1
    if (username, password) != (QB_USER, QB_PASS):
        return PlainTextResponse("Fails.")
    # 必须把 Cookie 挂在**返回的那个**响应上：FastAPI 不会把注入式 Response 的 Cookie
    # 合并进另建的响应（真实 qB 是直接回 Set-Cookie）
    resp = PlainTextResponse("Ok.")
    resp.set_cookie("SID", "fakesid")
    return resp


@fake.get("/api/v2/app/version")
async def qb_version(request: Request):
    if request.cookies.get("SID") != "fakesid":
        raise HTTPException(403, "Forbidden")
    return PlainTextResponse("v5.0.3")


@fake.post("/api/v2/torrents/add")
async def qb_add(request: Request):
    if request.cookies.get("SID") != "fakesid":
        raise HTTPException(403, "Forbidden")
    CALLS["torrents"].append(dict(await request.form()))
    return PlainTextResponse("Ok.")


fake_port = free_port()
fake_url = f"http://127.0.0.1:{fake_port}"
fake_server = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=fake_port, log_level="warning"))
fake_thread = threading.Thread(target=fake_server.run, daemon=True)
fake_thread.start()
check("假 MoviePilot / qBittorrent 服务真的起来了", wait_ready(fake_url, "/api/v1/subscribe/list"),
      fake_url)

ea_port = free_port()
ea_url = f"http://127.0.0.1:{ea_port}"
ea_server = uvicorn.Server(uvicorn.Config(ea.app, host="127.0.0.1", port=ea_port, log_level="warning"))
ea_thread = threading.Thread(target=ea_server.run, daemon=True)
ea_thread.start()
check("真 EA 也起来了（用它验证「设为当前使用」）", wait_ready(ea_url), ea_url)


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


def config_of(key: str) -> str:
    db = SessionLocal()
    try:
        row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        return ((row.value if row else "") or "").strip()
    finally:
        db.close()


# 造一个管理员 + 一条求片（走真正的管理端接口去推）
db = SessionLocal()
try:
    staff = models.WebUser(username=f"sv_staff{suf}", password_hash=hash_password(STAFF_PASSWORD),
                           is_staff=True, is_active=True)
    db.add(staff)
    db.commit()
    staff_id = staff.id
finally:
    db.close()

client = TestClient(em_app)

try:
    # ==================== 2. 鉴权与类型元数据 ====================
    print("\n--- 鉴权与类型元数据 ---")
    r = client.get("/api/admin/servers")
    check("匿名访问服务器清单被拒", r.status_code in (401, 403), f"HTTP {r.status_code}")
    r = client.post("/api/admin/servers/test", json={"kind": "ea", "url": ea_url})
    check("匿名测试连接被拒", r.status_code in (401, 403), f"HTTP {r.status_code}")

    r = client.post("/api/user/auth/login", json={"username": f"sv_staff{suf}", "password": STAFF_PASSWORD})
    token = r.json()["access_token"] if r.status_code == 200 else ""
    H = {"Authorization": f"Bearer {token}"}
    check("管理员登录拿到令牌", bool(token), f"HTTP {r.status_code}")

    r = client.get("/api/admin/servers", headers=H)
    body = r.json() if r.status_code == 200 else {}
    kinds = {k["value"]: k for k in body.get("kinds") or []}
    check("四类服务器都下发元数据",
          set(kinds) == {"ea", "emby", "moviepilot", "qbittorrent"}, str(list(kinds)))
    check("只有 EA / Emby 有「当前使用」的概念",
          kinds["ea"]["activatable"] and kinds["emby"]["activatable"]
          and not kinds["moviepilot"]["activatable"] and not kinds["qbittorrent"]["activatable"])
    check("密钥类字段在元数据里被标成 secret",
          any(f.get("secret") for f in kinds["moviepilot"]["fields"])
          and any(f.get("secret") for f in kinds["qbittorrent"]["fields"]))
    check("清单初始为空", body.get("servers") == [] and body["summary"]["total"] == 0,
          str(body.get("servers")))

    # ==================== 3. 新增 MoviePilot / qBittorrent ====================
    print("\n--- 新增并体检 ---")
    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"主站 MoviePilot{suf}", "kind": "moviepilot", "url": fake_url,
        "config": {"api_key": MP_TOKEN, "username": MP_USER, "password": MP_PASS},
    })
    mp = (r.json() if r.status_code == 200 else {}).get("server") or {}
    mp_id = mp.get("id")
    check("MoviePilot 新增成功且体检通过",
          r.status_code == 200 and mp.get("last_check_ok") is True,
          str(mp.get("last_check_message"))[:90])
    check("能查订阅（API 密钥有效）", CALLS["mp_logins"] >= 0 and "订阅" in (mp.get("last_check_message") or ""),
          str(mp.get("last_check_message"))[:90])
    check("能提交订阅（用户名密码可登录）", "能提交订阅" in (mp.get("last_check_message") or ""),
          str(mp.get("last_check_message"))[:90])
    check("MoviePilot 配置里不回密钥明文",
          "api_key" not in (mp.get("config") or {}) and "password" not in (mp.get("config") or {})
          and set(mp.get("secret_keys") or []) == {"api_key", "password"},
          str(mp.get("secret_keys")))

    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"下载器 qB{suf}", "kind": "qbittorrent", "url": fake_url,
        "config": {"username": QB_USER, "password": QB_PASS, "savepath": "/downloads"},
    })
    qb = (r.json() if r.status_code == 200 else {}).get("server") or {}
    qb_id = qb.get("id")
    check("qBittorrent 新增成功且体检通过",
          r.status_code == 200 and qb.get("last_check_ok") is True,
          str(qb.get("last_check_message"))[:90])
    check("体检报告里带真实版本号", "v5.0.3" in (qb.get("last_check_message") or ""),
          str(qb.get("last_check_message"))[:90])

    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"密码错的 qB{suf}", "kind": "qbittorrent", "url": fake_url,
        "config": {"username": QB_USER, "password": "wrong-password"},
    })
    bad_qb = (r.json() if r.status_code == 200 else {}).get("server") or {}
    check("qB 密码不对时如实报错（qB 用 200 + Fails. 表示失败）",
          bad_qb.get("last_check_ok") is False and "密码" in (bad_qb.get("last_check_message") or ""),
          str(bad_qb.get("last_check_message"))[:80])

    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"连不上的 MoviePilot{suf}", "kind": "moviepilot", "url": "http://127.0.0.1:9",
        "config": {"api_key": MP_TOKEN},
    })
    dead_mp = (r.json() if r.status_code == 200 else {}).get("server") or {}
    check("连不上的服务不会假成功",
          dead_mp.get("last_check_ok") is False and bool(dead_mp.get("last_check_message")),
          str(dead_mp.get("last_check_message"))[:80])

    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"连不上的 EA{suf}", "kind": "ea", "url": "http://127.0.0.1:9",
    })
    dead_ea = (r.json() if r.status_code == 200 else {}).get("server") or {}
    check("EA 连不上时也如实报错", dead_ea.get("last_check_ok") is False,
          str(dead_ea.get("last_check_message"))[:80])

    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"没有凭据的 MoviePilot{suf}", "kind": "moviepilot", "url": fake_url, "config": {},
    })
    check("MoviePilot 一个凭据都不填时被拦住", r.status_code == 400,
          f"HTTP {r.status_code} {str(r.json().get('detail') if r.status_code == 400 else '')[:60]}")
    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"缺用户名的 qB{suf}", "kind": "qbittorrent", "url": fake_url, "config": {},
    })
    check("qBittorrent 缺用户名时被拦住", r.status_code == 400, f"HTTP {r.status_code}")

    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"主站 MoviePilot{suf}", "kind": "moviepilot", "url": fake_url,
    })
    check("重名会被拒绝", r.status_code == 409, f"HTTP {r.status_code}")

    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"地址不规范的 EA{suf}", "kind": "ea", "url": "emby.local:8096",
    })
    check("只填主机名（没协议）会被拒绝", r.status_code == 400, f"HTTP {r.status_code}")

    # ==================== 4. 激活：连不上的不能当入口 ====================
    print("\n--- 设为当前使用 ---")
    r = client.post(f"/api/admin/servers/{dead_ea['id']}/activate", headers=H)
    body = r.json() if r.status_code == 200 else {}
    check("连不上的 EA 不能被设为当前使用", body.get("success") is False, str(body.get("message"))[:60])
    check("被拒时旧配置没有被切走", config_of("emby_managed_url") != "http://127.0.0.1:9",
          config_of("emby_managed_url") or "（空）")

    r = client.post(f"/api/admin/servers/{mp_id}/activate", headers=H)
    body = r.json() if r.status_code == 200 else {}
    check("MoviePilot 不需要「当前使用」（多台可同时用）",
          body.get("success") is True and body.get("activated") is False,
          str(body.get("message"))[:60])

    # 真的 EA：激活以后旧的 Emby 配置键必须换过去，否则网关闸门还是看旧地址
    r = client.post("/api/admin/servers", headers=H, json={
        "name": f"主站 EA{suf}", "kind": "ea", "url": ea_url,
    })
    ea_row = (r.json() if r.status_code == 200 else {}).get("server") or {}
    check("EA 新增且体检通过", ea_row.get("last_check_ok") is True,
          str(ea_row.get("last_check_message"))[:80])

    r = client.post(f"/api/admin/servers/{ea_row['id']}/activate", headers=H)
    body = r.json() if r.status_code == 200 else {}
    check("EA 设为当前使用成功", body.get("success") is True and body.get("activated") is True,
          str(body.get("message"))[:60])
    check("激活时顺带拉了 EA 视角的挂载体检", (body.get("mounts_health") or {}).get("ok") is True,
          str(body.get("mounts_health"))[:80])

    db = SessionLocal()
    try:
        row = db.query(models.RemoteServer).filter(models.RemoteServer.id == ea_row["id"]).first()
        check("激活后只有它被标为当前使用", row is not None and row.is_active is True)
        others = (db.query(models.RemoteServer)
                  .filter(models.RemoteServer.kind == "ea", models.RemoteServer.id != ea_row["id"]).all())
        check("同类其它 EA 的「当前使用」被清掉", all(o.is_active is False for o in others),
              str([o.is_active for o in others]))
    finally:
        db.close()

    check("旧配置 emby_managed_url 已被同步", config_of("emby_managed_url") == ea_url,
          config_of("emby_managed_url"))
    check("旧配置 emby_active_mode = managed_ea", config_of("emby_active_mode") == "managed_ea",
          config_of("emby_active_mode"))

    # 旧页面（Emby 服务入口）必须看到同一台：两个入口不能各说一套
    r = client.get("/api/admin/emby/servers", headers=H)
    legacy = r.json() if r.status_code == 200 else {}
    check("旧页面看到的 EA 地址与新清单一致",
          (legacy.get("managed_ea") or {}).get("url") == ea_url
          and (legacy.get("managed_ea") or {}).get("reachable") is True,
          str(legacy.get("managed_ea")))
    check("旧页面看到的模式是 managed_ea", legacy.get("active_mode") == "managed_ea",
          str(legacy.get("active_mode")))

    # 反向：旧页面保存外部 Emby → 清单里应出现一台「当前使用」的 Emby
    r = client.put("/api/admin/emby/servers", headers=H,
                   json={"mode": "external", "url": fake_url, "enabled": True, "api_key": "emby-key-x"})
    check("旧页面保存外部 Emby 成功", r.status_code == 200 and (r.json().get("probe") or {}).get("ok") is True,
          f"HTTP {r.status_code}")
    r = client.get("/api/admin/servers", headers=H)
    rows = (r.json() if r.status_code == 200 else {}).get("servers") or []
    emby_rows = [x for x in rows if x["kind"] == "emby"]
    check("旧页面保存后清单里出现这台 Emby 并标为当前使用",
          len(emby_rows) == 1 and emby_rows[0]["is_active"] is True
          and emby_rows[0]["last_check_ok"] is True,
          str([(x["name"], x["is_active"], x["last_check_ok"]) for x in emby_rows]))
    check("切到外部 Emby 后旧配置也跟着换", config_of("emby_active_mode") == "external"
          and config_of("emby_external_url") == fake_url,
          f"mode={config_of('emby_active_mode')} url={config_of('emby_external_url')}")
    r2 = client.get("/api/admin/servers", headers=H)
    summary = (r2.json() if r2.status_code == 200 else {}).get("summary") or {}
    check("统计卡口径正确（每类几台 / 几台可用 / 当前用哪台）",
          summary["kinds"]["ea"]["total"] == 2 and summary["kinds"]["ea"]["active_name"].startswith("主站 EA")
          and summary["kinds"]["moviepilot"]["total"] == 2
          and summary["kinds"]["qbittorrent"]["total"] == 2
          and summary["kinds"]["emby"]["total"] == 1,
          str({k: (v["total"], v["reachable"]) for k, v in summary["kinds"].items()}))
    check("求片可用目标只算「已启用且体检通过」的",
          set(summary["push_ready"]) == {"moviepilot", "qbittorrent"}, str(summary["push_ready"]))

    # ==================== 5. 密钥不出接口 ====================
    print("\n--- 密钥不外泄 ---")
    r = client.get("/api/admin/servers", headers=H)
    text = r.text
    check("响应里没有 MoviePilot 密码", MP_PASSWORD not in text)
    check("响应里没有 MoviePilot API_TOKEN", MP_TOKEN not in text)
    check("响应里没有 qB 密码", QB_PASSWORD not in text)
    check("响应里没有外部 Emby API Key", "emby-key-x" not in text)

    # ==================== 6. 求片转交 ====================
    print("\n--- 求片交给外部服务 ---")
    db = SessionLocal()
    try:
        req = models.MovieRequest(user_id=staff_id, movie_name=f"星际穿越{suf}", year="2014",
                                  type="movie", status="pending")
        db.add(req)
        db.commit()
        seek_id = req.id
    finally:
        db.close()

    r = client.post(f"/api/admin/media-seek/{seek_id}/push", headers=H,
                    json={"target": "moviepilot"})
    body = r.json() if r.status_code == 200 else {}
    check("推到 MoviePilot 成功", body.get("success") is True, str(body.get("message"))[:80])
    sent = CALLS["subscribe"][-1] if CALLS["subscribe"] else {}
    check("MoviePilot 收到的字段正确（片名/年份/类型）",
          sent.get("name") == f"星际穿越{suf}" and str(sent.get("year")) == "2014"
          and sent.get("type") == "电影",
          str(sent))
    check("推送成功后求片状态变成已批准", body.get("status") == "approved", str(body.get("status")))

    db = SessionLocal()
    try:
        row = db.query(models.MovieRequest).filter(models.MovieRequest.id == seek_id).first()
        check("推送结果落库（面板能看出交给谁、成没成）",
              row.push_target == "moviepilot" and row.push_status == "ok"
              and bool(row.push_message) and row.pushed_at is not None,
              f"{row.push_target}/{row.push_status}")
    finally:
        db.close()

    r = client.post(f"/api/admin/media-seek/{seek_id}/push", headers=H, json={"target": "qbittorrent"})
    body = r.json() if r.status_code == 200 else {}
    check("qB 没给链接时明确拒绝（它自己不会找片子）",
          body.get("success") is False and "链接" in (body.get("message") or ""),
          str(body.get("message"))[:80])

    magnet = f"magnet:?xt=urn:btih:{suf}&dn=Interstellar"
    r = client.post(f"/api/admin/media-seek/{seek_id}/push", headers=H,
                    json={"target": "qbittorrent", "link": magnet})
    body = r.json() if r.status_code == 200 else {}
    check("给链接后真的加进 qBittorrent", body.get("success") is True, str(body.get("message"))[:80])
    got = CALLS["torrents"][-1] if CALLS["torrents"] else {}
    check("qB 收到的链接与保存目录正确",
          got.get("urls") == magnet and got.get("savepath") == "/downloads", str(got))
    db = SessionLocal()
    try:
        row = db.query(models.MovieRequest).filter(models.MovieRequest.id == seek_id).first()
        check("qB 推送结果也落库", row.push_target == "qbittorrent" and row.push_status == "ok",
              f"{row.push_target}/{row.push_status}")
    finally:
        db.close()

    # 贴整段分享文本也应能从中挑出磁力链接
    r = client.post(f"/api/admin/media-seek/{seek_id}/push", headers=H,
                    json={"target": "qbittorrent", "link": f"看看这个 {magnet} 谢谢"})
    body = r.json() if r.status_code == 200 else {}
    last_torrent = CALLS["torrents"][-1] if CALLS["torrents"] else {}
    check("整段文本里能挑出磁力链接",
          body.get("success") is True and last_torrent.get("urls") == magnet,
          str(last_torrent)[:80])

    r = client.get(f"/api/admin/media-seek", headers=H)
    listed = r.json() if r.status_code == 200 else []
    row = next((x for x in listed if x["id"] == seek_id), {})
    check("求片列表回传转交状态（前端据此显示徽标）",
          row.get("push_target") == "qbittorrent" and row.get("push_status") == "ok"
          and bool(row.get("pushed_at")), str(row.get("push_status")))

    # ==================== 7. 停用 / 删除当前使用的 EA ====================
    print("\n--- 停用与删除 ---")
    emby_row_id = emby_rows[0]["id"] if emby_rows else None
    r = client.post(f"/api/admin/servers/{ea_row['id']}/toggle", headers=H)
    check("停用当前使用的 EA 会同时收回旧配置",
          r.status_code == 200 and config_of("emby_managed_enabled") == "false"
          and config_of("emby_active_mode") != "managed_ea",
          f"enabled={config_of('emby_managed_enabled')} mode={config_of('emby_active_mode')}")
    check("还有另一台激活的 Emby 时交给它，而不是直接关掉",
          config_of("emby_active_mode") == "external", config_of("emby_active_mode"))

    r = client.post(f"/api/admin/servers/{ea_row['id']}/toggle", headers=H)
    r = client.post(f"/api/admin/servers/{ea_row['id']}/activate", headers=H)
    check("重新启用后可以再切回来", (r.json() or {}).get("success") is True,
          str((r.json() or {}).get("message"))[:60])
    check("切回来后旧配置又指回 EA", config_of("emby_managed_url") == ea_url
          and config_of("emby_active_mode") == "managed_ea", config_of("emby_active_mode"))

    r = client.delete(f"/api/admin/servers/{ea_row['id']}", headers=H)
    check("删除当前使用的 EA 成功", r.status_code == 200 and r.json().get("success") is True,
          f"HTTP {r.status_code}")
    check("删除后不再指向一台不存在的服务",
          config_of("emby_active_mode") == "external" and config_of("emby_managed_enabled") == "false",
          f"mode={config_of('emby_active_mode')}")

    # 把另一类也删光：应该回到「面板自己出流」，而不是留在一个悬空模式上
    client.delete(f"/api/admin/servers/{emby_row_id}", headers=H)
    check("两类都没了以后回到面板自己出流", config_of("emby_active_mode") == "panel"
          and config_of("emby_external_enabled") == "false",
          f"mode={config_of('emby_active_mode')}")

    # 一个目标都没有时，求片推送要指向「服务器」页而不是静默失败
    client.delete(f"/api/admin/servers/{mp_id}", headers=H)
    client.delete(f"/api/admin/servers/{qb_id}", headers=H)
    r = client.post(f"/api/admin/media-seek/{seek_id}/push", headers=H, json={"target": "auto"})
    body = r.json() if r.status_code == 200 else {}
    check("没有可用服务时提示去「服务器」页添加",
          body.get("success") is False and "服务器" in (body.get("message") or ""),
          str(body.get("message"))[:90])

    r = client.post(f"/api/admin/servers/test", headers=H,
                    json={"kind": "qbittorrent", "url": fake_url,
                          "config": {"username": QB_USER, "password": QB_PASS}})
    check("「测试连接」也能测还没保存的配置",
          r.status_code == 200 and r.json().get("ok") is True, str(r.json())[:80])

    r = client.post("/api/admin/servers/999999/activate", headers=H)
    check("激活不存在的服务器返回 404", r.status_code == 404, f"HTTP {r.status_code}")
finally:
    fake_server.should_exit = True
    ea_server.should_exit = True
    fake_thread.join(timeout=10)
    ea_thread.join(timeout=10)
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
