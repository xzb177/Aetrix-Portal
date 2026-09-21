"""升级路径冒烟测试：老库直接跑新版本，不允许出现「模型有列、库里没列」

起因（v2.6.20 → v2.6.21）：自动迁移的清单写成了 ``{表名: 列}`` 字典，而同一张表
在不同版本各自加过列——``registration_codes`` 有 v2.5.6 与 v2.6.20 两批、
``movie_requests`` 有 v2.6.19 与 v2.6.20 两批。字典字面量里后一个键会**静默覆盖**
前一个（不报错、不告警），于是 ``movie_requests.realm_id`` 与 ``registration_codes.code_type``
这类列在升级上来的库上永远补不上：

- 全新安装（create_all 一次建全）完全正常；
- 老库升级后查询立刻报 ``no such column: movie_requests.realm_id``，管理后台首页
  （``/api/admin/stats/overview``、``/api/admin/realms/overview``）直接 500。

本测试的第一条断言就是「模型声明的列，库里必须都有」——它能在任何人再加一张表、
再写重复键的时候立刻失败，而不是等用户升级后炸。

覆盖：
1. 老库（只有旧列）跑 ``init_db()``：逐列补齐，且 legacy 行被回填到默认服；
2. 迁移是幂等的（连跑两次不报错、不重复加列）；
3. 迁移后管理后台首页与卡码页的接口全部 200（这些正是当年 500 的地方）。
"""
import os
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_FILE = ROOT / "ci-migration.db"

# 必须在 import backend 之前落定：database.py 在模块导入时就决定了 engine
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(f"{DB_FILE}{suffix}")
    except FileNotFoundError:
        pass
os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_FILE}"
os.environ.setdefault("REDIS_ENABLED", "false")

# 老版本的建表语句（故意缺列）：create_all 不会改已有的表，所以这些表就停留在旧形态
LEGACY_DDL = [
    """
    CREATE TABLE movie_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        movie_name VARCHAR(255) NOT NULL,
        year VARCHAR(10),
        type VARCHAR(50),
        note TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        admin_note TEXT,
        emby_item_id VARCHAR(100),
        created_at DATETIME,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE registration_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code VARCHAR(64) NOT NULL UNIQUE,
        max_uses INTEGER DEFAULT 1,
        use_count INTEGER DEFAULT 0,
        is_active BOOLEAN DEFAULT 1,
        note VARCHAR(255),
        used_by VARCHAR(500),
        expires_at DATETIME,
        created_by INTEGER,
        created_at DATETIME
    )
    """,
]

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def build_legacy_db() -> None:
    """造一个「老版本升级上来」的库：只有旧列，且已有业务数据"""
    con = sqlite3.connect(str(DB_FILE))
    try:
        for ddl in LEGACY_DDL:
            con.execute(ddl)
        con.execute(
            "INSERT INTO movie_requests (user_id, movie_name, status, created_at, updated_at) "
            "VALUES (1, '老库里的求片', 'pending', datetime('now'), datetime('now'))"
        )
        con.execute(
            "INSERT INTO registration_codes (code, max_uses, use_count, is_active) "
            "VALUES ('LEGACYCODE01', 1, 0, 1)"
        )
        con.commit()
    finally:
        con.close()


def columns_of(table: str) -> set[str]:
    con = sqlite3.connect(str(DB_FILE))
    try:
        return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


build_legacy_db()
check("老库已就位（movie_requests 无 realm_id）", "realm_id" not in columns_of("movie_requests"))
check("老库已就位（registration_codes 无 code_type）", "code_type" not in columns_of("registration_codes"))

# ---------- 跑迁移（init_db 就是启动时真正走的那条路）----------
from sqlalchemy import inspect  # noqa: E402

from backend import models  # noqa: E402
from backend.database import Base, SessionLocal, engine, init_db  # noqa: E402
from backend.security import hash_password  # noqa: E402

init_db()

