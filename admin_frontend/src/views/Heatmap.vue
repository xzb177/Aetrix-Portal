<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Flame, Calendar, RefreshCw, TrendingUp } from 'lucide-vue-next'
import { getPlaybackHeatmap } from '@/api/stats'

interface HeatmapData {
  hourly: { hour: number; count: number; label: string }[]
  weekly: { day: string; hours: number[] }[]
  total_plays: number
  peak_hour: string
  peak_count: number
}

const period = ref<'day' | 'week'>('week')
const loading = ref(false)
const heatmapData = ref<HeatmapData | null>(null)

// 初始化空数据结构
const hourlyData = ref<{ hour: number; count: number; label: string }[]>(
  Array.from({ length: 24 }, (_, i) => ({ hour: i, count: 0, label: `${i.toString().padStart(2, '0')}:00` }))
)

const weeklyData = ref<{ day: string; hours: number[] }[]>(
  ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map(day => ({ day, hours: Array(24).fill(0) }))
)

const maxValue = computed(() => {
  if (period.value === 'day') {
    return Math.max(...hourlyData.value.map(d => d.count), 1)
  } else {
    return Math.max(...weeklyData.value.flatMap(d => d.hours), 1)
  }
})

const peakHours = computed(() => {
  const sorted = [...hourlyData.value].sort((a, b) => b.count - a.count)
  return sorted.slice(0, 3)
})

const totalPlays = computed(() => {
  return heatmapData.value?.total_plays || hourlyData.value.reduce((sum, d) => sum + d.count, 0)
})

const getHeatColor = (value: number) => {
  const ratio = value / maxValue.value
  if (ratio > 0.8) return { background: 'rgba(239, 68, 68, 0.9)', color: 'var(--bg-card)' }
  if (ratio > 0.6) return { background: 'rgba(249, 115, 22, 0.9)', color: 'var(--bg-card)' }
  if (ratio > 0.4) return { background: 'rgba(234, 179, 8, 0.9)', color: 'var(--bg-card)' }
  if (ratio > 0.2) return { background: 'rgba(34, 197, 94, 0.9)', color: 'var(--bg-card)' }
  return { background: 'var(--bg-elevated)', color: 'var(--text-tertiary)' }
}

