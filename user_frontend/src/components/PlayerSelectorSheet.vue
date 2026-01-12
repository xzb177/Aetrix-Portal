<script setup lang="ts">
/**
 * 播放器选择 Bottom Sheet
 *
 * 支持一键导入 Emby 配置到各播放器
 *
 * 更新说明：
 * - 优化 URL Scheme 格式，确保正确编码
 * - 添加备用配置信息复制方案
 * - 改进 URL 解析逻辑，支持更多格式
 */
import { X, Zap, Copy, Play, Tv } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'

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
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
    recommended: true,
    importType: 'scheme' as const
  },
  {
    id: 'hills',
    name: 'Hills',
    icon: Play,
    description: '全能播放器',
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
    recommended: true,
    importType: 'scheme' as const
  },
  {
    id: 'senplayer',
    name: 'SenPlayer',
    icon: Tv,
    description: '网盘直连，多线路',
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
    recommended: true,
    importType: 'scheme' as const
  },
  {
    id: 'lenna',
    name: 'Lenna',
    icon: Play,
    description: 'HDR播放器，多服务器',
    color: 'text-orange-500',
    bgColor: 'bg-orange-500/10',
    recommended: false,
    importType: 'scheme' as const,
    experimental: true
  }
]

// 关闭 Sheet
const close = () => {
  emit('update:show', false)
}

