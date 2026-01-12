<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'

interface Props {
  label: string
  icon: Component
  color?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  color: 'primary',
  size: 'md',
  loading: false,
})

const emit = defineEmits<{
  click: []
}>()

const colorClass = computed(() => {
  const colorMap = {
    primary: 'quick-action-primary',
    success: 'quick-action-success',
    warning: 'quick-action-warning',
    danger: 'quick-action-danger',
    info: 'quick-action-info',
  }
  return colorMap[props.color]
})

const sizeClass = computed(() => {
  const sizeMap = {
    sm: 'min-h-[70px] p-3',
    md: 'min-h-[80px] p-4',
    lg: 'min-h-[90px] p-5',
  }
  return sizeMap[props.size]
})

function handleClick() {
  if (!props.loading) {
    emit('click')
  }
}
</script>

<template>
  <button
    class="quick-action"
    :class="[colorClass, sizeClass, { 'quick-action-loading': loading }]"
    :disabled="loading"
    @click="handleClick"
  >
    <!-- 图标 -->
    <div class="quick-action-icon">
      <component :is="icon" :size="24" />
    </div>

    <!-- 标签 -->
    <span class="quick-action-label">{{ label }}</span>

    <!-- 加载中遮罩 -->
    <div v-if="loading" class="quick-action-overlay">
      <svg class="quick-action-spinner" fill="none" viewBox="0 0 24 24">
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          stroke-width="3"
          stroke-linecap="round"
          class="opacity-25"
        />
        <path
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          class="opacity-75"
        />
      </svg>
    </div>
  </button>
</template>

<style scoped>
.quick-action {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  cursor: pointer;
  transition: all 250ms ease;
  overflow: hidden;
}

.quick-action:active:not(:disabled) {
  transform: scale(0.97);
  border-color: rgba(255, 255, 255, 0.15);
}

.quick-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.quick-action-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 250ms ease;
}

/* 颜色变体 */
.quick-action-primary .quick-action-icon {
  background: rgba(99, 102, 241, 0.15);
  color: var(--primary);
}

.quick-action-success .quick-action-icon {
  background: var(--success-bg);
  color: var(--success);
}

.quick-action-warning .quick-action-icon {
  background: var(--warning-bg);
  color: var(--warning);
}

.quick-action-danger .quick-action-icon {
  background: var(--danger-bg);
  color: var(--danger);
}

.quick-action-info .quick-action-icon {
  background: var(--info-bg);
  color: var(--info);
}

.quick-action-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

/* 加载状态 */
.quick-action-overlay {
  position: absolute;
  inset: 0;
  background: rgba(20, 21, 26, 0.8);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.quick-action-spinner {
  width: 24px;
  height: 24px;
  color: var(--primary);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
