#!/bin/bash
#
# 【已并入 scripts/backup_db.sh】保留这个文件名只为不让已经装好的 cron 行断掉。
#
# 它曾经是另一份独立实现，而且默认容器名写的是 ``aetrix_postgres``（下划线），
# docker-compose.yml 里实际是 ``aetrix-postgres``（连字符）——每次调用都是
# "No such container"，等于静默不产备份。与其修两份、以后再漂移，不如只留一份。
#
# 用法同 backup_db.sh：BACKUP_DIR / RETENTION_DAYS / PG_CONTAINER（旧名 DB_CONTAINER）
# 都仍然生效。
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

printf '\033[1;33m[deprecated]\033[0m scripts/backup.sh 已并入 scripts/backup_db.sh，请改用后者（含备份完整性校验）。\n' >&2

exec bash "$SCRIPT_DIR/backup_db.sh" "$@"
