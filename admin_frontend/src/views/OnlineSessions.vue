<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import {
  RefreshCw,
  Users,
  Monitor,
  Smartphone,
  Tv,
  LogOut,
  X,
  Filter,
  Server,
  Play,
  Pause,
} from 'lucide-vue-next'
import { http } from '@/utils/request'

interface Session {
  id: string
  user_id: string
  username: string
  server_id?: number
  server_name?: string
  client: string
  device_name: string
  device_type: string
  application_version: string
  now_playing_item?: {
    Id: string
    Name: string
    Type: string
    SeriesName?: string
    ProductionYear?: number
    RunTimeTicks?: number
  }
  play_state: {
    PositionTicks?: number
    IsPaused?: boolean
    PlayMethod?: string
  }
  last_activity_date: string
}

const loading = ref(false)
const sessions = ref<Session[]>([])
const selectedServer = ref<number | null>(null)
const autoRefresh = ref(true)
const refreshInterval = ref<number | null>(null)

// 显示提示
const showToast = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error' | 'warning' | 'info'>('success')

const showToastMessage = (message: string, type: 'success' | 'error' | 'warning' | 'info') => {
  toastMessage.value = message
  toastType.value = type
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

// 获取设备图标
const getDeviceIcon = (deviceType: string) => {
  switch (deviceType?.toLowerCase()) {
    case 'smartphone':
    case 'phone':
      return Smartphone
    case 'tv':
      return Tv
    default:
      return Monitor
  }
}

// 获取客户端名称
const getClientName = (client: string) => {
  const clientMap: Record<string, string> = {
    'Emby Web': 'Web浏览器',
    'Emby Mobile': '移动端',
    'Emby Theater': 'Theater',
    'Emby for Android TV': 'Android TV',
    'Emby for iOS': 'iOS',
    'Emby for Android': 'Android',
    'Kodi': 'Kodi',
    'Plex': 'Plex',
    'Jellyfin': 'Jellyfin',
  }
  return clientMap[client] || client
}

// 格式化播放进度
const formatProgress = (positionTicks: number, runTimeTicks: number) => {
  if (!positionTicks || !runTimeTicks) return 0
  return Math.round((positionTicks / runTimeTicks) * 100)
}

// 格式化时长
const formatDuration = (ticks: number) => {
  if (!ticks) return '-'
  const seconds = Math.floor(ticks / 10000000)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) {
    return `${hours}小时${minutes}分钟`
  }
  return `${minutes}分钟`
}

// 格式化时间
const formatTime = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 统计数据
const stats = computed(() => {
  const total = sessions.value.length
  const playing = sessions.value.filter(s =>
    s.now_playing_item && !s.play_state.IsPaused
  ).length
  const paused = sessions.value.filter(s =>
    s.now_playing_item && s.play_state.IsPaused
  ).length
  const idle = total - playing - paused

  // 按服务器分组
  const byServer: Record<string, number> = {}
  sessions.value.forEach(s => {
    const key = s.server_name || '未知服务器'
    byServer[key] = (byServer[key] || 0) + 1
  })

  return { total, playing, paused, idle, byServer }
})

// 加载会话数据
const loadSessions = async () => {
  loading.value = true
  try {
    const url = selectedServer.value
      ? `/emby-sessions/sessions?server_id=${selectedServer.value}`
      : '/emby-sessions/sessions'
    const response = await http.get<{ sessions: Session[] }>(url)
    sessions.value = response.sessions || []
  } catch (error) {
    console.error('加载会话失败:', error)
    showToastMessage('加载失败，请稍后重试', 'error')
  } finally {
    loading.value = false
  }
}

// 踢出用户
const handleKickUser = async (session: Session) => {
  if (!confirm(`确定要踢出用户 ${session.username} 吗？`)) {
    return
  }

  try {
    const serverId = session.server_id || selectedServer.value
    if (!serverId) {
      showToastMessage('无法确定服务器', 'error')
      return
    }

    await http.post(`/emby-sessions/sessions/${session.id}/kick?server_id=${serverId}`)
    showToastMessage(`用户 ${session.username} 已踢下线`, 'success')
    loadSessions()
  } catch (error) {
    console.error('踢出用户失败:', error)
    showToastMessage('操作失败，请稍后重试', 'error')
  }
}

