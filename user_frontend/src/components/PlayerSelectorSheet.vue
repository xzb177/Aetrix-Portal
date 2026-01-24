<script setup lang="ts">
/**
 * 播放器选择 Bottom Sheet - Neo-Noir 2.0 设计
 *
 * 支持一键导入 Emby 配置到各播放器
 */
import { ref, computed } from 'vue'
import { X, Copy, Play, Tv, Zap } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'
import { Badge } from '@/components/ui'

interface Props {
  show: boolean
  account: {
    server_url: string
    username: string
    password: string
  }
}

interface Emits {
  (e: 'update:show', value: boolean): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()
const toast = useToast()

// 播放器列表
const players = [
  {
    id: 'forward',
    name: 'Forward',
    icon: Zap,
    description: '智能聚合，多服管理',
    recommended: true,
    color: '#3B82F6'
  },
  {
    id: 'hills',
    name: 'Hills',
    icon: Play,
    description: '全能播放器',
    recommended: true,
    color: '#10B981'
  },
  {
    id: 'senplayer',
    name: 'SenPlayer',
    icon: Tv,
    description: '网盘直连，多线路',
    recommended: true,
    color: '#8B5CF6'
  },
  {
    id: 'vidhub',
    name: 'VidHub',
    icon: Tv,
    description: '多服管理，智能播放',
    recommended: true,
    color: '#8B5CF6'
  }
]

const selectedPlayer = ref<string | null>(null)

// 关闭
const close = () => {
  emit('update:show', false)
  selectedPlayer.value = null
}

// 解析服务器地址
const parseServerUrl = (url: string) => {
  try {
    const urlObj = new URL(url)
    return {
      host: urlObj.hostname,
      port: urlObj.port || (urlObj.protocol === 'https:' ? '443' : '80'),
      protocol: urlObj.protocol.replace(':', ''),
      fullHost: urlObj.host
    }
  } catch {
    const cleanUrl = url.replace(/^https?:\/\//, '').replace(/\/.*$/, '')
    const [hostPart, ..._rest] = cleanUrl.split('/')
    const [host, ...portParts] = hostPart.split(':')
    const port = portParts[0] || '443'
    return {
      host,
      port,
      protocol: 'https',
      fullHost: portParts[0] ? `${host}:${port}` : host
    }
  }
}

// 生成各播放器链接
const generateHillsLink = () => {
  const { host, port, protocol } = parseServerUrl(props.account.server_url)
  const params = new URLSearchParams()
  params.append('type', 'emby')
  params.append('scheme', protocol)
  params.append('host', host)
  params.append('port', port)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')
  return `hills://import?${params.toString()}`
}

const generateSenPlayerLink = () => {
  const { host } = parseServerUrl(props.account.server_url)
  const params = new URLSearchParams()
  params.append('type', 'emby')
  params.append('name', 'Emby 服务器')
  params.append('note', '主线路')
  params.append('address', props.account.server_url)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')
  return `senplayer://importserver?${params.toString()}`
}

const generateForwardLink = () => {
  const { host, port, protocol } = parseServerUrl(props.account.server_url)
  const params = new URLSearchParams()
  params.append('type', 'emby')
  params.append('scheme', protocol)
  params.append('host', host)
  params.append('port', port)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')
  return `forward://import?${params.toString()}`
}

const generateVidhubLink = () => {
  const { host, port, protocol } = parseServerUrl(props.account.server_url)
  const params = new URLSearchParams()
  params.append('type', 'emby')
  params.append('scheme', protocol)
  params.append('host', host)
  params.append('port', port)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')
  return `vidhub://import?${params.toString()}`
}

const generatePlayerUrl = (playerId: string) => {
  switch (playerId) {
    case 'forward': return generateForwardLink()
    case 'hills': return generateHillsLink()
    case 'senplayer': return generateSenPlayerLink()
    case 'vidhub': return generateVidhubLink()
    default: return generateHillsLink()
  }
}

// 复制配置
const copyConfig = async (playerId: string) => {
  const player = players.find(p => p.id === playerId)
  const { host, port } = parseServerUrl(props.account.server_url)

  const configText = `服务器: ${props.account.server_url}
主机: ${host}
端口: ${port}
用户名: ${props.account.username}
密码: ${props.account.password || ''}`

  try {
    await navigator.clipboard.writeText(configText)
    toast.success(`已复制 ${player?.name} 配置`)
  } catch (err) {
    console.error('复制失败:', err)
    toast.error('复制失败，请手动复制')
  }
}

// 打开播放器
const openPlayer = async (playerId: string) => {
  const player = players.find(p => p.id === playerId)
  if (!player) return

  selectedPlayer.value = playerId
  const url = generatePlayerUrl(playerId)

  // 先复制配置作为备用
  const { host, port } = parseServerUrl(props.account.server_url)
  const configText = `服务器: ${props.account.server_url}
主机: ${host}
端口: ${port}
用户名: ${props.account.username}
密码: ${props.account.password || ''}`

  try {
    await navigator.clipboard.writeText(configText)
    toast.success(`正在打开 ${player.name}...`)
  } catch (err) {
    console.error('复制失败:', err)
  }

  // 尝试打开播放器
  window.location.href = url

  // 延迟提示（如果播放器在连接 Emby 时显示 401，可能是账号已过期或密码错误）
  setTimeout(() => {
    toast.info(`已复制配置到剪贴板\n如 ${player.name} 未打开或显示 401 错误，请手动添加`)
    selectedPlayer.value = null
  }, 1000)

  setTimeout(() => {
    close()
  }, 1500)
}

// 计算服务器显示
const serverDisplay = computed(() => {
  return props.account.server_url?.replace(/^https?:\/\//, '').split('/')[0] || '-'
})
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="show" class="sheet-overlay" @click.self="close">
        <div class="sheet-container">
          <!-- 头部 -->
          <div class="sheet-header">
            <h3 class="sheet-title">选择播放器</h3>
            <button @click="close" class="sheet-close">
              <X :size="18" />
            </button>
          </div>

          <!-- 账号信息 -->
          <div class="account-info">
            <div class="info-row">
              <span class="info-label">服务器</span>
              <span class="info-value">{{ serverDisplay }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">用户名</span>
              <span class="info-value">{{ account.username }}</span>
            </div>
          </div>

          <!-- 播放器列表 -->
          <div class="players-list">
            <button
              v-for="player in players"
              :key="player.id"
              @click="openPlayer(player.id)"
              class="player-card"
              :class="{
                'player-card--selected': selectedPlayer === player.id,
                'player-card--loading': selectedPlayer === player.id
              }"
            >
              <div class="player-icon" :style="{ '--player-color': player.color }">
                <component :is="player.icon" :size="20" />
              </div>
              <div class="player-content">
                <div class="player-header">
                  <span class="player-name">{{ player.name }}</span>
                  <Badge v-if="player.recommended" variant="success" size="sm">推荐</Badge>
                  <Badge v-if="player.experimental" variant="warning" size="sm">实验性</Badge>
                </div>
                <span class="player-desc">{{ player.description }}</span>
              </div>
            </button>
          </div>

          <!-- 底部操作 -->
          <div class="sheet-footer">
            <button @click="copyConfig('forward')" class="copy-config-btn">
              <Copy :size="14" />
              <span>仅复制配置（手动添加）</span>
            </button>
            <p class="footer-tip">
              点击播放器自动跳转并导入配置。如显示 401 错误，可能是账号已过期或 Emby 服务器问题。
            </p>
          </div>

          <!-- 安全区域 -->
          <div class="safe-area"></div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ==================== 遮罩层 ==================== */
.sheet-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--neo-z-overlay, 80);
  background: var(--neo-bg-overlay, rgba(0, 0, 0, 0.75));
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 0;
}

/* prefers-reduced-motion：禁用模糊 */
@media (prefers-reduced-motion: reduce) {
  .sheet-overlay {
    backdrop-filter: none;
  }
}

@media (prefers-reduced-motion: no-preference) {
  .sheet-overlay {
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }
}

/* ==================== 容器 ==================== */
.sheet-container {
  width: 100%;
  max-width: 480px;
  background: var(--neo-bg-base, #0B0F14);
  border-radius: var(--neo-radius-lg, 18px) var(--neo-radius-lg, 18px) 0 0;
  padding: var(--space-4, 16px);
  padding-bottom: 0;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--neo-shadow-lg, 0 8px 32px rgba(0, 0, 0, 0.6));
}

@media (min-width: 481px) {
  .sheet-container {
    border-radius: var(--neo-radius-lg, 18px);
    margin-bottom: env(safe-area-inset-bottom, 0);
  }
}

/* ==================== 头部 ==================== */
.sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4, 16px);
}

