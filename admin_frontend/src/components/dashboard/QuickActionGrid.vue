<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'

export interface QuickActionItem {
  id: string
  label: string
  icon: Component
  color: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  route: string
  disabled?: boolean
}

interface Props {
  actions: QuickActionItem[]
  columns?: 2 | 3 | 4
}

const props = withDefaults(defineProps<Props>(), {
  columns: 2,
})

const emit = defineEmits<{
  click: [action: QuickActionItem]
}>()

const gridClass = computed(() => {
  return `grid-cols-${props.columns}`
})

const colorClass = (color: string) => {
  const map: Record<string, string> = {
    primary: 'action-primary',
    success: 'action-success',
    warning: 'action-warning',
    danger: 'action-danger',
    info: 'action-info',
  }
  return map[color] || 'action-primary'
}

function handleClick(action: QuickActionItem) {
  if (!action.disabled) {
    emit('click', action)
  }
}
</script>

<template>
  <div class="quick-action-grid" :class="gridClass">
    <div
      v-for="action in actions"
      :key="action.id"
      class="quick-action-item"
      :class="[colorClass(action.color), { 'action-disabled': action.disabled }]"
      @click="handleClick(action)"
    >
      <div class="action-icon">
        <component :is="action.icon" :size="20" />
      </div>
      <span class="action-label">{{ action.label }}</span>
    </div>
  </div>
</template>

<style scoped>
.quick-action-grid {
  display: grid;
  gap: 12px;
}

.grid-cols-2 {
  grid-template-columns: repeat(2, 1fr);
}

.grid-cols-3 {
  grid-template-columns: repeat(3, 1fr);
}

.grid-cols-4 {
  grid-template-columns: repeat(4, 1fr);
}

.quick-action-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 80px;
  padding: 16px;
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  cursor: pointer;
  transition: all 150ms ease;
}

.quick-action-item:active:not(.action-disabled) {
  transform: scale(0.98);
  background: rgba(255, 255, 255, 0.05);
}

.quick-action-item.action-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: white;
}

/* 颜色变体 */
.action-primary .action-icon {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
}

.action-success .action-icon {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.action-warning .action-icon {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.action-danger .action-icon {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
}

.action-info .action-icon {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
}

.action-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

/* 响应式 */
@media (max-width: 480px) {
  .grid-cols-3,
  .grid-cols-4 {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