const loadHeatmapData = async () => {
  loading.value = true
  try {
    const response = await getPlaybackHeatmap(30) as any
    heatmapData.value = response

    if (response.hourly) {
      hourlyData.value = Array.from({ length: 24 }, (_, i) => ({
        hour: i,
        count: response.hourly[i] || 0,
        label: `${i.toString().padStart(2, '0')}:00`
      }))
    }

    if (response.weekly) {
      const dayOrder = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
      weeklyData.value = dayOrder.map((day, idx) => ({
        day,
        hours: response.weekly[idx] || Array(24).fill(0)
      }))
    }
  } catch (error) {
    console.error('加载热力图数据失败:', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadHeatmapData()
})
</script>

<template>
  <div class="heatmap-page">
    <!-- 操作栏 -->
    <div class="page-actions">
      <div class="period-selector">
        <button
          :class="['period-btn', { active: period === 'day' }]"
          @click="period = 'day'"
        >
          <Calendar :size="16" />
          24小时
        </button>
        <button
          :class="['period-btn', { active: period === 'week' }]"
          @click="period = 'week'"
        >
          <Calendar :size="16" />
          7天
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-cards">
      <div class="stat-card stat-primary">
        <div class="stat-icon">
          <Flame :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ totalPlays.toLocaleString() }}</p>
          <p class="stat-label">今日播放次数</p>
        </div>
      </div>

      <div class="stat-card stat-success">
        <div class="stat-icon">
          <TrendingUp :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ peakHours[0]?.label || '--:--' }}</p>
          <p class="stat-label">最高峰时段</p>
        </div>
      </div>

      <div class="stat-card stat-warning">
        <div class="stat-icon">
          <Calendar :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">02:00 - 06:00</p>
          <p class="stat-label">建议维护时段</p>
        </div>
      </div>

      <div class="stat-card stat-info">
        <div class="stat-icon">
          <Flame :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ peakHours[0]?.count || 0 }}</p>
          <p class="stat-label">峰值播放数/小时</p>
        </div>
      </div>
    </div>

    <!-- 24小时热力图 -->
    <div v-if="period === 'day'" class="heatmap-section">
      <h2 class="section-title">24小时播放分布</h2>
      <div class="hourly-heatmap">
        <div class="hour-labels-start">
          <span class="hour-label">00:00</span>
          <span class="hour-label">06:00</span>
          <span class="hour-label">12:00</span>
          <span class="hour-label">18:00</span>
        </div>
        <div class="heatmap-grid">
          <div
            v-for="item in hourlyData"
            :key="item.hour"
            class="heatmap-cell"
            :style="getHeatColor(item.count)"
            :title="`${item.label}: ${item.count} 次播放`"
          >
            <span class="cell-value">{{ item.count }}</span>
            <span class="cell-label">{{ item.label }}</span>
          </div>
        </div>
      </div>

      <!-- 峰值时段分析 -->
      <div class="peak-analysis">
        <h3 class="analysis-title">峰值时段分析</h3>
        <div class="peak-list">
          <div v-for="(peak, index) in peakHours" :key="peak.hour" class="peak-item" :class="`peak-${index + 1}`">
            <span class="peak-rank">#{{ index + 1 }}</span>
            <span class="peak-time">{{ peak.label }}</span>
            <div class="peak-bar">
              <div class="peak-fill" :style="{ width: `${(peak.count / (peakHours[0]?.count || 1)) * 100}%` }"></div>
            </div>
            <span class="peak-count">{{ peak.count }} 次</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 7天热力图 -->
    <div v-if="period === 'week'" class="heatmap-section">
      <h2 class="section-title">7天 x 24小时 热力图</h2>
      <p class="section-desc">横轴为小时，纵轴为星期</p>
      <div class="weekly-heatmap">
        <div class="day-labels">
          <span v-for="day in weeklyData" :key="day.day" class="day-label">{{ day.day }}</span>
        </div>
        <div class="weekly-grid">
          <div
            v-for="(dayData, dayIndex) in weeklyData"
            :key="dayIndex"
            class="weekly-row"
          >
            <div
              v-for="(hourValue, hourIndex) in dayData.hours"
              :key="hourIndex"
              class="weekly-cell"
              :style="getHeatColor(hourValue)"
              :title="`${dayData.day} ${hourIndex}:00 - ${hourValue} 次播放`"
            >
              <span class="weekly-value">{{ hourValue }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 小时标签 -->
      <div class="hour-labels-bottom">
        <span v-for="i in 24" :key="i" class="hour-label-tiny">{{ i - 1 }}</span>
      </div>
    </div>

    <!-- 维护建议 -->
    <div class="maintenance-suggestions">
      <h3 class="suggestions-title">维护时间建议</h3>
      <div class="suggestions-grid">
        <div class="suggestion-card suggestion-best">
          <div class="suggestion-icon">最佳</div>
          <div class="suggestion-content">
            <h4>凌晨 02:00 - 05:00</h4>
            <p>播放量最低，建议进行系统维护、数据库备份等操作</p>
          </div>
        </div>
        <div class="suggestion-card suggestion-good">
          <div class="suggestion-icon">良好</div>
          <div class="suggestion-content">
            <h4>工作日上午 09:00 - 11:00</h4>
            <p>播放量适中，可进行非紧急的优化操作</p>
          </div>
        </div>
        <div class="suggestion-card suggestion-avoid">
          <div class="suggestion-icon">避免</div>
          <div class="suggestion-content">
            <h4>晚上 19:00 - 22:00</h4>
            <p>高峰时段，不建议进行任何维护操作</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.heatmap-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 页面标题 */





.period-selector {
  display: flex;
  gap: 0.5rem;
  background: var(--bg-elevated);
  padding: 0.25rem;
  border-radius: 10px;
  border: 1px solid var(--border-base);
}

.period-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 0.875rem;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-base) ease;
}

.period-btn.active {
  background: var(--bg-card);
  color: var(--primary);
  box-shadow: var(--shadow-sm);
}

/* 统计卡片 */
.stats-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}

