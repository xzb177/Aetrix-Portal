<script setup lang="ts">
import { computed } from 'vue'
import { RefreshCw, Calendar } from 'lucide-vue-next'

interface DateRange {
  start: Date
  end: Date
}

interface Props {
  dateRange?: DateRange
  lastUpdate?: Date
  refreshing?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  dateRange: () => ({
    start: new Date(),
    end: new Date(),
  }),
  lastUpdate: () => new Date(),
  refreshing: false,
})

const emit = defineEmits<{
  refresh: []
  dateChange: [dateRange: DateRange]
}>()

// 格式化日期显示
const formatDate = (date: Date): string => {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const dateRangeText = computed(() => {
  const start = formatDate(props.dateRange.start)
  const end = formatDate(props.dateRange.end)
  return start === end ? start : `${start} ~ ${end}`
})

// 计算更新时间距离现在的文字
const timeAgo = computed(() => {
  const now = new Date()
  const diff = Math.floor((now.getTime() - props.lastUpdate.getTime()) / 1000)

  if (diff < 60) return '刚刚更新'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前更新`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前更新`
  return formatDate(props.lastUpdate)
})

function handleRefresh() {
  emit('refresh')
}

function handleDateClick() {
  // 简化版：今天/本日切换，实际可扩展为日期选择器
  const now = new Date()
  emit('dateChange', { start: now, end: now })
}
</script>

<template>
  <div class="dashboard-header">
    <div class="header-left">
      <h1 class="page-title">控制台</h1>
      <button class="date-picker" @click="handleDateClick">
        <Calendar :size="14" />
        <span>{{ dateRangeText }}</span>
      </button>
    </div>
    <div class="header-right">
      <span class="update-time">{{ timeAgo }}</span>
      <button
        class="refresh-btn"
        :class="{ 'refreshing': refreshing }"
        @click="handleRefresh"
      >
        <RefreshCw :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding: 4px 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.date-picker {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-surface);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 150ms ease;
}

.date-picker:active {
  background: var(--bg-card-hover);
  transform: scale(0.97);
}

.date-picker svg {
  color: var(--text-tertiary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.update-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.refresh-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 150ms ease;
}

.refresh-btn:active {
  background: var(--bg-card-hover);
  transform: scale(0.95);
}

.refresh-btn.refreshing svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 响应式 */
@media (max-width: 480px) {
  .dashboard-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .header-right {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
