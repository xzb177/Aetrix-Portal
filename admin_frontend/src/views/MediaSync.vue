<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { RefreshCw, Database, Film, Clock, CheckCircle, AlertCircle, RotateCw, Server, PlayCircle } from 'lucide-vue-next'

interface Library {
  id: number
  name: string
  type: 'movie' | 'tv' | 'music' | 'other'
  server: string
  itemCount: number
  size: string
  lastScan: string
  scanStatus: 'idle' | 'scanning' | 'error'
  syncStatus: 'synced' | 'syncing' | 'pending' | 'error'
  syncProgress?: number
}

interface SyncLog {
  id: number
  library: string
  action: string
  status: 'success' | 'error'
  time: string
}

const loading = ref(false)
const libraries = ref<Library[]>([])
const syncLogs = ref<SyncLog[]>([])

// 模拟数据
const mockLibraries: Library[] = [
  {
    id: 1,
    name: '电影库',
    type: 'movie',
    server: '主服务器',
    itemCount: 2156,
    size: '4.2 TB',
    lastScan: '2024-01-05 14:00',
    scanStatus: 'idle',
    syncStatus: 'synced',
  },
  {
    id: 2,
    name: '剧集库',
    type: 'tv',
    server: '主服务器',
    itemCount: 18456,
    size: '12.8 TB',
    lastScan: '2024-01-05 13:30',
    scanStatus: 'scanning',
    syncStatus: 'syncing',
    syncProgress: 67,
  },
  {
    id: 3,
    name: '动漫库',
    type: 'tv',
    server: '备份服务器',
    itemCount: 3248,
    size: '2.1 TB',
    lastScan: '2024-01-05 12:00',
    scanStatus: 'idle',
    syncStatus: 'synced',
  },
  {
    id: 4,
    name: '音乐库',
    type: 'music',
    server: '主服务器',
    itemCount: 8946,
    size: '156 GB',
    lastScan: '2024-01-04 22:00',
    scanStatus: 'idle',
    syncStatus: 'pending',
  },
  {
    id: 5,
    name: '纪录片库',
    type: 'other',
    server: '海外节点',
    itemCount: 456,
    size: '890 GB',
    lastScan: '2024-01-05 10:00',
    scanStatus: 'error',
    syncStatus: 'error',
  },
]

const mockSyncLogs: SyncLog[] = [
  { id: 1, library: '剧集库', action: '新增 23 部剧集', status: 'success', time: '14:30' },
  { id: 2, library: '电影库', action: '扫描完成', status: 'success', time: '14:00' },
  { id: 3, library: '纪录片库', action: '扫描失败：连接超时', status: 'error', time: '10:00' },
  { id: 4, library: '动漫库', action: '同步完成', status: 'success', time: '09:30' },
  { id: 5, library: '音乐库', action: '新增 156 首歌曲', status: 'success', time: '08:00' },
]

const loadSyncData = async () => {
  loading.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 800))
    libraries.value = mockLibraries
    syncLogs.value = mockSyncLogs
  } catch (error) {
    console.error('加载同步数据失败:', error)
  } finally {
    loading.value = false
  }
}

const triggerScan = async (libraryId: number) => {
  const lib = libraries.value.find(l => l.id === libraryId)
  if (lib) {
    lib.scanStatus = 'scanning'
    // 模拟扫描
    setTimeout(() => {
      lib.scanStatus = 'idle'
      lib.lastScan = new Date().toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    }, 5000)
  }
}

const triggerSync = async (libraryId: number) => {
  const lib = libraries.value.find(l => l.id === libraryId)
  if (lib) {
    lib.syncStatus = 'syncing'
    lib.syncProgress = 0
    // 模拟同步进度
    const interval = setInterval(() => {
      if (lib.syncProgress! >= 100) {
        clearInterval(interval)
        lib.syncStatus = 'synced'
        lib.syncProgress = undefined
      } else {
        lib.syncProgress! += 10
      }
    }, 500)
  }
}

const getTypeIcon = (type: string) => {
  return Film
}

const getTypeClass = (type: string) => {
  switch (type) {
    case 'movie': return 'type-movie'
    case 'tv': return 'type-tv'
    case 'music': return 'type-music'
    default: return 'type-other'
  }
}

