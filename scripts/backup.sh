#!/bin/bash
# Aetrix Emby Portal - Database Backup Script

set -e

# Configuration
# 容器 / 库 / 账号名跟着项目品牌统一，但**全部可用环境变量覆盖**：
# 沿用旧栈命名（改名前的容器 / 库 / 账号）的部署，设一下这三个就能继续用。
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}
DB_CONTAINER="${DB_CONTAINER:-aetrix_postgres}"
DB_USER="${DB_USER:-aetrix}"
DB_NAME="${DB_NAME:-aetrix}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/aetrix_${TIMESTAMP}.sql.gz"

# Colors
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup database
log_info "开始备份..."
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"
log_info "备份完成: $BACKUP_FILE"

# Cleanup old backups
log_info "清理 ${RETENTION_DAYS} 天前的备份..."
find "$BACKUP_DIR" -name "aetrix_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

# List backups
log_info "当前备份列表:"
ls -lh "$BACKUP_DIR"/aetrix_*.sql.gz 2>/dev/null || echo "无备份文件"
