#!/bin/sh
#
# Docker Database Backup Script
# Runs inside the backup container
#

set -e

BACKUP_DIR="/backups"
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DATE_ONLY=$(date +"%Y%m%d")

# Create subdirectories
mkdir -p "$BACKUP_DIR/daily"
mkdir -p "$BACKUP_DIR/weekly"
mkdir -p "$BACKUP_DIR/monthly"

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Backup function
backup_database() {
    local backup_type=$1
    local filename="${PGDATABASE}_${backup_type}_${TIMESTAMP}.sql.gz"
    local filepath="$BACKUP_DIR/$backup_type/$filename"

    log "Starting $backup_type backup of database: $PGDATABASE"

    if pg_dump --no-owner --no-acl | gzip > "$filepath"; then
        size=$(du -h "$filepath" | cut -f1)
        log "Backup completed: $filename ($size)"
    else
        log "ERROR: Failed to backup database"
        return 1
    fi
}

# Cleanup old backups
cleanup_old_backups() {
    local backup_type=$1
    local keep_days=$2

    log "Cleaning up old $backup_type backups (keeping last $keep_days days)..."

    find "$BACKUP_DIR/$backup_type" -name "*.sql.gz" -mtime +$keep_days -delete 2>/dev/null || true
}

# Main
case "$1" in
    daily)
        backup_database "daily"
        cleanup_old_backups "daily" "$RETENTION_DAYS"
        ;;
    weekly)
        backup_database "weekly"
        cleanup_old_backups "weekly" 30
        ;;
    monthly)
        backup_database "monthly"
        cleanup_old_backups "monthly" 365
        ;;
    *)
        log "Usage: $0 {daily|weekly|monthly}"
        exit 1
        ;;
esac

# Report
log "Backup summary:"
for dir in daily weekly monthly; do
    count=$(find "$BACKUP_DIR/$dir" -name "*.sql.gz" 2>/dev/null | wc -l)
    total_size=$(du -sh "$BACKUP_DIR/$dir" 2>/dev/null | cut -f1)
    log "  $dir: $count files, $total_size"
done
