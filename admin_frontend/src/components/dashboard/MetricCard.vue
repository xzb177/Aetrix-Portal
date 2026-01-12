<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, TrendingUp, TrendingDown } from 'lucide-vue-next'
import type { Component } from 'vue'

export interface MetricItem {
  id: string
  label: string
  value: string | number
  icon?: Component
  color: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  route?: string
  suffix?: string
  prefix?: string
  trend?: {
    value: string
    up?: boolean  // undefined = 无方向, true = 上升绿, false = 下降红
  }
  subtitle?: string  // 副标题（如"本月 ¥12,345"）
}

interface Props {
  item: MetricItem
}

const props = defineProps<Props>()

const emit = defineEmits<{
  click: [item: MetricItem]
}>()

const colorClass = computed(() => {
  const map = {
    primary: 'metric-primary',
    success: 'metric-success',
    warning: 'metric-warning',
    danger: 'metric-danger',
    info: 'metric-info',
  }
  return map[props.item.color]
})

const hasClickableRoute = computed(() => !!props.item.route)

function handleClick() {
  if (hasClickableRoute.value) {
    emit('click', props.item)
  }
}
</script>

<template>
  <div
    class="metric-card"
    :class="[colorClass, { 'metric-clickable': hasClickableRoute }]"
    @click="handleClick"
  >
    <!-- 左侧图标 -->
    <div v-if="item.icon" class="metric-icon">
      <component :is="item.icon" :size="20" />
    </div>

    <!-- 主内容 -->
    <div class="metric-content">
      <div class="metric-value">
        <span v-if="item.prefix" class="metric-prefix">{{ item.prefix }}</span>
        <span>{{ item.value }}</span>
        <span v-if="item.suffix" class="metric-suffix">{{ item.suffix }}</span>
      </div>
      <div class="metric-label">{{ item.label }}</div>
    </div>

    <!-- 右侧信息区 -->
    <div class="metric-right">
      <!-- 趋势指示 -->
      <div v-if="item.trend" class="metric-trend" :class="item.trend.up ? 'trend-up' : item.trend.up === false ? 'trend-down' : 'trend-neutral'">
        <TrendingUp v-if="item.trend.up === true" :size="12" />
        <TrendingDown v-else-if="item.trend.up === false" :size="12" />
        <span>{{ item.trend.value }}</span>
      </div>

      <!-- 副标题 -->
      <div v-else-if="item.subtitle" class="metric-subtitle">
        {{ item.subtitle }}
      </div>

      <!-- 跳转箭头 -->
      <ChevronRight v-if="hasClickableRoute" :size="14" class="metric-arrow" />
    </div>
  </div>
</template>

<style scoped>
.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 100px;
  padding: 16px;
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  transition: all 150ms ease;
}

.metric-card.metric-clickable {
  cursor: pointer;
}

.metric-card.metric-clickable:active {
  transform: scale(0.98);
  background: rgba(255, 255, 255, 0.05);
}

.metric-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* 颜色变体 */
.metric-primary .metric-icon {
  background: rgba(99, 102, 241, 0.15);
  color: #6366f1;
}

.metric-success .metric-icon {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.metric-warning .metric-icon {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.metric-danger .metric-icon {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.metric-info .metric-icon {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.metric-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.metric-prefix,
.metric-suffix {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.metric-label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.metric-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
}

.metric-trend {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 6px;
  border-radius: 6px;
}

.metric-trend.trend-up {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.metric-trend.trend-down {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.metric-trend.trend-neutral {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-tertiary);
}

.metric-subtitle {
  font-size: 11px;
  color: var(--text-tertiary);
  text-align: right;
}

.metric-arrow {
  color: var(--text-tertiary);
  opacity: 0.5;
  transition: opacity 150ms ease;
}

.metric-card.metric-clickable:hover .metric-arrow {
  opacity: 1;
}
</style>
