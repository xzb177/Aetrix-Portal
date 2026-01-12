<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Cpu, HardDrive, Activity, Server, RefreshCw, Cpu as MemoryIcon } from 'lucide-vue-next'

interface ServerResource {
  id: number
  name: string
  host: string
  cpu: number
  cpuCores: number
  memory: {
    used: number
    total: number
    percent: number
  }
  disk: {
    used: number
    total: number
    percent: number
  }
  uptime: string
  status: 'online' | 'offline'
}

const loading = ref(false)
const resources = ref<ServerResource[]>([])

const mockResources: ServerResource[] = [
  {
    id: 1,
    name: '主服务器',
    host: 'emby1.example.com',
    cpu: 45,
    cpuCores: 16,
    memory: { used: 24.5, total: 64, percent: 38 },
    disk: { used: 6.2, total: 8, percent: 77 },
    uptime: '15天 8小时',
    status: 'online',
  },
  {
    id: 2,
    name: '备份服务器',
    host: 'emby2.example.com',
    cpu: 23,
    cpuCores: 12,
    memory: { used: 15.2, total: 32, percent: 47 },
    disk: { used: 9.5, total: 12, percent: 79 },
    uptime: '22天 3小时',
    status: 'online',
  },
  {
    id: 3,
    name: '缓存服务器',
    host: 'cache.example.com',
    cpu: 78,
    cpuCores: 8,
    memory: { used: 6.8, total: 16, percent: 42 },
    disk: { used: 450, total: 512, percent: 88 },
    uptime: '5天 12小时',
    status: 'online',
  },
]

const loadData = async () => {
  loading.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 500))
    // 模拟数据变化
    resources.value = mockResources.map(r => ({
      ...r,
      cpu: Math.min(100, r.cpu + Math.floor(Math.random() * 10 - 5)),
    }))
  } finally {
    loading.value = false
  }
}

const getCpuClass = (cpu: number) => {
  if (cpu >= 80) return 'cpu-critical'
  if (cpu >= 60) return 'cpu-high'
  if (cpu >= 40) return 'cpu-medium'
  return 'cpu-normal'
}

const getMemoryClass = (percent: number) => {
  if (percent >= 85) return 'mem-critical'
  if (percent >= 70) return 'mem-high'
  return 'mem-normal'
}

const getDiskClass = (percent: number) => {
  if (percent >= 90) return 'disk-critical'
  if (percent >= 75) return 'disk-high'
  return 'disk-normal'
}

let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadData()
  refreshInterval = setInterval(loadData, 5000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="resource-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="refresh-btn" @click="loadData" :class="{ spinning: loading }">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
    </div>

    <!-- 总体概览 -->
    <div class="overview-cards">
      <div class="overview-card cpu">
        <div class="overview-icon"><Cpu :size="24" /></div>
        <div class="overview-content">
          <p class="overview-label">平均 CPU 使用</p>
          <p class="overview-value">{{ Math.round(resources.reduce((sum, r) => sum + r.cpu, 0) / resources.length) || 0 }}%</p>
        </div>
      </div>

      <div class="overview-card memory">
        <div class="overview-icon"><MemoryIcon :size="24" /></div>
        <div class="overview-content">
          <p class="overview-label">平均内存使用</p>
          <p class="overview-value">{{ Math.round(resources.reduce((sum, r) => sum + r.memory.percent, 0) / resources.length) || 0 }}%</p>
        </div>
      </div>

      <div class="overview-card disk">
        <div class="overview-icon"><HardDrive :size="24" /></div>
        <div class="overview-content">
          <p class="overview-label">平均磁盘使用</p>
          <p class="overview-value">{{ Math.round(resources.reduce((sum, r) => sum + r.disk.percent, 0) / resources.length) || 0 }}%</p>
        </div>
      </div>

      <div class="overview-card">
        <div class="overview-icon"><Server :size="24" /></div>
        <div class="overview-content">
          <p class="overview-label">在线服务器</p>
          <p class="overview-value">{{ resources.filter(r => r.status === 'online').length }}/{{ resources.length }}</p>
        </div>
      </div>
    </div>

    <!-- 服务器列表 -->
    <div class="servers-list">
      <div v-for="server in resources" :key="server.id" class="server-card" :class="{ offline: server.status === 'offline' }">
        <div class="server-header">
          <div class="server-info">
            <div class="server-name">
              <Server :size="18" />
              <h3>{{ server.name }}</h3>
            </div>
            <span class="server-host">{{ server.host }}</span>
          </div>
          <div class="server-status" :class="server.status">
            <span class="status-dot"></span>
            <span>{{ server.status === 'online' ? '在线' : '离线' }}</span>
          </div>
        </div>

        <div class="server-metrics">
          <!-- CPU -->
          <div class="metric">
            <div class="metric-header">
              <Cpu :size="16" />
              <span>CPU</span>
              <span class="metric-value" :class="getCpuClass(server.cpu)">{{ server.cpu }}%</span>
            </div>
            <div class="metric-bar">
              <div class="metric-fill" :class="getCpuClass(server.cpu)" :style="{ width: `${server.cpu}%` }"></div>
            </div>
            <span class="metric-detail">{{ server.cpuCores }} 核心</span>
          </div>

          <!-- 内存 -->
          <div class="metric">
            <div class="metric-header">
              <MemoryIcon :size="16" />
              <span>内存</span>
              <span class="metric-value" :class="getMemoryClass(server.memory.percent)">{{ server.memory.percent }}%</span>
            </div>
            <div class="metric-bar">
              <div class="metric-fill" :class="getMemoryClass(server.memory.percent)" :style="{ width: `${server.memory.percent}%` }"></div>
            </div>
            <span class="metric-detail">{{ server.memory.used }} GB / {{ server.memory.total }} GB</span>
          </div>

          <!-- 磁盘 -->
          <div class="metric">
            <div class="metric-header">
              <HardDrive :size="16" />
              <span>磁盘</span>
              <span class="metric-value" :class="getDiskClass(server.disk.percent)">{{ server.disk.percent }}%</span>
            </div>
            <div class="metric-bar">
              <div class="metric-fill" :class="getDiskClass(server.disk.percent)" :style="{ width: `${server.disk.percent}%` }"></div>
            </div>
            <span class="metric-detail">{{ server.disk.used }} TB / {{ server.disk.total }} TB</span>
          </div>
        </div>

        <div class="server-footer">
          <span class="uptime-label">运行时间</span>
          <span class="uptime-value">{{ server.uptime }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.resource-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}





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
  white-space: nowrap;
}

