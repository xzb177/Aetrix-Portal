"""多服运营冒烟测试（v2.6.20）

要解决的问题：一个后端服（EA）可以部署到多台服务器，每一台就是一套「服」，而面板要同时运营
多个服——**订阅、套餐、媒体库、挂载、卡码、求片、播放节点全部是一个服一个的**。这一版需要
证明的不是「界面上多了一页」，而是下面这些口径真的成立：

1. **升级不改变行为**：没有任何服时自动建默认服 `main`，老数据回填给它，历史配置键名不变
   （默认服读 `emby_active_mode`，其它服读 `emby_active_mode__r<id>`）；
2. **套餐一个服一个**：不带 `realm_id` 建套餐归当前服；默认只列当前服的套餐，`realm_id=0` 才跨服；
3. **会员一个服一个**：给用户开 B 服的会员，不能让他在 A 服的 EA 上播放
   （`backend.subscriptions.has_active_subscription` 按服判定）；
4. **订阅清单按服**：`/api/admin/realms/{id}/subscriptions` 只看到那个服的（`0` = 全部服），
   支持按用户名搜索；
5. **服务器按服 + 内容自动化可共用**：EA 归某个服，MoviePilot / qB 声明 `shared` 后归属留空，
   于是每个服的清单里都能看到它；
6. **多台 EA 同时出流的内容边界**：`nodes.visible_library_ids` 同时按「服」与「节点」过滤——
   未分配的库（node_id 为空）所有节点都看得见，已分配的库只有归属节点看得见；
7. **删服要移交**：有数据的服必须指定 `move_to`，默认服永远不能删。

本脚本自己起一套临时 SQLite 库，用真管理端接口（不是直接调函数）走完整链路。
"""
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "smoke-test-only-secret-key-not-for-production")

# **强制**用自己的库：断言涉及全局状态（「初始没有服」「当前服是谁」），
# CI 里所有冒烟脚本共用一个 DATABASE_URL，别的脚本留下的数据会把这些断言弄脏。
DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

from fastapi.testclient import TestClient  # noqa: E402

from backend import codes, models, realms  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.main import app as em_app  # noqa: E402
from backend.security import hash_password  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import nodes as node_lib  # noqa: E402

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
PASSWORD = "pass12345"

# ==================== 1. 升级：默认服与历史键名 ====================

print("\n--- 升级兼容：默认服 / 历史配置键 ---")
db = SessionLocal()
try:
    check("空库首次启动自动建默认服（slug=main）",
          [(r.name, r.slug) for r in realms.list_realms(db)] == [("默认服", "main")],
          str([(r.id, r.slug) for r in realms.list_realms(db)]))
    default = realms.active_realm(db)
    check("当前服回退到默认服", realms.active_realm_id(db) == default.id, str(default.id))
    check("默认服沿用历史键名（老部署行为不变）",
          realms.realm_key(db, "emby_active_mode", default.id) == "emby_active_mode")
    check("默认服没有对外地址时回退全局 EMBY_PUBLIC_URL 的语义存在",
          realms.realm_public_url(db, default.id) ==
          (os.getenv("EMBY_PUBLIC_URL", "").rstrip("/")))
    default_id = default.id
finally:
    db.close()

# ==================== 2. 管理端：建服 / 改名 / 切换 / 删服 ====================

db = SessionLocal()
try:
    staff = models.WebUser(username=f"realm_staff{suf}", password_hash=hash_password(PASSWORD),
                           is_staff=True, is_active=True)
    db.add(staff)
    db.commit()
    staff_id = staff.id
finally:
    db.close()

client = TestClient(em_app)

r = client.post("/api/user/auth/login", json={"username": f"realm_staff{suf}", "password": PASSWORD})
token = r.json()["access_token"] if r.status_code == 200 else ""
H = {"Authorization": f"Bearer {token}"}
check("管理员登录拿到令牌", bool(token), f"HTTP {r.status_code}")

print("\n--- 服的增删改查 ---")
r = client.get("/api/admin/realms")
check("匿名访问服清单被拒", r.status_code in (401, 403), f"HTTP {r.status_code}")

r = client.get("/api/admin/realms", headers=H)
body = r.json() if r.status_code == 200 else {}
check("服清单含当前服与跨服汇总",
      body.get("active_realm_id") == default_id and body.get("summary", {}).get("total_realms") == 1,
      str(body.get("summary")))

r = client.post("/api/admin/realms", headers=H,
                json={"name": f"二服{suf}", "slug": f"second{suf}", "url": "https://b.example.com/"})
created = r.json().get("realm", {}) if r.status_code == 200 else {}
realm_b = created.get("id")
check("建第二个服成功，地址去掉尾部斜杠",
      r.status_code == 200 and bool(realm_b) and created.get("url") == "https://b.example.com",
      f"HTTP {r.status_code}")

