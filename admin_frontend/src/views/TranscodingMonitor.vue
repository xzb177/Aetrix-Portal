<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import {
  RefreshCw,
  Zap,
  Monitor,
  Film,
  Settings,
  X,
  Server,
  TrendingUp,
  Activity,
} from 'lucide-vue-next'
import { http } from '@/utils/request'

interface Transcoding {
  session_id: string
  username: string
  device_name: string
  client: string
  server_id?: number
  server_name?: string
  item_name: string
  item_type: string
  series_name?: string
  container: string
  video_codec: string
  audio_codec: string
  bitrate: number
  framerate: number
  width: number
  height: number
  audio_channels: number
  transcode_reasons: string[]
  is_video: boolean
  progress: number
}

const loading = ref(false)
const transcodings = ref<Transcoding[]>([])
const selectedServer = ref<number | null>(null)
const autoRefresh = ref(true)
const refreshInterval = ref<number | null>(null)
const showDetails = ref<string | null>(null)

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

// 格式化比特率
const formatBitrate = (bitrate: number) => {
  if (bitrate < 1000) return `${bitrate} kbps`
  return `${(bitrate / 1000).toFixed(1)} Mbps`
}

// 格式化分辨率
const formatResolution = (width: number, height: number) => {
  if (!width || !height) return '-'
  return `${width}x${height}`
}

// 获取转码原因标签
const getTranscodeReasons = (reasons: string[]) => {
  const reasonMap: Record<string, string> = {
    'VideoCodecNotSupported': '视频编码不支持',
    'AudioCodecNotSupported': '音频编码不支持',
    'ContainerNotSupported': '容器不支持',
    'VideoBitrateNotSupported': '视频码率过高',
    'AudioBitrateNotSupported': '音频码率过高',
    'VideoResolutionNotSupported': '分辨率过高',
    'AudioChannelsNotSupported': '声道数不支持',
    'DirectPlayError': '直接播放失败',
    'VideoCodecSupport': '视频编码',
    'AudioCodecSupport': '音频编码',
  }
  return reasons.map(r => reasonMap[r] || r).filter(Boolean)
}

// 统计数据
const stats = computed(() => {
  const total = transcodings.value.length

  // 按服务器分组
  const byServer: Record<string, Transcoding[]> = {}
  transcodings.value.forEach(t => {
    const key = t.server_name || '未知服务器'
    if (!byServer[key]) byServer[key] = []
    byServer[key].push(t)
  })

  // 按编码分组
  const byCodec: Record<string, number> = {}
  transcodings.value.forEach(t => {
    byCodec[t.video_codec] = (byCodec[t.video_codec] || 0) + 1
  })

  // 总码率
  const totalBitrate = transcodings.value.reduce((sum, t) => sum + t.bitrate, 0)

  return {
    total,
    byServer,
    byCodec,
    totalBitrate,
    avgBitrate: total > 0 ? totalBitrate / total : 0
  }
})

// 加载转码数据
const loadTranscodings = async () => {
  loading.value = true
  try {
    const url = selectedServer.value
      ? `/emby-sessions/transcodings?server_id=${selectedServer.value}`
      : '/emby-sessions/transcodings'
    const response = await http.get<{ transcodings: Transcoding[] }>(url)
    transcodings.value = response.transcodings || []
  } catch (error) {
    console.error('加载转码失败:', error)
    showToastMessage('加载失败，请稍后重试', 'error')
  } finally {
    loading.value = false
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
    loadTranscodings()
  }, 5000) // 5秒刷新一次
}

// 停止自动刷新
const stopAutoRefresh = () => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value)
    refreshInterval.value = null
  }
}

