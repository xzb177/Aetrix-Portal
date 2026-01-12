#!/bin/bash
#
# RoyalBot Portal Database Backup Script
#
# This script backs up PostgreSQL databases and can be run via cron
#
# Usage: ./backup_db.sh [user|admin|all]
#

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/root/RoyalBot-Portal/backups}"
RETENTION_DAYS=${RETENTION_DAYS:-7}
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DATE_ONLY=$(date +"%Y%m%d")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR/daily"
mkdir -p "$BACKUP_DIR/weekly"
mkdir -p "$BACKUP_DIR/monthly"

# Get database credentials from environment or docker-compose
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${POSTGRES_PASSWORD:-}"

if [ -z "$DB_PASSWORD" ]; then
    log_error "POSTGRES_PASSWORD environment variable not set"
    exit 1
fi

export PGPASSWORD="$DB_PASSWORD"

# Backup function
backup_database() {
    local db_name=$1
    local backup_type=$2  # daily, weekly, monthly

    local filename="${db_name}_${backup_type}_${TIMESTAMP}.sql.gz"
    local filepath="$BACKUP_DIR/$backup_type/$filename"

    log_info "Backing up database: $db_name"

    if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
            -d "$db_name" --no-owner --no-acl | gzip > "$filepath"; then
        log_info "Backup completed: $filename"

        # Calculate file size
        size=$(du -h "$filepath" | cut -f1)
        log_info "Backup size: $size"
    else
        log_error "Failed to backup database: $db_name"
        return 1
    fi
}

# Clean old backups
cleanup_old_backups() {
    local backup_type=$1
    local keep_days=$2

    log_info "Cleaning up old $backup_type backups (keeping last $keep_days days)..."

    find "$BACKUP_DIR/$backup_type" -name "*.sql.gz" -mtime +$keep_days -delete
}

# Backup specific databases
backup_user_databases() {
    log_info "Starting user databases backup..."

    # Backup portal_user database
    backup_database "portal_user" "daily"

    # Backup portal_admin database
    backup_database "portal_admin" "daily"
}

# Main backup routine
main() {
    local backup_target=${1:-all}

    log_info "========================================="
    log_info "Database Backup Started at $(date)"
    log_info "========================================="

    case $backup_target in
        user)
            backup_database "portal_user" "daily"
            ;;
        admin)
            backup_database "portal_admin" "daily"
            ;;
        all)
            backup_user_databases
            ;;
        *)
            log_error "Invalid target: $backup_target"
            echo "Usage: $0 [user|admin|all]"
            exit 1
            ;;
    esac

    # Cleanup old backups
    log_info "Cleaning up old backups..."
    cleanup_old_backups "daily" "$RETENTION_DAYS"
    cleanup_old_backups "weekly" 30
    cleanup_old_backups "monthly" 365

    # Generate backup report
    log_info "========================================="
    log_info "Backup Summary:"
    log_info "========================================="

    for dir in daily weekly monthly; do
        count=$(find "$BACKUP_DIR/$dir" -name "*.sql.gz" | wc -l)
        total_size=$(du -sh "$BACKUP_DIR/$dir" 2>/dev/null | cut -f1)
        log_info "$dir backups: $count files, $total_size"
    done

    log_info "========================================="
    log_info "Backup completed at $(date)"
    log_info "========================================="
}

# Run main function
main "$@"
