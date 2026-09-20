"""115 下载与转存冒烟测试（v2.6.5）

覆盖 twilight-kotomi 的「115 下载与转存」一章，逐条对应：

- 分享链接解析：`?password=`、`#提取码`、中文口令、纯分享码、非法输入
- Cookie 配置档：多账号、默认账号、媒体库绑定、服务器级环境变量兜底与优先级
- 路径浏览使用「表单 Cookie → 账号配置档 → 已保存 Cookie」的顺序
- 转存 / 取下载地址任务：分享快照落库、按文件原子落盘、完成后触发扫描
- 任务续跑：进程被杀（running）后恢复，已完成文件不重复转存
- Cookie 失效：任务保留为 waiting_auth，重试后继续
- items / urls 永不为 null（旧实现会让前端转存记录页崩溃）

网络层整体被替换（`transfer115._http_json`），因此本测试不依赖真实 115 账号。
"""
import json
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("DATABASE_URL", "sqlite:///./royalbot_unified.db")
os.environ.setdefault("SECRET_KEY", "smoke-test-only-secret-key-not-for-production")
os.environ.pop("PAN115_COOKIE", None)  # 环境变量兜底单独测，默认先清空

from fastapi.testclient import TestClient

from backend import models
from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.emby_server import transfer115 as t115
from backend.main import app
from backend.security import hash_password

init_db()
client = TestClient(app)
suf = str(random.randint(100000, 999999))
failures: list[str] = []

# 分享码按运行随机生成：重复跑冒烟测试不会与上一轮的任务互相干扰
CODE_MAIN = f"share{suf}"
CODE_RESUME = f"resume{suf}"
CODE_WAIT = f"wait{suf}"
CODE_NOAUTH = f"noauth{suf}"
CODE_DOWN = f"down{suf}"
CODE_CANCEL = f"cancel{suf}"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


# ==================== 假 115 服务 ====================

class FakePan115:
    """替换 transfer115._http_json 的假后端：只实现本功能用到的端点"""

    def __init__(self) -> None:
        self.items = [
            {"fid": "f1", "n": "Alpha.Target.2024.1080p.NF.WEB-DL.mkv", "s": 100, "pc": "pc1", "fc": "1"},
            {"fid": "f2", "n": "Beta.Strike.2023.2160p.mkv", "s": 200, "pc": "pc2", "fc": "1"},
            {"fid": "f3", "n": "Gamma.S01.1080p", "s": 0, "pc": "", "fc": "0"},
        ]
        self.dirs = [
            {"fid": "d1", "cid": "100", "n": "电影", "fc": "0"},
            {"fid": "d2", "cid": "200", "n": "剧集", "fc": "0"},
        ]
        self.receive_calls: list[str] = []
        self.download_calls: list[str] = []
        self.snap_calls = 0
        self.auth_broken = False          # Cookie 失效（所有端点）
        self.fail_next_receive = False    # 单个文件业务失败

    def __call__(self, method, url, *, params=None, data=None, cookie="", timeout=None):
        if not cookie:
            raise t115.Pan115AuthError("未配置 115 Cookie")
        if self.auth_broken:
            raise t115.Pan115AuthError("Cookie 已失效")
        p = params or {}
        if url.endswith("/share/snap"):
            self.snap_calls += 1
            return {"state": True, "data": {"count": len(self.items), "list": self.items}}
        if url.endswith("/share/receive"):
            if self.fail_next_receive:
                self.fail_next_receive = False
                raise t115.Pan115Error("转存失败：目标目录不存在")
            self.receive_calls.append((data or {}).get("file_id", ""))
            return {"state": True, "data": {}}
        if url.endswith("/files/download"):
            self.download_calls.append(p.get("pickcode"))
            return {"state": True, "file_url": f"https://cdn.example.com/{p.get('pickcode')}"}
        if url.endswith("/files"):
            return {"state": True, "data": self.dirs}
        return {"state": True, "data": {}}


