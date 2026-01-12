<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Activity, TrendingUp, RefreshCw, Zap } from 'lucide-vue-next'

const loading = ref(false)
const timeRange = ref<'hour' | 'day' | 'week'>('hour') as any

// 实时带宽数据
const currentBandwidth = ref({
  in: 125.8, // Mbps
  out: 1542.3,
  total: 1668.1,
})

// 历史数据
const bandwidthHistory = ref([
  { time: '14:00', in: 89, out: 1200, total: 1289 },
  { time: '14:15', in: 95, out: 1350, total: 1445 },
  { time: '14:30', in: 110, out: 1420, total: 1530 },
  { time: '14:45', in: 120, out: 1480, total: 1600 },
  { time: '15:00', in: 115, out: 1450, total: 1565 },
  { time: '15:15', in: 125, out: 1542, total: 1667 },
])

const maxValue = computed(() => {
  return Math.max(...bandwidthHistory.value.map(d => d.total))
})

const loadData = async () => {
  loading.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 500))
    // 模拟实时数据更新
    currentBandwidth.value = {
      in: 100 + Math.random() * 50,
      out: 1400 + Math.random() * 200,
      total: 1500 + Math.random() * 200,
    }
  } finally {
    loading.value = false
  }
}

let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadData()
  refreshInterval = setInterval(loadData, 5000) // 每5秒更新
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="bandwidth-page">
    <!-- 操作栏 -->
    <div class="page-actions">
      <div class="time-selector">
        <button v-for="range in ['hour', 'day', 'week']" :key="range"
          :class="['time-btn', { active: timeRange === range }]"
          @click="timeRange = range">
          {{ range === 'hour' ? '1小时' : range === 'day' ? '24小时' : '7天' }}
        </button>
      </div>
      <button class="refresh-btn" @click="loadData" :class="{ spinning: loading }">
        <RefreshCw :size="18" />
      </button>
    </div>

    <!-- 实时带宽卡片 -->
    <div class="bandwidth-cards">
      <div class="bandwidth-card bandwidth-main">
        <div class="card-header">
          <span class="card-label">当前总带宽</span>
          <Zap :size="20" class="live-indicator" />
        </div>
        <div class="bandwidth-value">
          {{ currentBandwidth.total.toFixed(1) }} <span class="unit">Mbps</span>
        </div>
        <div class="bandwidth-bar">
          <div class="bandwidth-fill" :style="{ width: `${(currentBandwidth.total / 2000) * 100}%` }"></div>
        </div>
      </div>

      <div class="bandwidth-card">
        <span class="card-label">入站带宽</span>
        <div class="bandwidth-value small">{{ currentBandwidth.in.toFixed(1) }} <span class="unit">Mbps</span></div>
      </div>

      <div class="bandwidth-card">
        <span class="card-label">出站带宽</span>
        <div class="bandwidth-value small">{{ currentBandwidth.out.toFixed(1) }} <span class="unit">Mbps</span></div>
      </div>

      <div class="bandwidth-card">
        <span class="card-label">峰值带宽</span>
        <div class="bandwidth-value small">{{ maxValue }} <span class="unit">Mbps</span></div>
      </div>
    </div>

    <!-- 带宽图表 -->
    <div class="chart-section">
      <h3 class="section-title">带宽趋势</h3>
      <div class="chart-container">
        <div class="chart-grid">
          <div class="chart-y-axis">
            <span>2000</span>
            <span>1500</span>
            <span>1000</span>
            <span>500</span>
            <span>0</span>
          </div>
          <div class="chart-area">
            <div class="chart-bars">
              <div v-for="(item, index) in bandwidthHistory" :key="index" class="chart-column">
                <div class="bar-group">
                  <div class="bar bar-out" :style="{ height: `${(item.out / maxValue) * 100}%` }"></div>
                  <div class="bar bar-in" :style="{ height: `${(item.in / maxValue) * 100}%` }"></div>
                </div>
                <span class="bar-label">{{ item.time }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="chart-legend">
          <div class="legend-item">
            <div class="legend-color legend-out"></div>
            <span>出站</span>
          </div>
          <div class="legend-item">
            <div class="legend-color legend-in"></div>
            <span>入站</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 带宽使用排行 -->
    <div class="top-streams">
      <h3 class="section-title">当前带宽占用 TOP 5</h3>
      <div class="streams-list">
        <div class="stream-item">
          <div class="stream-user">user_123456</div>
          <div class="stream-info">
            <span class="stream-title">流浪地球2 (4K)</span>
            <span class="stream-bandwidth">45.2 Mbps</span>
          </div>
          <div class="stream-bar">
            <div class="stream-fill" :style="{ width: '45%' }"></div>
          </div>
        </div>
        <div class="stream-item">
          <div class="stream-user">user_789012</div>
          <div class="stream-info">
            <span class="stream-title">三体 S01E03 (1080p)</span>
            <span class="stream-bandwidth">28.5 Mbps</span>
          </div>
          <div class="stream-bar">
            <div class="stream-fill" :style="{ width: '28%' }"></div>
          </div>
        </div>
        <div class="stream-item">
          <div class="stream-user">user_345678</div>
          <div class="stream-info">
            <span class="stream-title">满江红 (1080p)</span>
            <span class="stream-bandwidth">22.1 Mbps</span>
          </div>
          <div class="stream-bar">
            <div class="stream-fill" :style="{ width: '22%' }"></div>
          </div>
        </div>
        <div class="stream-item">
          <div class="stream-user">user_901234</div>
          <div class="stream-info">
            <span class="stream-title">狂飙 S01E05 (720p)</span>
            <span class="stream-bandwidth">15.8 Mbps</span>
          </div>
          <div class="stream-bar">
            <div class="stream-fill" :style="{ width: '16%' }"></div>
          </div>
        </div>
        <div class="stream-item">
          <div class="stream-user">user_567890</div>
          <div class="stream-info">
            <span class="stream-title">深海 (1080p)</span>
            <span class="stream-bandwidth">12.3 Mbps</span>
          </div>
          <div class="stream-bar">
            <div class="stream-fill" :style="{ width: '12%' }"></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bandwidth-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}