.refresh-btn.spinning svg { animation: spin 1s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

/* 概览卡片 */
.overview-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}

/* 移动端适配 */
@media (max-width: 1024px) {
  .overview-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {

.overview-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
}

.overview-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.overview-card.cpu .overview-icon { background: linear-gradient(135deg, #673AB7, #7B1FA2); }
.overview-card.memory .overview-icon { background: linear-gradient(135deg, #2196F3, #1976D2); }
.overview-card.disk .overview-icon { background: linear-gradient(135deg, #FF9800, #F57C00); }
.overview-card:not(.cpu):not(.memory):not(.disk) .overview-icon { background: linear-gradient(135deg, #4CAF50, #43A047); }

.overview-label {
  font-size: 0.75rem;
  color: #64748b;
}

.overview-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1a1a2e;
}

/* 服务器卡片 */
.servers-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.server-card {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
  transition: all 0.2s ease;
}

.server-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.server-card.offline {
  opacity: 0.6;
}

.server-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1.5rem;
}

.server-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.server-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.server-name h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.server-host {
  font-size: 0.8rem;
  color: #94a3b8;
}

.server-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
}

.server-status.online {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.server-status.offline {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.server-status.online .status-dot {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* 指标 */
.server-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
  margin-bottom: 1rem;
}

@media (max-width: 768px) {
  .server-metrics {
    grid-template-columns: 1fr;
    gap: 1rem;
  }
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.metric-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: #64748b;
}

.metric-value {
  margin-left: auto;
  font-weight: 600;
}

.cpu-normal, .mem-normal, .disk-normal { color: #4CAF50; }
.cpu-medium, .mem-high, .disk-high { color: #FF9800; }
.cpu-high, .mem-critical, .disk-critical { color: #F44336; }

.metric-bar {
  height: 6px;
  background: #f1f5f9;
  border-radius: 3px;
  overflow: hidden;
}

.metric-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.cpu-normal, .mem-normal, .disk-normal { background: #4CAF50; }
.cpu-medium { background: #FF9800; }
.cpu-high, .mem-high, .disk-high { background: #FF9800; }
.cpu-critical, .mem-critical, .disk-critical { background: #F44336; }

.metric-detail {
  font-size: 0.75rem;
  color: #94a3b8;
}

.server-footer {
  display: flex;
  justify-content: space-between;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
  font-size: 0.8rem;
}

.uptime-label {
  color: #94a3b8;
}

.uptime-value {
  color: #475569;
}
</style>
