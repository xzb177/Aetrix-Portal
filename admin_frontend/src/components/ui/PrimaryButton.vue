<script setup lang="ts">
import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
type ButtonSize = 'sm' | 'md' | 'lg'

interface Props {
  variant?: ButtonVariant
  size?: ButtonSize
  block?: boolean
  disabled?: boolean
  loading?: boolean
  icon?: any
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'primary',
  size: 'md',
  block: false,
  disabled: false,
  loading: false,
})

const classes = computed(() => [
  'btn',
  `btn-${props.variant}`,
  `btn-${props.size}`,
  { 'btn-block': props.block },
  { 'btn-loading': props.loading },
  { 'btn-disabled': props.disabled || props.loading },
])
</script>

<template>
  <button :class="classes" :disabled="disabled || loading">
    <Loader2 v-if="loading" :size="16" class="btn-spinner" />
    <component v-if="icon && !loading" :is="icon" :size="16" />
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
  white-space: nowrap;
}

.btn:active:not(.btn-disabled) {
  transform: scale(0.97);
}

/* Sizes */
.btn-sm {
  height: 36px;
  padding: 0 var(--space-3);
  font-size: var(--font-size-sm);
}

.btn-md {
  height: 44px;
  padding: 0 var(--space-4);
}

.btn-lg {
  height: 48px;
  padding: 0 var(--space-5);
  font-size: var(--font-size-lg);
}

.btn-block {
  width: 100%;
}

/* Variants */
.btn-primary {
  background: var(--primary);
  color: var(--primary-on);
}

.btn-primary:active:not(.btn-disabled) {
  background: var(--primary-active);
}

.btn-secondary {
  background: var(--bg-card-hover);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-secondary:active:not(.btn-disabled) {
  background: var(--bg-card);
  border-color: var(--border-strong);
}

.btn-danger {
  background: var(--danger);
  color: white;
}

.btn-danger:active:not(.btn-disabled) {
  opacity: 0.85;
}

.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
}

.btn-ghost:active:not(.btn-disabled) {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}

/* States */
.btn-disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

.btn-spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
