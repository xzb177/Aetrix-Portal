#!/bin/bash
# ==============================================================================
# RoyalBot Portal 密钥生成脚本
# ==============================================================================
# 用途: 生成安全的随机密钥用于生产环境
# 使用: ./generate-secrets.sh
# ==============================================================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 生成强密钥的函数
generate_strong_secret() {
    openssl rand -base64 64 | tr -d '=+/' | cut -c1-64
}

generate_medium_secret() {
    openssl rand -base64 32 | tr -d '=+/' | cut -c1-32
}

# 备份现有 .env 文件
if [ -f .env ]; then
    BACKUP_FILE=".env.backup.$(date +%Y%m%d_%H%M%S)"
    echo -e "${YELLOW}备份现有 .env 到 $BACKUP_FILE${NC}"
    cp .env "$BACKUP_FILE"
fi

# 生成管理员密码
ADMIN_PASSWORD=$(generate_strong_secret | head -c 20)

echo -e "${GREEN}生成新的安全密钥...${NC}"

# 读取现有 .env 中的非敏感配置
if [ -f .env ]; then
    API_URL=$(grep "^API_URL=" .env | cut -d= -f2 || echo "https://login.laodaemby.xyz")
    FRONTEND_URL=$(grep "^FRONTEND_URL=" .env | cut -d= -f2 || echo "https://login.laodaemby.xyz")
    VITE_API_BASE_URL=$(grep "^VITE_API_BASE_URL=" .env | cut -d= -f2 || echo "https://login.laodaemby.xyz")
    COOKIE_DOMAIN=$(grep "^COOKIE_DOMAIN=" .env | cut -d= -f2 || echo ".laodaemby.xyz")
    TELEGRAM_BOT_TOKEN=$(grep "^TELEGRAM_BOT_TOKEN=" .env | cut -d= -f2 || echo "")
    TELEGRAM_BOT_USERNAME=$(grep "^TELEGRAM_BOT_USERNAME=" .env | cut -d= -f2 || echo "")
    TELEGRAM_ADMIN_ID=$(grep "^TELEGRAM_ADMIN_ID=" .env | cut -d= -f2 || echo "")
    TELEGRAM_LOGIN_BOT_TOKEN=$(grep "^TELEGRAM_LOGIN_BOT_TOKEN=" .env | cut -d= -f2 || echo "")
    ADMIN_IDS=$(grep "^ADMIN_IDS=" .env | cut -d= -f2 || echo "")
    YIPAY_GATEWAY_URL=$(grep "^YIPAY_GATEWAY_URL=" .env | cut -d= -f2 || echo "")
    YIPAY_PARTNER_ID=$(grep "^YIPAY_PARTNER_ID=" .env | cut -d= -f2 || echo "")
    YIPAY_KEY=$(grep "^YIPAY_KEY=" .env | cut -d= -f2 || echo "")
else
    API_URL="https://login.laodaemby.xyz"
    FRONTEND_URL="https://login.laodaemby.xyz"
    VITE_API_BASE_URL="https://login.laodaemby.xyz"
    COOKIE_DOMAIN=".laodaemby.xyz"
fi

# 生成 .env 文件
cat > .env << EOF
# ==============================================================================
# RoyalBot Portal - 环境配置
# ==============================================================================
# 生成时间: $(date)
# 警告: 请妥善保管此文件，不要提交到版本控制系统！
# ==============================================================================

# ==================== 数据库配置 ====================
POSTGRES_PASSWORD=$(generate_strong_secret)
REDIS_PASSWORD=$(generate_strong_secret)

# ==================== JWT 配置 ====================
# 管理后台 JWT 密钥 (admin_backend) - 至少 64 字符
JWT_SECRET_KEY=$(generate_strong_secret)
# 用户端 JWT 密钥 (user_backend) - 与管理后台使用不同密钥
SECRET_KEY=$(generate_strong_secret)