fake = FakePan115()
t115._http_json = fake  # 整体替换网络层


def run_now(task_id: int) -> None:
    """同步执行任务（测试里不用后台线程，保证断言确定）"""
    t115.run_task(task_id)


def get_task(task_id: int):
    db = SessionLocal()
    try:
        return db.query(em.Pan115Task).filter(em.Pan115Task.id == task_id).first()
    finally:
        db.close()


def wait_status(task_id: int, status: str, timeout: float = 8.0) -> str:
    deadline = time.time() + timeout
    seen = ""
    while time.time() < deadline:
        task = get_task(task_id)
        seen = task.status if task else "missing"
        if seen == status:
            return seen
        time.sleep(0.05)
    return seen


# ==================== 一、分享链接解析 ====================

print("--- 分享链接解析 ---")
p = t115.parse_share_link("https://115.com/s/abcdefghij?password=1234")
check("?password= 形式", p["share_code"] == "abcdefghij" and p["receive_code"] == "1234", str(p))

p = t115.parse_share_link("https://115.com/s/abcdefghij#1234")
check("#提取码 片段形式", p["receive_code"] == "1234", str(p))

p = t115.parse_share_link("点击查看 https://115.com/s/abcdefghij 提取码：abcd")
check("中文口令文本", p["share_code"] == "abcdefghij" and p["receive_code"] == "abcd", str(p))

p = t115.parse_share_link("abcdefghij")
check("纯分享码（无提取码）", p["share_code"] == "abcdefghij" and p["receive_code"] == "", str(p))

p = t115.parse_share_link("https://115cdn.com/s/ZZZZZZZZZZ#9x9x")
check("115cdn 域名 + 提取码", p["share_code"] == "ZZZZZZZZZZ" and p["receive_code"] == "9x9x", str(p))

try:
    t115.parse_share_link("这不是链接")
    check("非法输入被拒绝", False, "未抛异常")
except t115.ShareLinkError:
    check("非法输入被拒绝", True)


# ==================== 二、Cookie 配置档与优先级 ====================

print("\n--- Cookie 配置档与优先级 ---")
db = SessionLocal()

# 清掉上一轮冒烟测试遗留的配置档（命名带纯数字后缀），避免干扰优先级断言
import re as _re  # noqa: E402
for _row in db.query(em.Pan115Account).all():
    if _re.match(r"^(主号|影库号|停用号|转存号|下载号)\d+$", _row.name or ""):
        db.delete(_row)
db.commit()

acc_a = em.Pan115Account(name=f"主号{suf}", cookie="UID=aaa; CID=aaa", is_default=True)
acc_b = em.Pan115Account(name=f"影库号{suf}", cookie="UID=bbb; CID=bbb")
acc_off = em.Pan115Account(name=f"停用号{suf}", cookie="UID=ccc; CID=ccc", is_enabled=False)
db.add_all([acc_a, acc_b, acc_off])
db.commit()
for row in (acc_a, acc_b, acc_off):
    db.refresh(row)
acc_a_id, acc_b_id, acc_off_id = acc_a.id, acc_b.id, acc_off.id

cookie, source = t115.resolve_cookie(db)
check("无绑定时用默认账号", cookie == "UID=aaa; CID=aaa" and "默认账号" in source, source)

cookie, source = t115.resolve_cookie(db, account_id=acc_b_id)
check("显式账号优先", cookie == "UID=bbb; CID=bbb", source)

cookie, source = t115.resolve_cookie(db, explicit_cookie="UID=form; CID=form")
check("表单 Cookie 优先于默认账号", cookie == "UID=form; CID=form", source)

# 扫描根目录指向空临时目录：任务完成后触发的扫描必须快且不污染真实媒体库
library = em.Library(guid=f"lib{suf}", name=f"媒体库{suf}", collection_type="movies",
                     paths=tempfile.mkdtemp(prefix="pan115_lib_"), account_115_id=acc_b_id)
db.add(library)
db.commit()
db.refresh(library)