r = client.post("/api/admin/realms", headers=H, json={"name": f"二服{suf}", "slug": f"again{suf}"})
check("同名服被拒", r.status_code == 400, f"HTTP {r.status_code}")

r = client.post("/api/admin/realms", headers=H, json={"name": f"坏 slug{suf}", "slug": "Bad Slug"})
check("非法 slug 被拒", r.status_code == 400, f"HTTP {r.status_code}")

r = client.post(f"/api/admin/realms/{realm_b}/activate", headers=H)
check("切换当前服成功", r.status_code == 200 and r.json().get("active_realm_id") == realm_b,
      f"HTTP {r.status_code}")
check("切换当前服会落库（所有管理员看到同一个作用域）", (
    lambda: (lambda d: realms.active_realm_id(d) == realm_b)(SessionLocal()))())
check("历史键名不受影响的只是默认服，新服用 __r<id> 后缀", (
    lambda: (lambda d: realms.realm_key(d, "emby_active_mode", realm_b) == f"emby_active_mode__r{realm_b}")(
        SessionLocal()))())

r = client.put(f"/api/admin/realms/{realm_b}", headers=H,
               json={"name": f"二服改名{suf}", "description": "面向夜间用户"})
check("改名 / 描述可保存",
      r.status_code == 200 and r.json()["realm"]["name"] == f"二服改名{suf}", f"HTTP {r.status_code}")

# ==================== 3. 套餐：一个服一个 ====================

print("\n--- 套餐（一个服一个）---")
# 当前服 = 二服
r = client.post("/api/admin/economy/plans", headers=H,
                json={"name": f"B 月付{suf}", "price": 29.9, "duration_days": 30})
check("不带 realm_id 建套餐：归当前服", r.status_code == 200, f"HTTP {r.status_code}")
plan_b = r.json().get("id")

r = client.post(f"/api/admin/realms/{default_id}/activate", headers=H)
check("切回默认服", r.status_code == 200 and r.json().get("active_realm_id") == default_id,
      f"HTTP {r.status_code}")

r = client.post("/api/admin/economy/plans", headers=H,
                json={"name": f"A 月付{suf}", "price": 19.9, "duration_days": 30})
plan_a = r.json().get("id")
check("在默认服建套餐成功", r.status_code == 200, f"HTTP {r.status_code}")

r = client.get("/api/admin/economy/plans", headers=H)
plans = {p["name"]: p for p in r.json().get("plans", [])}
check("套餐清单默认只看当前服（A）",
      f"A 月付{suf}" in plans and f"B 月付{suf}" not in plans, str(list(plans)))
check("套餐带归属服名称", plans[f"A 月付{suf}"]["realm_name"] == "默认服",
      str(plans[f"A 月付{suf}"].get("realm_name")))

r = client.get("/api/admin/economy/plans", headers=H, params={"realm_id": 0})
all_plans = {p["name"] for p in r.json().get("plans", [])}
check("realm_id=0 才是跨服汇总", {f"A 月付{suf}", f"B 月付{suf}"} <= all_plans, str(all_plans))

r = client.post("/api/admin/economy/plans", headers=H,
                json={"name": f"坏套餐{suf}", "price": 1, "duration_days": 30, "realm_id": 99999})
check("套餐归属不存在的服被拒", r.status_code == 400, f"HTTP {r.status_code}")

# 用户端：套餐按服下发
r = client.get("/api/user/subscription-plans")
plans = {p["name"]: p for p in (r.json() if r.status_code == 200 else [])}
check("用户端默认只看到当前服（A）的套餐",
      f"A 月付{suf}" in plans and f"B 月付{suf}" not in plans, str(list(plans)))
r = client.get("/api/user/subscription-plans", params={"realm_id": 0})
check("用户端 realm_id=0 看到全部服的套餐",
      {f"A 月付{suf}", f"B 月付{suf}"} <= {p["name"] for p in r.json()}, str(r.status_code))

# ==================== 4. 会员：一个服一个 ====================

print("\n--- 会员（一个服一个）---")
db = SessionLocal()
try:
    member = models.WebUser(username=f"realm_user{suf}", password_hash=hash_password(PASSWORD),
                            is_staff=False, is_active=True)
    db.add(member)
    db.commit()
    member_id = member.id
finally:
    db.close()

r = client.post(f"/api/admin/users/{member_id}/subscriptions", headers=H,
                json={"plan_id": plan_b, "duration_days": 30})
check("按 B 服的套餐给用户开会员", r.status_code == 200, f"HTTP {r.status_code}")

