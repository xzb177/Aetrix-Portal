<script setup lang="ts">
import { computed } from 'vue'

export interface TabItem {
  id: string
  label: string
  icon?: any
  badge?: string | number
  disabled?: boolean
}

interface Props {
  items: TabItem[]
  modelValue: string
  type?: 'line' | 'pills'
}

const props = withDefaults(defineProps<Props>(), {
  type: 'line',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', value: string): void
}>()

const classes = computed(() => [
  'tabs',
  `tabs-${props.type}`,
])

const activeId = computed(() => props.modelValue)

const handleTabClick = (item: TabItem) => {
  if (item.disabled) return
  emit('update:modelValue', item.id)
  emit('change', item.id)
}
</script>

<template>
  <div :class="classes">
    <div
      v-for="item in items"
      :key="item.id"
      :class="['tab-item', {
        'tab-active': activeId === item.id,
        'tab-disabled': item.disabled,
      }]"
      @click="handleTabClick(item)"
    >
      <component v-if="item.icon" :is="item.icon" :size="16" />
      <span class="tab-label">{{ item.label }}</span>
      <span v-if="item.badge" class="tab-badge">{{ item.badge }}</span>
    </div>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  align-items: center;
}

/* Line type */
.tabs-line {
  gap: var(--space-1);
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--border-subtle);
}

.tabs-line .tab-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
  position: relative;
}

.tabs-line .tab-item:active:not(.tab-disabled) {
  background: var(--bg-card-hover);
}

.tabs-line .tab-active {
  color: var(--text-primary);
}

.tabs-line .tab-active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--primary);
  border-radius: 2px 2px 0 0;
}

/* Pills type */
.tabs-pills {
  gap: var(--space-1);
  padding: var(--space-1);
  background: var(--bg-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
}

.tabs-pills .tab-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.tabs-pills .tab-item:active:not(.tab-disabled) {
  transform: scale(0.97);
}

.tabs-pills .tab-active {
  background: var(--bg-card);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
}

/* Common styles */
.tab-label {
  white-space: nowrap;
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  background: var(--danger);
  color: white;
  border-radius: 9px;
}

.tab-disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}
</style>