cookie, source = t115.resolve_cookie(db, library=library)
check("媒体库绑定账号生效", cookie == "UID=bbb; CID=bbb" and "绑定账号" in source, source)

library.account_115_id = acc_off_id  # 绑到停用账号
db.commit()
cookie, source = t115.resolve_cookie(db, library=library)
check("绑定账号停用时回退默认账号", cookie == "UID=aaa; CID=aaa", source)
library.account_115_id = acc_b_id
db.commit()

# 删除全部配置档后回落到服务器级环境变量
db.query(em.Pan115Account).filter(em.Pan115Account.id.in_([acc_a_id, acc_b_id, acc_off_id])).delete(
    synchronize_session=False
)
db.commit()
cookie, source = t115.resolve_cookie(db)
check("无配置档且无环境变量时返回空", cookie == "" and source == "未配置", source)

os.environ["PAN115_COOKIE"] = "UID=env; CID=env"
cookie, source = t115.resolve_cookie(db)
check("服务器级 PAN115_COOKIE 兜底", cookie == "UID=env; CID=env" and "PAN115_COOKIE" in source, source)
os.environ.pop("PAN115_COOKIE", None)

# 路径浏览的优先级：表单 Cookie > 配置档 > 已保存
cookie, source = t115.resolve_cookie(db, account_id=None, explicit_cookie="UID=form2; CID=form2")
check("浏览时表单 Cookie 优先", cookie == "UID=form2; CID=form2", source)

lib_path = library.paths
db.close()


# ==================== 三、管理端账号 API ====================

print("\n--- 管理端账号 API ---")
db = SessionLocal()
staff = models.WebUser(username=f"pan115_stf{suf}", password_hash=hash_password("pass12345"), is_staff=True)
db.add(staff)
db.commit()
db.refresh(staff)
staff_name = staff.username
staff_id = staff.id
db.close()

r = client.post("/api/user/auth/login", json={"username": staff_name, "password": "pass12345"})
assert r.status_code == 200, r.text
sh = {"Authorization": f"Bearer {r.json()['access_token']}"}

r = client.post("/api/admin/emby/115/accounts",
                json={"name": f"主号{suf}", "cookie": "UID=xxx; CID=xxx; SEID=yyy",
                      "is_default": True, "remark": "冒烟"}, headers=sh)
check("创建账号配置档", r.status_code == 200, r.text[:120])
acc_id = r.json()["account"]["id"]
check("Cookie 不回传明文",
      "cookie" not in r.json()["account"] and "UID=xxx" not in r.text, r.text[:120])

r = client.post("/api/admin/emby/115/accounts",
                json={"name": f"副号{suf}", "cookie": "UID=yyy; CID=yyy", "is_default": True}, headers=sh)
check("创建第二个账号", r.status_code == 200, r.text[:120])
r2 = client.get("/api/admin/emby/115/accounts", headers=sh)
defaults = [a for a in r2.json()["accounts"] if a["is_default"]]
check("默认账号唯一", len(defaults) == 1 and defaults[0]["id"] == r.json()["account"]["id"],
      str([a["id"] for a in defaults]))

r = client.post("/api/admin/emby/115/accounts",
                json={"name": f"副号{suf}", "cookie": "UID=zzz"}, headers=sh)
check("账号重名被拒绝", r.status_code == 400, r.text[:120])

r = client.post("/api/admin/emby/115/accounts",
                json={"name": f"空号{suf}", "cookie": "   "}, headers=sh)
check("空 Cookie 被拒绝", r.status_code == 400, r.text[:120])

r = client.put(f"/api/admin/emby/115/accounts/{acc_id}", json={"is_enabled": False}, headers=sh)
check("停用账号", r.status_code == 200 and r.json()["account"]["is_enabled"] is False, r.text[:120])