// 解析服务器地址 - 改进版本
const parseServerUrl = (url: string) => {
  try {
    const urlObj = new URL(url)
    return {
      host: urlObj.hostname,
      port: urlObj.port || (urlObj.protocol === 'https:' ? '443' : '80'),
      protocol: urlObj.protocol.replace(':', ''),
      fullHost: urlObj.host // 包含端口的主机
    }
  } catch {
    // 移除协议前缀后再试
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

// 生成 Hills URL Scheme
// Hills 官方格式（支持 Telegram 内跳转）
// 格式: hills://import?type=emby&scheme=SCHEME&host=HOST&port=PORT&username=USERNAME&password=PASSWORD
// TG内跳转: https://gocy.pages.dev/#hills://import?...
const generateHillsLink = () => {
  const { host, port, protocol } = parseServerUrl(props.account.server_url)
  const params = new URLSearchParams()
  params.append('type', 'emby')
  params.append('scheme', protocol)
  params.append('host', host)
  params.append('port', port)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')

  const url = `hills://import?${params.toString()}`
  console.log('[Hills URL]', url)
  return url
}

// 生成 SenPlayer URL Scheme
// SenPlayer 官方格式（支持多线路）
// 格式: senplayer://importserver?type=emby&name=xxx&note=xxx&address=xxx&username=xxx&password=xxx
// 多线路: &address1=xxx&address1name=xxx&address2=xxx&address2name=xxx
const generateSenPlayerLink = () => {
  const { host } = parseServerUrl(props.account.server_url)
  const params = new URLSearchParams()
  params.append('type', 'emby')
  params.append('name', 'Emby 服务器')
  params.append('note', '主线路')
  params.append('address', props.account.server_url)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')

  const url = `senplayer://importserver?${params.toString()}`
  console.log('[SenPlayer URL]', url)
  return url
}

// 生成 Forward URL Scheme
// Forward 官方格式（参考 Telegram 频道 @forwardplayer）
// 格式: forward://import?type=emby&scheme=SCHEME&host=HOST&port=PORT&username=USERNAME&password=PASSWORD
const generateForwardLink = () => {
  const { host, port, protocol } = parseServerUrl(props.account.server_url)
  const params = new URLSearchParams()
  params.append('type', 'emby')
  params.append('scheme', protocol)
  params.append('host', host)
  params.append('port', port)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')

  const url = `forward://import?${params.toString()}`
  console.log('[Forward URL]', url)
  return url
}

// 生成 Lenna URL Scheme（实验性）
// 注意：Lenna 官方未公开服务器导入的 URL Scheme 文档
// 以下格式基于 x-callback-url 标准推断，可能需要验证
// 推断格式: lenna://x-callback-url/addServer?url=SERVER_URL&username=USERNAME&password=PASSWORD
// 备选格式可能包括: lenna://addServer 或 lenna://import
const generateLennaLink = () => {
  const params = new URLSearchParams()
  // 使用完整的服务器 URL
  params.append('url', props.account.server_url)
  params.append('username', props.account.username)
  params.append('password', props.account.password || '')

  // x-callback-url 标准回调参数（可选）
  params.append('x-success', 'royalbot://callback/success')
  params.append('x-error', 'royalbot://callback/error')

  const url = `lenna://x-callback-url/addServer?${params.toString()}`
  console.log('[Lenna URL - 实验性]', url)
  console.log('[Lenna 注意] 官方未公开服务器导入文档，此格式基于推断')
  return url
}

// 根据播放器 ID 生成对应的 URL
const generatePlayerUrl = (playerId: string) => {
  switch (playerId) {
    case 'forward':
      return generateForwardLink()
    case 'hills':
      return generateHillsLink()
    case 'senplayer':
      return generateSenPlayerLink()
    case 'lenna':
      return generateLennaLink()
    default:
      return generateHillsLink()
  }
}

// 生成备用配置信息（JSON 格式，便于某些播放器识别）
const generateBackupConfig = (playerId: string) => {
  const { host, port, protocol } = parseServerUrl(props.account.server_url)
  const config = {
    server_url: props.account.server_url,
    host,
    port,
    protocol,
    username: props.account.username,
    password: props.account.password || '',
    player: playerId
  }
  return JSON.stringify(config, null, 2)
}

// 复制到剪贴板并显示提示
const copyToClipboard = async (text: string, message: string) => {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(message)
    return true
  } catch (err) {
    console.error('复制失败:', err)
    toast.error('复制失败，请手动复制')
    return false
  }
}

// 打开播放器
const openPlayer = async (playerId: string) => {
  const player = players.find(p => p.id === playerId)
  if (!player) return

  const url = generatePlayerUrl(playerId)

  // 1. 首先复制配置信息到剪贴板作为备用
  const { host, port } = parseServerUrl(props.account.server_url)
  const configText = `服务器: ${props.account.server_url}
主机: ${host}
端口: ${port}
用户名: ${props.account.username}
密码: ${props.account.password || ''}`

  await copyToClipboard(configText, `正在打开 ${player.name}...`)

  // 2. 尝试多种方式打开 URL Scheme
  console.log(`[打开 ${player.name}] URL:`, url)
  console.log(`[设备信息]`, {
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    isIOS: /iPad|iPhone|iPod/.test(navigator.userAgent),
    isAndroid: /Android/.test(navigator.userAgent)
  })

  // 方式1: 直接跳转（最可靠）
  window.location.href = url

  // 方式2: 创建隐藏的 a 标签并点击（备选）
  const link = document.createElement('a')
  link.href = url
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()

  // 延迟清理并提示
  setTimeout(() => {
    document.body.removeChild(link)

    toast.info(`已复制配置到剪贴板
如 ${player.name} 未打开，请手动添加`)
  }, 1000)

  close()
}

// 手动复制配置（用于不支持 URL Scheme 的播放器）
const copyConfig = async (playerId: string) => {
  const player = players.find(p => p.id === playerId)
  const { host, port } = parseServerUrl(props.account.server_url)

  const configText = `服务器: ${props.account.server_url}
主机: ${host}
端口: ${port}
用户名: ${props.account.username}
密码: ${props.account.password || ''}`

  await copyToClipboard(
    configText,
    `已复制 ${player?.name} 配置，请在应用中手动添加`
  )
}
</script>

<template>
  <Transition name="sheet">
    <div v-if="show" class="sheet-overlay" @click.self="close">
      <div class="sheet-container">
        <!-- 头部 -->
        <div class="sheet-header">
          <h3 class="sheet-title">选择播放器</h3>
          <button @click="close" class="sheet-close">
            <X :size="20" />
          </button>
        </div>

        <!-- 账号信息预览 -->
        <div class="account-preview">
          <div class="preview-row">
            <span class="preview-label">服务器</span>
            <span class="preview-value">{{ account.server_url?.replace(/^https?:\/\//, '').split('/')[0] }}</span>
          </div>
          <div class="preview-row">
            <span class="preview-label">用户名</span>
            <span class="preview-value">{{ account.username }}</span>
          </div>
        </div>

        <!-- 播放器列表 -->
        <div class="players-list">
          <button
            v-for="player in players"
            :key="player.id"
            @click="openPlayer(player.id)"
            class="player-item"
            :class="player.bgColor"
          >
            <div class="player-icon" :class="player.bgColor">
              <component :is="player.icon" :size="24" :class="player.color" />
            </div>
            <div class="player-info">
              <div class="player-header">
                <span class="player-name">{{ player.name }}</span>
                <span v-if="player.recommended" class="player-recommend">推荐</span>
                <span v-if="player.experimental" class="player-experimental">实验性</span>
              </div>
              <span class="player-desc">{{ player.description }}</span>
            </div>
          </button>
        </div>

        <!-- 底部操作 -->
        <div class="sheet-footer">
          <!-- 手动复制配置按钮 -->
          <button @click="copyConfig('forward')" class="copy-button">
            <Copy :size="16" />
            <span>仅复制配置（手动添加）</span>
          </button>
          <p class="footer-tip">
            点击播放器图标自动跳转并导入配置
            <br>如跳转失败，可使用复制按钮手动添加
          </p>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* Overlay */
.sheet-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 0;
  padding-bottom: env(safe-area-inset-bottom, 0);
}

/* Container */
.sheet-container {
  width: 100%;
  max-width: 600px;
  background: #1a1a1a;
  border-radius: 1.5rem 1.5rem 0 0;
  padding: 1.5rem 1rem 1rem;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.4);
}

/* Header */
.sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
  padding: 0 0.5rem;
}

.sheet-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #fafafa;
}

