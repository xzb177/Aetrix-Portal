#!/bin/bash
# RoyalBot Portal Docker 快速部署脚本
# 这是一个简化的脚本，推荐使用 ./deploy.sh 获得完整功能

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

print_header() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  RoyalBot Portal Docker 部署工具${NC}"
echo -e "${BLUE}========================================${NC}"

# 检查 Docker 和 Docker Compose
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker 未安装，请先安装 Docker${NC}"
    exit 1
fi

# 使用 docker compose 还是 docker-compose
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}✗ Docker Compose 未安装，请先安装 Docker Compose${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker 环境检查通过${NC}"

# 检查 .env 文件
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ .env 文件不存在，从 .env.example 复制...${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env

        # 生成随机密码
        POSTGRES_PASSWORD=$(openssl rand -base64 16 | tr -d '/+=')
        REDIS_PASSWORD=$(openssl rand -base64 16 | tr -d '/+=')
        JWT_SECRET_KEY=$(openssl rand -base64 32 | tr -d '/+=')
        CRYPTO_KEY=$(openssl rand -base64 32 | tr -d '/+=')
        CRON_SECRET=$(openssl rand -base64 16 | tr -d '/+=')
        DEFAULT_ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')
        GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')

        sed -i "s/POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASSWORD}/" .env
        sed -i "s/REDIS_PASSWORD=.*/REDIS_PASSWORD=${REDIS_PASSWORD}/" .env
        sed -i "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=${JWT_SECRET_KEY}/" .env
        sed -i "s/CRYPTO_KEY=.*/CRYPTO_KEY=${CRYPTO_KEY}/" .env
        sed -i "s/CRON_SECRET=.*/CRON_SECRET=${CRON_SECRET}/" .env
        sed -i "s/DEFAULT_ADMIN_PASSWORD=.*/DEFAULT_ADMIN_PASSWORD=${DEFAULT_ADMIN_PASSWORD}/" .env
        sed -i "s/GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}/" .env

        echo -e "${GREEN}✓ 随机密码已生成${NC}"
        echo -e "${YELLOW}⚠ 请编辑 .env 文件配置密码和密钥！${NC}"
        echo -e "${YELLOW}  编辑命令: vi .env${NC}"
    else
        echo -e "${RED}✗ .env.example 文件不存在${NC}"
        exit 1
    fi
    read -p "按回车继续..."
fi

# 菜单
show_menu() {
    echo ""
    echo -e "${BOLD}请选择操作:${NC}"
    echo "  1. 构建并启动所有服务"
    echo "  2. 启动服务（不重新构建）"
    echo "  3. 停止服务"
    echo "  4. 重启服务"
    echo "  5. 查看服务状态"
    echo "  6. 查看日志"
    echo "  7. 停止并清理所有服务"
    echo "  8. 更新服务（重新构建）"
    echo "  9. 构建前端"
    echo " 10. 备份数据库"
    echo " 11. 恢复数据库"
    echo "  0. 退出"
    echo -n "请输入选项: "
}

# 构建并启动
build_and_start() {
    print_header "构建并启动服务"
    $DOCKER_COMPOSE up -d --build
    echo -e "${GREEN}✓ 服务启动完成${NC}"
    show_status
}

# 启动服务
start_services() {
    print_header "启动服务"
    $DOCKER_COMPOSE up -d
    echo -e "${GREEN}✓ 服务启动完成${NC}"
    show_status
}

# 停止服务
stop_services() {
    print_header "停止服务"
    $DOCKER_COMPOSE stop
    echo -e "${GREEN}✓ 服务已停止${NC}"
}

# 重启服务
restart_services() {
    print_header "重启服务"
    $DOCKER_COMPOSE restart
    echo -e "${GREEN}✓ 服务已重启${NC}"
    show_status
}

# 显示状态
show_status() {
    echo ""
    echo -e "${BOLD}服务状态:${NC}"
    $DOCKER_COMPOSE ps
    echo ""
    echo -e "${BOLD}访问地址:${NC}"
    echo "  用户端: http://localhost/"
    echo "  管理后台: http://localhost/admin"
    echo "  用户 API: http://localhost:8001/docs"
    echo "  管理 API: http://localhost:8080/docs"
    echo "  Prometheus: http://localhost:9090"
    echo "  Grafana: http://localhost:3002"
}

# 查看日志
show_logs() {
    echo -n "请输入服务名称 (留空查看所有): "
    read service
    if [ -z "$service" ]; then
        $DOCKER_COMPOSE logs -f
    else
        $DOCKER_COMPOSE logs -f "$service"
    fi
}

# 清理服务
clean_services() {
    echo -e "${RED}警告: 此操作将停止并删除所有容器、网络和匿名卷！${NC}"
    read -p "确认继续? (y/N): " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        $DOCKER_COMPOSE down -v
        echo -e "${GREEN}✓ 清理完成${NC}"
    else
        echo "操作已取消"
    fi
}

# 更新服务
update_services() {
    print_header "更新服务"
    $DOCKER_COMPOSE up -d --build
    echo -e "${GREEN}✓ 服务更新完成${NC}"
    show_status
}

# 构建前端
build_frontend() {
    print_header "构建前端"

    # 构建用户前端
    echo -e "${BLUE}ℹ${NC} 构建用户前端..."
    if [ -d "user_frontend" ] && [ -f "user_frontend/package.json" ]; then
        cd user_frontend
        npm install --legacy-peer-deps
        npm run build
        cd ..
        echo -e "${GREEN}✓ 用户前端构建完成${NC}"
    else
        echo -e "${YELLOW}⚠ user_frontend 不存在或缺少 package.json，跳过${NC}"
    fi

    # 构建管理前端
    echo -e "${BLUE}ℹ${NC} 构建管理前端..."
    if [ -d "admin_frontend" ] && [ -f "admin_frontend/package.json" ]; then
        cd admin_frontend
        npm install --legacy-peer-deps
        npm run build
        cd ..
        echo -e "${GREEN}✓ 管理前端构建完成${NC}"
    else
        echo -e "${YELLOW}⚠ admin_frontend 不存在或缺少 package.json，跳过${NC}"
    fi
}

# 备份数据库
backup_database() {
    print_header "备份数据库"

    mkdir -p backups

    timestamp=$(date +%Y%m%d_%H%M%S)
    backup_file="backups/royalbot_backup_${timestamp}.sql"

    echo -e "${BLUE}ℹ${NC} 正在备份数据库..."

    $DOCKER_COMPOSE exec -T postgres pg_dump -U royalbot royalbot > "$backup_file" 2>/dev/null || {
        echo -e "${RED}✗ 备份失败，请确保 postgres 服务正在运行${NC}"
        return 1
    }

    echo -e "${GREEN}✓ 备份完成: $backup_file${NC}"

    # 压缩备份
    gzip "$backup_file"
    echo -e "${GREEN}✓ 已压缩: ${backup_file}.gz${NC}"
}

# 恢复数据库
restore_database() {
    print_header "恢复数据库"

    # 检查备份目录
    if [ ! -d "backups" ]; then
        echo -e "${RED}✗ backups 目录不存在${NC}"
        return 1
    fi

    # 显示可用备份
    echo ""
    echo -e "${BOLD}可用备份文件:${NC}"
    ls -th backups/*.gz 2>/dev/null || ls -th backups/*.sql 2>/dev/null || {
        echo -e "${RED}✗ 没有找到备份文件${NC}"
        return 1
    }

    echo ""
    echo -n "请输入要恢复的备份文件名: "
    read backup_file

    if [ ! -f "backups/$backup_file" ]; then
        echo -e "${RED}✗ 文件不存在: backups/$backup_file${NC}"
        return 1
    fi

    echo -e "${YELLOW}⚠ 恢复数据库将覆盖现有数据！${NC}"
    read -p "确认继续? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "操作已取消"
        return 0
    fi

    echo -e "${BLUE}ℹ${NC} 正在恢复数据库..."

    if [[ "$backup_file" == *.gz ]]; then
        gunzip -c "backups/$backup_file" | $DOCKER_COMPOSE exec -T postgres psql -U royalbot royalbot
    else
        cat "backups/$backup_file" | $DOCKER_COMPOSE exec -T postgres psql -U royalbot royalbot
    fi

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 恢复完成${NC}"
    else
        echo -e "${RED}✗ 恢复失败${NC}"
    fi
}

# 主循环
while true; do
    show_menu
    read -r choice
    case $choice in
        1) build_and_start; read -p "按回车继续..." ;;
        2) start_services; read -p "按回车继续..." ;;
        3) stop_services; read -p "按回车继续..." ;;
        4) restart_services; read -p "按回车继续..." ;;
        5) show_status; read -p "按回车继续..." ;;
        6) show_logs ;;
        7) clean_services; read -p "按回车继续..." ;;
        8) update_services; read -p "按回车继续..." ;;
        9) build_frontend; read -p "按回车继续..." ;;
        10) backup_database; read -p "按回车继续..." ;;
        11) restore_database; read -p "按回车继续..." ;;
        0) echo "退出"; exit 0 ;;
        *) echo -e "${RED}无效选项${NC}"; sleep 1 ;;
    esac
done