db = SessionLocal()
try:
    sub = (db.query(models.UserSubscription)
           .filter(models.UserSubscription.user_id == member_id).first())
    check("会员落在套餐所属的服（B）", sub is not None and sub.realm_id == realm_b,
          f"realm_id={getattr(sub, 'realm_id', None)}")
    from backend import subscriptions

    check("A 服判定：不是会员（甲服的票不能在白瞟乙服）",
          not subscriptions.has_active_subscription(db, member_id, default_id))
    check("B 服判定：是会员", subscriptions.has_active_subscription(db, member_id, realm_b))
    check("不指定服时（单服部署口径）仍判为会员",
          subscriptions.has_active_subscription(db, member_id))
finally:
    db.close()

# 用**用户自己**的令牌看自己的会员：多服下要能分清哪份是哪个服的
r = client.post("/api/user/auth/login", json={"username": f"realm_user{suf}", "password": PASSWORD})
user_token = r.json()["access_token"] if r.status_code == 200 else ""
r = client.get("/api/user/subscriptions", headers={"Authorization": f"Bearer {user_token}"})
subs = r.json() if r.status_code == 200 else []
member_subs = subs if isinstance(subs, list) else subs.get("subscriptions", [])
check("用户端会员列表带归属服名称（多服会员分得清）",
      any(s.get("realm_name") == f"二服改名{suf}" for s in member_subs),
      str([(s.get("plan_name"), s.get("realm_name")) for s in member_subs]))

# ==================== 5. 订阅清单按服 + 搜索 ====================

print("\n--- 订阅清单（按服 / 搜索）---")
r = client.get(f"/api/admin/realms/{realm_b}/subscriptions", headers=H)
body = r.json() if r.status_code == 200 else {}
check("B 服的订阅清单里有这条会员",
      r.status_code == 200 and any(s["realm_id"] == realm_b for s in body.get("subscriptions", [])),
      f"HTTP {r.status_code}")
check("B 服清单里的会员带所属服名称",
      all(s.get("realm_name") == f"二服改名{suf}" for s in body.get("subscriptions", []) if s["realm_id"]),
      str(body.get("realm_name")))
check("B 服的生效订阅数 = 1", body.get("summary", {}).get("active") == 1, str(body.get("summary")))

r = client.get(f"/api/admin/realms/{default_id}/subscriptions", headers=H)
body_a = r.json() if r.status_code == 200 else {}
check("A 服的订阅清单里看不到 B 服的会员",
      all(s["realm_id"] != realm_b for s in body_a.get("subscriptions", [])),
      str([s["realm_id"] for s in body_a.get("subscriptions", [])]))
check("A 服的生效订阅数为 0", body_a.get("summary", {}).get("active") == 0, str(body_a.get("summary")))

r = client.get(f"/api/admin/realms/{realm_b}/subscriptions", headers=H,
               params={"search": f"realm_user{suf}"})
check("订阅清单支持按用户名搜索（命中）",
      len(r.json().get("subscriptions", [])) == 1, f"HTTP {r.status_code}")
r = client.get(f"/api/admin/realms/{realm_b}/subscriptions", headers=H,
               params={"search": "根本不存在的用户"})
check("订阅清单搜索不命中时为空", r.json().get("subscriptions") == [])

r = client.get("/api/admin/realms/0/subscriptions", headers=H)
check("realm_id=0 看全部服的订阅",
      any(s["realm_id"] == realm_b for s in r.json().get("subscriptions", [])),
      f"HTTP {r.status_code}")

# ==================== 6. 服务器：EA 归服，内容自动化可共用 ====================

print("\n--- 服务器（EA 一个服一个 / MoviePilot 可共用）---")
r = client.post("/api/admin/servers", headers=H, json={
    "name": f"A 服 EA{suf}", "kind": "ea", "url": "http://127.0.0.1:9/", "realm_id": default_id,
})
check("给 A 服加一台 EA", r.status_code == 200, f"HTTP {r.status_code}")
ea_a = r.json().get("server", {}).get("id")

r = client.post("/api/admin/servers", headers=H, json={
    "name": f"B 服 EA{suf}", "kind": "ea", "url": "http://127.0.0.1:9/", "realm_id": realm_b,
})
ea_b = r.json().get("server", {}).get("id")
check("给 B 服加一台 EA（同一个后端服部署到多台机器）",
      r.status_code == 200 and ea_b != ea_a, f"HTTP {r.status_code}")

