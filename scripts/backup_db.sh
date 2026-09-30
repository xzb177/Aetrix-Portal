#!/usr/bin/env bash
#
# Aetrix Portal · PostgreSQL 定时备份
#
# 用法：
#   bash scripts/backup_db.sh            # 备份
#   bash scripts/backup_db.sh all        # 兼容旧 cron 行的写法（单库后已无区别）
#
# 设计约束：
# - 统一后端只有一个库（aetrix），不再是旧拆分栈的 portal_user / portal_admin；
# - pg_dump 在 **postgres 容器里** 跑，所以不需要在宿主机 / cron 环境里导出
#   POSTGRES_PASSWORD（cron 没有环境变量，旧脚本正是因此每次直接 exit 1）；
# - 备份完要校验（gzip 完整 + 里面真有 CREATE TABLE）—— 一份空壳备份比不备份更危险；
# - BACKUP_DIR / PG_CONTAINER / DB_NAME / DB_USER 都可用环境变量覆盖。
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

# 默认落在仓库外的 backups/（.gitignore 已忽略，避免 SQLite 部署误提交）
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# docker-compose.yml 里 postgres 服务的 container_name
# （DB_CONTAINER 是 scripts/backup.sh 时代的旧名，一并认，免得老的 cron 行断掉）
PG_CONTAINER="${PG_CONTAINER:-${DB_CONTAINER:-aetrix-postgres}}"
# docker-compose.yml 里 POSTGRES_USER / POSTGRES_DB 的默认值
DB_USER="${DB_USER:-aetrix}"
DB_NAME="${DB_NAME:-aetrix}"

log()  { printf '\033[1;36m[backup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# 兼容旧 cron 行里的 `all` / `user` / `admin`：单库之后它们没有区别，
# 认得就好，别让已经装好的 cron 因为一个多余参数开始报错。
if (($#)); then
  case "$1" in
    all|user|admin) ;;
    *) die "未知参数：$1（用法：bash scripts/backup_db.sh [all|user|admin]）" ;;
  esac
fi

command -v docker >/dev/null 2>&1 || die "找不到 docker。本脚本走容器内 pg_dump；裸机 PG 请自行 pg_dump（见 docs/operations.md）。"

state="$(docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null || true)"
[[ "$state" == "true" ]] || die "容器 $PG_CONTAINER 没在运行。用 docker compose ps 看一眼，或 PG_CONTAINER=xxx 覆盖。"

mkdir -p "$BACKUP_DIR"

stamp="$(date +%Y%m%d-%H%M%S)"
partial="$BACKUP_DIR/.aetrix-$stamp.sql.gz.part"
final="$BACKUP_DIR/aetrix-$stamp.sql.gz"

log "备份 $DB_NAME（容器 $PG_CONTAINER）→ $final"

# 先写临时文件，校验过了再改名：中途失败不会留下一个"看起来像备份"的半成品
if ! docker exec "$PG_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
        --no-owner --no-acl 2>"$BACKUP_DIR/.aetrix-$stamp.err" | gzip > "$partial"; then
  err="$(tail -n 3 "$BACKUP_DIR/.aetrix-$stamp.err" 2>/dev/null | tr '\n' ' ')"
  rm -f "$partial" "$BACKUP_DIR/.aetrix-$stamp.err"
  die "pg_dump 失败：${err:-无输出}（DB_USER=$DB_USER / DB_NAME=$DB_NAME 是否与 .env 一致？）"
fi
rm -f "$BACKUP_DIR/.aetrix-$stamp.err"

gzip -t "$partial" 2>/dev/null || { rm -f "$partial"; die "产出不是合法 gzip，已丢弃。"; }

# grep -c 会把整条流读完，不会给 gzip 发 SIGPIPE（pipefail 下那会让判定反转）
tables="$(gzip -dc "$partial" | grep -c 'CREATE TABLE' || true)"
[[ "${tables:-0}" -ge 1 ]] || { rm -f "$partial"; die "备份里没有 CREATE TABLE，像是空壳，已丢弃。"; }

mv "$partial" "$final"
log "完成：$(du -h "$final" | cut -f1)，含 $tables 张表"

# 保留策略
removed="$(find "$BACKUP_DIR" -maxdepth 1 -name 'aetrix-*.sql.gz' -mtime "+$RETENTION_DAYS" -print -delete | wc -l)"
log "清理超过 $RETENTION_DAYS 天的备份：删除 $removed 个"
log "当前共 $(find "$BACKUP_DIR" -maxdepth 1 -name 'aetrix-*.sql.gz' | wc -l) 份备份在 $BACKUP_DIR"
