<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Zap, Play, Clock, Cpu, HardDrive, RefreshCw, XCircle, CheckCircle, Pause, Server } from 'lucide-vue-next'
import { getTranscodeQueue } from '@/api/stats'

interface TranscodeJob {
  user: string
  item_name: string
  item_type: string
  container: string
  video_codec: string
  audio_codec: string
  width: number
  height: number
  bitrate: number
  framerate: string
  is_video_direct: boolean
  is_audio_direct: boolean
  progress: number
  duration: number
  percent_complete: number
}

const loading = ref(false)
const jobs = ref<TranscodeJob[]>([])
const activeCount = ref(0)

const filterStatus = ref<string>('all')

const stats = computed(() => {
  const queued = jobs.value.filter(j => j.percent_complete === 0).length
  const completed = jobs.value.filter(j => j.percent_complete >= 100).length
  const failed = jobs.value.filter(j => j.percent_complete < 0).length

  return {
    active: activeCount.value,
    queued,
    completed,
    failed,
    avgSpeed: '0.0',
    avgTime: '0'
  }
})

const filteredJobs = computed(() => {
  let result = jobs.value

  if (filterStatus.value === 'processing') {
    result = result.filter(job => job.percent_complete < 100 && job.percent_complete > 0)
  } else if (filterStatus.value === 'queued') {
    result = result.filter(job => job.percent_complete === 0)
  } else if (filterStatus.value === 'completed') {
    result = result.filter(job => job.percent_complete >= 100)
  }

  return result
})

const processingJobs = computed(() => filteredJobs.value.filter(j => j.percent_complete > 0 && j.percent_complete < 100))

const loadTranscodeData = async () => {
  loading.value = true
  try {
    const response = await getTranscodeQueue() as any
    jobs.value = response.items || []
    activeCount.value = response.active_transcodes || 0
  } catch (error) {
    console.error('加载转码数据失败:', error)
    jobs.value = []
    activeCount.value = 0
  } finally {
    loading.value = false
  }
}

const getStatusClass = (job: TranscodeJob) => {
  if (job.percent_complete >= 100) return 'status-completed'
  if (job.percent_complete > 0) return 'status-processing'
  return 'status-queued'
}

const getStatusText = (job: TranscodeJob) => {
  if (job.percent_complete >= 100) return '已完成'
  if (job.percent_complete > 0) return '转码中'
  return '等待中'
}

const getMediaTypeIcon = (type: string) => {
  if (type === 'Movie') return 'media-movie'
  if (type === 'Series' || type === 'Episode') return 'media-tv'
  return 'media-movie'
}

const getMediaTypeText = (type: string) => {
  if (type === 'Movie') return '电影'
  if (type === 'Series') return '剧集'
  if (type === 'Episode') return '集'
  if (type === 'Audio') return '音乐'
  return type
}

const getResolution = (width: number, height: number) => {
  if (width >= 3800) return '4K'
  if (width >= 1900) return '1080p'
  if (width >= 1280) return '720p'
  return '480p'
}

const getCodecInfo = (container: string, videoCodec: string, audioCodec: string, isVideoDirect: boolean, isAudioDirect: boolean) => {
  const parts = []
  if (isVideoDirect) parts.push('直放')
  else parts.push(`${videoCodec}`)
  parts.push(audioCodec)
  return parts.join(' / ')
}

const formatTime = (seconds: number) => {
  if (seconds < 60) return `${Math.round(seconds)}秒`
  const minutes = Math.floor(seconds / 60)
  const remaining = Math.round(seconds % 60)
  return `${minutes}分${remaining}秒`
}

const calculateSpeed = (progress: number, duration: number) => {
  if (duration <= 0 || progress <= 0) return 0
  // 简化的速度计算，假设每5秒刷新
  return progress / duration * 100
}

