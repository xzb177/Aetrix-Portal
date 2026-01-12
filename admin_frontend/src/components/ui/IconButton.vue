<script setup lang="ts">
import { computed } from 'vue'

type IconButtonVariant = 'default' | 'primary' | 'danger' | 'ghost'

interface Props {
  icon?: any
  variant?: IconButtonVariant
  size?: number
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'default',
  size: 40,
  disabled: false,
})

const classes = computed(() => [
  'icon-btn',
  `icon-btn-${props.variant}`,
  { 'icon-btn-disabled': props.disabled },
])
</script>

<template>
  <button :class="classes" :disabled="disabled" :style="{ width: `${size}px`, height: `${size}px` }">
    <slot>
      <component v-if="icon" :is="icon" :size="size * 0.5" />
    </slot>
  </button>
</template>

<style scoped>
.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.icon-btn:active:not(.icon-btn-disabled) {
  transform: scale(0.95);
}

/* Variants */
.icon-btn-default {
  background: var(--bg-card-hover);
  color: var(--text-secondary);
}

.icon-btn-default:active:not(.icon-btn-disabled) {
  background: var(--bg-card);
  color: var(--text-primary);
}

.icon-btn-primary {
  background: var(--primary);
  color: var(--primary-on);
}

.icon-btn-primary:active:not(.icon-btn-disabled) {
  background: var(--primary-active);
}

.icon-btn-danger {
  background: var(--danger-bg);
  color: var(--danger);
}

.icon-btn-danger:active:not(.icon-btn-disabled) {
  background: rgba(239, 68, 68, 0.25);
}

.icon-btn-ghost {
  background: transparent;
  color: var(--text-secondary);
}

.icon-btn-ghost:active:not(.icon-btn-disabled) {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}

/* Disabled state */
.icon-btn-disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}
</style>
