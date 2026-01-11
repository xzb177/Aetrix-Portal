#!/bin/bash
################################################################################
# RoyalBot Portal 一键部署脚本
# 用途: 快速部署/更新 RoyalBot Portal 服务
# 使用: ./deploy.sh [选项]
#
# 选项:
#   --build           强制重新构建镜像
#   --no-cache        构建时不使用缓存
#   --backend         仅部署后端服务 (admin + user)
#   --admin-backend   仅部署管理后台后端
#   --user-backend    仅部署用户端后端
#   --frontend        仅部署前端服务 (admin + user)
#   --admin-frontend  仅部署管理后台前端
#   --user-frontend   仅部署用户端前端
#   --admin           仅部署管理后台 (backend + frontend)
#   --user            仅部署用户端 (backend + frontend)
#   --bot             仅部署 Telegram Bot
#   --all             部署所有服务
#   --rollback        回滚到上一版本
#   --status          显示服务状态
#   --logs            显示服务日志
#   --update          更新代码并部署
#   -h, --help        显示帮助信息
################################################################################

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目目录
PROJECT_DIR="/root/RoyalBot-Portal"
cd "$PROJECT_DIR"

# 默认选项
BUILD_FLAG=""
CACHE_FLAG="--pull"
SERVICES=""
ACTION="deploy"

# 解析命令行参数
while [[ $# -gt 0 ]]; do
  case $1 in
    --build)
      BUILD_FLAG="--build --force-recreate"
      shift
      ;;
    --no-cache)
      CACHE_FLAG="--no-cache"
      shift
      ;;
    --backend)
      SERVICES="admin_backend user_backend"
      shift
      ;;
    --admin-backend)
      SERVICES="admin_backend"
      shift
      ;;
    --user-backend)
      SERVICES="user_backend"
      shift
      ;;
    --frontend)
      SERVICES="admin_frontend user_frontend"
      shift
      ;;
    --admin-frontend)
      SERVICES="admin_frontend"
      shift
      ;;
    --user-frontend)
      SERVICES="user_frontend"
      shift
      ;;
    --user)
      SERVICES="user_backend user_frontend"
      shift
      ;;
    --admin)
      SERVICES="admin_backend admin_frontend"
      shift
      ;;
    --bot)
      SERVICES="telegram_login_bot"
      shift
      ;;
    --all)
      SERVICES=""
      shift
      ;;
    --rollback)
      ACTION="rollback"
      shift
      ;;
    --status)
      ACTION="status"
      shift
      ;;
    --logs)
      ACTION="logs"
      shift
      ;;
    --update)
      ACTION="update"
      shift
      ;;
    -h|--help)
      echo "RoyalBot Portal 部署脚本"
      echo ""
      echo "用法: $0 [选项]"
      echo ""
      echo "选项:"
      echo "  --build           强制重新构建镜像"
      echo "  --no-cache        构建时不使用缓存"
      echo "  --backend         仅部署后端服务 (admin + user)"
      echo "  --admin-backend   仅部署管理后台后端"
      echo "  --user-backend    仅部署用户端后端"
      echo "  --frontend        仅部署前端服务 (admin + user)"
      echo "  --admin-frontend  仅部署管理后台前端"
      echo "  --user-frontend   仅部署用户端前端"
      echo "  --admin           仅部署管理后台 (backend + frontend)"
      echo "  --user            仅部署用户端 (backend + frontend)"
      echo "  --bot             仅部署 Telegram Bot"
      echo "  --all             部署所有服务"
      echo "  --rollback        回滚到上一版本"
      echo "  --status          显示服务状态"
      echo "  --logs            显示服务日志"
      echo "  --update          更新代码并部署"
      echo "  -h, --help        显示帮助信息"
      echo ""
      echo "示例:"
      echo "  $0                # 部署默认服务 (admin_backend + admin_frontend)"
      echo "  $0 --build        # 强制重新构建并部署"
      echo "  $0 --backend      # 仅部署后端服务 (admin + user)"
      echo "  $0 --admin        # 仅部署管理后台"
      echo "  $0 --user         # 仅部署用户端"
      echo "  $0 --update       # 更新代码并部署"
      echo "  $0 --rollback     # 回滚到上一版本"
      echo "  $0 --status       # 显示服务状态"
      exit 0
      ;;
    *)
      echo -e "${RED}未知选项: $1${NC}"
      echo "使用 -h 或 --help 查看帮助"
      exit 1
      ;;
  esac
done

# 日志函数
log_info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
  echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

# 检查环境
check_environment() {
  log_info "检查部署环境..."

  # 检查 Docker
  if ! command -v docker &> /dev/null; then
    log_error "Docker 未安装"
    exit 1
  fi

  # 检查 docker compose
  if ! docker compose version &> /dev/null; then
    log_error "Docker Compose 未安装"
    exit 1
  fi

  # 检查 .env 文件
  if [ ! -f "$PROJECT_DIR/.env" ]; then
    log_warning ".env 文件不存在，将从 .env.example 复制"
    if [ -f "$PROJECT_DIR/.env.example" ]; then
      cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
      log_warning "请编辑 .env 文件配置必要的环境变量！"
    else
      log_error ".env.example 文件不存在"
      exit 1
    fi
  fi

  log_success "环境检查通过"
}

