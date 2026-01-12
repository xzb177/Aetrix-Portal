<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'

interface Props {
  label: string
  value: string | number
  icon?: Component
  color?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  trend?: string
  trendUp?: boolean
  clickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  color: 'primary',
  clickable: false,
})

const emit = defineEmits<{
  (e: 'click'): void
}>()

const classes = computed(() => [
  'stat-card',
  `stat-card-${props.color}`,
  { 'stat-card-clickable': props.clickable },
])

const iconContainerClass = computed(() => `stat-icon stat-icon-${props.color}`)
</script>

<template>
  <div :class="classes" @click="clickable ? emit('click') : null">
    <div :class="iconContainerClass">
      <component v-if="icon" :is="icon" :size="20" />
      <slot v-else name="icon" />
    </div>
    <div class="stat-content">
      <div class="stat-value">{{ value }}</div>
      <div class="stat-label">{{ label }}</div>
    </div>
    <div v-if="trend" class="stat-trend" :class="{ 'trend-up': trendUp }">
      {{ trend }}
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast) ease;
}

.stat-card-clickable {
  cursor: pointer;
}

.stat-card-clickable:active {
  background: var(--bg-card-hover);
  border-color: var(--border-default);
  transform: scale(0.98);
}

.stat-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

.stat-icon-primary {
  background: var(--primary-bg);
  color: var(--primary);
}

.stat-icon-success {
  background: var(--success-bg);
  color: var(--success);
}

.stat-icon-warning {
  background: var(--warning-bg);
  color: var(--warning);
}

.stat-icon-danger {
  background: var(--danger-bg);
  color: var(--danger);
}

.stat-icon-info {
  background: var(--info-bg);
  color: var(--info);
}

.stat-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.stat-value {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  line-height: var(--line-height-tight);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-label {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  line-height: var(--line-height-normal);
}

.stat-trend {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.trend-up {
  color: var(--success);
}
</style>
