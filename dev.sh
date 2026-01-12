#!/bin/bash
# RoyalBot Portal 开发模式启动脚本
# 使用代码挂载，修改代码后自动生效

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

print_header "RoyalBot Portal - 开发模式启动"

echo ""
echo -e "${BOLD}开发模式特性：${NC}"
echo "  ✓ 后端代码修改后自动重载"
echo "  ✓ 前端代码修改后热更新"
echo "  ✓ 日志实时输出"
echo "  ✓ 代码挂载（无需重新构建）"
echo ""
echo -e "${BOLD}访问地址：${NC}"
echo "  - 用户端: http://localhost"
echo "  - 管理后台: http://localhost/admin"
echo "  - 用户 API: http://localhost:8001/docs"
echo "  - 管理 API: http://localhost:8080/docs"
echo ""

# 检查 Docker Compose
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# 检查开发配置文件
if [ ! -f docker-compose.dev.yml ]; then
    echo -e "${RED}✗ docker-compose.dev.yml 不存在${NC}"
    echo -e "${YELLOW}请确保开发配置文件存在${NC}"
    exit 1
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ .env 文件不存在，从 .env.example 复制...${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ .env 文件已创建${NC}"
        echo -e "${YELLOW}⚠ 请编辑 .env 文件配置必要的环境变量${NC}"
    else
        echo -e "${RED}✗ .env.example 文件不存在${NC}"
        exit 1
    fi
fi

# 停止现有服务
echo -e "${BLUE}ℹ${NC} 停止现有服务..."
$DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml down 2>/dev/null || true

# 构建并启动开发模式服务
echo ""
echo -e "${BLUE}ℹ${NC} 构建后端服务（支持代码热重载）..."
$DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml build user_backend admin_backend

echo ""
echo -e "${BLUE}ℹ${NC} 启动服务..."
$DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis user_backend admin_backend user_frontend admin_frontend nginx

echo ""
print_header "开发模式已启动！"

echo ""
echo -e "${BOLD}常用命令：${NC}"
echo ""
echo "查看日志："
echo "  $DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml logs -f"
echo ""
echo "查看特定服务日志："
echo "  $DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml logs -f user_backend"
echo "  $DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml logs -f admin_backend"
echo ""
echo "停止服务："
echo "  $DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml down"
echo ""
echo "重启特定服务："
echo "  $DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml restart user_backend"
echo ""
echo "进入后端容器："
echo "  $DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml exec user_backend bash"
echo "  $DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml exec admin_backend bash"
echo ""
echo -e "${BOLD}前端开发服务器（可选，需要额外配置）：${NC}"
echo ""
echo "用户端 Vite 开发服务器："
echo "  cd user_frontend"
echo "  npm install"
echo "  npm run dev"
echo "  # 访问: http://localhost:5173"
echo ""
echo "管理后台 Vite 开发服务器："
echo "  cd admin_frontend"
echo "  npm install"
echo "  npm run dev"
echo "  # 访问: http://localhost:5174"
echo ""

# 显示服务状态
echo -e "${BOLD}服务状态：${NC}"
$DOCKER_COMPOSE -f docker-compose.yml -f docker-compose.dev.yml ps

echo ""
print_header "开发环境准备完成"
echo ""