# 更新代码
update_code() {
  log_info "更新代码..."

  # 检查是否是 git 仓库
  if [ -d ".git" ]; then
    # 保存当前 commit
    CURRENT_COMMIT=$(git rev-parse HEAD)

    # 拉取最新代码
    git fetch origin
    git pull origin main

    NEW_COMMIT=$(git rev-parse HEAD)

    if [ "$CURRENT_COMMIT" != "$NEW_COMMIT" ]; then
      log_success "代码已更新: $CURRENT_COMMIT -> $NEW_COMMIT"
      git log --oneline -1
    else
      log_info "代码已是最新版本"
    fi
  else
    log_warning "不是 Git 仓库，跳过代码更新"
  fi
}

# 构建镜像
build_images() {
  log_info "构建 Docker 镜像..."

  if [ -z "$SERVICES" ]; then
    # 默认构建 admin_backend 和 admin_frontend
    docker compose build $CACHE_FLAG admin_backend admin_frontend
  else
    # 根据指定的服务构建
    for service in $SERVICES; do
      case $service in
        admin_backend|admin_frontend|user_backend|user_frontend|telegram_login_bot)
          docker compose build $CACHE_FLAG $service
          ;;
        *)
          log_warning "未知服务: $service，跳过构建"
          ;;
      esac
    done
  fi

  log_success "镜像构建完成"
}

# 部署服务
deploy_services() {
  log_info "部署服务..."

  if [ -z "$SERVICES" ]; then
    SERVICES="admin_backend admin_frontend"
  fi

  # 停止旧服务
  log_info "停止旧服务: $SERVICES"
  docker compose stop $SERVICES 2>/dev/null || true

  # 启动新服务
  log_info "启动新服务: $SERVICES"
  docker compose up -d $BUILD_FLAG $SERVICES

  # 等待服务健康检查
  log_info "等待服务健康检查..."
  sleep 5

  # 检查服务状态
  for service in $SERVICES; do
    CONTAINER_NAME="royalbot_${service}"
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
      STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null)
      HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "no healthcheck")

      if [ "$HEALTH_STATUS" = "healthy" ] || [ "$HEALTH_STATUS" = "no healthcheck" ]; then
        log_success "$service 服务运行正常 ($STATUS)"
      elif [ "$HEALTH_STATUS" = "starting" ]; then
        log_warning "$service 服务正在启动..."
      else
        log_warning "$service 服务健康检查: $HEALTH_STATUS"
      fi
    else
      log_error "$service 服务未启动"
    fi
  done

  log_success "服务部署完成"
}

# 回滚
rollback() {
  log_warning "开始回滚到上一版本..."

  if [ ! -d ".git" ]; then
    log_error "不是 Git 仓库，无法回滚"
    exit 1
  fi

  # 保存当前 commit
  CURRENT_COMMIT=$(git rev-parse HEAD)

  # 回滚到上一个 commit
  log_info "回滚到上一个 commit..."
  git reset --hard HEAD~1

  # 重新构建并部署
  build_images
  deploy_services

  log_success "回滚完成 (从 $CURRENT_COMMIT)"
}

# 显示状态
show_status() {
  log_info "服务状态:"
  echo ""
  docker compose ps
  echo ""

  # 显示镜像信息
  log_info "最近构建的镜像:"
  docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}\t{{.Size}}" | grep -E "REPOSITORY|royalbot"
}

# 显示日志
show_logs() {
  if [ -z "$SERVICES" ]; then
    docker compose logs -f --tail=100
  else
    docker compose logs -f --tail=100 $SERVICES
  fi
}

# 健康检查
health_check() {
  log_info "执行健康检查..."

  # 检查后端健康
  if curl -f -s http://localhost:8080/health > /dev/null; then
    log_success "admin_backend 健康检查通过"
  else
    log_error "admin_backend 健康检查失败"
  fi

  # 检查前端
  if curl -f -s http://localhost/ > /dev/null; then
    log_success "nginx 健康检查通过"
  else
    log_error "nginx 健康检查失败"
  fi

  # 外部检查
  EXTERNAL_URL="${API_URL:-https://login.laodaemby.xyz}"
  if curl -f -s "$EXTERNAL_URL/health" > /dev/null; then
    log_success "外部健康检查通过 ($EXTERNAL_URL)"
  else
    log_warning "外部健康检查失败 ($EXTERNAL_URL)"
  fi
}

# 清理旧镜像
cleanup() {
  log_info "清理旧镜像..."
  docker image prune -af --filter "until=24h" || true
  log_success "清理完成"
}

# 主函数
main() {
  echo ""
  echo "=========================================="
  echo "  RoyalBot Portal 部署脚本"
  echo "=========================================="
  echo ""

  check_environment

  case $ACTION in
    update)
      update_code
      build_images
      deploy_services
      cleanup
      health_check
      ;;
    rollback)
      rollback
      health_check
      ;;
    status)
      show_status
      ;;
    logs)
      show_logs
      ;;
    deploy)
      build_images
      deploy_services
      cleanup
      health_check
      ;;
  esac

  echo ""
  log_success "部署脚本执行完成！"
  echo ""
}

# 执行主函数
main