let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadTranscodeData()
  refreshInterval = setInterval(loadTranscodeData, 10000) // 每10秒刷新
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<template>
  <div class="transcode-page">
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card stat-processing">
        <div class="stat-icon">
          <Play :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.active }}</p>
          <p class="stat-label">转码中</p>
        </div>
        <div class="stat-indicator" :class="{ active: stats.active > 0 }"></div>
      </div>

      <div class="stat-card stat-queued">
        <div class="stat-icon">
          <Clock :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.queued }}</p>
          <p class="stat-label">排队中</p>
        </div>
      </div>

      <div class="stat-card stat-completed">
        <div class="stat-icon">
          <CheckCircle :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.completed }}</p>
          <p class="stat-label">今日完成</p>
        </div>
      </div>

      <div class="stat-card stat-failed">
        <div class="stat-icon">
          <XCircle :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.failed }}</p>
          <p class="stat-label">失败</p>
        </div>
      </div>

      <div class="stat-card stat-speed">
        <div class="stat-icon">
          <Cpu :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.avgSpeed }}x</p>
          <p class="stat-label">平均速度</p>
        </div>
      </div>

      <div class="stat-card stat-time">
        <div class="stat-icon">
          <HardDrive :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.avgTime }}m</p>
          <p class="stat-label">平均耗时</p>
        </div>
      </div>
    </div>

    <!-- 过滤器 -->
    <div class="filters">
      <div class="filter-group">
        <label>状态筛选</label>
        <select v-model="filterStatus">
          <option value="all">全部</option>
          <option value="processing">转码中</option>
          <option value="queued">排队中</option>
          <option value="completed">已完成</option>
        </select>
      </div>

      <div class="filter-info">
        <span>显示 {{ filteredJobs.length }} 个任务</span>
        <span v-if="processingJobs.length > 0" class="active-indicator">
          {{ processingJobs.length }} 个正在处理
        </span>
      </div>
    </div>

    <!-- 转码任务列表 -->
    <div class="jobs-list">
      <div v-for="(job, index) in filteredJobs" :key="`${job.user}-${job.item_name}-${index}`" class="job-card" :class="`job-${job.percent_complete >= 100 ? 'completed' : job.percent_complete > 0 ? 'processing' : 'queued'}`">
        <div class="job-main">
          <div class="job-media">
            <div class="media-icon" :class="getMediaTypeIcon(job.item_type)">
              <Play :size="16" />
            </div>
            <div class="media-info">
              <h4 class="media-title">{{ job.item_name }}</h4>
              <span class="media-type">{{ getMediaTypeText(job.item_type) }}</span>
            </div>
          </div>

          <div class="job-details">
            <div class="detail-item">
              <span class="detail-label">用户</span>
              <span class="detail-value">{{ job.user }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">编码</span>
              <span class="detail-value">{{ getCodecInfo(job.container, job.video_codec, job.audio_codec, job.is_video_direct, job.is_audio_direct) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">分辨率</span>
              <span class="detail-value">{{ getResolution(job.width, job.height) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">比特率</span>
              <span class="detail-value">{{ Math.round(job.bitrate / 1000) }}kbps</span>
            </div>
          </div>

          <div class="job-status">
            <span class="status-badge" :class="getStatusClass(job)">
              {{ getStatusText(job) }}
            </span>
          </div>
        </div>

        <!-- 进度条 -->
        <div v-if="job.percent_complete > 0 && job.percent_complete < 100" class="job-progress">
          <div class="progress-info">
            <span class="progress-percent">{{ job.percent_complete }}%</span>
            <span class="progress-speed">{{ formatTime(job.duration) }}</span>
            <span class="progress-eta">进度 {{ formatTime(job.progress) }}</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${job.percent_complete}%` }"></div>
          </div>
        </div>

        <!-- 排队信息 -->
        <div v-if="job.percent_complete === 0" class="job-queued">
          <Clock :size="16" />
          <span>等待前序任务完成...</span>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!filteredJobs.length && !loading" class="empty-state">
        <Zap :size="48" />
        <p>暂无转码任务</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.transcode-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 1rem;
}

@media (max-width: 1400px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  background: white;
  border-radius: 10px;
  border: 1px solid #e8edf3;
  position: relative;
  overflow: hidden;
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.stat-processing .stat-icon { background: linear-gradient(135deg, #673AB7, #7B1FA2); }
.stat-queued .stat-icon { background: linear-gradient(135deg, #FF9800, #F57C00); }
.stat-completed .stat-icon { background: linear-gradient(135deg, #4CAF50, #43A047); }
.stat-failed .stat-icon { background: linear-gradient(135deg, #F44336, #D32F2F); }
.stat-speed .stat-icon { background: linear-gradient(135deg, #2196F3, #1976D2); }
.stat-time .stat-icon { background: linear-gradient(135deg, #9C27B0, #7B1FA2); }

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1a1a2e;
}

.stat-label {
  font-size: 0.75rem;
  color: #64748b;
}

.stat-indicator {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4CAF50;
}

.stat-indicator.active {
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* 过滤器 */
.filters {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: white;
  border-radius: 10px;
  border: 1px solid #e8edf3;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.filter-group label {
  font-size: 0.875rem;
  color: #64748b;
}

.filter-group select {
  padding: 0.5rem 2rem 0.5rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #1a1a2e;
  background: white;
  cursor: pointer;
}

.filter-info {
  margin-left: auto;
  display: flex;
  gap: 1rem;
  font-size: 0.875rem;
  color: #64748b;
}

.active-indicator {
  color: #673AB7;
  font-weight: 500;
}

/* 任务列表 */
.jobs-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.job-card {
  background: white;
  border-radius: 12px;
  padding: 1.25rem;
  border: 1px solid #e8edf3;
  transition: all 0.2s ease;
}

.job-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.job-card.job-processing {
  border-left: 4px solid #673AB7;
}

.job-card.job-queued {
  border-left: 4px solid #FF9800;
  opacity: 0.8;
}

.job-card.job-completed {
  border-left: 4px solid #4CAF50;
  opacity: 0.7;
}

.job-card.job-failed {
  border-left: 4px solid #F44336;
}

.job-main {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.job-media {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 200px;
}

.media-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.media-movie { background: linear-gradient(135deg, #673AB7, #7B1FA2); }
.media-tv { background: linear-gradient(135deg, #4CAF50, #43A047); }
.media-music { background: linear-gradient(135deg, #2196F3, #1976D2); }

.media-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.media-type {
  font-size: 0.75rem;
  color: #94a3b8;
}

.job-details {
  flex: 1;
  display: flex;
  gap: 2rem;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.detail-label {
  font-size: 0.7rem;
  color: #94a3b8;
}

.detail-value {
  font-size: 0.8rem;
  color: #475569;
}

.status-badge {
  padding: 0.375rem 0.75rem;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status-processing {
  background: rgba(103, 58, 183, 0.15);
  color: #673AB7;
}

.status-queued {
  background: rgba(255, 152, 0, 0.15);
  color: #FF9800;
}

.status-completed {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.status-failed {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

/* 进度条 */
.job-progress {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
  font-size: 0.8rem;
}

.progress-percent {
  font-weight: 600;
  color: #673AB7;
}

.progress-speed {
  color: #4CAF50;
}

.progress-eta {
  color: #94a3b8;
}

.progress-bar {
  height: 6px;
  background: #f1f5f9;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #673AB7, #4CAF50);
  border-radius: 3px;
  transition: width 0.3s ease;
}

/* 排队状态 */
.job-queued {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding: 0.5rem;
  background: rgba(255, 152, 0, 0.08);
  border-radius: 6px;
  font-size: 0.8rem;
  color: #F57C00;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  color: #94a3b8;
}

.empty-state svg {
  margin-bottom: 1rem;
  opacity: 0.5;
}
</style>
