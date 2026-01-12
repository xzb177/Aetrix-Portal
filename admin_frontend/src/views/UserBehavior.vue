<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { BarChart3, Clock, Eye, Monitor, Smartphone, Tv, RefreshCw } from 'lucide-vue-next'
import { getUserBehavior } from '@/api/stats'

interface BehaviorData {
  avg_watch_time: number
  avg_watch_time_daily: number
  peak_hour: string
  active_days: number
  device_stats: { device: string; count: number; percent: number }[]
  time_distribution: { period: string; hours: string; percent: number; count: number }[]
  weekly_pattern: { day: string; value: number }[]
  watch_depth: { label: string; percent: number }[]
}

const loading = ref(false)
const behaviorData = ref<BehaviorData | null>(null)

// 默认数据结构
const behaviorStats = computed(() => ({
  avgWatchTime: behaviorData.value?.avg_watch_time || 0,
  avgWatchTimeDaily: behaviorData.value?.avg_watch_time_daily || 0,
  peakHour: behaviorData.value?.peak_hour || '--:--',
  activeDays: behaviorData.value?.active_days || 0,
}))

const deviceStats = computed(() => {
  const stats = behaviorData.value?.device_stats || []
  const iconMap: Record<string, any> = {
    'TV': Tv,
    '手机': Smartphone,
    '平板': Monitor,
  }
  const colorMap: Record<string, string> = {
    'TV': 'var(--primary)',
    '手机': 'var(--success)',
    '平板': 'var(--warning)',
  }
  return stats.map(s => ({
    device: s.device,
    icon: iconMap[s.device] || Tv,
    count: s.count,
    percent: s.percent,
    color: colorMap[s.device] || 'var(--primary)'
  }))
})

const timeDistribution = computed(() => {
  return behaviorData.value?.time_distribution || [
    { period: '凌晨', hours: '0-6', percent: 0, count: 0 },
    { period: '上午', hours: '6-12', percent: 0, count: 0 },
    { period: '下午', hours: '12-18', percent: 0, count: 0 },
    { period: '晚上', hours: '18-24', percent: 0, count: 0 },
  ]
})

const weeklyPattern = computed(() => {
  return behaviorData.value?.weekly_pattern || [
    { day: '周一', value: 0 },
    { day: '周二', value: 0 },
    { day: '周三', value: 0 },
    { day: '周四', value: 0 },
    { day: '周五', value: 0 },
    { day: '周六', value: 0 },
    { day: '周日', value: 0 },
  ]
})

const watchDepth = computed(() => {
  return behaviorData.value?.watch_depth || [
    { label: '完整观看 (>90%)', percent: 0 },
    { label: '部分观看 (50-90%)', percent: 0 },
    { label: '浅层观看 (<50%)', percent: 0 },
  ]
})

const loadUserBehavior = async () => {
  loading.value = true
  try {
    const response = await getUserBehavior(7) as any
    behaviorData.value = response
  } catch (error) {
    console.error('加载用户行为数据失败:', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadUserBehavior()
})
</script>

<template>
  <div class="behavior-page page-container">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-info">
        <h2 class="header-title">用户行为分析</h2>
        <p class="header-desc">基于门户用户数据统计，了解用户观看习惯和偏好</p>
      </div>
      <button class="refresh-btn" @click="loadUserBehavior" :class="{ spinning: loading }" title="刷新数据">
        <RefreshCw :size="16" />
        <span>刷新</span>
      </button>
    </div>

    <!-- 核心指标 -->
    <div class="stats-grid">
      <div class="stat-card mobile-card">
        <div class="stat-icon stat-purple">
          <Clock :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ behaviorStats.avgWatchTime }}</p>
          <p class="stat-label">平均观看时长(分钟)</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-blue">
          <Eye :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ behaviorStats.avgWatchTimeDaily }}</p>
          <p class="stat-label">日均观看时长(小时)</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-green">
          <BarChart3 :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ behaviorStats.peakHour }}</p>
          <p class="stat-label">最高峰时段</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-orange">
          <Clock :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ behaviorStats.activeDays }}</p>
          <p class="stat-label">周活跃天数</p>
        </div>
      </div>
    </div>

    <!-- 设备分布 -->
    <div class="section-card mobile-card">
      <h3 class="section-title">设备分布</h3>
      <div class="device-list">
        <div v-for="device in deviceStats" :key="device.device" class="device-item">
          <div class="device-icon" :style="{ background: device.color }">
            <component :is="device.icon" :size="18" />
          </div>
          <div class="device-info">
            <span class="device-name">{{ device.device }}</span>
            <span class="device-count">{{ device.count.toLocaleString() }} 用户</span>
          </div>
          <div class="device-percent">{{ device.percent }}%</div>
          <div class="device-bar">
            <div class="device-fill" :style="{ width: `${device.percent}%`, background: device.color }"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 时段分布 -->
    <div class="section-card mobile-card">
      <h3 class="section-title">时段分布</h3>
      <div class="time-distribution">
        <div v-for="time in timeDistribution" :key="time.period" class="time-item">
          <div class="time-header">
            <span class="time-period">{{ time.period }}</span>
            <span class="time-hours">{{ time.hours }}</span>
            <span class="time-percent">{{ time.percent }}%</span>
          </div>
          <div class="time-bar">
            <div class="time-fill" :style="{ width: `${time.percent}%` }"></div>
          </div>
          <span class="time-count">{{ time.count.toLocaleString() }} 次观看</span>
        </div>
      </div>
    </div>

    <!-- 周模式 -->
    <div class="section-card mobile-card">
      <h3 class="section-title">周活跃模式</h3>
      <div class="weekly-pattern">
        <div class="pattern-chart">
          <div v-for="day in weeklyPattern" :key="day.day" class="pattern-bar-wrapper">
            <span class="pattern-value">{{ day.value }}</span>
            <div class="pattern-bar">
              <div class="pattern-fill" :style="{ height: `${day.value}%` }"></div>
            </div>
            <span class="pattern-label">{{ day.day }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 观看深度分析 -->
    <div class="section-card mobile-card">
      <h3 class="section-title">观看深度分析</h3>
      <div class="watch-depth">
        <div v-for="(depth, index) in watchDepth" :key="index" class="depth-item">
          <div class="depth-label">{{ depth.label }}</div>
          <div class="depth-bar">
            <div class="depth-fill"
              :class="index === 0 ? 'depth-high' : index === 1 ? 'depth-medium' : 'depth-low'"
              :style="{ width: `${depth.percent}%` }">
            </div>
          </div>
          <div class="depth-value">{{ depth.percent }}%</div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && !behaviorData" class="empty-state">
      <div class="empty-icon">📊</div>
      <p class="empty-text">暂无用户行为数据</p>
    </div>
  </div>
</template>

<style scoped>
.behavior-page {
  background: var(--bg-primary);
}

/* ===== 页面头部 ===== */
.page-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--space-4);
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--glass-gradient);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.refresh-btn:hover {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}