// 切换自动刷新
const toggleAutoRefresh = () => {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}

// 启动自动刷新
const startAutoRefresh = () => {
  stopAutoRefresh()
  refreshInterval.value = window.setInterval(() => {
    loadSessions()
  }, 10000) // 10秒刷新一次
}

// 停止自动刷新
const stopAutoRefresh = () => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value)
    refreshInterval.value = null
  }
}

onMounted(() => {
  loadSessions()
  if (autoRefresh.value) {
    startAutoRefresh()
  }
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div class="online-sessions-page">
    <!-- 操作按钮 -->
    <div class="page-actions">
      <button class="btn-secondary" @click="loadSessions" :class="{ spinning: loading }">
        <RefreshCw :size="18" :class="{ 'animate-spin': loading }" />
        刷新
      </button>
      <button
        class="btn-toggle"
        :class="{ active: autoRefresh }"
        @click="toggleAutoRefresh"
      >
        <span class="toggle-indicator"></span>
        自动刷新 (10s)
      </button>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon stat-icon-blue">
          <Users :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">总在线</div>
          <div class="stat-value">{{ stats.total }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-green">
          <Play :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">播放中</div>
          <div class="stat-value">{{ stats.playing }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-yellow">
          <Pause :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">已暂停</div>
          <div class="stat-value">{{ stats.paused }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-gray">
          <Monitor :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">空闲</div>
          <div class="stat-value">{{ stats.idle }}</div>
        </div>
      </div>
    </div>

    <!-- 服务器筛选 -->
    <div class="filter-bar" v-if="Object.keys(stats.byServer).length > 1">
      <div class="filter-group">
        <Filter :size="16" />
        <span>服务器筛选:</span>
        <button
          :class="['filter-btn', { active: selectedServer === null }]"
          @click="selectedServer = null; loadSessions()"
        >
          全部 ({{ stats.total }})
        </button>
        <button
          v-for="(count, name) in stats.byServer"
          :key="name"
          :class="['filter-btn', { active: selectedServer === sessions.find(s => s.server_name === name)?.server_id }]"
          @click="selectedServer = sessions.find(s => s.server_name === name)?.server_id || null; loadSessions()"
        >
          {{ name }} ({{ count }})
        </button>
      </div>
    </div>

    <!-- 会话列表 -->
    <div class="sessions-container">
      <!-- 空状态 -->
      <div v-if="!loading && sessions.length === 0" class="empty-state">
        <Users :size="48" />
        <p>当前没有在线用户</p>
      </div>

      <!-- 会话卡片列表 -->
      <div v-else class="sessions-list">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="session-card"
          :class="{ 'is-playing': session.now_playing_item && !session.play_state.IsPaused }"
        >
          <!-- 用户信息 -->
          <div class="session-header">
            <div class="user-info">
              <component :is="getDeviceIcon(session.device_type)" :size="20" class="device-icon" />
              <div>
                <div class="username">{{ session.username }}</div>
                <div class="device-info">
                  {{ getClientName(session.client) }} · {{ session.device_name }}
                </div>
              </div>
            </div>
            <div class="session-actions">
              <button
                class="btn-icon btn-danger"
                @click="handleKickUser(session)"
                title="踢下线"
              >
                <LogOut :size="16" />
              </button>
            </div>
          </div>

          <!-- 正在播放 -->
          <div v-if="session.now_playing_item" class="now-playing">
            <div class="playing-info">
              <div class="media-title">
                {{ session.now_playing_item.SeriesName || session.now_playing_item.Name }}
              </div>
              <div class="media-meta">
                <span v-if="session.now_playing_item.SeriesName">
                  {{ session.now_playing_item.Name }}
                </span>
                <span v-if="session.now_playing_item.ProductionYear">
                  · {{ session.now_playing_item.ProductionYear }}
                </span>
                <span>· {{ session.now_playing_item.Type === 'Episode' ? '剧集' : '电影' }}</span>
              </div>
            </div>
            <div class="playing-status">
              <div class="status-badge" :class="{ paused: session.play_state.IsPaused }">
                <Play v-if="!session.play_state.IsPaused" :size="12" />
                <Pause v-else :size="12" />
                {{ session.play_state.IsPaused ? '暂停' : '播放中' }}
              </div>
              <div class="play-method" :class="{
                'transcode': session.play_state.PlayMethod === 'Transcode',
                'direct-play': session.play_state.PlayMethod === 'DirectPlay'
              }">
                {{ session.play_state.PlayMethod === 'Transcode' ? '转码' : '直推' }}
              </div>
            </div>
          </div>

          <!-- 会话元数据 -->
          <div class="session-meta">
            <span v-if="session.server_name" class="meta-item">
              <Server :size="12" />
              {{ session.server_name }}
            </span>
            <span class="meta-item">
              活动时间: {{ formatTime(session.last_activity_date) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <p>加载中...</p>
      </div>
    </div>

    <!-- 提示消息 -->
    <div v-if="showToast" :class="['toast', `toast-${toastType}`]">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.online-sessions-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

/* 操作按钮 */
.page-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--border-base);
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.stat-icon-blue { background: var(--info); }
.stat-icon-green { background: var(--success); }
.stat-icon-yellow { background: var(--warning); }
.stat-icon-gray { background: var(--text-secondary); }

.stat-content {
  flex: 1;
}

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 筛选栏 */
.filter-bar {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 12px 16px;
  margin-bottom: 20px;
  border: 1px solid var(--border-base);
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-btn {
  padding: 6px 12px;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-base) ease;
  font-size: 13px;
}

.filter-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.filter-btn.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

/* 会话容器 */
.sessions-container {
  min-height: 400px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: var(--text-tertiary);
}

.empty-state svg {
  margin-bottom: 16px;
}

/* 会话列表 */
.sessions-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 16px;
}

.session-card {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: 16px;
  border: 1px solid var(--border-base);
  transition: all var(--transition-base) ease;
}

.session-card:hover {
  box-shadow: var(--shadow-lg);
}

.session-card.is-playing {
  border-left: 3px solid var(--primary);
}

/* 会话头部 */
.session-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}

.device-icon {
  color: var(--text-secondary);
}

.username {
  font-weight: 600;
  font-size: 15px;
  color: var(--text-primary);
}

.device-info {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

.session-actions {
  display: flex;
  gap: 6px;
}

/* 正在播放 */
.now-playing {
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  padding: 12px;
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.playing-info {
  flex: 1;
  min-width: 0;
}

.media-title {
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.media-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.playing-status {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.status-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
  background: var(--success);
  color: #fff;
}

.status-badge.paused {
  background: var(--warning);
}

.play-method {
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
}

.play-method.transcode {
  background: var(--warning-bg);
  color: var(--warning);
}

.play-method.direct-play {
  background: var(--success-bg);
  color: var(--success);
}

/* 会话元数据 */
.session-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 按钮样式 */
.btn-secondary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base) ease;
  font-size: 14px;
}

.btn-secondary:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--bg-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base) ease;
  font-size: 13px;
}

.btn-toggle.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.toggle-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border-strong);
}

.btn-toggle.active .toggle-indicator {
  background: #fff;
  box-shadow: 0 0 8px rgba(255, 255, 255, 0.8);
}

.btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--bg-hover);
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-base) ease;
}

.btn-icon:hover {
  background: var(--bg-elevated);
}

.btn-icon.btn-danger {
  background: var(--danger-bg);
  color: var(--danger);
}

.btn-icon.btn-danger:hover {
  background: rgba(239, 68, 68, 0.2);
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-tertiary);
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--bg-hover);
  border-top: 3px solid var(--primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 16px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* 提示消息 */
.toast {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 12px 20px;
  border-radius: var(--radius-lg);
  color: #fff;
  font-size: 14px;
  z-index: 1000;
  animation: slideIn 0.3s ease;
}

.toast-success { background: var(--success); }
.toast-error { background: var(--danger); }
.toast-warning { background: var(--warning); }
.toast-info { background: var(--info); }

@keyframes slideIn {
  from {
    transform: translateX(100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

/* 响应式 */
@media (max-width: 768px) {
  .online-sessions-page {
    padding: 12px;
  }

  .sessions-list {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
