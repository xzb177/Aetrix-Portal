#!/usr/bin/env bash
# Aetrix Portal Docker 一键更新脚本
#
# 默认流程：检查工作区 → 备份数据库（尽可能）→ git pull --ff-only
#          → docker compose build --pull → docker compose up -d --remove-orphans
#
# 设计约束：
# - 有未提交改动时直接拒绝，避免 git pull 覆盖现场；
# - 更新前尽量备份容器内的 SQLite，备份失败会阻断更新；
# - 任何一步失败立即退出，不继续执行后续步骤；
# - 不碰 .env、数据库卷、媒体目录和宿主机配置。
#
# 用法：
#   bash scripts/update.sh
#   bash scripts/update.sh --dry-run
#   bash scripts/update.sh --skip-backup

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$ROOT_DIR"

DRY_RUN=0
SKIP_BACKUP=0

usage() {
  cat <<'EOF'
用法：bash scripts/update.sh [选项]

选项：
  --dry-run       只打印将要执行的命令，不拉取、备份、构建或重启
  --skip-backup   跳过更新前的 SQLite 备份尝试
  -h, --help      显示帮助
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --skip-backup) SKIP_BACKUP=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知选项：$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

log()  { printf '\033[1;36m[update]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

run() {
  if ((DRY_RUN)); then
    printf '  + '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

command -v git >/dev/null 2>&1 || die "找不到 git，请先安装 Git。"
if (( ! DRY_RUN )); then
  command -v docker >/dev/null 2>&1 || die "找不到 docker，请先安装 Docker。"
  docker compose version >/dev/null 2>&1 || die "找不到 Docker Compose v2（docker compose）。"
fi

git rev-parse --show-toplevel >/dev/null 2>&1 || die "当前目录不是 Git 仓库：$ROOT_DIR"
repo_root="$(git rev-parse --show-toplevel)"
[[ "$repo_root" == "$ROOT_DIR" ]] || die "脚本必须在项目根目录对应的仓库中运行。"

branch="$(git symbolic-ref --quiet --short HEAD || true)"
[[ -n "$branch" ]] || die "当前处于 detached HEAD 状态，请先切换到要部署的分支。"
git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1 \
  || die "分支 $branch 没有上游分支，请先执行：git branch --set-upstream-to=origin/$branch $branch"

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  warn "工作区存在未提交改动，已停止更新，避免覆盖现场："
  git status --short >&2
  die "请先提交、暂存或移走这些改动后再运行。"
fi

compose=(docker compose)
if ((DRY_RUN)); then
  log "dry-run：将在更新前尝试备份 /data 下的 SQLite 数据库。"
elif ! "${compose[@]}" ps --status running --services 2>/dev/null | grep -qx 'aetrix'; then
  warn "未发现正在运行的 aetrix 容器，跳过数据库备份。"
elif ((SKIP_BACKUP)); then
  warn "已按 --skip-backup 跳过数据库备份。"
else
  db_path="$("${compose[@]}" exec -T aetrix sh -c \
    'for db in /data/*.db; do [ -f "$db" ] && printf "%s" "$db" && break; done' \
    | tr -d '\r\n')"
  if [[ -z "$db_path" ]]; then
    warn "容器 /data 下没有找到 SQLite 数据库，跳过备份。"
  else
    backup_path="/data/aetrix-update-$(date +%Y%m%d-%H%M%S).db"
    log "备份数据库：$db_path → $backup_path"
    "${compose[@]}" exec -T aetrix python - "$db_path" "$backup_path" <<'PY' \
      || die "数据库备份失败，已停止更新。"
import sqlite3
import sys

source_path, backup_path = sys.argv[1:]
with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
    source.backup(backup)
PY
    log "数据库备份完成。"
  fi
fi

log "当前分支：$branch"
log "拉取远端更新（仅允许 fast-forward）"
run git pull --ff-only

log "重新构建 Docker 镜像"
run "${compose[@]}" build --pull

log "更新 Compose 服务"
run "${compose[@]}" up -d --remove-orphans

log "查看服务状态"
run "${compose[@]}" ps

log "更新流程完成"
if ((DRY_RUN)); then
  log "这是 dry-run，未执行任何实际更新。"
else
  log "建议随后检查：curl http://127.0.0.1:8000/api/health"
fi