# 绑定媒体库 → 通过媒体库接口
r = client.put(f"/api/admin/emby/libraries/{library.id}", json={"account_115_id": acc_id}, headers=sh)
check("媒体库绑定 115 账号", r.status_code == 200, r.text[:120])
r = client.get("/api/admin/emby/libraries", headers=sh)
bound = [x for x in r.json()["libraries"] if x["id"] == library.id]
check("媒体库列表返回 account_115_id", bool(bound) and bound[0]["account_115_id"] == acc_id,
      str(bound[:1]))

# 通过 API 删除后，媒体库绑定被解除（不留悬空引用）
r = client.delete(f"/api/admin/emby/115/accounts/{acc_id}", headers=sh)
check("删除账号配置档", r.status_code == 200, r.text[:120])
r = client.get("/api/admin/emby/libraries", headers=sh)
bound = [x for x in r.json()["libraries"] if x["id"] == library.id]
check("删除账号后媒体库绑定被解除", bound and bound[0]["account_115_id"] is None, str(bound[:1]))

# 解析接口
r = client.post("/api/admin/emby/115/parse", json={"share_url": "https://115.com/s/abcdefghij#1234"}, headers=sh)
check("解析接口返回分享码", r.status_code == 200 and r.json()["parsed"]["receive_code"] == "1234", r.text[:120])
r = client.post("/api/admin/emby/115/parse", json={"share_url": "坏链接"}, headers=sh)
check("解析接口拒绝非法链接", r.status_code == 400, r.text[:120])

# 目标路径浏览（假服务返回两个目录）
r = client.get("/api/admin/emby/115/browse", params={"cid": "0"}, headers=sh)
body = r.json()
check("路径浏览只返回目录", r.status_code == 200 and [e["name"] for e in body["entries"]] == ["电影", "剧集"],
      r.text[:160])

# 清理 api 建的账号，避免影响后续优先级断言
db = SessionLocal()
db.query(em.Pan115Account).filter(em.Pan115Account.name.like(f"%{suf}")).delete(synchronize_session=False)
db.commit()
db.close()


# ==================== 四、转存任务：从建单到完成 ====================

print("\n--- 转存任务 ---")
db = SessionLocal()
account = em.Pan115Account(name=f"转存号{suf}", cookie="UID=t; CID=t", is_default=True)
db.add(account)
db.commit()
db.refresh(account)
account_id = account.id

task = t115.create_task(db, share_url=f"https://115.com/s/{CODE_MAIN}#8888",
                        target_cid="100", target_path="/电影",
                        account_id=account_id, library_id=library.id, run_now=False)
task_id = task.id
check("创建转存任务", task.status == t115.STATUS_PENDING, task.status)
check("解析出分享码与提取码", task.share_code == CODE_MAIN and task.receive_code == "8888",
      f"{task.share_code}/{task.receive_code}")

dup = t115.create_task(db, share_url=f"https://115.com/s/{CODE_MAIN}", account_id=account_id, run_now=False)
check("重复提交被合并到同一任务", dup.id == task_id, f"{dup.id} vs {task_id}")
db.close()

fake.receive_calls.clear()
run_now(task_id)
task = get_task(task_id)
check("任务完成", task.status == t115.STATUS_DONE, f"{task.status} / {task.error}")
check("转存次数 = 文件数", len(fake.receive_calls) == 3, str(fake.receive_calls))
check("进度 100", task.progress == 100, str(task.progress))

payload = t115.task_payload(task)
check("快照条目已持久化", len(payload.get("items") or []) == 3, str(len(payload.get("items") or [])))
check("已完成文件键已持久化", len(payload.get("done_keys") or []) == 3, str(payload.get("done_keys")))
state_path = t115._state_path(task.uid)
check("状态文件原子落盘", os.path.isfile(state_path), state_path)
with open(state_path, encoding="utf-8") as fh:
    check("状态文件是完整 JSON", len(json.load(fh).get("done_keys", [])) == 3)
