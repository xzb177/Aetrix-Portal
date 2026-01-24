<script setup lang="ts">
/**
 * Button - 按钮组件 (Neo-Noir 2.0)
 *
 * 提供 4 类按钮样式：主按钮、次按钮、幽灵按钮、危险按钮。
 *
 * @props
 * - variant: 按钮类型 ('primary' | 'secondary' | 'ghost' | 'danger')
 * - size: 尺寸 ('sm' | 'md' | 'lg')
 * - block: 是否块级按钮（占满容器宽度）
 * - disabled: 是否禁用
 * - loading: 是否加载中
 * - tag: HTML 标签
 */

interface Props {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  block?: boolean
  disabled?: boolean
  loading?: boolean
  tag?: string
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'primary',
  size: 'md',
  block: false,
  disabled: false,
  loading: false,
  tag: 'button'
})
</script>

<template>
  <component
    :is="tag"
    class="neo-btn"
    :class="[
      `neo-btn--${variant}`,
      `neo-btn--${size}`,
      {
        'neo-btn--block': block,
        'neo-btn--disabled': disabled || loading,
        'neo-btn--loading': loading
      }
    ]"
    :disabled="disabled || loading"
  >
    <svg v-if="loading" class="neo-btn__spinner" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" stroke-opacity="0.25"/>
      <path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 2a10 10 0 0 1 10 10"/>
    </svg>
    <slot />
  </component>
</template>

<style scoped>
.neo-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--neo-space-2);
  border: none;
  font-weight: var(--neo-font-weight-semibold);
  cursor: pointer;
  user-select: none;
  transition: background-color var(--neo-duration-fast) var(--neo-ease-default),
              transform var(--neo-duration-fast) var(--neo-ease-default);
  outline: none;
  text-decoration: none;
  white-space: nowrap;
}

.neo-btn--block {
  display: flex;
  width: 100%;
}

/* 尺寸变体 */
.neo-btn--sm {
  height: var(--neo-btn-height-sm);
  padding: 0 16px;
  border-radius: var(--neo-btn-radius-sm);
  font-size: var(--neo-font-size-sm);
}

.neo-btn--md {
  height: var(--neo-btn-height-md);
  padding: 0 20px;
  border-radius: var(--neo-btn-radius-md);
  font-size: var(--neo-font-size-md);
}

.neo-btn--lg {
  height: var(--neo-btn-height-lg);
  padding: 0 28px;
  border-radius: var(--neo-btn-radius-lg);
  font-size: var(--neo-font-size-lg);
}

/* 主按钮 - 绿色，主角感 */
.neo-btn--primary {
  background: var(--neo-primary);
  color: var(--neo-text-inverse);
  box-shadow: var(--neo-glow-primary);
}

.neo-btn--primary:hover:not(.neo-btn--disabled) {
  background: var(--neo-primary-hover);
}

.neo-btn--primary:active:not(.neo-btn--disabled) {
  transform: scale(var(--neo-scale-press));
  background: var(--neo-primary-active);
}

/* 次按钮 - 玻璃态 */
.neo-btn--secondary {
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-default);
  color: var(--neo-text-primary);
}

.neo-btn--secondary:hover:not(.neo-btn--disabled) {
  background: var(--neo-bg-surface-hover);
  border-color: var(--neo-border-strong);
}

.neo-btn--secondary:active:not(.neo-btn--disabled) {
  transform: scale(var(--neo-scale-press));
  background: var(--neo-bg-surface-active);
}

/* 幽灵按钮 */
.neo-btn--ghost {
  background: transparent;
  color: var(--neo-text-secondary);
}

.neo-btn--ghost:hover:not(.neo-btn--disabled) {
  background: var(--neo-bg-surface-2);
  color: var(--neo-text-primary);
}

.neo-btn--ghost:active:not(.neo-btn--disabled) {
  transform: scale(var(--neo-scale-press));
  background: var(--neo-bg-surface-hover);
}

/* 危险按钮 */
.neo-btn--danger {
  background: var(--neo-danger-bg);
  color: var(--neo-danger);
}

.neo-btn--danger:hover:not(.neo-btn--disabled) {
  background: rgba(239, 68, 68, 0.2);
}

.neo-btn--danger:active:not(.neo-btn--disabled) {
  transform: scale(var(--neo-scale-press));
  background: rgba(239, 68, 68, 0.25);
}

/* 禁用状态 */
.neo-btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

/* 加载动画 */
.neo-btn__spinner {
  width: 16px;
  height: 16px;
  animation: neo-btn-spin 0.6s linear infinite;
}

@keyframes neo-btn-spin {
  to { transform: rotate(360deg); }
}

.neo-btn--loading {
  pointer-events: none;
}

/* Focus 可访问性 */
.neo-btn:focus-visible {
  box-shadow: 0 0 0 2px var(--neo-bg-base),
              0 0 0 4px var(--neo-border-focus);
}

/* 减少动画 */
@media (prefers-reduced-motion: reduce) {
  .neo-btn {
    transition: none;
  }

  .neo-btn:active {
    transform: none;
  }

  .neo-btn__spinner {
    animation: none;
  }
}
</style>
