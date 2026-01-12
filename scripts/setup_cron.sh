#!/bin/bash
#
# Setup cron jobs for database backups
#
# This script configures automated database backups using cron
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/backup_db.sh"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    log_warn "This script should be run with sudo to set up cron jobs"
    log_warn "Run: sudo $0"
fi

log_info "Setting up automated database backups..."
log_info ""

# Define cron jobs
# Daily backup at 2 AM
DAILY_CRON="0 2 * * * $BACKUP_SCRIPT all > /var/log/portal_backup.log 2>&1"

# Weekly full backup on Sunday at 3 AM
WEEKLY_CRON="0 3 * * 0 $BACKUP_SCRIPT all > /var/log/portal_backup_weekly.log 2>&1"

# Check if crontab already has our jobs
if crontab -l 2>/dev/null | grep -q "backup_db.sh"; then
    log_warn "Cron jobs for backup_db.sh already exist."
    log_info "Current crontab entries:"
    crontab -l 2>/dev/null | grep "backup_db.sh"
    echo ""
    read -p "Do you want to replace them? (y/n): " replace

    if [ "$replace" = "y" ]; then
        # Remove existing backup entries
        crontab -l 2>/dev/null | grep -v "backup_db.sh" | crontab -
    else
        log_info "Keeping existing cron jobs."
        exit 0
    fi
fi

# Add new cron jobs
log_info "Adding cron jobs..."
(crontab -l 2>/dev/null; echo "$DAILY_CRON"; echo "$WEEKLY_CRON") | crontab -

log_info ""
log_info "========================================="
log_info "Cron jobs configured successfully!"
log_info "========================================="
log_info ""
log_info "Daily backup schedule:"
log_info "  - Runs daily at 2:00 AM"
log_info "  - Backs up: portal_user, portal_admin"
log_info "  - Retention: 7 days"
log_info ""
log_info "Weekly backup schedule:"
log_info "  - Runs every Sunday at 3:00 AM"
log_info "  - Same databases, weekly retention: 30 days"
log_info ""
log_info "Backup location: ${BACKUP_DIR:-/root/RoyalBot-Portal/backups}"
log_info ""
log_info "To view current cron jobs: crontab -l"
log_info "To view backups: $SCRIPT_DIR/list_backups.sh"
log_info "To restore: $SCRIPT_DIR/restore_db.sh <db_name> <backup_file>"
log_info "========================================="
