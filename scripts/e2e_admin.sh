#!/bin/bash
# v2.2.0 管理后台端到端冒烟测试（借鉴 twilight-kotomi 的运营能力）
set -u
B=http://127.0.0.1:8767
DB=/tmp/rbtest/e2e_admin.db

echo "== 0. 准备 =="
rm -f "$DB" "${DB}-shm" "${DB}-wal"

echo "== 1. 启动服务 =="
mkdir -p /tmp/rbtest
DATABASE_URL="sqlite:///$DB" nohup python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8767 > /tmp/rbtest/admin_e2e.log 2>&1 &
SERVER_PID=$!
sleep 4
curl -s -m 5 -o /dev/null -w "health: %{http_code}\n" $B/ || { echo "server failed"; tail -20 /tmp/rbtest/admin_e2e.log; exit 1; }

echo "== 2. 注册首个用户 + 升级 staff =="
R=$(curl -s -m 10 -X POST $B/api/user/auth/register -H "Content-Type: application/json" -d '{"username":"boss","password":"boss12345"}')
echo "$R" | python3 -c 'import sys,json;print("boss uid =",json.load(sys.stdin)["user"]["id"])' || { echo "$R"; exit 1; }
DATABASE_URL="sqlite:///$DB" python3 scripts/_e2e_mkstaff.py

echo "== 3. 管理员登录 =="
A=$(curl -s -m 10 -X POST $B/api/admin/auth/login -H "Content-Type: application/json" -d '{"username":"boss","password":"boss12345"}')
TOKEN=$(echo "$A" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])' 2>/dev/null) || { echo "LOGIN FAILED: $A"; exit 1; }
echo "token ok: ${TOKEN:0:20}..."

echo "== 4. auth/me =="
curl -s -m 10 $B/api/admin/auth/me -H "Authorization: Bearer $TOKEN"; echo

echo "== 5. 批量生成注册码(3个, 每个2次) =="
C=$(curl -s -m 10 -X POST $B/api/admin/registration-codes -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"count":3,"max_uses":2}')
CODE=$(echo "$C" | python3 -c 'import sys,json;print(json.load(sys.stdin)["codes"][0]["code"])' 2>/dev/null)
echo "$C" | python3 -c 'import sys,json;print("codes:",[c["code"] for c in json.load(sys.stdin)["codes"]])' || { echo "$C"; exit 1; }

echo "== 6. 切换注册模式 = code =="
curl -s -m 10 -X PUT $B/api/admin/settings/registration -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"mode":"code"}'; echo

echo "== 7. 无码注册应被拒 =="
curl -s -m 10 -X POST $B/api/user/auth/register -H "Content-Type: application/json" -d '{"username":"nocode","password":"pass12345"}'; echo

echo "== 8. 用码注册成功 =="
R2=$(curl -s -m 10 -X POST $B/api/user/auth/register -H "Content-Type: application/json" -d '{"username":"coder","password":"pass12345","registration_code":"'$CODE'"}')
echo "$R2" | python3 -c 'import sys,json;print("coder uid =",json.load(sys.stdin).get("user",{}).get("id"))' 2>/dev/null || echo "$R2"

echo "== 9. 注册码审计 =="
curl -s -m 10 "$B/api/admin/registration-codes" -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;c=json.load(sys.stdin)["codes"][0];print("code",c["code"],": use",c["use_count"],"/",c["max_uses"],"used_by",[u["username"] for u in c["used_by"]])'

echo "== 10. 用户管理: 列表/禁用/重置密码 =="
curl -s -m 10 "$B/api/admin/users" -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;print("total users:",json.load(sys.stdin)["total"])'
curl -s -m 10 -X PUT "$B/api/admin/users/2" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"is_active":false}'; echo
curl -s -m 10 -X POST "$B/api/admin/users/2/reset-password" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"new_password":"newpass99"}'; echo

echo "== 11. 禁用后登录应被拒 =="
curl -s -m 10 -X POST $B/api/user/auth/login -H "Content-Type: application/json" -d '{"username":"coder","password":"newpass99"}'; echo

echo "== 12. 非staff访问管理端应 403/401 =="
curl -s -m 10 -o /dev/null -w "anonymous -> /api/admin/users: %{http_code}\n" "$B/api/admin/users"

echo "== 13. 播放统计 =="
curl -s -m 10 "$B/api/admin/stats/playback" -H "Authorization: Bearer $TOKEN"; echo

echo "== 14. 概览统计 =="
curl -s -m 10 "$B/api/admin/stats/overview" -H "Authorization: Bearer $TOKEN"; echo

echo "== 15. 审计日志 =="
curl -s -m 10 "$B/api/admin/logs?limit=8" -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json;print("actions:",[l["action"] for l in json.load(sys.stdin)])'

echo "== 16. 公告创建(联动通知) =="
curl -s -m 10 -X POST "$B/api/admin/announcements" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"维护通知","content":"今晚 02:00-04:00 系统维护"}'; echo

echo "== 17. 改密后重新登录 =="
curl -s -m 10 -X POST "$B/api/admin/auth/change-password" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"old_password":"boss12345","new_password":"bossnew666"}'; echo
curl -s -m 10 -X POST $B/api/admin/auth/login -H "Content-Type: application/json" -d '{"username":"boss","password":"bossnew666"}' | python3 -c 'import sys,json;print("re-login with new password:","access_token" in json.load(sys.stdin))'

kill $SERVER_PID 2>/dev/null
echo "== DONE =="