r = client.post("/api/admin/servers", headers=H, json={
    "name": f"共用 MoviePilot{suf}", "kind": "moviepilot", "url": "http://127.0.0.1:9/",
    "config": {"api_key": "x", "username": "u", "password": "p"}, "shared": True,
})
mp = r.json().get("server", {}) if r.status_code == 200 else {}
check("内容自动化可以声明「全服共用」（归属留空）",
      r.status_code == 200 and mp.get("shared") is True and mp.get("realm_id") is None,
      f"HTTP {r.status_code} realm_id={mp.get('realm_id')}")

r = client.get("/api/admin/servers", headers=H)  # 当前服 = A
names = {s["name"] for s in r.json().get("servers", [])}
check("A 服清单：自己那台 EA + 共用的 MoviePilot，看不到 B 服的 EA",
      f"A 服 EA{suf}" in names and f"共用 MoviePilot{suf}" in names and f"B 服 EA{suf}" not in names,
      str(sorted(names)))

r = client.get("/api/admin/servers", headers=H, params={"realm_id": realm_b})
names_b = {s["name"] for s in r.json().get("servers", [])}
check("B 服清单：B 服的 EA + 同一台共用 MoviePilot",
      f"B 服 EA{suf}" in names_b and f"共用 MoviePilot{suf}" in names_b and f"A 服 EA{suf}" not in names_b,
      str(sorted(names_b)))

r = client.get("/api/admin/servers", headers=H, params={"realm_id": 0})
names_all = {s["name"] for s in r.json().get("servers", [])}
check("realm_id=0 看到全部服的服务器",
      {f"A 服 EA{suf}", f"B 服 EA{suf}", f"共用 MoviePilot{suf}"} <= names_all, str(sorted(names_all)))

# EA 的归属就是「一个服一个」：把 B 服的 EA 改成 A 服
r = client.put(f"/api/admin/servers/{ea_b}", headers=H, json={
    "name": f"B 服 EA{suf}", "kind": "ea", "url": "http://127.0.0.1:9/", "realm_id": default_id,
})
check("EA 可以改归属服（把机器调到另一个服）",
      r.status_code == 200 and r.json()["server"]["realm_id"] == default_id, f"HTTP {r.status_code}")

# ==================== 7. 多台 EA 的内容边界 ====================

# ==================== 6.5 媒体库归属：创建时就要能指定服与节点 ====================

print("\n--- 媒体库归属（服 / 播放节点）---")
# 前面那台 B 服 EA 已经被改到默认服（测过「改归属」），这里再添一台真属于 B 的节点
r = client.post("/api/admin/servers", headers=H, json={
    "name": f"B 服 EA2{suf}", "kind": "ea", "url": "http://127.0.0.1:9/", "realm_id": realm_b,
})
node_b = (r.json().get("server") or {}).get("id") if r.status_code == 200 else None
check("B 服可以再添一台播放节点（一个服多台机器）",
      r.status_code == 200 and bool(node_b), f"HTTP {r.status_code}")

media_dir = tempfile.mkdtemp(prefix="realm_lib_")
r = client.post("/api/admin/emby/mounts", headers=H, json={
    "name": f"B 服挂载{suf}", "mount_type": "local", "path": media_dir, "realm_id": realm_b,
})
mount_b = (r.json().get("mount") or {}).get("id") if r.status_code == 200 else None
check("存储挂载可以指定归属服",
      r.status_code == 200 and (r.json()["mount"].get("realm_id") == realm_b), f"HTTP {r.status_code}")

r = client.post("/api/admin/emby/libraries", headers=H, json={
    "name": f"B 服库{suf}", "collection_type": "movies", "paths": [],
    "mount_ids": [mount_b], "realm_id": realm_b, "node_id": node_b,
})
lib_b_id = (r.json() or {}).get("id") if r.status_code == 200 else None
check("新建媒体库时可以一并指定归属服与播放节点",
      r.status_code == 200 and bool(lib_b_id), f"HTTP {r.status_code} {(r.text or '')[:80]}")

db = SessionLocal()
try:
    lib = db.query(em.Library).filter(em.Library.id == lib_b_id).first()
    check("库的归属真的落库了（服 + 节点）",
          lib is not None and lib.realm_id == realm_b and lib.node_id == node_b,
          f"realm_id={getattr(lib, 'realm_id', None)} node_id={getattr(lib, 'node_id', None)}")
finally:
    db.close()

# 跨服出流必须被拒：库在 B 服，节点却属于默认服（ea_b 前面被改到了默认服）
r = client.post("/api/admin/emby/libraries", headers=H, json={
    "name": f"跨服库{suf}", "collection_type": "movies", "paths": [],
    "mount_ids": [mount_b], "realm_id": realm_b, "node_id": ea_b,
})
check("把库分配给不属于该服的节点会被拒（避免跨服出流）",
      r.status_code == 400, f"HTTP {r.status_code} {r.text[:60]}")