@media (max-width: 1200px) {
  .stats-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-base);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.stat-primary .stat-icon { background: linear-gradient(135deg, var(--primary), #7B1FA2); }
.stat-success .stat-icon { background: linear-gradient(135deg, var(--success), #059669); }
.stat-warning .stat-icon { background: linear-gradient(135deg, var(--warning), #ea580c); }
.stat-info .stat-icon { background: linear-gradient(135deg, var(--info), #1d4ed8); }

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-label {
  font-size: 0.75rem;
  color: var(--text-tertiary);
}

/* 热力图区域 */
.heatmap-section {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: 1.5rem;
  border: 1px solid var(--border-base);
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.5rem 0;
}

.section-desc {
  font-size: 0.875rem;
  color: var(--text-tertiary);
  margin: 0 0 1.5rem 0;
}

/* 24小时热力图 */
.hourly-heatmap {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 2rem;
}

.hour-labels-start {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 1rem 0;
}

.hour-label {
  font-size: 0.7rem;
  color: var(--text-tertiary);
}

.heatmap-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 4px;
}

.heatmap-cell {
  aspect-ratio: 1;
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform var(--transition-base) ease;
}

.heatmap-cell:hover {
  transform: scale(1.1);
  z-index: 1;
}

.cell-value {
  font-size: 0.7rem;
  font-weight: 600;
}

.cell-label {
  font-size: 0.6rem;
  opacity: 0.8;
}

/* 峰值分析 */
.peak-analysis {
  margin-top: 1.5rem;
  padding: 1.5rem;
  background: var(--bg-elevated);
  border-radius: var(--radius-lg);
}

.analysis-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 1rem 0;
}

.peak-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.peak-item {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.peak-rank {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--primary), var(--success));
  color: white;
}

.peak-item.peak-1 .peak-rank {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
}

.peak-item.peak-2 .peak-rank {
  background: linear-gradient(135deg, #94a3b8, #64748b);
}

.peak-item.peak-3 .peak-rank {
  background: linear-gradient(135deg, #b45309, #92400e);
}

.peak-time {
  width: 50px;
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.peak-bar {
  flex: 1;
  height: 8px;
  background: var(--bg-hover);
  border-radius: 4px;
  overflow: hidden;
}

.peak-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--success));
  border-radius: 4px;
  transition: width var(--transition-base) ease;
}

.peak-count {
  width: 60px;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--primary);
  text-align: right;
}

/* 7天热力图 */
.weekly-heatmap {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.day-labels {
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  padding: 1rem 0;
}

.day-label {
  font-size: 0.75rem;
  color: var(--text-tertiary);
  height: 20px;
  display: flex;
  align-items: center;
}

.weekly-grid {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.weekly-row {
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 4px;
}

.weekly-cell {
  aspect-ratio: 1;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform var(--transition-base) ease;
}

.weekly-cell:hover {
  transform: scale(1.2);
  z-index: 1;
}

.weekly-value {
  font-size: 0.65rem;
  font-weight: 600;
}

.hour-labels-bottom {
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 4px;
  padding-left: 50px;
}

.hour-label-tiny {
  font-size: 0.6rem;
  color: var(--text-tertiary);
  text-align: center;
}

/* 维护建议 */
.maintenance-suggestions {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: 1.5rem;
  border: 1px solid var(--border-base);
}

.suggestions-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 1rem 0;
}

.suggestions-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

@media (max-width: 768px) {
  .suggestions-grid {
    grid-template-columns: 1fr;
  }
}

.suggestion-card {
  display: flex;
  gap: 1rem;
  padding: 1.25rem;
  border-radius: var(--radius-lg);
  border-left: 4px solid;
}

.suggestion-best {
  background: var(--success-bg);
  border-left-color: var(--success);
}

.suggestion-good {
  background: var(--warning-bg);
  border-left-color: var(--warning);
}

.suggestion-avoid {
  background: var(--danger-bg);
  border-left-color: var(--danger);
}

.suggestion-icon {
  padding: 0.5rem;
  border-radius: var(--radius-md);
  font-size: 0.75rem;
  font-weight: 600;
  text-align: center;
  flex-shrink: 0;
}

.suggestion-best .suggestion-icon {
  background: var(--success);
  color: white;
}

.suggestion-good .suggestion-icon {
  background: var(--warning);
  color: white;
}

.suggestion-avoid .suggestion-icon {
  background: var(--danger);
  color: white;
}

.suggestion-content h4 {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.5rem 0;
}

.suggestion-content p {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin: 0;
}
</style>
