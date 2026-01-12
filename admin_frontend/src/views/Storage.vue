<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { HardDrive, TrendingUp, AlertTriangle, RefreshCw, Server } from 'lucide-vue-next'

interface StorageInfo {
  id: number
  name: string
  host: string
  path: string
  total: number
  used: number
  available: number
  usagePercent: number
  trend: number[] // 最近7天使用率趋势
  status: 'normal' | 'warning' | 'critical'
}

const loading = ref(false)
const storageList = ref<StorageInfo[]>([])
const selectedServer = ref<number | null>(null)

// 模拟数据
const mockStorageData: StorageInfo[] = [
  {
    id: 1,
    name: '主服务器',
    host: 'emby1.example.com',
    path: '/data/media',
    total: 8192, // GB
    used: 2456,
    available: 5736,
    usagePercent: 30,
    trend: [25, 26, 27, 28, 29, 30, 30],
    status: 'normal',
  },
  {
    id: 2,
    name: '备份服务器',
    host: 'emby2.example.com',
    path: '/data/media',
    total: 10240,
    used: 7680,
    available: 2560,
    usagePercent: 75,
    trend: [65, 67, 69, 71, 73, 74, 75],
    status: 'warning',
  },
  {
    id: 3,
    name: '缓存服务器',
    host: 'cache.example.com',
    path: '/var/cache/emby',
    total: 512,
    used: 486,
    available: 26,
    usagePercent: 95,
    trend: [88, 90, 91, 92, 93, 94, 95],
    status: 'critical',
  },
  {
    id: 4,
    name: '海外节点',
    host: 'us.emby.example.com',
    path: '/mnt/media',
    total: 4096,
    used: 1638,
    available: 2458,
    usagePercent: 40,
    trend: [35, 36, 37, 38, 39, 40, 40],
    status: 'normal',
  },
]

const totalStorage = computed(() => {
  return storageList.value.reduce((sum, s) => sum + s.total, 0)
})

const totalUsed = computed(() => {
  return storageList.value.reduce((sum, s) => sum + s.used, 0)
})

const totalUsagePercent = computed(() => {
  return Math.round((totalUsed.value / totalStorage.value) * 100)
})

const loadStorageData = async () => {
  loading.value = true
  try {
    // 模拟 API 调用
    await new Promise(resolve => setTimeout(resolve, 800))
    storageList.value = mockStorageData
  } catch (error) {
    console.error('加载存储数据失败:', error)
  } finally {
    loading.value = false
  }
}

const formatBytes = (gb: number) => {
  if (gb >= 1024) {
    return `${(gb / 1024).toFixed(1)} TB`
  }
  return `${gb} GB`
}

const getStatusClass = (status: string) => {
  switch (status) {
    case 'warning': return 'status-warning'
    case 'critical': return 'status-critical'
    default: return 'status-normal'
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'warning': return '警告'
    case 'critical': return '严重'
    default: return '正常'
  }
}

const getProgressClass = (percent: number) => {
  if (percent >= 90) return 'progress-critical'
  if (percent >= 70) return 'progress-warning'
  return 'progress-normal'
}

let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadStorageData()
  refreshInterval = setInterval(loadStorageData, 30000) // 每30秒刷新
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<template>
  <div class="storage-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="refresh-btn" @click="loadStorageData" :class="{ spinning: loading }">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
    </div>

    <!-- 总体统计卡片 -->
    <div class="summary-cards">
      <div class="summary-card summary-primary">
        <div class="summary-icon">
          <Server :size="24" />
        </div>
        <div class="summary-content">
          <p class="summary-label">服务器数量</p>
          <p class="summary-value">{{ storageList.length }} 台</p>
        </div>
      </div>

      <div class="summary-card summary-info">
        <div class="summary-icon">
          <HardDrive :size="24" />
        </div>
        <div class="summary-content">
          <p class="summary-label">总存储容量</p>
          <p class="summary-value">{{ formatBytes(totalStorage) }}</p>
        </div>
      </div>

      <div class="summary-card summary-success">
        <div class="summary-icon">
          <TrendingUp :size="24" />
        </div>
        <div class="summary-content">
          <p class="summary-label">已使用空间</p>
          <p class="summary-value">{{ formatBytes(totalUsed) }} ({{ totalUsagePercent }}%)</p>
        </div>
      </div>

      <div class="summary-card" :class="storageList.some(s => s.status === 'critical') ? 'summary-danger' : 'summary-warning'">
        <div class="summary-icon">
          <AlertTriangle :size="24" />
        </div>
        <div class="summary-content">
          <p class="summary-label">需要关注</p>
          <p class="summary-value">{{ storageList.filter(s => s.status !== 'normal').length }} 台</p>
        </div>
      </div>
    </div>

    <!-- 存储列表 -->
    <div class="storage-list">
      <div v-for="storage in storageList" :key="storage.id" class="storage-card" :class="`storage-${storage.status}`">
        <div class="storage-header">
          <div class="storage-info">
            <div class="storage-name">
              <Server :size="18" />
              <h3>{{ storage.name }}</h3>
            </div>
            <span class="storage-host">{{ storage.host }}</span>
            <span class="storage-path">{{ storage.path }}</span>
          </div>
          <div class="storage-status" :class="getStatusClass(storage.status)">
            <span class="status-dot"></span>
            <span>{{ getStatusText(storage.status) }}</span>
          </div>
        </div>

        <div class="storage-progress-section">
          <div class="progress-info">
            <span class="progress-label">使用率</span>
            <span class="progress-value">{{ storage.usagePercent }}%</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :class="getProgressClass(storage.usagePercent)" :style="{ width: `${storage.usagePercent}%` }"></div>
          </div>
          <div class="storage-details">
            <span>已使用 {{ formatBytes(storage.used) }}</span>
            <span>可用 {{ formatBytes(storage.available) }}</span>
            <span>总计 {{ formatBytes(storage.total) }}</span>
          </div>
        </div>

        <!-- 7天趋势图 -->
        <div class="storage-trend">
          <span class="trend-label">7天趋势</span>
          <div class="trend-chart">
            <div
              v-for="(value, index) in storage.trend"
              :key="index"
              class="trend-bar"
              :class="getProgressClass(value)"
              :style="{ height: `${value}%` }"
              :title="`${value}%`"
            ></div>
          </div>
          <span class="trend-prediction">
            {{ (storage.trend[6] ?? 0) > (storage.trend[0] ?? 0) ? '+' : '' }}{{ (storage.trend[6] ?? 0) - (storage.trend[0] ?? 0) }}%
          </span>
        </div>

        <!-- 预计可使用天数 -->
        <div class="storage-estimate" v-if="storage.status !== 'normal'">
          <AlertTriangle :size="16" />
          <span>按当前增长速度，预计 {{ Math.ceil((storage.available / ((storage.used / 7) || 1)) * (storage.trend.length / 7)) }} 天后空间耗尽</span>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!storageList.length && !loading" class="empty-state">
        <HardDrive :size="48" />
        <p>暂无存储数据</p>
        <button class="btn-primary" @click="loadStorageData">加载数据</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.storage-page {
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
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.refresh-btn:hover {
  background: #552b9f;
}

.refresh-btn.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 统计卡片 */
.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}

