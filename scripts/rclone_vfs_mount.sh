#!/bin/bash
# 开箱即用的 rclone VFS 挂载脚本。
#
# 用户部署 Aetrix、配好 rclone remote 后，直接跑这个脚本就能挂载，
# 自动带上播放优化参数，不用手动调。
#
# 用法：
#   ./scripts/rclone_vfs_mount.sh <remote:路径> <挂载点> [rclone.conf]
#
# 示例：
#   ./scripts/rclone_vfs_mount.sh "MP:" /mnt/mp
#   ./scripts/rclone_vfs_mount.sh "gdrive:Movies" /mnt/movies /root/.config/rclone/rclone.conf
#
# 额外参数用环境变量 RCLONE_EXTRA_ARGS 传（空格分隔），会覆盖默认值：
#   RCLONE_EXTRA_ARGS="--vfs-cache-max-size 50G" ./scripts/rclone_vfs_mount.sh "MP:" /mnt/mp
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "用法: $0 <remote:路径> <挂载点> [rclone.conf]" >&2
  exit 1
fi

REMOTE="$1"
MOUNTPOINT="$2"
CONF="${3:-}"

# 1. SA 自动轮换（如果配了 SA 目录）
SA_DIR="${RCLONE_SA_DIR:-/opt/rclone-sa}"
if [ -n "$CONF" ] && [ -d "$SA_DIR" ]; then
  python3 -c "
import sys
sys.path.insert(0, 'backend')
from emby_server import playback_tune
r = playback_tune.ensure_sa_rotation('$CONF', '$SA_DIR')
print('SA 轮换:', r)
if r.get('warning'):
    print('告警:', r['warning'], file=sys.stderr)
" 2>&1 | head -5 || true
fi

# 2. 组装挂载参数（Python 算，避免 bash 解析引号坑）
ARGS_JSON=$(python3 -c "
import sys, json
sys.path.insert(0, 'backend')
from emby_server import playback_tune
extra = '$RCLONE_EXTRA_ARGS'.split() if '$RCLONE_EXTRA_ARGS' else []
print(json.dumps(playback_tune.build_rclone_mount_args(extra)))
")
mapfile -t ARGS < <(python3 -c "import json,sys; [print(a) for a in json.loads(sys.argv[1])]" "$ARGS_JSON")

CMD=(rclone mount "$REMOTE" "$MOUNTPOINT")
if [ -n "$CONF" ]; then
  CMD+=(--config "$CONF")
fi
CMD+=("${ARGS[@]}")
CMD+=(--cache-dir "${RCLONE_CACHE_DIR:-/var/cache/rclone-$(basename "$MOUNTPOINT")}")
CMD+=(--log-file "${RCLONE_LOG_FILE:-/tmp/rclone-$(basename "$MOUNTPOINT").log}")

echo "==> 挂载 $REMOTE -> $MOUNTPOINT"
echo "    ${CMD[*]}"
mkdir -p "$MOUNTPOINT"
"${CMD[@]}" &
echo "    已后台启动，日志：${RCLONE_LOG_FILE:-/tmp/rclone-$(basename "$MOUNTPOINT").log}"
