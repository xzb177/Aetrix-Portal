#!/bin/bash
#
# RoyalBot Portal Backup Listing Script
#
# This script lists all available database backups
#

BACKUP_DIR="${BACKUP_DIR:-/root/RoyalBot-Portal/backups}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}RoyalBot Portal Database Backups${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""

for dir in daily weekly monthly; do
    if [ -d "$BACKUP_DIR/$dir" ]; then
        count=$(find "$BACKUP_DIR/$dir" -name "*.sql.gz" 2>/dev/null | wc -l)
        if [ $count -gt 0 ]; then
            echo -e "${BLUE}$dir backups ($count files):${NC}"
            echo ""
            printf "%-50s %15s %15s\n" "File" "Size" "Date"
            printf "%-50s %15s %15s\n" "----" "----" "----"

            find "$BACKUP_DIR/$dir" -name "*.sql.gz" -printf "%f %s %T+\n" 2>/dev/null | sort -r -k3 | head -10 | while read -r line; do
                filename=$(echo "$line" | cut -d' ' -f1)
                size=$(echo "$line" | cut -d' ' -f2 | awk '{printf "%.1fM", $1/1024/1024}')
                date=$(echo "$line" | cut -d' ' -f3- | cut -d'.' -f1)

                # Truncate filename if too long
                if [ ${#filename} -gt 47 ]; then
                    filename="...${filename: -44}"
                fi

                printf "%-50s %15s %15s\n" "$filename" "$size" "$date"
            done
            echo ""
        fi
    fi
done

# Show total space used
total_size=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
echo -e "${YELLOW}Total backup size: $total_size${NC}"
