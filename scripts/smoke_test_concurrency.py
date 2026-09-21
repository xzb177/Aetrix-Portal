"""经济链并发冒烟测试 + 限流 IP 取值

这些场景都是「读-判断-写」型逻辑，单线程跑永远是对的，只有真并发才暴露：

1. 单次兑换码被多个请求同时核销 → 只能成功一次（不能发两份奖励）
2. 同一用户同时签到 → 只能成功一次（不能发两份积分，也不能 500）
3. `_add_points` 并发累加 → 不能丢更新（最终余额 = 初始 + 各次之和）
4. 同一被邀请人被重复应用邀请码 → 只建立一次关系、只发一次双向奖励
5. `client_ip` 不再采信攻击者可控的 `X-Forwarded-For` 首值（限流桶不可伪造）

用临时 SQLite 文件库 + 真线程 + 真会话，不碰开发库。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "e2e-test-secret-key-not-for-production"

DB = os.path.join(tempfile.mkdtemp(), "concurrency.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

from fastapi import HTTPException  # noqa: E402

from backend import models  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402

init_db()

from backend.api.economy import _add_points, do_checkin, redeem_exchange_code  # noqa: E402
from backend.api.economy import _today_start  # noqa: E402
from backend.api.invitation import apply_invitation  # noqa: E402
from backend.ratelimit import client_ip  # noqa: E402

failures: list[str] = []
TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


# ==================== 请求替身（端点里只用 IP 与路径）====================

class _URL:
    path = "/api/user/economy/checkin"


class _Client:
    host = "10.0.0.9"


class FakeRequest:
    """最小 Request 替身：端点只读 headers / client / url"""

    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}
        self.client = _Client()
        self.url = _URL()
        self.query_params: dict = {}


def run_async_endpoint(fn, *args):
    """在独立线程里跑 async 端点，返回 (成功?, 结果或异常)"""
    try:
        return True, asyncio.run(fn(*args))
    except HTTPException as exc:
        return False, exc
    except Exception as exc:  # noqa: BLE001
        return False, exc


def run_parallel(target, count: int):
    """启动 count 个线程同时执行 target(i)，收集结果"""
    results: list = [None] * count
    barrier = threading.Barrier(count)

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        results[i] = target(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


# ==================== 播种 ====================

with SessionLocal() as db:
    users = []
    for name in ("cc-alice", "cc-bob", "cc-inviter", "cc-invitee"):
        u = models.WebUser(username=name, password_hash="not-used", is_active=True, points=0)
        db.add(u)
        users.append(u)
    db.commit()
    for u in users:
        db.refresh(u)
    alice, bob, inviter, invitee = users
    alice_id, bob_id, inviter_id, invitee_id = alice.id, bob.id, inviter.id, invitee.id

    db.add(models.ExchangeCode(
        code="CC-SINGLE-USE", type="points", points_value=100,
        max_uses=1, use_count=0, is_active=True,
    ))
    inv = models.InvitationCode(code="CCINVITE", user_id=inviter_id, is_active=True, use_count=0)
    db.add(inv)
    db.commit()


def balance(uid: int) -> int:
    with SessionLocal() as db:
        return int(db.query(models.WebUser.points).filter(models.WebUser.id == uid).scalar() or 0)


# ==================== 1. 单次兑换码并发核销 ====================

def redeem_once(i: int):
    db = SessionLocal()
    try:
        user = db.query(models.WebUser).filter(models.WebUser.id == alice_id).first()
        from backend.api.economy import RedeemRequest

        return run_async_endpoint(
            redeem_exchange_code, FakeRequest(), RedeemRequest(code="CC-SINGLE-USE"), user, db
        )
    finally:
        db.close()


results = run_parallel(redeem_once, 4)
oks = [r for r in results if r and r[0]]
fails = [r for r in results if r and not r[0]]

with SessionLocal() as db:
    code_row = db.query(models.ExchangeCode).filter(models.ExchangeCode.code == "CC-SINGLE-USE").first()
    use_count = code_row.use_count
    is_active = code_row.is_active

check("单次码并发核销：只有 1 个请求成功", len(oks) == 1, f"成功 {len(oks)} / 失败 {len(fails)}")
bad = [
    getattr(exc, "status_code", 500)
    for _, exc in fails
    if not (isinstance(exc, HTTPException) and exc.status_code in (400, 409))
]
check("单次码并发核销：失败方返回 400/409（可重试语义），不是 500", not bad, f"异常状态码={bad}")
check("单次码并发核销：只发了一份积分", balance(alice_id) == 100, f"余额={balance(alice_id)}")
check("单次码并发核销：use_count 恰好为 1", use_count == 1, f"use_count={use_count}")
check("单次码并发核销：用满后自动停用", is_active is False, f"is_active={is_active}")

# ==================== 2. 同一用户并发签到 ====================

def checkin_once(i: int):
    db = SessionLocal()
    try:
        user = db.query(models.WebUser).filter(models.WebUser.id == bob_id).first()
        return run_async_endpoint(do_checkin, FakeRequest(), user, db)
    finally:
        db.close()


results = run_parallel(checkin_once, 4)
oks = [r for r in results if r and r[0]]
fails = [r for r in results if r and not r[0]]

with SessionLocal() as db:
    records = db.query(models.CheckinRecord).filter(
        models.CheckinRecord.user_id == bob_id,
        models.CheckinRecord.checkin_date >= _today_start(),
    ).count()

check("并发签到：只有 1 个请求成功", len(oks) == 1, f"成功 {len(oks)} / 失败 {len(fails)}")
bad = [
    getattr(exc, "status_code", 500)
    for _, exc in fails
    if not (isinstance(exc, HTTPException) and exc.status_code in (400, 409))
]
check("并发签到：失败方返回 400/409，不是 500", not bad, f"异常状态码={bad}")
check("并发签到：当日只有 1 条记录", records == 1, f"记录数={records}")
check("并发签到：只发了一份奖励", balance(bob_id) == 5, f"余额={balance(bob_id)}")

# ==================== 3. _add_points 并发累加不丢更新 ====================

with SessionLocal() as db:
    db.query(models.WebUser).filter(models.WebUser.id == alice_id).update(
        {models.WebUser.points: 1000}, synchronize_session=False
    )
    db.commit()

def add_points_once(i: int):
    db = SessionLocal()
    try:
        user = db.query(models.WebUser).filter(models.WebUser.id == alice_id).first()
        balance_after = _add_points(db, user, 7, "test", f"并发自增 {i}", f"cc:{i}")
        db.commit()
        return True, balance_after
    except HTTPException as exc:
        return False, exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return False, exc
    finally:
        db.close()


results = run_parallel(add_points_once, 6)
oks = [r for r in results if r and r[0]]
check("并发 _add_points：6 次全部成功", len(oks) == 6, f"成功 {len(oks)}")
final = balance(alice_id)
check("并发 _add_points：无丢更新（1000 + 6×7）", final == 1042, f"余额={final}")

with SessionLocal() as db:
    logs = db.query(models.PointsLog).filter(models.PointsLog.ref_id.like("cc:%")).count()
check("并发 _add_points：台账逐笔落库", logs == 6, f"台账条数={logs}")

# ==================== 4. 邀请关系幂等 ====================

before_inviter = balance(inviter_id)
before_invitee = balance(invitee_id)

applied = []
with SessionLocal() as db:
    for _ in range(2):
        user = db.query(models.WebUser).filter(models.WebUser.id == invitee_id).first()
        applied.append(apply_invitation(db, user, "CCINVITE"))
        db.commit()

check("邀请幂等：第一次应用成功", applied[0].get("applied") is True, f"{applied[0]}")
check("邀请幂等：第二次被拒（不重复发奖）", applied[1].get("applied") is False, f"{applied[1]}")

with SessionLocal() as db:
    rec = db.query(models.InvitationRecord).filter(
        models.InvitationRecord.invitee_id == invitee_id
    ).count()
check("邀请幂等：只有 1 条关系记录", rec == 1, f"记录数={rec}")
check(
    "邀请幂等：双向奖励各只发一次",
    balance(inviter_id) - before_inviter == 100 and balance(invitee_id) - before_invitee == 50,
    f"邀请者 +{balance(inviter_id) - before_inviter} / 被邀请者 +{balance(invitee_id) - before_invitee}",
)

# 并发重复应用
with SessionLocal() as db:
    u = models.WebUser(username="cc-invitee2", password_hash="not-used", is_active=True, points=0)
    db.add(u)
    db.commit()
    db.refresh(u)
    invitee2_id = u.id


def invite_once(i: int):
    db = SessionLocal()
    try:
        user = db.query(models.WebUser).filter(models.WebUser.id == invitee2_id).first()
        res = apply_invitation(db, user, "CCINVITE")
        db.commit()
        return True, res
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return False, exc
    finally:
        db.close()


results = run_parallel(invite_once, 3)
applied_count = len([r for r in results if r and r[0] and r[1].get("applied") is True])
with SessionLocal() as db:
    rec2 = db.query(models.InvitationRecord).filter(
        models.InvitationRecord.invitee_id == invitee2_id
    ).count()
check("邀请并发：最多只应用一次", applied_count <= 1, f"applied={applied_count}")
check("邀请并发：关系记录不超过 1 条", rec2 <= 1, f"记录数={rec2}")
check("邀请并发：无未处理异常", all(r and r[0] for r in results),
      f"{[str(r[1])[:60] for r in results if r and not r[0]]}")

# ==================== 5. 限流 IP 取值不可伪造 ====================

ip_xff_multi = client_ip(FakeRequest({"x-forwarded-for": "1.2.3.4, 203.0.113.7"}))
check("client_ip：XFF 取最后一段（忽略攻击者前缀）", ip_xff_multi == "203.0.113.7", f"ip={ip_xff_multi}")

ip_real_wins = client_ip(FakeRequest({
    "x-real-ip": "198.51.100.5",
    "x-forwarded-for": "1.1.1.1, 2.2.2.2",
}))
check("client_ip：X-Real-IP 优先（Nginx 按 $remote_addr 硬写）",
      ip_real_wins == "198.51.100.5", f"ip={ip_real_wins}")

ip_direct = client_ip(FakeRequest())
check("client_ip：无代理头时使用直连地址", ip_direct == "10.0.0.9", f"ip={ip_direct}")

# 攻击者轮换 XFF 但真实 IP 固定 → 仍然只能用一个限流桶
from backend.ratelimit import check_rate_limit  # noqa: E402

key_ip = client_ip(FakeRequest({"x-real-ip": "203.0.113.99", "x-forwarded-for": "1.1.1.1"}))
statuses = []
for i in range(9):
    spoofed = FakeRequest({"x-real-ip": "203.0.113.99", "x-forwarded-for": f"9.9.9.{i}"})
    allowed, _ = check_rate_limit(f"cc-spoof:{client_ip(spoofed)}", 8, 60)
    statuses.append(allowed)
check("限流不可靠伪造 XFF 绕过：第 9 次被拒",
      statuses[:8] == [True] * 8 and statuses[8] is False, f"allowed={statuses}")

# ==================== 汇总 ====================

print()
if failures:
    print(f"FAILED  {len(failures)}/{TOTAL}：")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"ALL PASS  {TOTAL}/{TOTAL}")
