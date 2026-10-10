#!/usr/bin/env bash
# 一键部署流节点（分离架构）：在高宽带大盘机器上起独立出流服务。
#
# 做什么：
#   1. 检查 docker / fuse / rclone（缺啥装啥，Debian/Ubuntu）
#   2. 从主服务拉配置包（GET /api/admin/stream-nodes/bundle，面板密钥鉴权）：
#      SECRET_KEY、DATABASE_URL、rclone.conf、SA 文件
#   3. 落盘 rclone.conf + SA，rclone 挂载每个远端到 /mnt/<远端小写>
#     （VFS 缓存按磁盘自动放大：>500GB 大盘自动给 70% 空闲）
#   4. 写 docker-compose.stream-node.yml + .env，起 aetrix-stream 容器
#   5. 回主服务注册自己（POST /api/admin/stream-nodes/register）
#
# 用法：
#   curl -fsSL https://example.com/deploy-streaming-node.sh -o deploy.sh
#   chmod +x deploy.sh
#   sudo ./deploy.sh
#
# 需要 root（rclone mount 要 fuse）。
set -euo pipefail

IMAGE="${AETRIX_IMAGE_TAG:-latest}"
WORKDIR="/opt/aetrix-stream-node"
CACHE_DIR="/var/cache/rclone-stream"

