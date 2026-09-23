"""播放可达性冒烟测试（v2.28.0）

要防的那类故障（推荐拓扑下最容易踩）：

    EM（面板 / 控制面）扫描、刮削一切正常，item_count 也在涨；
    但内容其实只存在于 EM 那台机器上（本机目录 / local 挂载），
    出流的 EA（数据面）根本读不到 —— 客户端点播放才 404/502。

本测试断言 `reachability` 能把这件事在后台提前说清楚，并且只说有证据的话：

1. 面板自己出流（一体化）：本机路径的库 = ok（内容就在这台机器上）；
2. EA 出流 + 本机路径 / local 挂载：没体检证据 = warn（无法确认，给出改法），
   EA 体检明确报读不到 = bad；体检明确说能读到（两端同一份 NFS）= ok；
3. EA 出流 + 共享挂载（WebDAV 等）：体检 ok = ok、没体检 = warn、体检失败 = bad；
4. 停用挂载 / 挂载被删 = bad（面板一眼看出这条来源不会出内容）；
5. 已有 Emby 入口 + 本机路径 = warn（对方的库不是这台机器）；
6. 用户端地址一致性：面板关了协议面却仍让用户连面板 = bad；localhost 地址 = warn/bad；
7. 接口层：/api/admin/emby/reachability 与 /api/admin/emby/libraries 都带上判定。

不联网：EA 体检用的是写进 SystemConfig 的快照（真实结构，来自 EA 的
/api/admin/mounts/health）。
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
os.environ.setdefault("SECRET_KEY", "smoke-test-only-secret-key-not-for-production")
os.environ.pop("ENABLE_EMBY_GATEWAY", None)

from fastapi.testclient import TestClient  # noqa: E402

from backend import models, realms  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import mount_health, reachability  # noqa: E402
from backend.main import app  # noqa: E402
from backend.security import create_access_token, hash_password  # noqa: E402

init_db()
client = TestClient(app)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def make_admin() -> dict:
    with SessionLocal() as db:
        user = models.WebUser(username="reach_admin", password_hash=hash_password("pass12345"),
                              is_active=True, is_staff=True)
        db.add(user)
        db.commit()
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def seed() -> dict:
    """一个服 + 一台 EA + 三条挂载 + 五条库（覆盖判定矩阵）"""
    out: dict = {}
    with SessionLocal() as db:
        realm = realms.ensure_default_realm(db)
        out["realm_id"] = realm.id
        node = models.RemoteServer(name="EA-东京", kind="ea", realm_id=realm.id,
                                   node_key="ea-tokyo", url="https://ea.example.com",
                                   is_enabled=True, config="{}")
        db.add(node)
        db.commit()
        out["node_id"] = node.id

        def add_mount(name, mount_type, path="", enabled=True) -> int:
            mount = em.StorageMount(name=name, mount_type=mount_type, path=path,
                                    realm_id=realm.id, is_enabled=enabled, config="{}")
            db.add(mount)
            db.commit()
            return mount.id

        out["m_webdav"] = add_mount("共享影库", "webdav", "https://dav.example.com/media")
        out["m_local"] = add_mount("本机磁盘", "local", "/srv/media")
        out["m_nfs"] = add_mount("同路径 NFS", "local", "/mnt/nfs-media")
        out["m_off"] = add_mount("已停用挂载", "webdav", "https://old.example.com", enabled=False)

        def add_lib(name, *, mounts=(), paths=(), node_id=None, virtual=False,
                    enabled=True, realm_id=None) -> int:
            lib = em.Library(
                guid=f"guid-{name}", name=name, collection_type="movies",
                paths=",".join(paths), mount_ids=",".join(str(m) for m in mounts),
                realm_id=realm_id if realm_id is not None else realm.id,
                node_id=node_id, is_virtual=virtual, is_enabled=enabled,
            )
            db.add(lib)
            db.commit()
            return lib.id

        out["l_path"] = add_lib("本机路径库", paths=["/srv/media/movies"], node_id=node.id)
        out["l_webdav"] = add_lib("共享挂载库", mounts=[out["m_webdav"]], node_id=node.id)
        out["l_local"] = add_lib("本机挂载库", mounts=[out["m_local"]], node_id=node.id)
        out["l_nfs"] = add_lib("同路径库", mounts=[out["m_nfs"]], node_id=node.id)
        out["l_virtual"] = add_lib("虚拟聚合库", virtual=True, node_id=node.id)
        out["l_disabled"] = add_lib("停用库", mounts=[out["m_webdav"]], node_id=node.id,
                                    enabled=False)
    return out


def set_mode(mode: str, *, enabled: bool = True, url: str = "") -> None:
    """切换出流方式（与「服务器」页保存入口时的写入一致）"""
    with SessionLocal() as db:
        realms.set_realm_config(db, "emby_active_mode", mode)
        realms.set_realm_config(db, "emby_managed_enabled", "true" if enabled else "false")
        realms.set_realm_config(db, "emby_external_enabled",
                                "true" if (mode == "external" and enabled) else "false")
        realms.set_realm_config(db, "emby_managed_url", url)
        realms.set_realm_config(db, "emby_external_url", url if mode == "external" else "")
        db.commit()


def set_url(url: str) -> None:
    with SessionLocal() as db:
        realms.set_realm_config(db, "emby_managed_url", url)
        db.commit()


def write_snapshot(items: list[dict]) -> None:
    """写入 EA 视角的挂载体检快照（结构 = EA 的 /api/admin/mounts/health 返回）"""
    with SessionLocal() as db:
        mount_health.write_ea_health(db, {
            "service": "ea",
            "checked_at": datetime.now().isoformat(),
            "mounts": items,
            "total": len(items),
        })
        db.commit()


def set_ea_connected(value: bool) -> None:
    """面板里「服务器」页保存 EA 入口并连接成功后会写这个标记（见 
    POST /api/admin/emby/servers 的连接测试）：自建功能的全部门都要它才算通"""
    with SessionLocal() as db:
        realms.set_realm_config(db, "emby_managed_reachable", "true" if value else "false")
        db.commit()


def clear_snapshot() -> None:
    with SessionLocal() as db:
        db.query(models.SystemConfig).filter(
            models.SystemConfig.key == mount_health.EA_HEALTH_KEY).delete()
        db.commit()


def detail_of(field: str, lib_id: int) -> dict:
    with SessionLocal() as db:
        lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
        return reachability.library_reachability(db, lib)


def report() -> dict:
    with SessionLocal() as db:
        return reachability.summary(db)


ids = seed()
headers = make_admin()
print(f"\n--- 现场：服 #{ids['realm_id']} + EA「EA-东京」+ 4 条挂载 / 6 条库 ---\n")

# ==================== 1. 面板自己出流：本机路径没问题 ====================
print("--- 1. 一体化（面板本机出流）---")
set_mode("", enabled=False)
set_url("https://panel.example.com")
r = detail_of("l_path", ids["l_path"])
check("本机路径库：面板出流 → ok", r["level"] == "ok", f"{r['level']}/{r['code']}")
r = detail_of("l_webdav", ids["l_webdav"])
check("共享挂载库：面板出流 → ok（面板自己扫自己播）", r["level"] == "ok",
      f"{r['level']}/{r['code']}")
r = detail_of("l_nfs", ids["l_nfs"])
check("同路径本地挂载：面板出流 → ok", r["level"] == "ok", f"{r['level']}/{r['code']}")

# ==================== 2. EA 出流 + 无体检证据：只说「无法确认」 ====================
print("\n--- 2. 分离部署（EA 出流）+ 还没拉过 EA 体检 ---")
set_mode("managed_ea", url="https://emby.example.com")
os.environ["ENABLE_EMBY_GATEWAY"] = "false"  # EM 只跑控制面
clear_snapshot()
r = detail_of("l_path", ids["l_path"])
check("本机路径库：EA 出流无证据 → warn/local_path_unchecked",
      r["level"] == "warn" and r["code"] == "local_path_unchecked", f"{r['level']}/{r['code']}")
check("  提示里点明「看得到条目却播不了」并给出改法",
      "播不了" in r["message"] and "共享挂载" in r["fix"], r["message"])
check("  文案带上出流节点名", "EA-东京" in r["message"], r["message"])
r = detail_of("l_local", ids["l_local"])
check("本机挂载库：EA 出流无证据 → warn/host_local_unchecked",
      r["level"] == "warn" and r["code"] == "host_local_unchecked", f"{r['level']}/{r['code']}")
r = detail_of("l_webdav", ids["l_webdav"])
check("共享挂载库：EA 出流无证据 → warn/mount_unchecked（存疑不装 ok）",
      r["level"] == "warn" and r["code"] == "mount_unchecked", f"{r['level']}/{r['code']}")
check("  共享来源与主机相对来源分开报", r["shared_sources"] and not r["local_sources"],
      f"{r['shared_sources']} / {r['local_sources']}")

# ==================== 3. EA 体检快照：按证据升级/降级 ====================
print("\n--- 3. 拉过 EA 体检（按证据判定）---")
write_snapshot([
    {"id": ids["m_webdav"], "name": "共享影库", "ok": True, "message": "目录可读"},
    {"id": ids["m_local"], "name": "本机磁盘", "ok": False,
     "message": "路径不存在或不可读: /srv/media"},
    {"id": ids["m_nfs"], "name": "同路径 NFS", "ok": True, "message": "目录可读"},
    {"id": ids["m_off"], "name": "已停用挂载", "ok": None, "message": "已停用（未体检）"},
])
r = detail_of("l_webdav", ids["l_webdav"])
check("共享挂载库：EA 体检 ok → ok", r["level"] == "ok", f"{r['level']}/{r['code']}")
r = detail_of("l_local", ids["l_local"])
check("本机挂载库：EA 体检报读不到 → bad/mount_unreachable_on_node",
      r["level"] == "bad" and r["code"] == "mount_unreachable_on_node",
      f"{r['level']}/{r['code']}")
check("  bad 文案带上 EA 的原始报错", "路径不存在" in r["message"], r["message"])
r = detail_of("l_nfs", ids["l_nfs"])
check("同路径本地挂载：EA 体检 ok（两端同一份存储）→ ok", r["level"] == "ok",
      f"{r['level']}/{r['code']}")
r = detail_of("l_virtual", ids["l_virtual"])
check("虚拟库 → ok（内容随来源库）", r["level"] == "ok" and "虚拟库" in r["message"],
      f"{r['level']}/{r['code']}")
r = detail_of("l_path", ids["l_path"])
check("本机路径库：仍为 warn（本机目录没有体检通道）", r["level"] == "warn",
      f"{r['level']}/{r['code']}")

# ==================== 4. 停用 / 缺失的挂载 ====================
print("\n--- 4. 来源本身有问题 ---")
with SessionLocal() as db:
    lib = em.Library(guid="guid-off", name="停用来源库", collection_type="movies",
                     mount_ids=str(ids["m_off"]), realm_id=ids["realm_id"],
                     node_id=ids["node_id"], is_enabled=True)
    db.add(lib)
    db.commit()
    off_lib = lib.id
    missing_lib = em.Library(guid="guid-miss", name="引用已删挂载", collection_type="movies",
                             mount_ids="9999", realm_id=ids["realm_id"],
                             node_id=ids["node_id"], is_enabled=True)
    db.add(missing_lib)
    db.commit()
    missing_id = missing_lib.id
r = detail_of("l_off", off_lib)
check("停用挂载 → bad/mount_disabled", r["level"] == "bad" and r["code"] == "mount_disabled",
      f"{r['level']}/{r['code']}")
r = detail_of("l_miss", missing_id)
check("引用已删除的挂载 → bad/mount_missing",
      r["level"] == "bad" and r["code"] == "mount_missing", f"{r['level']}/{r['code']}")

# ==================== 5. 已有 Emby 入口 ====================
print("\n--- 5. 入口是已有 Emby 服务器 ---")
set_mode("external", url="https://my-emby.example.com")
r = detail_of("l_path", ids["l_path"])
check("本机路径库：已有 Emby 出流 → warn/external_emby_local_path",
      r["level"] == "warn" and any(p["code"] == "external_emby_local_path" for p in r["problems"]),
      f"{r['level']}/{r['code']}")
r = detail_of("l_webdav", ids["l_webdav"])
check("共享挂载库：已有 Emby → ok（不理我们自己的库来源）", r["level"] == "ok",
      f"{r['level']}/{r['code']}")

# ==================== 6. 用户端地址一致性 ====================
print("\n--- 6. 用户端该连哪个地址 ---")
set_mode("managed_ea", url="https://emby.example.com")
os.environ["ENABLE_EMBY_GATEWAY"] = "false"
with SessionLocal() as db:
    c = reachability.client_endpoint_check(db)
check("EA 入口 + 面板已关协议面 + 对外地址 → ok", c["level"] == "ok", f"{c['level']}/{c['code']}")

set_mode("", enabled=False)
os.environ["ENABLE_EMBY_GATEWAY"] = "false"
with SessionLocal() as db:
    c = reachability.client_endpoint_check(db)
check("面板已关协议面却仍让用户连面板 → bad/gateway_off_but_panel_entry",
      c["level"] == "bad" and c["code"] == "gateway_off_but_panel_entry", f"{c['level']}/{c['code']}")
check("  给出改法（入口改成 EA）", "EA" in c["fix"], c["fix"])

os.environ["ENABLE_EMBY_GATEWAY"] = "true"
set_mode("managed_ea", url="https://emby.example.com")
with SessionLocal() as db:
    c = reachability.client_endpoint_check(db)
check("面板还开着协议面但同时配了 EA → warn/panel_gateway_still_on",
      c["level"] == "warn" and c["code"] == "panel_gateway_still_on", f"{c['level']}/{c['code']}")
check("  gateway_enabled 反映实时环境", c["gateway_enabled"] is True)

set_mode("managed_ea", url="http://localhost:8000")
with SessionLocal() as db:
    c = reachability.client_endpoint_check(db)
check("地址解析成 localhost → warn/client_url_localhost",
      any(p["code"] == "client_url_localhost" for p in c["problems"]), f"{c['level']}/{c['problems']}")

# ==================== 7. 汇总与接口层 ====================
print("\n--- 7. 汇总与接口 ---")
set_mode("managed_ea", url="https://emby.example.com")
os.environ["ENABLE_EMBY_GATEWAY"] = "false"
write_snapshot([
    {"id": ids["m_webdav"], "name": "共享影库", "ok": True, "message": "目录可读"},
    {"id": ids["m_local"], "name": "本机磁盘", "ok": False, "message": "路径不存在: /srv/media"},
    {"id": ids["m_nfs"], "name": "同路径 NFS", "ok": True, "message": "目录可读"},
])
r = report()
check("汇总：停用的库不计入", r["counts"]["libraries"] == 7, str(r["counts"]))
check("汇总：bad 计数含「本机挂载库」与两条坏来源的库", r["counts"]["bad"] == 3, str(r["counts"]))
check("汇总：整体等级 = bad", r["level"] == "bad", r["level"])
check("汇总：坏库排前面（面板逐条修）",
      r["libraries"][0]["level"] == "bad" and r["libraries"][-1]["level"] == "ok",
      f"{[i['level'] for i in r['libraries']]}")
check("汇总：带出流方式与节点清单",
      r["playback"]["mode"] == "ea" and r["playback"]["targets"][0]["name"] == "EA-东京",
      str(r["playback"]["targets"]))

set_ea_connected(False)
resp = client.get("/api/admin/emby/reachability", params={"realm_id": 0}, headers=headers)
check("EA 尚未连接成功时：自建端点被闸门拦住（503，与既有自建端点一致）",
      resp.status_code == 503, str(resp.status_code))

set_ea_connected(True)
resp = client.get("/api/admin/emby/reachability", params={"realm_id": 0}, headers=headers)
check("GET /api/admin/emby/reachability → 200", resp.status_code == 200, str(resp.status_code))
api = resp.json() if resp.status_code == 200 else {}
check("  接口带 counts / playback / client_endpoint",
      api.get("counts", {}).get("bad") == 3 and "client_endpoint" in api and "playback" in api,
      str(api.get("counts")))

resp = client.get("/api/admin/emby/libraries", params={"realm_id": 0}, headers=headers)
check("GET /api/admin/emby/libraries → 200", resp.status_code == 200, str(resp.status_code))
libs = {l["name"]: l for l in (resp.json().get("libraries", []) if resp.status_code == 200 else [])}
check("  每条库都带 playback 判定",
      libs.get("本机挂载库", {}).get("playback", {}).get("level") == "bad"
      and libs.get("共享挂载库", {}).get("playback", {}).get("level") == "ok",
      str({k: v.get("playback", {}).get("level") for k, v in libs.items()}))
check("  停用的库仍在清单里（有 playback 字段）",
      libs.get("停用库", {}).get("playback", {}).get("level") in {"bad", "ok"},
      str(libs.get("停用库", {}).get("playback", {}).get("level")))

resp = client.get("/api/admin/emby/reachability")
check("未登录 → 401/403", resp.status_code in (401, 403), str(resp.status_code))

print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} 项")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("全部通过：播放可达性判定符合预期")