onMounted(() => {
  loadTranscodings()
  if (autoRefresh.value) {
    startAutoRefresh()
  }
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div class="transcoding-monitor-page">
    <!-- 操作按钮 -->
    <div class="page-actions">
      <button class="btn-secondary" @click="loadTranscodings" :class="{ spinning: loading }">
        <RefreshCw :size="18" :class="{ 'animate-spin': loading }" />
        刷新
      </button>
      <button
        class="btn-toggle"
        :class="{ active: autoRefresh }"
        @click="toggleAutoRefresh"
      >
        <span class="toggle-indicator"></span>
        自动刷新 (5s)
      </button>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon stat-icon-orange">
          <Activity :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">转码任务</div>
          <div class="stat-value">{{ stats.total }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-purple">
          <TrendingUp :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">总码率</div>
          <div class="stat-value">{{ formatBitrate(stats.totalBitrate) }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-blue">
          <Monitor :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">平均码率</div>
          <div class="stat-value">{{ formatBitrate(Math.round(stats.avgBitrate)) }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-green">
          <Server :size="20" />
        </div>
        <div class="stat-content">
          <div class="stat-label">服务器</div>
          <div class="stat-value">{{ Object.keys(stats.byServer).length }}</div>
        </div>
      </div>
    </div>

    <!-- 服务器筛选 -->
    <div class="filter-bar" v-if="Object.keys(stats.byServer).length > 1">
      <div class="filter-group">
        <span>服务器筛选:</span>
        <button
          :class="['filter-btn', { active: selectedServer === null }]"
          @click="selectedServer = null; loadTranscodings()"
        >
          全部 ({{ stats.total }})
        </button>
        <button
          v-for="(items, name) in stats.byServer"
          :key="name"
          :class="['filter-btn', { active: selectedServer === transcodings.find(t => t.server_name === name)?.server_id }]"
          @click="selectedServer = transcodings.find(t => t.server_name === name)?.server_id || null; loadTranscodings()"
        >
          {{ name }} ({{ items.length }})
        </button>
      </div>
    </div>

    <!-- 转码列表 -->
    <div class="transcodings-container">
      <!-- 空状态 -->
      <div v-if="!loading && transcodings.length === 0" class="empty-state">
        <Zap :size="48" />
        <p>当前没有转码任务</p>
      </div>

      <!-- 转码卡片列表 -->
      <div v-else class="transcodings-list">
        <div
          v-for="trans in transcodings"
          :key="trans.session_id"
          class="transcoding-card"
        >
          <!-- 卡片头部 -->
          <div class="card-header">
            <div class="user-info">
              <Film :size="20" class="media-icon" />
              <div>
                <div class="media-title">
                  {{ trans.series_name ? `${trans.series_name} - ${trans.item_name}` : trans.item_name }}
                </div>
                <div class="user-detail">
                  {{ trans.username }} · {{ trans.device_name }} · {{ trans.client }}
                </div>
              </div>
            </div>
            <button
              class="btn-expand"
              @click="showDetails = showDetails === trans.session_id ? null : trans.session_id"
            >
              <Settings :size="16" :class="{ rotate: showDetails === trans.session_id }" />
            </button>
          </div>

          <!-- 视频信息 -->
          <div class="video-info">
            <div class="info-row">
              <span class="label">分辨率:</span>
              <span class="value">{{ formatResolution(trans.width, trans.height) }}</span>
            </div>
            <div class="info-row">
              <span class="label">视频编码:</span>
              <span class="value codec-badge">{{ trans.video_codec }}</span>
            </div>
            <div class="info-row">
              <span class="label">音频编码:</span>
              <span class="value codec-badge">{{ trans.audio_codec }}</span>
            </div>
            <div class="info-row">
              <span class="label">码率:</span>
              <span class="value">{{ formatBitrate(trans.bitrate) }}</span>
            </div>
            <div class="info-row">
              <span class="label">帧率:</span>
              <span class="value">{{ trans.framerate }} fps</span>
            </div>
            <div class="info-row" v-if="trans.server_name">
              <span class="label">服务器:</span>
              <span class="value">{{ trans.server_name }}</span>
            </div>
          </div>

          <!-- 转码原因 -->
          <div class="transcode-reasons" v-if="trans.transcode_reasons.length > 0">
            <div class="reasons-label">转码原因:</div>
            <div class="reasons-list">
              <span
                v-for="(reason, idx) in getTranscodeReasons(trans.transcode_reasons)"
                :key="idx"
                class="reason-tag"
              >
                {{ reason }}
              </span>
            </div>
          </div>

          <!-- 详细信息（可展开） -->
          <div v-if="showDetails === trans.session_id" class="details-panel">
            <div class="detail-row">
              <span class="detail-label">容器:</span>
              <span class="detail-value">{{ trans.container }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">音频声道:</span>
              <span class="detail-value">{{ trans.audio_channels }} 声道</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">媒体类型:</span>
              <span class="detail-value">{{ trans.item_type }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">会话ID:</span>
              <span class="detail-value mono">{{ trans.session_id }}</span>
            </div>
          </div>

          <!-- 进度条 -->
          <div class="progress-bar" v-if="trans.progress > 0">
            <div class="progress-fill" :style="{ width: `${trans.progress}%` }"></div>
            <span class="progress-text">{{ Math.round(trans.progress) }}%</span>
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
.transcoding-monitor-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

/* 操作按钮区 */
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

.stat-icon-orange { background: var(--warning); }
.stat-icon-purple { background: #8b5cf6; }
.stat-icon-blue { background: var(--info); }
.stat-icon-green { background: var(--success); }

.stat-content {
  flex: 1;
}

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.stat-value {
  font-size: 20px;
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
  border-color: var(--warning);
  color: var(--warning);
}

.filter-btn.active {
  background: var(--warning);
  border-color: var(--warning);
  color: #fff;
}

/* 转码容器 */
.transcodings-container {
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

/* 转码列表 */
.transcodings-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(450px, 1fr));
  gap: 16px;
}

.transcoding-card {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: 16px;
  border: 1px solid var(--border-base);
  border-left: 3px solid var(--warning);
  transition: all var(--transition-base) ease;
}

.transcoding-card:hover {
  box-shadow: var(--shadow-lg);
}

/* 卡片头部 */
.card-header {
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

.media-icon {
  color: var(--warning);
}

.media-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.user-detail {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.btn-expand {
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

.btn-expand:hover {
  background: var(--bg-elevated);
}

.btn-expand svg {
  transition: transform var(--transition-base) ease;
}

.btn-expand svg.rotate {
  transform: rotate(90deg);
}

/* 视频信息 */
.video-info {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.info-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-row .label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.info-row .value {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
}

.codec-badge {
  background: var(--bg-hover);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: monospace;
  font-size: 12px;
}

/* 转码原因 */
.transcode-reasons {
  background: var(--warning-bg);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  margin-bottom: 12px;
}

.reasons-label {
  font-size: 11px;
  color: #92400e;
  margin-bottom: 6px;
  font-weight: 500;
}

.reasons-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.reason-tag {
  background: #fff;
  color: #92400e;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
}

/* 详细信息面板 */
.details-panel {
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  padding: 12px;
  margin-bottom: 12px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
}

.detail-label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.detail-value {
  font-size: 12px;
  color: var(--text-primary);
}

.detail-value.mono {
  font-family: monospace;
}

/* 进度条 */
.progress-bar {
  position: relative;
  height: 24px;
  background: var(--bg-hover);
  border-radius: 12px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--warning), #f97316);
  transition: width var(--transition-base) ease;
}

.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
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
  border-color: var(--warning);
  color: var(--warning);
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
  background: var(--warning);
  border-color: var(--warning);
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
  border-top: 3px solid var(--warning);
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
  .transcoding-monitor-page {
    padding: 12px;
  }

  .transcodings-list {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .video-info {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
