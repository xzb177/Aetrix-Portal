<script setup lang="ts">
import { computed } from 'vue'

type ChipVariant = 'success' | 'warning' | 'danger' | 'info' | 'primary' | 'default'
type ChipSize = 'sm' | 'md'

interface Props {
  variant?: ChipVariant
  size?: ChipSize
  dot?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'default',
  size: 'md',
  dot: false,
})

const classes = computed(() => [
  'chip',
  `chip-${props.variant}`,
  `chip-${props.size}`,
  { 'chip-dot': props.dot },
])
</script>

<template>
  <span :class="classes">
    <span v-if="dot" class="chip-dot-indicator"></span>
    <slot />
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  line-height: var(--line-height-normal);
  white-space: nowrap;
}

.chip-sm {
  padding: 2px var(--space-2);
  font-size: var(--font-size-xs);
}

.chip-md {
  padding: 4px var(--space-2);
  height: 24px;
}

/* Variants */
.chip-default {
  background: var(--bg-card-hover);
  color: var(--text-secondary);
}

.chip-success {
  background: var(--success-bg);
  color: var(--success);
}

.chip-warning {
  background: var(--warning-bg);
  color: var(--warning);
}

.chip-danger {
  background: var(--danger-bg);
  color: var(--danger);
}

.chip-info {
  background: var(--info-bg);
  color: var(--info);
}

.chip-primary {
  background: var(--primary-bg);
  color: var(--primary);
}

/* Dot indicator */
.chip-dot {
  padding-left: var(--space-1);
}

.chip-dot-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: currentColor;
}
</style>