.sheet-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  background: transparent;
  border: none;
  color: #737373;
  cursor: pointer;
  transition: all 0.2s ease;
}

.sheet-close:active {
  background: rgba(255, 255, 255, 0.1);
  color: #fafafa;
}

/* Account Preview */
.account-preview {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.75rem;
  margin-bottom: 1rem;
}

.preview-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-label {
  font-size: 0.75rem;
  color: #737373;
}

.preview-value {
  font-size: 0.813rem;
  color: #d4d4d4;
  font-family: 'SF Mono', ui-monospace, monospace;
}

/* Players List */
.players-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.player-item {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.875rem 1rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
}

.player-item:active {
  background: rgba(255, 255, 255, 0.06);
  transform: scale(0.98);
}

.player-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.625rem;
  flex-shrink: 0;
}

.player-info {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  flex: 1;
}

.player-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.player-name {
  font-size: 0.938rem;
  font-weight: 600;
  color: #fafafa;
}

.player-recommend {
  padding: 0.125rem 0.375rem;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  font-size: 0.625rem;
  font-weight: 500;
  border-radius: 0.25rem;
}

.player-experimental {
  padding: 0.125rem 0.375rem;
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  color: white;
  font-size: 0.625rem;
  font-weight: 500;
  border-radius: 0.25rem;
}

.player-desc {
  font-size: 0.75rem;
  color: #737373;
}

/* Footer */
.sheet-footer {
  padding: 0.75rem 0.5rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.copy-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 0.75rem;
  color: #a3a3a3;
  font-size: 0.813rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.copy-button:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
}

.copy-button:active {
  background: rgba(255, 255, 255, 0.12);
  transform: scale(0.98);
}

.footer-tip {
  font-size: 0.688rem;
  color: #525252;
  text-align: center;
  line-height: 1.5;
}

/* Transition */
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
</style>
