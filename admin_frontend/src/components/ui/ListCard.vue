<script setup lang="ts">
import { computed } from 'vue'

export interface ListCardItem {
  id: string | number
  label: string
  value?: string
  icon?: any
  action?: () => void
  clickable?: boolean
}

interface Props {
  title?: string
  items: ListCardItem[]
  divider?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  divider: true,
})

const emit = defineEmits<{
  (e: 'click', item: ListCardItem): void
}>()

const handleClick = (item: ListCardItem) => {
  if (item.clickable !== false) {
    if (item.action) {
      item.action()
    }
    emit('click', item)
  }
}
</script>

<template>
  <div class="list-card">
    <div v-if="title" class="list-card-header">
      <h3 class="list-card-title">{{ title }}</h3>
    </div>
    <div class="list-card-body">
      <div
        v-for="(item, index) in items"
        :key="item.id"
        :class="['list-item', { 'list-item-clickable': item.clickable !== false }]"
        @click="handleClick(item)"
      >
        <div class="list-item-left">
          <component v-if="item.icon" :is="item.icon" :size="18" class="list-item-icon" />
          <slot v-else name="icon" :item="item" />
          <span class="list-item-label">{{ item.label }}</span>
        </div>
        <div class="list-item-right">
          <span v-if="item.value" class="list-item-value">{{ item.value }}</span>
          <slot name="value" :item="item" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.list-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.list-card-header {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}

.list-card-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.list-card-body {
  padding: var(--space-1) 0;
}

.list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: var(--list-item-min);
  padding: var(--space-2) var(--space-4);
  transition: background-color var(--transition-fast) ease;
}

.list-item-clickable {
  cursor: pointer;
}

.list-item-clickable:active {
  background: var(--bg-card-hover);
}

.list-item-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
}

.list-item-icon {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.list-item-label {
  font-size: var(--font-size-md);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.list-item-right {
  flex-shrink: 0;
}

.list-item-value {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}
</style>