r = client.put(f"/api/admin/emby/libraries/{lib_b_id}", headers=H, json={"node_id": None})
check("库可以改成未分配节点（所有节点可见、由面板扫描）", r.status_code == 200, f"HTTP {r.status_code}")

db = SessionLocal()
try:
    lib = db.query(em.Library).filter(em.Library.id == lib_b_id).first()
    check("未分配节点的库确实不再指定归属节点", lib is not None and lib.node_id is None,
          f"node_id={getattr(lib, 'node_id', None)}")
finally:
    db.close()

r = client.put(f"/api/admin/emby/libraries/{lib_b_id}", headers=H, json={"node_id": node_b})
check("再把它分配回那台节点", r.status_code == 200, f"HTTP {r.status_code} {(r.text or '')[:80]}")

# ==================== 7. 多台 EA 同时出流（内容边界）====================

print("\n--- 多台 EA 同时出流（内容边界）---")
db = SessionLocal()
try:
    lib_a = em.Library(guid=f"lib-a-{suf}", name=f"A 服库{suf}", realm_id=default_id)
    lib_b = em.Library(guid=f"lib-b-{suf}", name=f"B 服库 2{suf}", realm_id=realm_b)
    b_lib_65 = lib_b_id  # 6.5 里按服建的库也在 B 服
    # A 服里有一台节点专属的库（只有它能碰到那些文件）
    lib_a2 = em.Library(guid=f"lib-a2-{suf}", name=f"A 服节点库{suf}", realm_id=default_id, node_id=ea_a)
    db.add_all([lib_a, lib_b, lib_a2])
    db.commit()
    lib_a_id, lib_b_id, lib_a2_id = lib_a.id, lib_b.id, lib_a2.id
finally:
    db.close()

db = SessionLocal()
try:
    check("A 服（不限节点）能看到：未分配的库 + 本服节点库，看不到 B 服的库",
          node_lib.visible_library_ids(db, realm_id=default_id) == {lib_a_id, lib_a2_id},
          str(sorted(node_lib.visible_library_ids(db, realm_id=default_id))))
    check("A 服那台节点能看到未分配的库与它自己的库",
          node_lib.visible_library_ids(db, realm_id=default_id, node_id=ea_a) == {lib_a_id, lib_a2_id})
    check("另一台节点看不到别人负责的库（同一份规则管可见性与扫描归属）",
          node_lib.visible_library_ids(db, realm_id=default_id, node_id=ea_b) == {lib_a_id})
    check("B 服只看得到 B 服的库（含前面按服建的库）",
          node_lib.visible_library_ids(db, realm_id=realm_b) == {lib_b_id, b_lib_65})
    check("既没配服也没配节点时不过滤（单机单服部署零影响）",
          node_lib.visible_library_ids(db, realm_id=None, node_id=None) is None)
    check("条目可见性按所属库判定",
          node_lib.library_visible(db, lib_a2_id, node_id=ea_b, realm_id=default_id) is False
          and node_lib.library_visible(db, lib_a2_id, node_id=ea_a, realm_id=default_id) is True)
finally:
    db.close()

# 服统计与序列化里要能看出「这个服有几台节点」
db = SessionLocal()
try:
    data = realms.serialize(db, realms.get_realm(db, default_id))
    check("服序列化带节点清单与运营数据",
          data["stats"]["libraries"] == 2 and len(data["nodes"]) == 2,
          f"libraries={data['stats']['libraries']} nodes={len(data['nodes'])}")
finally:
    db.close()

# ==================== 7.5 卡码 / 求片 / 挂载：补齐按服 ====================

print("\n--- 卡码（一个服一个：开的就是归属服的会员）---")
r = client.post("/api/admin/registration-codes/generate", headers=H,
                json={"code_type": 1, "count": 1, "days": 30, "expires_days": 30,
                      "realm_id": realm_b})
body = r.json() if r.status_code == 200 else {}
code_b = (body.get("codes") or [{}])[0].get("code")
check("生成卡码时可以指定归属服",
      r.status_code == 200 and body.get("realm_id") == realm_b and bool(code_b),
      f"HTTP {r.status_code} {body.get('message')}")

r = client.get("/api/admin/registration-codes/list", headers=H,
               params={"code_type": 1, "realm_id": realm_b})
codes_b = {c["code"]: c for c in r.json().get("codes", [])}
check("卡码清单按服过滤，且带归属服名称",
      code_b in codes_b and codes_b[code_b].get("realm_name") == f"二服改名{suf}",
      str([(c['code'], c.get('realm_name')) for c in codes_b.values()][:3]))
check("清单同时下发可选服（生成弹窗要用）",
      len(r.json().get("realms") or []) >= 2, str(r.json().get("realms")))