.refresh-btn.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ===== 统计卡片 ===== */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}

@media (min-width: 640px) {
  .stats-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.stat-purple {
  background: linear-gradient(135deg, #8B5CF6, #7C3AED);
}

.stat-blue {
  background: linear-gradient(135deg, #3B82F6, #2563EB);
}

.stat-green {
  background: linear-gradient(135deg, #22C55E, #16A34A);
}

.stat-orange {
  background: linear-gradient(135deg, #F59E0B, #D97706);
}

.stat-content {
  flex: 1;
  min-width: 0;
}

.stat-value {
  font-size: var(--font-size-4xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  margin: 0;
  line-height: 1;
}

.stat-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin: var(--space-1) 0 0 0;
}

/* ===== 区域卡片 ===== */
.section-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.section-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
}

/* ===== 设备列表 ===== */
.device-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.device-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  position: relative;
}

.device-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.device-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.device-name {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.device-count {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.device-percent {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  min-width: 40px;
  text-align: right;
}

.device-bar {
  position: absolute;
  bottom: -2px;
  left: 52px;
  right: 50px;
  height: 3px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 2px;
  overflow: hidden;
}

.device-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

/* ===== 时段分布 ===== */
.time-distribution {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.time-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.time-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.time-period {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.time-hours {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.time-percent {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--primary);
}

.time-bar {
  height: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  overflow: hidden;
}

.time-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--success));
  border-radius: 4px;
  transition: width 0.3s ease;
}

.time-count {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  text-align: right;
}

/* ===== 周模式 ===== */
.pattern-chart {
  display: flex;
  justify-content: space-around;
  align-items: flex-end;
  height: 160px;
  padding: var(--space-3) 0;
}

.pattern-bar-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  height: 100%;
  flex: 1;
}

.pattern-value {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--primary);
}

.pattern-bar {
  width: 28px;
  height: 100%;
  background: rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-sm);
  overflow: hidden;
  display: flex;
  align-items: flex-end;
}

.pattern-fill {
  width: 100%;
  background: linear-gradient(180deg, var(--success), var(--primary));
  border-radius: var(--radius-sm);
  transition: height 0.3s ease;
  min-height: 4px;
}

.pattern-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

/* ===== 观看深度 ===== */
.watch-depth {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.depth-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.depth-label {
  min-width: 120px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.depth-bar {
  flex: 1;
  height: 10px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.depth-fill {
  height: 100%;
  border-radius: var(--radius-sm);
  transition: width 0.3s ease;
}

.depth-high {
  background: linear-gradient(90deg, var(--success), #4ADE80);
}

.depth-medium {
  background: linear-gradient(90deg, var(--warning), #FBBF24);
}

.depth-low {
  background: linear-gradient(90deg, var(--text-tertiary), rgba(255, 255, 255, 0.1));
}

.depth-value {
  min-width: 45px;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  text-align: right;
}

/* ===== 空状态 ===== */
.empty-state {
  text-align: center;
  padding: var(--space-6) var(--space-4);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--space-3);
  opacity: 0.5;
}

.empty-text {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  margin: 0;
}

/* ===== 移动端适配 ===== */
@media (max-width: 480px) {
  .depth-item {
    flex-wrap: wrap;
  }

  .depth-label {
    min-width: auto;
    width: 100%;
  }

  .depth-value {
    min-width: auto;
  }

  .pattern-bar {
    width: 20px;
  }

  .device-item {
    flex-wrap: wrap;
  }

  .device-bar {
    display: none;
  }
}
</style>