@media (max-width: 1200px) {
  .summary-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .summary-cards {
    grid-template-columns: 1fr;
  }
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.summary-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.summary-primary .summary-icon { background: linear-gradient(135deg, #4CAF50, #673AB7); }
.summary-info .summary-icon { background: linear-gradient(135deg, #2196F3, #1976D2); }
.summary-success .summary-icon { background: linear-gradient(135deg, #4CAF50, #43A047); }
.summary-warning .summary-icon { background: linear-gradient(135deg, #FF9800, #F57C00); }
.summary-danger .summary-icon { background: linear-gradient(135deg, #F44336, #D32F2F); }

.summary-content {
  flex: 1;
}

.summary-label {
  font-size: 0.75rem;
  color: #64748b;
  margin-bottom: 0.25rem;
}

.summary-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1a1a2e;
}

/* 存储列表 */
.storage-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.storage-card {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: all 0.2s ease;
}

.storage-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.storage-card.storage-warning {
  border-color: #FF9800;
  background: linear-gradient(135deg, rgba(255, 152, 0, 0.03) 0%, rgba(255, 255, 255, 1) 50%);
}

.storage-card.storage-critical {
  border-color: #F44336;
  background: linear-gradient(135deg, rgba(244, 67, 54, 0.03) 0%, rgba(255, 255, 255, 1) 50%);
}

.storage-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.storage-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.storage-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.storage-name h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.storage-host {
  font-size: 0.8rem;
  color: #64748b;
}

.storage-path {
  font-size: 0.75rem;
  color: #94a3b8;
  font-family: monospace;
}

.storage-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  border-radius: 20px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status-normal {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.status-warning {
  background: rgba(255, 152, 0, 0.15);
  color: #FF9800;
}

.status-critical {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* 进度条 */
.storage-progress-section {
  margin-bottom: 1rem;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.progress-label {
  font-size: 0.8rem;
  color: #64748b;
}

.progress-value {
  font-size: 0.8rem;
  font-weight: 600;
  color: #1a1a2e;
}

.progress-bar {
  height: 8px;
  background: #f1f5f9;
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.progress-normal {
  background: linear-gradient(90deg, #4CAF50, #66BB6A);
}

.progress-warning {
  background: linear-gradient(90deg, #FF9800, #FFA726);
}

.progress-critical {
  background: linear-gradient(90deg, #F44336, #EF5350);
}

.storage-details {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #94a3b8;
}

/* 趋势图 */
.storage-trend {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem;
  background: #f8fafc;
  border-radius: 8px;
}

.trend-label {
  font-size: 0.75rem;
  color: #64748b;
}

.trend-chart {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 0.25rem;
  height: 32px;
}

.trend-bar {
  flex: 1;
  min-width: 8px;
  border-radius: 2px 2px 0 0;
  transition: height 0.3s ease;
}

.trend-prediction {
  font-size: 0.75rem;
  font-weight: 600;
}

.trend-prediction[title*="+"] {
  color: #F44336;
}

.trend-prediction:not([title*="+"]) {
  color: #4CAF50;
}

/* 预计提示 */
.storage-estimate {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: rgba(255, 152, 0, 0.1);
  border-radius: 8px;
  font-size: 0.8rem;
  color: #F57C00;
}

.storage-card.storage-critical .storage-estimate {
  background: rgba(244, 67, 54, 0.1);
  color: #D32F2F;
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

.btn-primary {
  margin-top: 1rem;
  padding: 0.625rem 1.25rem;
  background: #673AB7;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 0.2s ease;
}

.btn-primary:hover {
  background: #552b9f;
}
</style>