r = client.get("/api/admin/registration-codes/list", headers=H, params={"code_type": 1})
codes_default = {c["code"] for c in r.json().get("codes", [])}
check("默认只看当前服（A）的卡码，B 服的不会混进来",
      code_b not in codes_default, f"当前服={r.json().get('realm_name')}")

r = client.get("/api/admin/registration-codes/list", headers=H, params={"code_type": 1, "realm_id": 0})
check("realm_id=0 才跨服汇总卡码",
      code_b in {c["code"] for c in r.json().get("codes", [])}, str(r.status_code))

r = client.get("/api/admin/registration-codes/stats", headers=H, params={"realm_id": realm_b})
stat_b = r.json() if r.status_code == 200 else {}
check("卡码统计按服（B 服的统计只算 B 服的码）",
      stat_b.get("realm_id") == realm_b and stat_b.get("total") == 1,
      f"total={stat_b.get('total')} realm={stat_b.get('realm_name')}")

# 一个「只有 A 服会员」的用户来核销 B 服的注册码：旧实现在这里会误报「已有会员」
db = SessionLocal()
try:
    solo = models.WebUser(username=f"code_user{suf}", password_hash=hash_password(PASSWORD),
                          is_staff=False, is_active=True)
    db.add(solo)
    db.commit()
    solo_id = solo.id
finally:
    db.close()

r = client.post(f"/api/admin/users/{solo_id}/subscriptions", headers=H,
                json={"plan_id": plan_a, "duration_days": 30})
check("先给这个用户开 A 服会员", r.status_code == 200, f"HTTP {r.status_code}")

db = SessionLocal()
try:
    sub_a = (db.query(models.UserSubscription)
             .filter(models.UserSubscription.user_id == solo_id).first())
    sub_a_end = sub_a.end_date
    check("A 服会员落在 A 服", sub_a.realm_id == default_id, f"realm_id={sub_a.realm_id}")
finally:
    db.close()

r = client.post("/api/user/auth/login", json={"username": f"code_user{suf}", "password": PASSWORD})
solo_token = r.json()["access_token"] if r.status_code == 200 else ""
SH = {"Authorization": f"Bearer {solo_token}"}

# 只有 A 服会员：求片不选服也该自动归 A（这一步必须在核销 B 服卡码之前做，
# 否则这个用户就变成「持有两个服的会员」了，正确的行为反而是不猜）
r = client.post("/api/user/media-seek", headers=SH,
                json={"movie_name": f"单服默认片{suf}", "type": "movie"})
check("只有一个服的会员时，求片自动归到那个服", r.status_code == 200, f"HTTP {r.status_code}")
seek_solo_id = r.json().get("request_id")

db = SessionLocal()
try:
    req = db.query(models.MovieRequest).filter(models.MovieRequest.id == seek_solo_id).first()
    check("自动归属落库为 A 服", req is not None and req.realm_id == default_id,
          f"realm_id={getattr(req, 'realm_id', None)}")
finally:
    db.close()

r = client.post("/api/user/membership/redeem/preview", headers=SH, json={"code": code_b})
check("卡码预检就告诉用户开的是哪个服的会员",
      r.status_code == 200 and r.json().get("realm_name") == f"二服改名{suf}",
      str(r.json().get("realm_name")))

r = client.post("/api/user/membership/redeem", headers=SH, json={"code": code_b})
check("A 服会员可以核销 B 服的注册码（不再被误判为「已有会员」）",
      r.status_code == 200, f"HTTP {r.status_code} {(r.text or '')[:80]}")

db = SessionLocal()
try:
    rows = (db.query(models.UserSubscription)
            .filter(models.UserSubscription.user_id == solo_id).all())
    by_realm = {s.realm_id: s for s in rows}
    check("B 服的注册码开的是 B 服的会员",
          realm_b in by_realm, str(sorted(r for r in by_realm if r is not None)))
    check("A 服的会员没有被那张 B 服的注册码改变",
          by_realm[default_id].end_date == sub_a_end,
          f"{sub_a_end} → {by_realm[default_id].end_date}")
    from backend import subscriptions as subs_lib

    check("付费墙口径成立：B 服是会员、A 服仍是会员",
          subs_lib.has_active_subscription(db, solo_id, realm_b)
          and subs_lib.has_active_subscription(db, solo_id, default_id))
finally:
    db.close()

# 续期码 / 白名单码：只在同一个服里叠加，不能去延长别服的会员
r = client.post("/api/admin/registration-codes/generate", headers=H,
                json={"code_type": 2, "count": 1, "days": 7, "expires_days": 30,
                      "realm_id": realm_b})