# ==================== 应用配置 ====================
# API 地址（用于前端和回调）
API_URL=${API_URL}
EXTERNAL_API_URL=${API_URL}

# 前端 URL（用于 CORS）
FRONTEND_URL=${FRONTEND_URL}
ADDITIONAL_CORS_ORIGINS=${FRONTEND_URL},http://154.40.33.2

# Vite 构建时使用的 API 地址
VITE_API_BASE_URL=${VITE_API_BASE_URL}

# 调试模式（生产环境必须为 False）
DEBUG=False

# ==================== 管理员配置 ====================
# 管理后台默认管理员密码
# 警告：首次部署后请立即修改管理员密码！
DEFAULT_ADMIN_PASSWORD=${ADMIN_PASSWORD}

# ==================== Telegram 配置 ====================
TELEGRAM_BOT_TOKEN=\${TELEGRAM_BOT_TOKEN:-$TELEGRAM_BOT_TOKEN}
TELEGRAM_BOT_USERNAME=\${TELEGRAM_BOT_USERNAME:-$TELEGRAM_BOT_USERNAME}
TELEGRAM_ADMIN_ID=\${TELEGRAM_ADMIN_ID:-$TELEGRAM_ADMIN_ID}

# ==================== 支付配置 ====================
YIPAY_GATEWAY_URL=\${YIPAY_GATEWAY_URL:-$YIPAY_GATEWAY_URL}
YIPAY_PARTNER_ID=\${YIPAY_PARTNER_ID:-$YIPAY_PARTNER_ID}
YIPAY_KEY=\${YIPAY_KEY:-$YIPAY_KEY}
# 订阅支付回调地址
YIPAY_NOTIFY_URL=${API_URL}/api/user/payment/notify
YIPAY_RETURN_URL=${API_URL}/payment/return
# 充值支付回调地址
YIPAY_RECHARGE_NOTIFY_URL=${API_URL}/api/user/recharge/notify
YIPAY_RECHARGE_RETURN_URL=${API_URL}/recharge/return

# ==================== 监控配置 ====================
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=$(generate_strong_secret)

# ==================== 安全配置 ====================
# 最小密码长度
MIN_PASSWORD_LENGTH=12
# 登录失败锁定
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION_MINUTES=30

# ==================== Cookie 配置 ====================
# Cookie 域名 (注意前面的点，支持所有子域名)
COOKIE_DOMAIN=${COOKIE_DOMAIN}
# 是否启用 Cookie 认证
ENABLE_COOKIE_AUTH=true

# ==================== 日志配置 ====================
LOG_LEVEL=INFO

# ==================== 外部数据库配置 ====================
# 主项目数据库路径（用于获取 Telegram 用户积分等信息）
ROYALBOT_DB_PATH=/root/royalbot/royalbot.db

# ==================== Telegram 登录 Bot ====================
TELEGRAM_LOGIN_BOT_TOKEN=\${TELEGRAM_LOGIN_BOT_TOKEN:-$TELEGRAM_LOGIN_BOT_TOKEN}
WEB_URL=${API_URL}
ADMIN_IDS=\${ADMIN_IDS:-$ADMIN_IDS}

# ==================== 加密密钥 ====================
# 用于加密 API Key 等敏感数据（至少 32 字符）
CRYPTO_KEY=$(generate_strong_secret)
EOF

# 设置文件权限
chmod 600 .env

echo -e "${GREEN}✓ 密钥生成完成！${NC}"
echo ""
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${RED}⚠️  重要：请立即保存以下管理员密码，丢失后无法恢复！${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}DEFAULT_ADMIN_PASSWORD = ${ADMIN_PASSWORD}${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}✓ .env 文件权限已设置为 600${NC}"
echo -e "${GREEN}✓ 备份文件: $BACKUP_FILE${NC}"
echo ""
echo -e "${YELLOW}下一步：${NC}"
echo "1. 检查 .env 文件中的配置是否正确"
echo "2. 重启服务: docker compose restart"
echo "3. 使用新密码登录管理后台"
EOF
