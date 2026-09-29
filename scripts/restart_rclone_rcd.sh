#!/bin/bash
# 安全重启 aetrix-rclone（rcd 控制面），释放其累积的 Go 堆内存。
#
# 背景：rcd 在持续 RC 调用（扫描列目录）下堆会涨到 2.6GB（23M live objects，
# 强制 GC 只能回收约 2%），这是 rclone 内部累积，调参降不下来。
# rcd 是无状态的（RC API + --rc-serve 按请求服务，无 VFS 状态），重启即回到
# 几十 MB。真正的根治是 Drive 走 SA 池直调 API（见 PR 描述第二步）。
#
# 注意：
# - 重启瞬间：正在进行的 RC 列目录会失败重试（扫描器有重试）；极少数走
#   --rc-serve 回退代理的播放流会被掐断（正常都走 Drive 302 直链，不受影响）。
# - 建议在低峰期执行，或在 cron 里每周一次（示例见文件末尾注释）。
# - 需要用户点头才能在生产执行（改的是运行中的容器）。

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 检查 aetrix-rclone 状态…"
if ! docker ps --format '{{.Names}}' | grep -qx 'aetrix-rclone'; then
  echo "aetrix-rclone 未在运行，无需重启。"
  exit 0
fi

BEFORE=$(docker stats --no-stream --format '{{.MemUsage}}' aetrix-rclone 2>/dev/null | awk '{print $1}' || echo "?")
echo "    重启前内存: ${BEFORE}"

echo "==> 重启 aetrix-rclone（3 秒后执行，Ctrl-C 可取消）…"
sleep 3
docker restart aetrix-rclone >/dev/null

echo "==> 等待 RC 端口恢复…"
for i in $(seq 1 30); do
  if docker exec aetrix-rclone sh -c 'nc -z 127.0.0.1 5572' 2>/dev/null; then
    break
  fi
  sleep 2
done

AFTER=$(docker stats --no-stream --format '{{.MemUsage}}' aetrix-rclone 2>/dev/null | awk '{print $1}' || echo "?")
echo "    重启后内存: ${AFTER}"
echo "完成。"

# 每周低峰重启示例（crontab -e，VPS 上）：
# 0 4 * * 0 /opt/aetrix-portal/scripts/restart_rclone_rcd.sh >> /var/log/rclone_rcd_restart.log 2>&1