renew_b = (r.json().get("codes") or [{}])[0].get("code")
r = client.post("/api/user/membership/redeem", headers=SH, json={"code": renew_b})
check("B 服的续期码可以核销（叠加到 B 服的会员上）", r.status_code == 200,
      f"HTTP {r.status_code} {(r.text or '')[:80]}")

db = SessionLocal()
try:
    b_after = (db.query(models.UserSubscription)
               .filter(models.UserSubscription.user_id == solo_id,
                       models.UserSubscription.realm_id == realm_b).first())
    a_after = (db.query(models.UserSubscription)
               .filter(models.UserSubscription.user_id == solo_id,
                       models.UserSubscription.realm_id == default_id).first())
    check("B 服的续期码只延长 B 服的会员",
          b_after is not None and a_after is not None and a_after.end_date == sub_a_end,
          f"A={a_after.end_date} B={b_after.end_date}")
finally:
    db.close()

# 老数据（升级前生成、没有归属服）的卡码：按当前服算，单服部署行为不变
db = SessionLocal()
try:
    legacy = models.RegistrationCode(
        code=f"LEGACY{suf}", max_uses=1, use_count=0, is_active=True,
        code_type=1, days=30, expires_at=datetime.now() + timedelta(days=30),
        realm_id=None, source="admin",
    )
    db.add(legacy)
    db.commit()
    check("未标注归属的老卡码按当前服解释（不报错、不消失）",
          codes.code_realm_id(db, legacy) == realms.active_realm_id(db),
          f"code_realm={codes.code_realm_id(db, legacy)} active={realms.active_realm_id(db)}")
finally:
    db.close()

print("\n--- 求片（说清楚给哪个服求）---")
# 单服用户的「自动归属」已在上一节验证（必须在给他开第二个服的会员之前）

# 两个服都有会员的用户：必须自己选一个（不选就未标注，不替他猜）
db = SessionLocal()
try:
    dual = models.WebUser(username=f"dual_user{suf}", password_hash=hash_password(PASSWORD),
                          is_staff=False, is_active=True)
    db.add(dual)
    db.commit()
    dual_id = dual.id
finally:
    db.close()

for plan in (plan_a, plan_b):
    r = client.post(f"/api/admin/users/{dual_id}/subscriptions", headers=H,
                    json={"plan_id": plan, "duration_days": 30})
    check(f"给双服用户开会员（plan={plan}）", r.status_code == 200, f"HTTP {r.status_code}")

r = client.post("/api/user/auth/login", json={"username": f"dual_user{suf}", "password": PASSWORD})
dual_token = r.json()["access_token"] if r.status_code == 200 else ""
DH = {"Authorization": f"Bearer {dual_token}"}

r = client.get("/api/user/subscriptions", headers=DH)
dual_realms = {s.get("realm_id") for s in (r.json() if r.status_code == 200 else [])
               if s.get("status") == "active"}
check("双服用户的会员分得清两个服（前端据此给选择器）",
      {default_id, realm_b} <= dual_realms, str(dual_realms))

r = client.post("/api/user/media-seek", headers=DH,
                json={"movie_name": f"未选服片{suf}", "type": "movie"})
check("两个服都有会员又不选服时提交成功", r.status_code == 200, f"HTTP {r.status_code}")
db = SessionLocal()
try:
    req = db.query(models.MovieRequest).filter(
        models.MovieRequest.id == r.json().get("request_id")).first()
    check("没选就记成未标注（不替用户猜一个服）", req is not None and req.realm_id is None,
          f"realm_id={getattr(req, 'realm_id', None)}")
finally:
    db.close()

r = client.post("/api/user/media-seek", headers=DH,
                json={"movie_name": f"指定 B 服片{suf}", "type": "movie", "realm_id": realm_b})
seek_b_id = r.json().get("request_id") if r.status_code == 200 else None
check("用户明确选了服就按他选的记", r.status_code == 200, f"HTTP {r.status_code}")

db = SessionLocal()
try:
    req = db.query(models.MovieRequest).filter(models.MovieRequest.id == seek_b_id).first()
    check("指定 B 服的求片落在 B 服", req is not None and req.realm_id == realm_b,
          f"realm_id={getattr(req, 'realm_id', None)}")
finally:
    db.close()

r = client.post("/api/user/media-seek", headers=DH,
                json={"movie_name": f"坏服片{suf}", "realm_id": 99999})
check("指定不存在的服被拒", r.status_code == 400, f"HTTP {r.status_code}")

r = client.get("/api/user/media-seek", headers=DH)
rows = {x["id"]: x for x in r.json().get("requests", [])}
check("用户自己就能看到这条求片是给哪个服的",
      rows.get(seek_b_id, {}).get("realm_name") == f"二服改名{suf}",
      str(rows.get(seek_b_id, {}).get("realm_name")))