const getTypeText = (type: string) => {
  switch (type) {
    case 'movie': return '电影'
    case 'tv': return '剧集'
    case 'music': return '音乐'
    default: return '其他'
  }
}

const getSyncStatusClass = (status: string) => {
  switch (status) {
    case 'synced': return 'status-synced'
    case 'syncing': return 'status-syncing'
    case 'pending': return 'status-pending'
    case 'error': return 'status-error'
    default: return ''
  }
}

const getSyncStatusText = (status: string) => {
  switch (status) {
    case 'synced': return '已同步'
    case 'syncing': return '同步中'
    case 'pending': return '待同步'
    case 'error': return '同步失败'
    default: return status
  }
}

let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadSyncData()
  refreshInterval = setInterval(loadSyncData, 10000) // 每10秒刷新
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<template>
  <div class="media-sync-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="refresh-btn" @click="loadSyncData" :class="{ spinning: loading }">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
    </div>

    <!-- 统计概览 -->
    <div class="summary-grid">
      <div class="summary-card">
        <div class="summary-icon summary-primary">
          <Database :size="20" />
        </div>
        <div class="summary-content">
          <p class="summary-value">{{ libraries.length }}</p>
          <p class="summary-label">媒体库总数</p>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-icon summary-success">
          <CheckCircle :size="20" />
        </div>
        <div class="summary-content">
          <p class="summary-value">{{ libraries.filter(l => l.syncStatus === 'synced').length }}</p>
          <p class="summary-label">已同步</p>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-icon summary-warning">
          <RotateCw :size="20" />
        </div>
        <div class="summary-content">
          <p class="summary-value">{{ libraries.filter(l => l.syncStatus === 'syncing' || l.scanStatus === 'scanning').length }}</p>
          <p class="summary-label">同步中</p>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-icon summary-danger">
          <AlertCircle :size="20" />
        </div>
        <div class="summary-content">
          <p class="summary-value">{{ libraries.filter(l => l.syncStatus === 'error' || l.scanStatus === 'error').length }}</p>
          <p class="summary-label">异常</p>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-icon summary-info">
          <PlayCircle :size="20" />
        </div>
        <div class="summary-content">
          <p class="summary-value">{{ libraries.reduce((sum, l) => sum + l.itemCount, 0).toLocaleString() }}</p>
          <p class="summary-label">总项目数</p>
        </div>
      </div>

      <div class="summary-card">
        <div class="summary-icon">
          <Clock :size="20" />
        </div>
        <div class="summary-content">
          <p class="summary-value">2分钟前</p>
          <p class="summary-label">最近扫描</p>
        </div>
      </div>
    </div>

    <!-- 媒体库列表 -->
    <div class="libraries-section">
      <h2 class="section-title">媒体库列表</h2>
      <div class="libraries-grid">
        <div v-for="library in libraries" :key="library.id" class="library-card">
          <div class="library-header">
            <div class="library-type" :class="getTypeClass(library.type)">
              <component :is="getTypeIcon(library.type)" :size="20" />
            </div>
            <div class="library-info">
              <h3 class="library-name">{{ library.name }}</h3>
              <span class="library-server">
                <Server :size="14" />
                {{ library.server }}
              </span>
            </div>
            <span class="library-status" :class="getSyncStatusClass(library.syncStatus)">
              {{ getSyncStatusText(library.syncStatus) }}
            </span>
          </div>

          <div class="library-stats">
            <div class="stat-item">
              <span class="stat-label">项目数</span>
              <span class="stat-value">{{ library.itemCount.toLocaleString() }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">大小</span>
              <span class="stat-value">{{ library.size }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">最后扫描</span>
              <span class="stat-value">{{ library.lastScan }}</span>
            </div>
          </div>

          <!-- 同步进度 -->
          <div v-if="library.syncStatus === 'syncing'" class="sync-progress">
            <div class="progress-info">
              <span>同步中...</span>
              <span>{{ library.syncProgress }}%</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: `${library.syncProgress}%` }"></div>
            </div>
          </div>

          <div class="library-actions">
            <button class="btn-scan" @click="triggerScan(library.id)" :disabled="library.scanStatus === 'scanning'">
              <RefreshCw :size="16" :class="{ spinning: library.scanStatus === 'scanning' }" />
              扫描
            </button>
            <button class="btn-sync" @click="triggerSync(library.id)" :disabled="library.syncStatus === 'syncing'">
            <RotateCw :size="16" />
            同步
          </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 同步日志 -->
    <div class="logs-section">
      <h2 class="section-title">最近同步日志</h2>
      <div class="logs-list">
        <div v-for="log in syncLogs" :key="log.id" class="log-item">
          <div class="log-icon" :class="log.status === 'success' ? 'log-success' : 'log-error'">
            <CheckCircle v-if="log.status === 'success'" :size="16" />
            <AlertCircle v-else :size="16" />
          </div>
          <div class="log-content">
            <span class="log-library">{{ log.library }}</span>
            <span class="log-action">{{ log.action }}</span>
          </div>
          <span class="log-time">{{ log.time }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.media-sync-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 页面标题 */





.refresh-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  background: #673AB7;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 0.2s ease;
}

.refresh-btn:hover {
  background: #552b9f;
}

.refresh-btn.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 统计卡片 */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 1rem;
}