# ---------- 1. 模型声明的列，库里必须都有 ----------
inspector = inspect(engine)
db_tables = set(inspector.get_table_names())
missing_report: list[str] = []
for table in Base.metadata.sorted_tables:
    if table.name not in db_tables:
        continue
    have = {c["name"] for c in inspector.get_columns(table.name)}
    for col in table.columns:
        if col.name not in have:
            missing_report.append(f"{table.name}.{col.name}")
check("迁移后没有「模型有列、库里没有」的表", not missing_report, ", ".join(missing_report[:8]))

# 这次翻车的那几列，单独点名断言（回归标记）
for table, cols in (
    ("movie_requests", ["realm_id", "push_target", "push_status", "push_message", "pushed_at"]),
    ("registration_codes", ["code_type", "days", "is_decoy", "target_username", "source", "realm_id"]),
    ("emby_libraries", ["node_id", "realm_id", "mount_ids"]),
    ("remote_servers", ["node_key", "realm_id"]),
):
    have = columns_of(table)
    absent = [c for c in cols if c not in have]
    check(f"{table} 的新增列全部补齐", not absent, ", ".join(absent))

# ---------- 2. 老数据被回填 / 拿到默认值 ----------
con = sqlite3.connect(str(DB_FILE))
try:
    realm_id, = con.execute("SELECT id FROM server_realms ORDER BY id LIMIT 1").fetchone()
    row_realm, = con.execute("SELECT realm_id FROM movie_requests WHERE movie_name = '老库里的求片'").fetchone()
    code_type, = con.execute("SELECT code_type FROM registration_codes WHERE code = 'LEGACYCODE01'").fetchone()
    active, = con.execute("SELECT value FROM system_configs WHERE key = 'active_realm_id'").fetchone()
finally:
    con.close()

check("升级后自动建了默认服", isinstance(realm_id, int) and realm_id > 0, f"id={realm_id}")
check("老求片被回填到默认服", row_realm == realm_id, f"realm_id={row_realm}")
check("老卡码拿到 code_type 默认值 1", code_type == 1, f"code_type={code_type}")
check("当前服已落库", str(active) == str(realm_id), f"active_realm_id={active}")

# ---------- 3. 幂等：再跑一次不报错、不重复加列 ----------
before = {t: columns_of(t) for t in ("movie_requests", "registration_codes", "emby_libraries")}
init_db()
after = {t: columns_of(t) for t in ("movie_requests", "registration_codes", "emby_libraries")}
check("重复执行迁移不改变表结构（幂等）", before == after)

# ---------- 4. 迁移后管理端接口真的能打开 ----------
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

suf = str(random.randint(100000, 999999))
db = SessionLocal()
db.add(models.WebUser(username=f"migadm{suf}", password_hash=hash_password("admin12345"), is_staff=True))
db.commit()
db.close()

with TestClient(app) as client:
    login = client.post("/api/user/auth/login",
                        json={"username": f"migadm{suf}", "password": "admin12345"})
    check("管理员能登录（迁移后的库）", login.status_code == 200, str(login.status_code))
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 这两个就是用户报「后台首页显示 500」的接口
    for path in (
        "/api/admin/auth/me",
        "/api/admin/stats/overview",
        "/api/admin/realms/overview",
        "/api/admin/media-seek",
        "/api/admin/registration-codes",
        "/api/admin/registration-codes/list",
        "/api/admin/registration-codes/stats",
        "/api/admin/emby/libraries",
        "/api/admin/servers/summary",
        "/api/admin/economy/subscriptions",
    ):
        resp = client.get(path, headers=headers)
        check(f"迁移后 GET {path} 正常", resp.status_code == 200,
              f"{resp.status_code} {resp.text[:120]}")

# ---------- 收尾 ----------
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(f"{DB_FILE}{suffix}")
    except FileNotFoundError:
        pass

print(f"\n{'=' * 60}")
if failures:
    print(f"❌ 升级路径冒烟测试失败：{len(failures)}/{checks} 项")
    for name in failures:
        print(f"   - {name}")
    sys.exit(1)
print(f"✅ 升级路径冒烟测试通过（{checks} 项断言）")
