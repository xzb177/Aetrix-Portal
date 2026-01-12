<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'
import { ChevronRight } from 'lucide-vue-next'

interface Props {
  title: string
  subtitle?: string
  icon?: Component
  color?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  showArrow?: boolean
  clickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  color: 'primary',
  showArrow: true,
  clickable: true,
})

const emit = defineEmits<{
  (e: 'click'): void
}>()

const classes = computed(() => [
  'action-card',
  `action-card-${props.color}`,
  { 'action-card-clickable': props.clickable },
])

const iconBgClass = computed(() => `action-icon-bg action-icon-bg-${props.color}`)
const iconColorClass = computed(() => `action-icon-${props.color}`)
</script>

<template>
  <div :class="classes" @click="clickable ? emit('click') : null">
    <div v-if="icon || $slots.icon" :class="iconBgClass">
      <slot name="icon">
        <component :is="icon" :size="20" :class="iconColorClass" />
      </slot>
    </div>
    <div class="action-content">
      <div class="action-title">{{ title }}</div>
      <div v-if="subtitle" class="action-subtitle">{{ subtitle }}</div>
    </div>
    <ChevronRight v-if="showArrow" :size="18" class="action-arrow" />
  </div>
</template>

<style scoped>
.action-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast) ease;
}

.action-card-clickable {
  cursor: pointer;
}

.action-card-clickable:active {
  background: var(--bg-card-hover);
  border-color: var(--border-default);
  transform: scale(0.98);
}

.action-icon-bg {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

.action-icon-bg-primary {
  background: var(--primary-bg);
}

.action-icon-bg-success {
  background: var(--success-bg);
}

.action-icon-bg-warning {
  background: var(--warning-bg);
}

.action-icon-bg-danger {
  background: var(--danger-bg);
}

.action-icon-bg-info {
  background: var(--info-bg);
}

.action-icon-primary {
  color: var(--primary);
}

.action-icon-success {
  color: var(--success);
}

.action-icon-warning {
  color: var(--warning);
}

.action-icon-danger {
  color: var(--danger);
}

.action-icon-info {
  color: var(--info);
}

.action-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.action-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.action-subtitle {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.action-arrow {
  flex-shrink: 0;
  color: var(--text-tertiary);
}
</style>