r = client.get("/api/admin/media-seek", headers=H, params={"realm_id": realm_b})
admin_b = {x["id"]: x for x in (r.json() if r.status_code == 200 else [])}
check("后台求片清单按服过滤，并带归属服",
      seek_b_id in admin_b and admin_b[seek_b_id].get("realm_name") == f"二服改名{suf}",
      f"HTTP {r.status_code}")

r = client.get("/api/admin/media-seek", headers=H, params={"realm_id": default_id})
admin_a = {x["id"] for x in (r.json() if r.status_code == 200 else [])}
check("B 服的求片不会出现在 A 服的清单里",
      seek_b_id not in admin_a and seek_solo_id in admin_a, str(sorted(admin_a)[:5]))

r = client.get("/api/admin/media-seek", headers=H, params={"realm_id": 0})
all_seek = {x["id"] for x in (r.json() if r.status_code == 200 else [])}
check("realm_id=0 跨服汇总求片", {seek_b_id, seek_solo_id} <= all_seek, str(len(all_seek)))

print("\n--- 存储挂载（按服列出与归属）---")
r = client.get("/api/admin/emby/mounts", headers=H, params={"realm_id": realm_b})
mounts_b = {m["id"]: m for m in r.json().get("mounts", [])}
check("挂载清单按服过滤", mount_b in mounts_b, f"HTTP {r.status_code} {sorted(mounts_b)}")
check("挂载响应带归属服名映射（列表要显示“归属服”）",
      str(realm_b) in {str(k) for k in (r.json().get("realm_names") or {})},
      str(r.json().get("realm_names")))

r = client.get("/api/admin/emby/mounts", headers=H, params={"realm_id": default_id})
mounts_a = {m["id"] for m in r.json().get("mounts", [])}
check("B 服的挂载不会出现在 A 服的清单里", mount_b not in mounts_a, str(sorted(mounts_a)))

r = client.post("/api/admin/emby/mounts", headers=H, json={
    "name": f"坏归属挂载{suf}", "mount_type": "local", "path": media_dir, "realm_id": 99999,
})
check("挂载归属不存在的服被拒", r.status_code == 400, f"HTTP {r.status_code}")

r = client.get("/api/admin/emby/mounts", headers=H, params={"realm_id": 0})
check("realm_id=0 跨服汇总挂载",
      mount_b in {m["id"] for m in r.json().get("mounts", [])}, str(r.status_code))

# ==================== 8. 删服：必须移交 ====================

print("\n--- 删服（数据移交）---")
r = client.delete(f"/api/admin/realms/{realm_b}", headers=H)
check("有数据的服不指定移交目标时被拒", r.status_code == 400, f"HTTP {r.status_code}")

r = client.delete(f"/api/admin/realms/{default_id}", headers=H)
check("默认服永远不能删", r.status_code == 400, f"HTTP {r.status_code}")

# 先把「当前服」切到别的服，避免删的是当前服
client.post(f"/api/admin/realms/{realm_b}/activate", headers=H)

r = client.delete(f"/api/admin/realms/{realm_b}", headers=H, params={"move_to": default_id})
check("指定移交目标后可以删", r.status_code == 200, f"HTTP {r.status_code}")

db = SessionLocal()
try:
    moved_plan = db.query(models.SubscriptionPlan).filter(models.SubscriptionPlan.id == plan_b).first()
    moved_sub = (db.query(models.UserSubscription)
                 .filter(models.UserSubscription.user_id == member_id).first())
    check("套餐随数据移交到目标服",
          moved_plan is not None and moved_plan.realm_id == default_id,
          f"realm_id={getattr(moved_plan, 'realm_id', None)}")
    check("会员随数据移交到目标服（用户会员继续有效）",
          moved_sub is not None and moved_sub.realm_id == default_id,
          f"realm_id={getattr(moved_sub, 'realm_id', None)}")
    check("被删的服连同它的每服配置键一起清掉",
          db.query(models.SystemConfig)
          .filter(models.SystemConfig.key == f"emby_active_mode__r{realm_b}").first() is None)
    check("当前服不会停在已被删除的服上",
          realms.active_realm_id(db) == default_id, str(realms.active_realm_id(db)))
    check("删服后只剩默认服", [r.id for r in realms.list_realms(db)] == [default_id])
finally:
    db.close()

# ==================== 收尾 ====================

print(f"\n{'=' * 60}")
if failures:
    print(f"❌ {len(failures)} / {checks} 项检查失败：")
    for name in failures:
        print(f"   - {name}")
    sys.exit(1)
print(f"✅ 多服运营冒烟全部通过（{checks} 项检查）")
