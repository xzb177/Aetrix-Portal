<template>
  <component
    :is="tag"
    :class="[
      'loading-button',
      `loading-button--${variant}`,
      `loading-button--${size}`,
      {
        'loading-button--loading': loading,
        'loading-button--disabled': disabled || loading,
        'loading-button--block': block,
        'loading-button--icon-only': iconOnly && !$slots.default
      }
    ]"
    :type="tag === 'button' ? nativeType : undefined"
    :disabled="disabled || loading"
    v-bind="$attrs"
  >
    <span v-if="loading" class="loading-button__spinner">
      <svg viewBox="0 0 24 24" fill="none">
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          class="loading-button__spinner-track"
        />
        <path
          d="M12 2a10 10 0 0 1 10 10"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          class="loading-button__spinner-indicator"
        />
      </svg>
    </span>

    <span v-if="$slots.icon" class="loading-button__icon">
      <slot name="icon" />
    </span>

    <span v-if="$slots.default" class="loading-button__content">
      <slot />
    </span>

    <slot name="suffix" />
  </component>
</template>

<script setup lang="ts">
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'
export type ButtonTag = 'button' | 'a' | 'router-link'

export interface LoadingButtonProps {
  loading?: boolean
  disabled?: boolean
  block?: boolean
  iconOnly?: boolean
  variant?: ButtonVariant
  size?: ButtonSize
  tag?: ButtonTag
  nativeType?: 'button' | 'submit' | 'reset'
}

withDefaults(defineProps<LoadingButtonProps>(), {
  loading: false,
  disabled: false,
  block: false,
  iconOnly: false,
  variant: 'primary',
  size: 'md',
  tag: 'button',
  nativeType: 'button'
})
</script>

<style scoped>
.loading-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  font-weight: 500;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  text-decoration: none;
  border: none;
  outline: none;
}

.loading-button:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

/* 尺寸 */
.loading-button--sm {
  padding: 0.5rem 0.875rem;
  font-size: 0.8125rem;
}

.loading-button--md {
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
}

.loading-button--lg {
  padding: 0.875rem 1.75rem;
  font-size: 1rem;
}

/* 变体 */
.loading-button--primary {
  background: var(--brand-primary);
  color: white;
}

.loading-button--primary:hover:not(.loading-button--disabled) {
  background: var(--brand-primary-hover);
}

.loading-button--secondary {
  background: var(--bg-glass);
  border: 1px solid var(--border-default);
  color: var(--text-primary);
}

.loading-button--secondary:hover:not(.loading-button--disabled) {
  background: var(--bg-elevated-hover);
  border-color: var(--border-strong);
}

.loading-button--ghost {
  background: transparent;
  color: var(--text-secondary);
}

.loading-button--ghost:hover:not(.loading-button--disabled) {
  background: var(--bg-elevated-hover);
  color: var(--text-primary);
}

.loading-button--danger {
  background: var(--color-danger);
  color: white;
}

.loading-button--danger:hover:not(.loading-button--disabled) {
  background: #dc2626;
}

/* 状态 */
.loading-button--disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

.loading-button--block {
  width: 100%;
}

.loading-button--icon-only {
  padding: 0.625rem;
}

/* 加载状态 */
.loading-button--loading {
  pointer-events: none;
}

.loading-button--loading .loading-button__content,
.loading-button--loading .loading-button__icon {
  opacity: 0.5;
}

.loading-button__spinner {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-button__spinner svg {
  width: 18px;
  height: 18px;
  animation: spin 0.8s linear infinite;
}

.loading-button--sm .loading-button__spinner svg {
  width: 14px;
  height: 14px;
}

.loading-button--lg .loading-button__spinner svg {
  width: 22px;
  height: 22px;
}

.loading-button__spinner-track {
  stroke: currentColor;
  opacity: 0.3;
}

.loading-button__spinner-indicator {
  stroke: currentColor;
  stroke-linecap: round;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 图标 */
.loading-button__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.loading-button__content {
  display: flex;
  align-items: center;
}
</style>
