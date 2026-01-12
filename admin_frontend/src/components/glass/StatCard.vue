<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'

interface Props {
  value: string | number
  label: string
  icon?: Component
  iconColor?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  trend?: string
  trendUp?: boolean
  suffix?: string
  prefix?: string
  clickable?: boolean
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  iconColor: 'primary',
  trendUp: true,
  clickable: false,
  loading: false,
})

const emit = defineEmits<{
  click: []
}>()

const iconColorClass = computed(() => {
  const colorMap = {
    primary: 'bg-primary/10 text-primary',
    success: 'bg-success-bg text-success',
    warning: 'bg-warning-bg text-warning',
    danger: 'bg-danger-bg text-danger',
    info: 'bg-info-bg text-info',
  }
  return colorMap[props.iconColor]
})

const trendColorClass = computed(() => {
  return props.trendUp ? 'text-success' : 'text-danger'
})

function handleClick() {
  if (props.clickable) {
    emit('click')
  }
}
</script>

<template>
  <div
    class="stat-card-base"
    :class="clickable ? 'cursor-pointer active:scale-[0.99]' : ''"
    @click="handleClick"
  >
    <!-- 左侧图标 -->
    <div v-if="icon && !loading" class="stat-icon" :class="iconColorClass">
      <component :is="icon" :size="24" />
    </div>

    <!-- 加载中骨架 -->
    <div v-else-if="loading" class="stat-icon stat-icon-loading" />

    <!-- 主内容区 -->
    <div class="stat-content">
      <!-- 数值 -->
      <p v-if="loading" class="stat-value stat-value-loading">
        <span class="skeleton-pulse"></span>
      </p>
      <p v-else class="stat-value">
        <span v-if="prefix" class="stat-prefix">{{ prefix }}</span>
        <span>{{ value }}</span>
        <span v-if="suffix" class="stat-suffix">{{ suffix }}</span>
      </p>

      <!-- 标签 -->
      <p class="stat-label">{{ label }}</p>

      <!-- 趋势 -->
      <div v-if="trend && !loading" class="stat-trend" :class="trendColorClass">
        <svg
          class="w-3 h-3"
          :class="trendUp ? '' : 'rotate-180'"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M5 15l7-7 7 7"
          />
        </svg>
        <span>{{ trend }}</span>
      </div>
    </div>

    <!-- 底部插槽 -->
    <div v-if="$slots.footer" class="stat-footer">
      <slot name="footer" />
    </div>

    <!-- 右箭头（可点击时显示） -->
    <div v-if="clickable" class="stat-arrow">
      <svg class="w-4 h-4 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
      </svg>
    </div>
  </div>
</template>

<style scoped>
.stat-card-base {
  display: flex;
  align-items: center;
  gap: 1rem;
  min-height: 120px;
  padding: 1rem;
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
  transition: all 250ms ease;
}

.stat-card-base:hover {
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon-loading {
  background: rgba(255, 255, 255, 0.05);
}

.stat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
}

.stat-prefix,
.stat-suffix {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-secondary);
}

.stat-value-loading {
  height: 32px;
  display: flex;
  align-items: center;
}

.stat-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-tertiary);
}

.stat-trend {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 12px;
  font-weight: 600;
  margin-top: 0.25rem;
}

.stat-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 0.5rem;
}

.stat-arrow {
  opacity: 0;
  transition: opacity 250ms ease;
}

.stat-card-base:hover .stat-arrow {
  opacity: 1;
}

/* 骨架屏动画 */
.skeleton-pulse {
  display: inline-block;
  width: 80px;
  height: 28px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
</style>
