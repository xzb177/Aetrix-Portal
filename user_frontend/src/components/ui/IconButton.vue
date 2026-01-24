<script setup lang="ts">
/**
 * IconButton - 图标按钮组件
 *
 * 用于复制、关闭、更多等操作，只有图标没有文字。
 *
 * @props
 * - icon: 图标组件
 * - size: 尺寸 ('sm' | 'md' | 'lg')
 * - variant: 样式变体 ('primary' | 'secondary' | 'ghost' | 'danger')
 * - disabled: 是否禁用
 * - loading: 是否加载中
 */

interface Props {
  icon: any
  size?: 'sm' | 'md' | 'lg'
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  disabled?: boolean
  loading?: boolean
  tag?: string
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  variant: 'ghost',
  disabled: false,
  loading: false,
  tag: 'button'
})
</script>

<template>
  <component
    :is="tag"
    class="neo-icon-btn"
    :class="[
      `neo-icon-btn--${size}`,
      `neo-icon-btn--${variant}`,
      {
        'neo-icon-btn--disabled': disabled || loading,
        'neo-icon-btn--loading': loading
      }
    ]"
    :disabled="disabled || loading"
  >
    <svg v-if="loading" class="neo-icon-btn__spinner" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" stroke-opacity="0.25"/>
      <path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 2a10 10 0 0 1 10 10"/>
    </svg>
    <component v-else :is="icon" class="neo-icon-btn__icon" />
  </component>
</template>

<style scoped>
.neo-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  border: none;
  cursor: pointer;
  user-select: none;
  transition: background-color var(--neo-duration-fast) var(--neo-ease-default),
              transform var(--neo-duration-fast) var(--neo-ease-default);
  outline: none;
}

/* 尺寸变体 */
.neo-icon-btn--sm {
  width: var(--neo-icon-btn-sm);
  height: var(--neo-icon-btn-sm);
  border-radius: var(--neo-radius-xs);
}

.neo-icon-btn--md {
  width: var(--neo-icon-btn-md);
  height: var(--neo-icon-btn-md);
  border-radius: var(--neo-icon-btn-radius);
}

.neo-icon-btn--lg {
  width: var(--neo-icon-btn-lg);
  height: var(--neo-icon-btn-lg);
  border-radius: var(--neo-radius-sm);
}

/* 图标大小 */
.neo-icon-btn__icon {
  width: 55%;
  height: 55%;
  stroke-width: 1.5;
}

/* 主按钮 */
.neo-icon-btn--primary {
  background: var(--neo-primary);
  color: var(--neo-text-inverse);
}

.neo-icon-btn--primary:hover:not(.neo-icon-btn--disabled) {
  background: var(--neo-primary-hover);
}

.neo-icon-btn--primary:active:not(.neo-icon-btn--disabled) {
  transform: scale(var(--neo-scale-press));
  background: var(--neo-primary-active);
}

/* 次按钮 */
.neo-icon-btn--secondary {
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-default);
  color: var(--neo-text-primary);
}

.neo-icon-btn--secondary:hover:not(.neo-icon-btn--disabled) {
  background: var(--neo-bg-surface-hover);
  border-color: var(--neo-border-strong);
}

.neo-icon-btn--secondary:active:not(.neo-icon-btn--disabled) {
  transform: scale(var(--neo-scale-press));
}

/* 幽灵按钮 */
.neo-icon-btn--ghost {
  background: transparent;
  color: var(--neo-text-secondary);
}

.neo-icon-btn--ghost:hover:not(.neo-icon-btn--disabled) {
  background: var(--neo-bg-surface-2);
  color: var(--neo-text-primary);
}

.neo-icon-btn--ghost:active:not(.neo-icon-btn--disabled) {
  transform: scale(var(--neo-scale-press));
  background: var(--neo-bg-surface-hover);
}

/* 危险按钮 */
.neo-icon-btn--danger {
  background: transparent;
  color: var(--neo-danger);
}

.neo-icon-btn--danger:hover:not(.neo-icon-btn--disabled) {
  background: var(--neo-danger-bg);
}

.neo-icon-btn--danger:active:not(.neo-icon-btn--disabled) {
  transform: scale(var(--neo-scale-press));
  background: var(--neo-danger-bg);
}

/* 禁用状态 */
.neo-icon-btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

/* 加载动画 */
.neo-icon-btn__spinner {
  width: 55%;
  height: 55%;
  animation: neo-icon-spin 0.6s linear infinite;
}

@keyframes neo-icon-spin {
  to { transform: rotate(360deg); }
}

/* Focus 可访问性 */
.neo-icon-btn:focus-visible {
  box-shadow: 0 0 0 2px var(--neo-bg-base),
              0 0 0 4px var(--neo-border-focus);
}

/* 减少动画 */
@media (prefers-reduced-motion: reduce) {
  .neo-icon-btn {
    transition: none;
  }

  .neo-icon-btn:active {
    transform: none;
  }

  .neo-icon-btn__spinner {
    animation: none;
  }
}
</style>
