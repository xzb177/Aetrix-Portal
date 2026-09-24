"""端到端 API 冒烟：使用 TestClient 验证 v2.3.0 经济系统全链路"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 不写死库文件名：交给 backend.database 解析，升级上来的老部署继续用原库文件
os.environ.setdefault("DATABASE_TYPE", "sqlite")

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

# 健康检查
r = client.get("/api/health")
print("health:", r.status_code)

# 注册两个用户（含邀请码链路）
suf = str(random.randint(100000, 999999))
r1 = client.post("/api/user/auth/register", json={"username": f"api_a{suf}", "password": "secret123"})
print("register A:", r1.status_code)
r2 = client.post("/api/user/auth/register", json={"username": f"api_b{suf}", "password": "secret123"})
print("register B:", r2.status_code)
tok_a = r1.json()["access_token"]

# A 生成邀请码
r = client.get("/api/user/invite/my-code", headers={"Authorization": f"Bearer {tok_a}"})
print("invite my-code:", r.status_code, r.json().get("code"))
code = r.json()["code"]

# C 注册时用邀请码
r3 = client.post(
    "/api/user/auth/register",
    json={"username": f"api_c{suf}", "password": "secret123", "invitation_code": code},
)
print("register C with invite:", r3.status_code)
tok_c = r3.json()["access_token"]

# C 的积分应为 50（invitee 奖励）
r = client.get("/api/user/economy/checkin/status", headers={"Authorization": f"Bearer {tok_c}"})
print("C checkin status:", r.status_code, "points:", r.json().get("points"))

# C 签到
r = client.post("/api/user/economy/checkin", headers={"Authorization": f"Bearer {tok_c}"})
print("C checkin:", r.status_code, r.json().get("message"))

# 管理端生成兑换码（需要 staff）
from backend import models
from backend.database import SessionLocal
from backend.security import hash_password

db = SessionLocal()
admin = models.WebUser(username=f"api_admin{suf}", password_hash=hash_password("admin12345"), is_staff=True)
db.add(admin)
db.commit()
db.refresh(admin)
db.close()

r = client.post("/api/user/auth/login", json={"username": f"api_admin{suf}", "password": "admin12345"})
tok_admin = r.json()["access_token"]

r = client.post(
    "/api/admin/economy/exchange-codes",
    json={"count": 1, "type": "points", "points_value": 66},
    headers={"Authorization": f"Bearer {tok_admin}"},
)
print("admin gen code:", r.status_code, r.json().get("codes"))
new_code = r.json()["codes"][0]["code"]

# C 兑换
r = client.post(
    "/api/user/economy/exchange/redeem",
    json={"code": new_code},
    headers={"Authorization": f"Bearer {tok_c}"},
)
print("C redeem:", r.status_code, r.json().get("message"))

# 管理端经济统计
r = client.get("/api/admin/economy/stats", headers={"Authorization": f"Bearer {tok_admin}"})
print("admin econ stats:", r.status_code, r.json())

# 下单（未配置网关应 503 明确报错）
r = client.post(
    "/api/user/economy/payment/order",
    json={"kind": "recharge", "item_id": 1, "payment_method": "alipay"},
    headers={"Authorization": f"Bearer {tok_c}"},
)
print("order without gateway:", r.status_code, r.json().get("detail"))

# 积分流水
r = client.get("/api/user/economy/points/log", headers={"Authorization": f"Bearer {tok_c}"})
print("C points log:", r.status_code, "balance:", r.json().get("balance"), "entries:", len(r.json().get("logs", [])))

# 清理
db = SessionLocal()
names = [f"api_a{suf}", f"api_b{suf}", f"api_c{suf}", f"api_admin{suf}"]
for u in db.query(models.WebUser).filter(models.WebUser.username.in_(names)).all():
    db.query(models.StationMessage).filter(models.StationMessage.to_user_id == u.id).delete(synchronize_session=False)
    db.query(models.PointsLog).filter(models.PointsLog.user_id == u.id).delete(synchronize_session=False)
    db.query(models.CheckinRecord).filter(models.CheckinRecord.user_id == u.id).delete(synchronize_session=False)
    db.delete(u)
db.commit()
db.close()
print("E2E DONE")