# 临时文件只在「原子写入进行中」或「进程被强杀」时存在：
# - 正在写的不能算残留（后台线程可能刚好在落盘），
# - 超过清理阈值（STALE_TMP_SECONDS）的才是真残留，产品会在下次落盘 / 启动时清掉。
state_dir = os.path.dirname(state_path)
now = time.time()
stale_file = os.path.join(state_dir, f"{CODE_MAIN}-stale.json.999999.1.tmp")
with open(stale_file, "w", encoding="utf-8") as fh:
    fh.write("{}")
old_ts = now - t115.STALE_TMP_SECONDS - 60
os.utime(stale_file, (old_ts, old_ts))
removed = t115.cleanup_stale_tmp()
check("上次强杀留下的过期临时文件会被清理",
      not os.path.exists(stale_file) and removed >= 1, f"removed={removed}")
leftovers = [
    f for f in os.listdir(state_dir)
    if f.endswith(".tmp") and now - os.path.getmtime(os.path.join(state_dir, f)) > t115.STALE_TMP_SECONDS
]
check("没有超过清理阈值的残留临时文件", not leftovers, str(leftovers))

serialized = t115.serialize_task(task)
check("serialize 的 items 是列表且非空", isinstance(serialized["items"], list) and len(serialized["items"]) == 3)
check("serialize 的 urls 是列表（转存模式为空）", serialized["urls"] == [])
check("serialize 带状态中文标签", serialized["status_label"] == "已完成", serialized["status_label"])

# items / urls 为 null 的历史脏数据不能把前端打崩
db = SessionLocal()
db.query(em.Pan115Task).filter(em.Pan115Task.id == task_id).update(
    {"payload": '{"items": null, "urls": null, "done_keys": null}'}
)
db.commit()
db.close()
os.remove(t115._state_path(get_task(task_id).uid))  # 去掉文件副本，单独考察数据库里的 null
serialized = t115.serialize_task(get_task(task_id))
check("脏数据 items/urls 归一化为列表",
      serialized["items"] == [] and serialized["urls"] == [], json.dumps(serialized)[:160])
for value in (serialized["items"], serialized["urls"], serialized["failed_keys"]):
    assert isinstance(value, list)
check("序列化输出里没有 null 列表字段",
      all(serialized[k] is not None for k in ("items", "urls", "failed_keys")))


# ==================== 五、续跑：不重复转存 ====================

print("\n--- 续跑 ---")
fake.snap_calls = 0
db = SessionLocal()
payload = {"items": fake.items, "urls": [], "done_keys": ["f1"], "failed_keys": []}
task2 = em.Pan115Task(
    uid="resume" + suf, share_url=f"https://115.com/s/{CODE_RESUME}", share_code=CODE_RESUME,
    receive_code="", mode=t115.MODE_RECEIVE, target_cid="0", account_id=account_id,
    status=t115.STATUS_RUNNING,  # 模拟上次进程被杀
    payload=json.dumps(payload), total_files=3,
)
db.add(task2)
db.commit()
db.refresh(task2)
task2_id = task2.id
# 清掉历史遗留的未完成任务，保证「恢复」只处理本用例造出来的那一个
db.query(em.Pan115Task).filter(
    em.Pan115Task.id != task2_id, em.Pan115Task.status.in_(t115.ACTIVE_STATUSES)
).update({"status": t115.STATUS_CANCELED}, synchronize_session=False)
db.commit()
db.close()

fake.receive_calls.clear()
resumed = t115.resume_pending_tasks()
check("启动时恢复未完成任务", resumed >= 1, str(resumed))
check("running 任务已续跑完成", wait_status(task2_id, t115.STATUS_DONE) == t115.STATUS_DONE,
      get_task(task2_id).status)
check("已完成文件不重复转存（只剩 2 个）", len(fake.receive_calls) == 2, str(fake.receive_calls))
check("续跑不重复拉分享快照（快照已落库）", fake.snap_calls == 0, str(fake.snap_calls))
check("再次恢复不会重复处理", t115.resume_pending_tasks() == 0)


# ==================== 六、Cookie 失效与重试 ====================

