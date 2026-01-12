#!/bin/bash
# ==============================================================================
# RoyalBot Portal 密钥轮换脚本
# ==============================================================================
# 用途: 轮换敏感密钥（JWT、数据库密码等）
# 使用: ./rotate-secrets.sh [jwt|postgres|redis|crypto|all]
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 生成强密钥的函数
generate_strong_secret() {
    openssl rand -base64 64 | tr -d '=+/' | cut -c1-64
}

# 备份 .env
backup_env() {
    BACKUP_FILE=".env.backup.$(date +%Y%m%d_%H%M%S)"
    cp .env "$BACKUP_FILE"
    echo -e "${GREEN}✓ 备份到 $BACKUP_FILE${NC}"
}

# 轮换 JWT 密钥
rotate_jwt_secret() {
    echo -e "${YELLOW}轮换 JWT 密钥...${NC}"
    NEW_SECRET=$(generate_strong_secret)
    sed -i "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$NEW_SECRET/" .env
    echo -e "${GREEN}✓ JWT 密钥已轮换${NC}"
    echo -e "${RED}⚠️  所有现有会话将失效！${NC}"
}

# 轮换用户端密钥
rotate_user_secret() {
    echo -e "${YELLOW}轮换用户端密钥...${NC}"
    NEW_SECRET=$(generate_strong_secret)
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$NEW_SECRET/" .env
    echo -e "${GREEN}✓ 用户端密钥已轮换${NC}"
}

# 轮换 PostgreSQL 密码
rotate_postgres_password() {
    echo -e "${YELLOW}轮换 PostgreSQL 密码...${NC}"
    NEW_PASSWORD=$(generate_strong_secret)
    OLD_PASSWORD=$(grep "^POSTGRES_PASSWORD=" .env | cut -d= -f2)

    # 更新 .env
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$NEW_PASSWORD/" .env

    # 尝试更新 PostgreSQL (需要 Docker 容器运行)
    if docker ps | grep -q royalbot_postgres; then
        docker exec -i royalbot_postgres psql -U royalbot -c "ALTER USER royalbot WITH PASSWORD '$NEW_PASSWORD';" 2>/dev/null || true
        echo -e "${GREEN}✓ PostgreSQL 密码已轮换${NC}"
    else
        echo -e "${YELLOW}⚠️  PostgreSQL 容器未运行，请手动更新数据库密码${NC}"
    fi
}

# 轮换 Redis 密码
rotate_redis_password() {
    echo -e "${YELLOW}轮换 Redis 密钥...${NC}"
    NEW_PASSWORD=$(generate_strong_secret)
    sed -i "s/^REDIS_PASSWORD=.*/REDIS_PASSWORD=$NEW_PASSWORD/" .env
    echo -e "${GREEN}✓ Redis 密钥已轮换${NC}"
    echo -e "${YELLOW}⚠️  需要重启 Redis 容器${NC}"
}

# 轮换加密密钥
rotate_crypto_key() {
    echo -e "${YELLOW}轮换加密密钥...${NC}"
    NEW_KEY=$(generate_strong_secret)
    sed -i "s/^CRYPTO_KEY=.*/CRYPTO_KEY=$NEW_KEY/" .env
    echo -e "${GREEN}✓ 加密密钥已轮换${NC}"
    echo -e "${RED}⚠️  使用旧密钥加密的数据将无法解密！${NC}"
}

# 显示帮助
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  jwt       轮换 JWT 密钥 (会话将失效)"
    echo "  user      轮换用户端密钥"
    echo "  postgres  轮换 PostgreSQL 密码"
    echo "  redis     轮换 Redis 密码"
    echo "  crypto    轮换加密密钥 (数据可能丢失)"
    echo "  all       轮换所有密钥"
    echo "  help      显示此帮助"
    echo ""
    echo "示例:"
    echo "  $0 jwt           # 只轮换 JWT 密钥"
    echo "  $0 all           # 轮换所有密钥"
}

# 主函数
case "${1:-help}" in
    jwt)
        backup_env
        rotate_jwt_secret
        echo ""
        echo -e "${YELLOW}请重启后端服务使更改生效：${NC}"
        echo "  docker compose restart admin_backend user_backend"
        ;;
    user)
        backup_env
        rotate_user_secret
        echo ""
        echo -e "${YELLOW}请重启用户端后端服务：${NC}"
        echo "  docker compose restart user_backend"
        ;;
    postgres)
        backup_env
        rotate_postgres_password
        echo ""
        echo -e "${YELLOW}请重启所有服务：${NC}"
        echo "  docker compose restart"
        ;;
    redis)
        backup_env
        rotate_redis_password
        echo ""
        echo -e "${YELLOW}请重启相关服务：${NC}"
        echo "  docker compose restart admin_backend user_backend redis"
        ;;
    crypto)
        backup_env
        rotate_crypto_key
        ;;
    all)
        backup_env
        echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}"
        echo -e "${RED}⚠️  警告：轮换所有密钥将导致所有服务中断！${NC}"
        echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}"
        read -p "确认继续? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            rotate_jwt_secret
            rotate_user_secret
            rotate_postgres_password
            rotate_redis_password
            rotate_crypto_key
            echo ""
            echo -e "${GREEN}✓ 所有密钥已轮换，请重启所有服务${NC}"
        else
            echo -e "${YELLOW}已取消${NC}"
        fi
        ;;
    *)
        show_help
        ;;
esac