.time-selector {
  display: flex;
  gap: 0.25rem;
  background: #f1f5f9;
  padding: 0.25rem;
  border-radius: 8px;
}

.time-btn {
  padding: 0.375rem 0.75rem;
  border: none;
  background: transparent;
  border-radius: 6px;
  font-size: 0.8rem;
  color: #64748b;
  cursor: pointer;
  white-space: nowrap;
}

.time-btn.active {
  background: white;
  color: #673AB7;
}

.refresh-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: #673AB7;
  color: white;
  border-radius: 8px;
  cursor: pointer;
}

.refresh-btn.spinning svg { animation: spin 1s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

/* 带宽卡片 */
.bandwidth-cards {
  display: grid;
  grid-template-columns: 2fr repeat(3, 1fr);
  gap: 1rem;
}

/* 移动端适配 */
@media (max-width: 1024px) {
  .bandwidth-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .bandwidth-main {
    grid-column: span 2;
  }
}

@media (max-width: 768px) {

.bandwidth-card {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.bandwidth-main {
  background: linear-gradient(135deg, rgba(103, 58, 183, 0.05), rgba(76, 175, 80, 0.05));
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.card-label {
  font-size: 0.875rem;
  color: #64748b;
}

.live-indicator {
  color: #4CAF50;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.bandwidth-value {
  font-size: 2rem;
  font-weight: 700;
  color: #1a1a2e;
}

.bandwidth-value.small {
  font-size: 1.5rem;
}

.unit {
  font-size: 1rem;
  color: #94a3b8;
  font-weight: 400;
}

.bandwidth-bar {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 1rem;
}

.bandwidth-fill {
  height: 100%;
  background: linear-gradient(90deg, #4CAF50, #673AB7);
  border-radius: 4px;
  transition: width 0.3s ease;
}

/* 图表区域 */
.chart-section {
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

.chart-container {
  padding: 1rem 0;
}

.chart-grid {
  display: flex;
}

.chart-y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding-right: 1rem;
  height: 200px;
}

.chart-y-axis span {
  font-size: 0.7rem;
  color: #94a3b8;
}

.chart-area {
  flex: 1;
}

.chart-bars {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  height: 200px;
  gap: 0.5rem;
}

@media (max-width: 640px) {
  .chart-bars {
    gap: 0.25rem;
  }

  .bar {
    width: 8px;
  }

  .bar-label {
    font-size: 0.6rem;
  }
}

.chart-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}

.bar-group {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 2px;
}

.bar {
  width: 12px;
  border-radius: 3px 3px 0 0;
  transition: height 0.3s ease;
}

.bar-out {
  background: linear-gradient(180deg, #673AB7, #7B1FA2);
}

.bar-in {
  background: linear-gradient(180deg, #4CAF50, #43A047);
}

.bar-label {
  margin-top: 0.5rem;
  font-size: 0.7rem;
  color: #94a3b8;
}

.chart-legend {
  display: flex;
  justify-content: center;
  gap: 2rem;
  margin-top: 1rem;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: #64748b;
}

.legend-color {
  width: 12px;
  height: 12px;
  border-radius: 3px;
}

.legend-out { background: #673AB7; }
.legend-in { background: #4CAF50; }

/* TOP 流量 */
.top-streams {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.streams-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.stream-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem;
  background: #f8fafc;
  border-radius: 8px;
}

.stream-user {
  width: 100px;
  font-size: 0.8rem;
  color: #64748b;
  font-family: monospace;
}

.stream-info {
  flex: 1;
  display: flex;
  justify-content: space-between;
  margin-right: 1rem;
}

.stream-title {
  font-size: 0.875rem;
  color: #1a1a2e;
}

.stream-bandwidth {
  font-size: 0.8rem;
  font-weight: 600;
  color: #673AB7;
}

.stream-bar {
  width: 100px;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}

.stream-fill {
  height: 100%;
  background: linear-gradient(90deg, #673AB7, #4CAF50);
  border-radius: 3px;
}
</style>