.sheet-title {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
  margin: 0;
}

.sheet-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-xs, 8px);
  color: var(--neo-text-tertiary);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.sheet-close:active {
  background: var(--neo-bg-surface-hover);
  color: var(--neo-text-secondary);
}

/* ==================== 账号信息 ==================== */
.account-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px);
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-sm, 12px);
  margin-bottom: var(--space-4, 16px);
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.info-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

.info-value {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-secondary);
  font-family: ui-monospace, monospace;
}

/* ==================== 播放器列表 ==================== */
.players-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  margin-bottom: var(--space-4, 16px);
  overflow-y: auto;
  flex: 1;
}

.players-list::-webkit-scrollbar {
  display: none;
}

.player-card {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
  padding: var(--space-3, 12px);
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-sm, 12px);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
  text-align: left;
}

.player-card:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(var(--neo-scale-press, 0.98));
}

.player-card--selected {
  border-color: var(--neo-primary, #10B981);
  background: rgba(16, 185, 129, 0.08);
}

.player-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--neo-radius-xs, 8px);
  background: color-mix(in srgb, var(--player-color, #10B981) 12%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--player-color, #10B981);
  flex-shrink: 0;
}

.player-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.player-header {
  display: flex;
  align-items: center;
  gap: var(--space-1, 4px);
}

.player-name {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary);
}

.player-desc {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

/* ==================== 底部操作 ==================== */
.sheet-footer {
  padding: var(--space-3, 12px) 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
}

.copy-config-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.copy-config-btn:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(var(--neo-scale-press, 0.98));
}

.footer-tip {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
  text-align: center;
  line-height: var(--neo-line-height-normal, 1.5);
  margin: 0;
}

/* ==================== 安全区域 ==================== */
.safe-area {
  height: env(safe-area-inset-bottom, 0);
  min-height: var(--space-3, 12px);
}

/* ==================== 动画 ==================== */
.sheet-enter-active,
.sheet-leave-active {
  transition: all 0.3s ease;
}

.sheet-enter-from,
.sheet-leave-to {
  opacity: 0;
}

.sheet-enter-from .sheet-container,
.sheet-leave-to .sheet-container {
  transform: translateY(100%);
}

.sheet-enter-active .sheet-container,
.sheet-leave-active .sheet-container {
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

/* ==================== 减少动画 ==================== */
@media (prefers-reduced-motion: reduce) {
  .player-card:active,
  .copy-config-btn:active {
    transform: none;
  }

  .sheet-enter-active,
  .sheet-leave-active,
  .sheet-enter-active .sheet-container,
  .sheet-leave-active .sheet-container {
    transition: none;
  }
}
</style>
