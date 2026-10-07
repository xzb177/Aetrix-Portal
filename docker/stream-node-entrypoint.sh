#!/usr/bin/env bash
# Aetrix 流节点 entrypoint（join token 自助接入，无需脚本/SSH）。
#
# 容器启动流程：
#   1. 读 JOIN_TOKEN + MAIN_URL（环境变量）
#   2. POST $MAIN_URL/api/admin/stream-nodes/join → 拿到配置包
#      （SECRET_KEY、DATABASE_URL、rclone.conf、SA 文件）
#   3. 落盘 rclone.conf + SA，按磁盘自动放大 VFS 缓存并挂载各远端
#   4. 启动 EA 出流（AETRIX_ROLE=stream）
#
# 用法（管理后台"添加节点"复制即用）：
#   docker run -d --name aetrix-stream --restart unless-stopped \
#     --cap-add SYS_ADMIN --device /dev/fuse --security-opt apparmor:unconfined \
#     -e JOIN_TOKEN=xxx -e MAIN_URL=https://emby.example.com \
#     -v /var/cache/rclone-stream:/var/cache/rclone \
#     ghcr.io/xzb177/aetrix-stream-node:latest
set -euo pipefail

log() { echo "[stream-node] $*"; }
fatal() { echo "[stream-node][失败] $*" >&2; exit 1; }

[ -n "${JOIN_TOKEN:-}" ] || fatal "缺少 JOIN_TOKEN 环境变量"
[ -n "${MAIN_URL:-}" ] || fatal "缺少 MAIN_URL 环境变量（主服务公网地址）"
MAIN_URL="${MAIN_URL%/}"
NODE_URL_REPORT="${STREAM_NODE_PUBLIC_URL:-}"  # 建 token 时未预填则由本变量上报

RCLONE_CONF_DIR="/config/rclone"
SA_DIR="/sa-accounts"
CACHE_DIR="${RCLONE_CACHE_DIR:-/var/cache/rclone}"
mkdir -p "$RCLONE_CONF_DIR" "$SA_DIR" "$CACHE_DIR"

# ---------- 1. join ----------
log "向主服务自注册…"
JOIN_RESP="$(curl -fsSL -m 30 -X POST "$MAIN_URL/api/admin/stream-nodes/join" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,os; print(json.dumps({'token': os.environ['JOIN_TOKEN'], 'node_url': os.environ.get('STREAM_NODE_PUBLIC_URL','')}))")")" \
  || fatal "join 失败：检查 MAIN_URL / JOIN_TOKEN 是否正确、token 是否过期"
echo "$JOIN_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok'), d; print('join OK:', d['node']['url'])" \
  || fatal "join 返回异常"

# ---------- 2. 落盘配置 ----------
log "落盘 rclone 配置…"
echo "$JOIN_RESP" | python3 -c "
import json, os, sys
d = json.load(sys.stdin)
b = d['bundle']
open('$RCLONE_CONF_DIR/rclone.conf', 'w').write(b.get('rclone_conf', ''))
for name, content in (b.get('sa_files') or {}).items():
    # 防路径穿越：只取 basename
    safe = os.path.basename(name)
    if safe.endswith('.json'):
        open(os.path.join('$SA_DIR', safe), 'w').write(content)
# 写 .env（给 run_all.py 用）
env_lines = [
    'SECRET_KEY=' + b.get('secret_key', ''),
    'DATABASE_URL=' + b.get('database_url', ''),
    'DATABASE_TYPE=' + b.get('database_type', 'postgresql'),
    'AETRIX_ROLE=stream',
    'REDIS_ENABLED=false',
    'EMBY_API_PORT=8001',
]
open('/tmp/stream-node.env', 'w').write('\n'.join(env_lines) + '\n')
print('bundle OK: SA', b.get('sa_count', 0), '个，远端', b.get('rclone_remotes'))
"
chmod 600 "$RCLONE_CONF_DIR/rclone.conf" 2>/dev/null || true
set -a; . /tmp/stream-node.env; set +a
export SECRET_KEY DATABASE_URL DATABASE_TYPE AETRIX_ROLE REDIS_ENABLED EMBY_API_PORT

# ENFORCE_DOMAIN：只允许公网域名访问（CF 隐藏 IP 配套）
if [ -n "$NODE_URL_REPORT" ]; then
  export ENFORCE_DOMAIN="$(echo "$NODE_URL_REPORT" | sed -e 's#https\?://##' -e 's#/.*##' | cut -d: -f1)"
  export TRUST_CF_IP=true
fi

REMOTES="$(echo "$JOIN_RESP" | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin)['bundle'].get('rclone_remotes', [])))")"
[ -n "$REMOTES" ] || fatal "配置包里没有 rclone 远端"

# ---------- 3. 大盘自动放大 VFS 缓存 ----------
TOTAL_GB="$(df -BG "$CACHE_DIR" | awk 'NR==2{gsub(/G/,"",$2); print $2}')"
FREE_GB="$(df -BG "$CACHE_DIR" | awk 'NR==2{gsub(/G/,"",$4); print $4}')"
if [ "${TOTAL_GB:-0}" -ge 500 ]; then
  CACHE_SIZE="$(( FREE_GB * 70 / 100 ))G"
  log "大盘 ${TOTAL_GB}GB，VFS 缓存自动放大到 ${CACHE_SIZE}"
else
  CACHE_SIZE="20G"
  log "磁盘 ${TOTAL_GB}GB，VFS 缓存 ${CACHE_SIZE}"
fi

# ---------- 4. 挂载 ----------
for remote in $REMOTES; do
  mp="/mnt/$(echo "$remote" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
  mkdir -p "$mp"
  if mountpoint -q "$mp" 2>/dev/null; then log "$remote 已挂载，跳过"; continue; fi
  log "挂载 $remote -> $mp"
  # 开箱即用的读优化（与 playback_tune.DEFAULT_RCLONE_VFS_ARGS 同源）
  rclone mount "${remote}:" "$mp" \
    --config "$RCLONE_CONF_DIR/rclone.conf" \
    --vfs-cache-mode full \
    --vfs-cache-max-size "$CACHE_SIZE" \
    --vfs-cache-max-age 168h \
    --cache-dir "$CACHE_DIR" \
    --vfs-read-chunk-size 32M \
    --vfs-read-chunk-size-limit 256M \
    --vfs-read-ahead 128M \
    --buffer-size 32M \
    --drive-chunk-size 128M \
    --allow-other \
    --daemon-timeout 10m \
    --daemon >/tmp/rclone-mount.log 2>&1 || log "警告：$remote 挂载可能失败，看 /tmp/rclone-mount.log"
  sleep 1
done

# ---------- 5. 启动 EA 出流 ----------
log "启动流服务…"
exec python backend/run_all.py