@media (max-width: 1400px) {
  .summary-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  background: white;
  border-radius: 10px;
  border: 1px solid #e8edf3;
}

.summary-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.summary-primary { background: linear-gradient(135deg, #673AB7, #7B1FA2); }
.summary-success { background: linear-gradient(135deg, #4CAF50, #43A047); }
.summary-warning { background: linear-gradient(135deg, #FF9800, #F57C00); }
.summary-danger { background: linear-gradient(135deg, #F44336, #D32F2F); }
.summary-info { background: linear-gradient(135deg, #2196F3, #1976D2); }

.summary-content {
  flex: 1;
}

.summary-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1a1a2e;
}

.summary-label {
  font-size: 0.75rem;
  color: #64748b;
}

/* 媒体库列表 */
.libraries-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 1rem 0;
}

.libraries-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

@media (max-width: 1200px) {
  .libraries-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .libraries-grid {
    grid-template-columns: 1fr;
  }
}

.library-card {
  padding: 1.25rem;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  transition: all 0.2s ease;
}

.library-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.library-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.library-type {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.type-movie { background: linear-gradient(135deg, #673AB7, #7B1FA2); }
.type-tv { background: linear-gradient(135deg, #4CAF50, #43A047); }
.type-music { background: linear-gradient(135deg, #2196F3, #1976D2); }
.type-other { background: linear-gradient(135deg, #9C27B0, #7B1FA2); }

.library-info {
  flex: 1;
}

.library-name {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.library-server {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: #94a3b8;
}

.library-status {
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-synced {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.status-syncing {
  background: rgba(103, 58, 183, 0.15);
  color: #673AB7;
}

.status-pending {
  background: rgba(255, 152, 0, 0.15);
  color: #FF9800;
}

.status-error {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

.library-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: white;
  border-radius: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.stat-label {
  font-size: 0.7rem;
  color: #94a3b8;
}

.stat-value {
  font-size: 0.8rem;
  font-weight: 500;
  color: #475569;
}

.sync-progress {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: rgba(103, 58, 183, 0.08);
  border-radius: 8px;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  margin-bottom: 0.5rem;
  color: #673AB7;
}

.progress-bar {
  height: 4px;
  background: #e2e8f0;
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #673AB7, #4CAF50);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.library-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-scan,
.btn-sync {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border: 1px solid #e2e8f0;
  background: white;
  border-radius: 8px;
  font-size: 0.8rem;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-syn:hover,
.btn-sync:hover {
  border-color: #673AB7;
  color: #673AB7;
}

.btn-scan:disabled,
.btn-sync:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 日志 */
.logs-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.logs-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.log-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  background: #f8fafc;
  border-radius: 8px;
}

.log-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.log-success {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.log-error {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

.log-content {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.log-library {
  font-size: 0.875rem;
  font-weight: 500;
  color: #1a1a2e;
}

.log-action {
  font-size: 0.8rem;
  color: #64748b;
}

.log-time {
  font-size: 0.75rem;
  color: #94a3b8;
}
</style>