info()  { echo -e "\033[1;32m[流节点]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[警告]\033[0m $*"; }
fatal() { echo -e "\033[1;31m[失败]\033[0m $*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || fatal "请用 root 运行（rclone mount 需要 fuse 权限）"

# ---------- 1. 依赖 ----------
info "检查依赖…"
command -v docker >/dev/null || {
  info "安装 docker…"
  curl -fsSL https://get.docker.com | sh
}
docker compose version >/dev/null 2>&1 || fatal "需要 docker compose v2"
command -v fusermount3 >/dev/null || command -v fusermount >/dev/null || {
  info "安装 fuse…"
  apt-get update -qq && apt-get install -y -qq fuse3 curl jq python3
}
command -v rclone >/dev/null || {
  info "安装 rclone…"
  curl -fsSL https://rclone.org/install.sh | bash
}
command -v jq >/dev/null || apt-get install -y -qq jq
command -v curl >/dev/null || apt-get install -y -qq curl

mkdir -p "$WORKDIR" "$CACHE_DIR"
cd "$WORKDIR"

# ---------- 2. 读主服务信息 ----------
echo ""
echo "=== 主服务信息 ==="
read -rp "主服务地址（https://emby.example.com）: " MAIN_URL
MAIN_URL="${MAIN_URL%/}"
# 安全修复 S3：这里填**节点密钥**，不是 SECRET_KEY。主服务上查看：
#   docker exec <主服务容器> python -m backend.node_auth
# （= NODE_SHARED_SECRET；未设置时为 HMAC(SECRET_KEY, "aetrix-node-auth")）
read -rsp "节点密钥（主服务上 python -m backend.node_auth 的输出）: " PANEL_KEY
echo ""
read -rp "本节点公网域名（https://stream.example.com，CF 橙云后的域名）: " NODE_URL
NODE_URL="${NODE_URL%/}"
read -rp "节点名称（默认：流节点-1）: " NODE_NAME
NODE_NAME="${NODE_NAME:-流节点-1}"
read -rp "权重（默认 100，多节点按权重分流）: " NODE_WEIGHT
NODE_WEIGHT="${NODE_WEIGHT:-100}"

info "从主服务拉取配置包…"
# P1 安全加固：bundle 下发只接受 HMAC 签名头（有时效+防重放），不再接受静态
# X-Panel-Key。签名规范见 backend/node_auth.py：canonical = ts\nonce\nMETHOD\npath。
_bundle_sign() {
  local ts nonce canonical
  ts="$(date +%s)"
  nonce="$(openssl rand -hex 16)"
  canonical="$(printf '%s\n%s\n%s\n%s' "$ts" "$nonce" "GET" "/api/admin/stream-nodes/bundle")"
  printf '%s\n%s\n%s' "$ts" "$nonce" \
    "$(printf '%s' "$canonical" | openssl dgst -sha256 -hmac "$PANEL_KEY" | awk '{print $2}')"
}
read -r _BTS _BNO _BSG < <(_bundle_sign)
BUNDLE="$(curl -fsSL -m 30 "$MAIN_URL/api/admin/stream-nodes/bundle" \
  -H "X-Panel-Ts: $_BTS" -H "X-Panel-Nonce: $_BNO" -H "X-Panel-Sign: $_BSG")" \
  || fatal "拉取失败：检查主服务地址/节点密钥（需与主服务 NODE_SHARED_SECRET 一致）"
echo "$BUNDLE" | jq -e '.secret_key' >/dev/null || fatal "配置包格式错误"

SECRET_KEY="$(echo "$BUNDLE" | jq -r '.secret_key')"
NODE_SHARED_SECRET="$(echo "$BUNDLE" | jq -r '.node_shared_secret // ""')"
DATABASE_URL="$(echo "$BUNDLE" | jq -r '.database_url')"
DATABASE_TYPE="$(echo "$BUNDLE" | jq -r '.database_type')"
SA_COUNT="$(echo "$BUNDLE" | jq -r '.sa_count')"
info "配置包 OK（SA 文件 $SA_COUNT 个）"

# ---------- 3. 落盘 rclone 配置 ----------
info "落盘 rclone 配置…"
mkdir -p "$WORKDIR/rclone" "$WORKDIR/sa-accounts"
echo "$BUNDLE" | jq -r '.rclone_conf' > "$WORKDIR/rclone/rclone.conf"
chmod 600 "$WORKDIR/rclone/rclone.conf"
echo "$BUNDLE" | jq -r '.sa_files | to_entries[] | "\(.key)\t\(.value)"' |
  while IFS=$'\t' read -r name content; do
    printf '%s' "$content" > "$WORKDIR/sa-accounts/$name"
  done
chmod 600 "$WORKDIR"/sa-accounts/*.json 2>/dev/null || true

REMOTES="$(echo "$BUNDLE" | jq -r '.rclone_remotes[]?')"
[ -n "$REMOTES" ] || fatal "rclone.conf 里没有远端"

# ---------- 4. 大盘自动放大 VFS 缓存 ----------
# 磁盘总量 >500GB 时，VFS 缓存自动给到空闲空间的 70%（热门常驻）；
# 小盘走默认 20GB。rclone VFS 缓存自带类 LRU 淘汰，热门优先保留。
TOTAL_GB="$(df -BG "$CACHE_DIR" | awk 'NR==2{gsub(/G/,"",$2); print $2}')"
FREE_GB="$(df -BG "$CACHE_DIR" | awk 'NR==2{gsub(/G/,"",$4); print $4}')"
if [ "${TOTAL_GB:-0}" -ge 500 ]; then
  CACHE_SIZE="$(( FREE_GB * 70 / 100 ))G"
  info "检测到大盘（${TOTAL_GB}GB），VFS 缓存自动放大到 ${CACHE_SIZE}"
else
  CACHE_SIZE="20G"
  info "磁盘 ${TOTAL_GB}GB，VFS 缓存用默认 ${CACHE_SIZE}"
fi

# ---------- 5. rclone 挂载每个远端 ----------
info "挂载远端…"
RCLONE_VER="$(rclone version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
info "rclone 版本：$RCLONE_VER"
for remote in $REMOTES; do
  mp="/mnt/$(echo "$remote" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
  mkdir -p "$mp"
  if mountpoint -q "$mp" 2>/dev/null; then
    info "$remote 已挂载在 $mp，跳过"
    continue
  fi
  info "挂载 $remote -> $mp"
  # 开箱即用的读优化参数（与 playback_tune.DEFAULT_RCLONE_VFS_ARGS 同源）
  nohup rclone mount "${remote}:" "$mp" \
    --config "$WORKDIR/rclone/rclone.conf" \
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
    >"$WORKDIR/rclone-mount-$(echo "$remote" | tr '[:upper:]' '[:lower:]').log" 2>&1 &
  sleep 2
  mountpoint -q "$mp" && info "$mp 挂载成功" || warn "$mp 挂载可能失败，看日志"
done

# ---------- 6. 写 compose + .env ----------
info "生成流节点 compose…"
# 挂载点 bind 进容器（file_path 是绝对路径，容器内必须同路径可读）
VOLUMES=""
for remote in $REMOTES; do
  mp="/mnt/$(echo "$remote" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
  VOLUMES="${VOLUMES}      - ${mp}:${mp}:ro
"
done

cat > "$WORKDIR/docker-compose.yml" <<EOF
# Aetrix 流节点（分离架构）：只出流，无状态，可横向扩展。
# 由 scripts/deploy-streaming-node.sh 一键生成，不要手改（重跑脚本会覆盖）。
name: aetrix-stream-node
services:
  aetrix-stream:
    image: ghcr.io/xzb177/aetrix-api:${IMAGE}
    container_name: aetrix-stream
    restart: unless-stopped
    # 流角色：只起 EA 出流进程（run_all.py 的 stream 分支）
    command: ["python", "backend/run_all.py"]
    env_file: [".env"]
    environment:
      AETRIX_ROLE: stream
    ports:
      - "127.0.0.1:8001:8001"
    volumes:
${VOLUMES}      - ./rclone:/config/rclone:ro
      - ./sa-accounts:/sa-accounts:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=5)"]
      interval: 30s
      timeout: 10s
      start_period: 60s
      retries: 5
EOF

# .env：SECRET_KEY 等敏感值只落本机文件，权限 600
cat > "$WORKDIR/.env" <<EOF
# 由 deploy-streaming-node.sh 生成（$(date -u +%FT%TZ)），含敏感值，勿外传
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=${DATABASE_URL}
DATABASE_TYPE=${DATABASE_TYPE}
AETRIX_ROLE=stream
# 域名强制：只允许 CF 后的域名访问，直接 IP 打 403
ENFORCE_DOMAIN=$(echo "$NODE_URL" | sed -e 's#https\?://##' -e 's#/.*##' | cut -d: -f1)
# 显式配置过的节点密钥（主服务未设置时为空 = 由 SECRET_KEY 派生，两端一致）
NODE_SHARED_SECRET=${NODE_SHARED_SECRET}
# 信任 CF 的真实 IP 头（日志/限流用真人 IP）。H4：只有 TCP 直连对端是 Cloudflare 官方网段 /
# 本机回环 / TRUSTED_PROXIES 时才采信。容器端口只绑 127.0.0.1，经宿主机反代进来时容器看到的是
# docker 网关地址，所以把 docker 默认私网段列为可信；**宿主机反代必须只接受 Cloudflare 回源**
# （防火墙放行 CF 网段），否则直连源站的人仍可伪造 CF-Connecting-IP。
TRUST_CF_IP=true
TRUSTED_PROXIES=172.16.0.0/12
# 本节点公网地址（节点自检/日志用）
STREAM_NODE_PUBLIC_URL=${NODE_URL}
# EA 端口
EMBY_API_PORT=8001
# Redis：流节点不需要（播放签名验签只依赖 SECRET_KEY + 主库只读）
REDIS_ENABLED=false
EOF
chmod 600 "$WORKDIR/.env"

# ---------- 7. 启动 ----------
info "拉取镜像并启动…"
docker compose -f "$WORKDIR/docker-compose.yml" pull -q
docker compose -f "$WORKDIR/docker-compose.yml" up -d
sleep 8
curl -fsSL -m 10 "http://127.0.0.1:8001/api/health" >/dev/null \
  && info "流节点健康检查通过" \
  || warn "健康检查未通过，docker logs aetrix-stream 看详情"

# ---------- 8. 回主服务注册 ----------
info "向主服务注册流节点…"
REG="$(curl -fsSL -m 20 -X POST "$MAIN_URL/api/admin/stream-nodes/register" \
  -H "X-Panel-Key: $PANEL_KEY" -H "Content-Type: application/json" \
  -d "$(jq -n --arg url "$NODE_URL" --arg name "$NODE_NAME" --argjson weight "$NODE_WEIGHT" \
    '{url:$url,name:$name,weight:$weight}')")" \
  || fatal "注册失败"
echo "$REG" | jq -e '.ok' >/dev/null && info "注册成功" || fatal "注册返回异常"

# ---------- 9. 预热（可选） ----------
echo ""
read -rp "是否立即预热热门内容到本地缓存？(y/N) " DO_PREHEAT
if [ "${DO_PREHEAT,,}" = "y" ]; then
  read -rp "预热 Top N（默认 50）: " PREHEAT_N
  PREHEAT_N="${PREHEAT_N:-50}"
  info "预热 Top $PREHEAT_N（后台进行）…"
  nohup docker exec aetrix-stream python scripts/preheat-hot-cache.py \
    --top "$PREHEAT_N" >"$WORKDIR/preheat.log" 2>&1 &
fi

echo ""
info "=== 完成 ==="
echo "  节点地址: $NODE_URL"
echo "  下一步（Cloudflare 隐藏 IP，见 docs/streaming-node.md）："
echo "    1. CF 后台给 $NODE_URL 开橙云（代理）"
echo "    2. 源站指向本机公网 IP 的 8001 端口（建议 CF Access/防火墙只放 CF 回源 IP 段）"
echo "    3. 本机防火墙只放行 CF IP 段 + 主服务内网 IP 的 8001"
