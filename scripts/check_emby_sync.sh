#!/bin/bash
################################################################################
# Emby 账号同步检查脚本
# 用于检查数据库中的 Emby 账号是否正确同步到 Emby 服务器
#
# 需要两个环境变量（本脚本原先把它们写死在文件里——公开仓库等于已泄露）：
#   EMBY_URL      Emby 服务地址，例如 https://emby.example.com
#   EMBY_API_KEY  Emby 管理 API Key（X-Emby-Token）
# 二者都读自环境（Freebuff 工作区会自动带上 .env / .env.local）。
################################################################################

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 数据库连接（可用环境变量覆盖）
DB_CONTAINER="${DB_CONTAINER:-aetrix_postgres}"
DB_USER="${DB_USER:-aetrix}"
DB_NAME="${DB_NAME:-aetrix}"

# Emby 服务器配置：只从环境读，不在仓库里落凭据
EMBY_URL="${EMBY_URL:-}"
EMBY_API_KEY="${EMBY_API_KEY:-}"
if [ -z "$EMBY_URL" ] || [ -z "$EMBY_API_KEY" ]; then
    echo "❌ 缺少 EMBY_URL / EMBY_API_KEY（读自环境变量或 .env）。" >&2
    echo "   例：EMBY_URL=https://emby.example.com EMBY_API_KEY=xxxx sh scripts/check_emby_sync.sh" >&2
    echo "   旧版本把这两项写死在本脚本里；不要再把真实凭据提交回仓库。" >&2
    exit 2
fi

echo "========================================"
echo "Emby 账号同步检查"
echo "========================================"
echo ""

# 1. 检查 emby_user_id 为空的账号
echo "1. 检查 emby_user_id 为空的账号..."
EMPTY_COUNT=$(docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c \
    "SELECT COUNT(*) FROM user_emby_accounts WHERE emby_user_id IS NULL OR emby_user_id = '';")

if [ "$EMPTY_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ 没有空 emby_user_id 的账号${NC}"
else
    echo -e "${RED}❌ 发现 $EMPTY_COUNT 个 emby_user_id 为空的账号:${NC}"
    docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -c \
        "SELECT id, user_id, username FROM user_emby_accounts WHERE emby_user_id IS NULL OR emby_user_id = '';"
    echo ""
    echo -e "${YELLOW}提示: 可以使用以下命令手动修复:${NC}"
    echo "  1. 在 Emby 服务器上创建用户"
    echo "  2. 更新数据库: UPDATE user_emby_accounts SET emby_user_id = 'xxx' WHERE id = xxx;"
fi

# 2. 检查 Emby 服务器连接
echo ""
echo "2. 检查 Emby 服务器连接..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Emby-Token: $EMBY_API_KEY" "$EMBY_URL/System/Info")

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✅ Emby 服务器连接正常${NC}"
else
    echo -e "${RED}❌ Emby 服务器连接失败 (HTTP $HTTP_CODE)${NC}"
fi

# 3. 检查服务器用户数
echo ""
echo "3. 检查用户数统计..."
DB_USER_COUNT=$(docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c \
    "SELECT current_users FROM emby_servers WHERE id = 2;")
EMBY_USER_COUNT=$(curl -s -H "X-Emby-Token: $EMBY_API_KEY" "$EMBY_URL/Users" | \
    python3 -c "import sys,json; users=json.load(sys.stdin); print(len([u for u in users if not u.get('Hidden', False)]))" 2>/dev/null || echo "0")

echo "   数据库记录: $DB_USER_COUNT"
echo "   Emby 实际: $EMBY_USER_COUNT"

# 4. 检查最近的账号创建
echo ""
echo "4. 最近创建的账号 (5条)..."
docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -c \
    "SELECT id, user_id, username, emby_user_id, created_at FROM user_emby_accounts ORDER BY created_at DESC LIMIT 5;"

echo ""
echo "========================================"
echo "检查完成"
echo "========================================"