print("\n--- Cookie 失效 ---")
db = SessionLocal()
task3 = t115.create_task(db, share_url=f"https://115.com/s/{CODE_WAIT}", account_id=account_id, run_now=False)
task3_id = task3.id
db.close()

fake.auth_broken = True
run_now(task3_id)
task = get_task(task3_id)
check("Cookie 失效置为等待 Cookie", task.status == t115.STATUS_WAITING_AUTH, f"{task.status} / {task.error}")
check("失效任务被保留（未删除）", task is not None)
check("失效任务不进入终态", task.status not in t115.TERMINAL_STATUSES)

fake.auth_broken = False
fake.receive_calls.clear()
run_now(task3_id)
task = get_task(task3_id)
check("修好 Cookie 后重试可完成", task.status == t115.STATUS_DONE, f"{task.status} / {task.error}")
check("重试后文件都被转存", len(fake.receive_calls) == 3, str(fake.receive_calls))

# 未配置 Cookie：同样保留任务而不是直接失败
db = SessionLocal()
db.query(em.Pan115Account).filter(em.Pan115Account.name.like(f"%{suf}")).delete(synchronize_session=False)
db.commit()
task4 = t115.create_task(db, share_url=f"https://115.com/s/{CODE_NOAUTH}", run_now=False)
task4_id = task4.id
db.close()
run_now(task4_id)
task = get_task(task4_id)
check("未配置 Cookie 时任务保留为等待", task.status == t115.STATUS_WAITING_AUTH, f"{task.status} / {task.error}")


# ==================== 七、下载地址模式与取消 ====================

print("\n--- 下载地址模式 / 取消 ---")
db = SessionLocal()
acc2 = em.Pan115Account(name=f"下载号{suf}", cookie="UID=d; CID=d", is_default=True)
db.add(acc2)
db.commit()
db.refresh(acc2)
acc2_id = acc2.id  # 先取出主键：create_task 内部 commit 会让对象过期
task5 = t115.create_task(db, share_url=f"https://115.com/s/{CODE_DOWN}", mode=t115.MODE_DOWNLOAD,
                         account_id=acc2_id, run_now=False)
task5_id = task5.id
db.close()

fake.download_calls.clear()
run_now(task5_id)
task = get_task(task5_id)
check("下载模式完成", task.status == t115.STATUS_DONE, f"{task.status} / {task.error}")
serialized = t115.serialize_task(task)
check("下载地址落在 urls 列表", len(serialized["urls"]) == 3 and all(
    u.startswith("https://") for u in serialized["urls"]), str(serialized["urls"])[:160])

db = SessionLocal()
task6 = t115.create_task(db, share_url=f"https://115.com/s/{CODE_CANCEL}", account_id=acc2_id, run_now=False)
task6_id = task6.id
canceled = t115.cancel_task(db, task6_id)
check("取消任务", canceled is not None and canceled.status == t115.STATUS_CANCELED, str(canceled))
check("终态任务不可重复取消", t115.cancel_task(db, task6_id) is None)
db.close()


# ==================== 八、任务列表接口与鉴权 ====================

print("\n--- 任务接口 ---")
r = client.get("/api/admin/emby/115/tasks", headers=sh)
body = r.json()
check("任务列表可读", r.status_code == 200 and len(body["tasks"]) >= 1, r.text[:120])
check("列表每条的 items/urls 都是列表",
      all(isinstance(t["items"], list) and isinstance(t["urls"], list) for t in body["tasks"]))
check("返回模式与状态字典", bool(body["modes"]) and bool(body["statuses"]))

r = client.post(f"/api/admin/emby/115/tasks/{task6_id}/retry", headers=sh)
check("已取消任务可重试入队", r.status_code == 200, r.text[:120])

# 未登录 / 非管理员不能碰 115 接口
r = client.get("/api/admin/emby/115/accounts")
check("未登录被拒绝", r.status_code in (401, 403), f"HTTP {r.status_code}")


# ==================== 结果 ====================

print()
if failures:
    print(f"FAILED {len(failures)}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("ALL PASS")
