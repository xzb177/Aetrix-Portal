"""门户认证端到端测试：注册 → 登录 → me → refresh → 改密 → 受保护端点"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
os.environ["EMBY_PUBLIC_URL"] = "http://media.example.com:8000"
os.environ["SECRET_KEY"] = "e2e-test-secret-key-not-for-production"

DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

from fastapi.testclient import TestClient  # noqa: E402

from backend.database import engine, init_db  # noqa: E402

init_db()

from backend.main import app  # noqa: E402

client = TestClient(app)

AH = {"Content-Type": "application/json"}

# ==================== 1. 注册 ====================
r = client.post("/api/user/auth/register", json={
    "username": "newuser",
    "password": "secret123",
    "email": "newuser@example.com",
})
assert r.status_code == 201, (r.status_code, r.text)
data = r.json()
assert data["access_token"], "应返回 access_token"
assert data["refresh_token"], "应返回 refresh_token"
assert data["token_type"] == "bearer"
assert data["user"]["username"] == "newuser"
assert data["user"]["id"] > 0
print("OK register -> token + user:", data["user"])

# 注册响应里应带自动生成的 Emby 凭据
assert data["user"]["emby_username"], "注册应自动生成 emby_username"
print("OK auto emby_username:", data["user"]["emby_username"])

# ==================== 2. 重复注册拒绝 ====================
r = client.post("/api/user/auth/register", json={"username": "newuser", "password": "secret123"})
assert r.status_code == 409, (r.status_code, r.text)
assert "已被注册" in r.json()["detail"]
print("OK duplicate register rejected (409)")

# 非法用户名
r = client.post("/api/user/auth/register", json={"username": "ab", "password": "secret123"})
assert r.status_code == 422 or r.status_code == 400, (r.status_code, r.text)
print("OK invalid username rejected")

# ==================== 3. JWT 结构校验 ====================
from backend.security import decode_token  # noqa: E402

payload = decode_token(data["access_token"], expected_type="access")
assert payload and payload["sub"] == str(data["user"]["id"])
assert decode_token(data["refresh_token"], expected_type="refresh") is not None
assert decode_token(data["access_token"], expected_type="refresh") is None, "access 不能当 refresh 用"
assert decode_token(data["refresh_token"], expected_type="access") is None, "refresh 不能当 access 用"
print("OK JWT structure (type isolation)")

# ==================== 4. 登录 ====================
r = client.post("/api/user/auth/login", json={"username": "newuser", "password": "secret123"})
assert r.status_code == 200, (r.status_code, r.text)
login_data = r.json()
assert login_data["access_token"] and login_data["user"]["username"] == "newuser"
access = login_data["access_token"]
print("OK login -> token")

# 错误密码
r = client.post("/api/user/auth/login", json={"username": "newuser", "password": "wrongpass"})
assert r.status_code == 401, (r.status_code, r.text)
assert "用户名或密码错误" in r.json()["detail"]
print("OK wrong password rejected (401)")

# 不存在的用户
r = client.post("/api/user/auth/login", json={"username": "ghost", "password": "whatever"})
assert r.status_code == 401
print("OK unknown user rejected (401)")

# ==================== 5. /me（JWT 鉴权）====================
r = client.get("/api/user/auth/me", headers={"Authorization": f"Bearer {access}"})
assert r.status_code == 200, (r.status_code, r.text)
assert r.json()["username"] == "newuser"
print("OK /me with JWT")

# 无 token
r = client.get("/api/user/auth/me")
assert r.status_code == 401
print("OK /me without token rejected (401)")

# 篡改 token
r = client.get("/api/user/auth/me", headers={"Authorization": "Bearer forged.token.here"})
assert r.status_code == 401
print("OK /me with forged token rejected (401)")

# refresh token 不能访问受保护端点
refresh_token = login_data["refresh_token"]
r = client.get("/api/user/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
assert r.status_code == 401, (r.status_code, r.text)
print("OK refresh token cannot access protected endpoint")

# ==================== 6. refresh 轮换 ====================
r = client.post("/api/user/auth/refresh", json={"refresh_token": refresh_token})
assert r.status_code == 200, (r.status_code, r.text)
new_access = r.json()["access_token"]
assert new_access
new_refresh = r.json()["refresh_token"]
assert new_refresh and new_refresh != refresh_token, "refresh 应轮换"
print("OK refresh -> new tokens")

# 新 access 可用
r = client.get("/api/user/auth/me", headers={"Authorization": f"Bearer {new_access}"})
assert r.status_code == 200
print("OK new access token works")

# 无效 refresh
r = client.post("/api/user/auth/refresh", json={"refresh_token": "garbage"})
assert r.status_code == 401
print("OK invalid refresh rejected (401)")

# ==================== 7. 改密 ====================
r = client.post("/api/user/auth/change-password",
                headers={"Authorization": f"Bearer {new_access}"},
                json={"old_password": "secret123", "new_password": "newpass456"})
assert r.status_code == 200, (r.status_code, r.text)
print("OK change-password")

# 旧密码登录失败
r = client.post("/api/user/auth/login", json={"username": "newuser", "password": "secret123"})
assert r.status_code == 401
# 新密码登录成功，且 Emby 密码已同步
r = client.post("/api/user/auth/login", json={"username": "newuser", "password": "newpass456"})
assert r.status_code == 200
emby_password_synced = r.json()["user"]["emby_username"] is not None
assert emby_password_synced
print("OK relogin with new password")

# Emby 播放密码同步验证
import sqlite3  # noqa: E402

db = sqlite3.connect(DB)
row = db.execute("SELECT emby_password FROM web_users WHERE username='newuser'").fetchone()
db.close()
assert row and row[0] == "newpass456", f"Emby 密码应同步为 newpass456, got {row}"
print("OK emby play password synced with portal password")

# ==================== 8. 旧数字 token 兼容（门户 Emby 端点）====================
user_id = data["user"]["id"]
r = client.get("/api/user/emby/server", headers={"Authorization": f"Bearer {user_id}"})
assert r.status_code == 200, (r.status_code, r.text)
print("OK legacy numeric token still works on /api/user/emby/server")

# JWT 也可访问门户 Emby 端点
r = client.get("/api/user/emby/server", headers={"Authorization": f"Bearer {new_access}"})
assert r.status_code == 200
print("OK JWT works on /api/user/emby/server")

# Emby 协议端点仍正常（注册时自动生成的凭据可直接登录）
r = client.post("/emby/Users/AuthenticateByName",
                json={"Username": data["user"]["emby_username"], "Pw": "newpass456"},
                headers={"X-Emby-Authorization": 'MediaBrowser Client="T", Device="T", DeviceId="t1", Version="1"'})
assert r.status_code == 200, (r.status_code, r.text)
print("OK Emby AuthenticateByName with synced credentials")

# ==================== 9. logout ====================
r = client.post("/api/user/auth/logout", headers={"Authorization": f"Bearer {new_access}"})
assert r.status_code == 200
print("OK logout")

print("\n✅ 门户认证端到端测试全部通过")
os.remove(DB)
