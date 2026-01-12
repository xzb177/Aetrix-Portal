<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  title: string
  actionLabel?: string
  showArrow?: boolean
  size?: 'sm' | 'md' | 'lg'
  badge?: string | number
  badgeType?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
}

const props = withDefaults(defineProps<Props>(), {
  showArrow: false,
  size: 'md',
  badgeType: 'primary',
})

const emit = defineEmits<{
  action: []
}>()

const titleClass = computed(() => {
  const sizeMap = {
    sm: 'text-sm',
    md: 'text-base',
    lg: 'text-lg',
  }
  return sizeMap[props.size]
})

const badgeClass = computed(() => {
  const typeMap = {
    primary: 'bg-primary text-white',
    success: 'bg-success-bg text-success',
    warning: 'bg-warning-bg text-warning',
    danger: 'bg-danger-bg text-danger',
    info: 'bg-info-bg text-info',
  }
  return typeMap[props.badgeType]
})

function handleAction() {
  emit('action')
}
</script>

<template>
  <div class="section-header">
    <h3 class="section-title" :class="titleClass">{{ title }}</h3>

    <div class="section-right">
      <!-- 徽章 -->
      <span v-if="badge !== undefined" class="section-badge" :class="badgeClass">
        {{ badge }}
      </span>

      <!-- 右侧动作按钮 -->
      <button
        v-if="actionLabel"
        class="section-action"
        @click="handleAction"
      >
        <span>{{ actionLabel }}</span>
        <svg
          v-if="showArrow"
          class="w-4 h-4 transition-transform"
          :class="{ 'translate-x-0.5': true }"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      <!-- 默认插槽（自定义右侧内容） -->
      <slot name="right" />
    </div>
  </div>
</template>

<style scoped>
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  min-height: 44px;
}

.section-title {
  font-weight: 600;
  color: var(--text-primary);
}

.section-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.section-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 24px;
  padding: 0 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.section-action {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.375rem 0.625rem;
  font-size: 13px;
  font-weight: 500;
  color: var(--primary);
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 150ms ease;
}

.section-action:active {
  opacity: 0.7;
  transform: scale(0.97);
}
</style>
