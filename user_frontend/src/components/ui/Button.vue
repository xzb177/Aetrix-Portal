<script setup lang="ts">
/**
 * Button - 按钮组件
 *
 * 提供 4 类按钮样式：主按钮、次按钮、幽灵按钮、危险按钮。
 *
 * @props
 * - variant: 按钮类型 ('primary' | 'secondary' | 'ghost' | 'danger')
 * - size: 尺寸 ('sm' | 'md' | 'lg')
 * - block: 是否块级按钮（占满容器宽度）
 * - disabled: 是否禁用
 * - loading: 是否加载中
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
    class="ui-btn"
    :class="[
      `ui-btn--${variant}`,
      `ui-btn--${size}`,
      {
        'ui-btn--block': block,
        'ui-btn--disabled': disabled || loading,
        'ui-btn--loading': loading
      }
    ]"
    :disabled="disabled || loading"
  >
    <span v-if="loading" class="ui-btn__spinner"></span>
    <slot />
  </component>
</template>

<style scoped>
.ui-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--btn-radius);
  font-weight: 500;
  cursor: pointer;
  user-select: none;
  transition: background-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              opacity var(--duration-fast) var(--ease-out);
  text-decoration: none;
  gap: 6px;
}

.ui-btn--block {
  display: flex;
  width: 100%;
}

/* 尺寸变体 */
.ui-btn--sm {
  height: 36px;
  padding: 0 16px;
  font-size: var(--text-caption-size);
}

.ui-btn--md {
  height: var(--btn-height);
  padding: var(--btn-padding);
  font-size: var(--text-body-size);
}

.ui-btn--lg {
  height: 52px;
  padding: 0 24px;
  font-size: var(--text-subtitle-size);
}

/* 主按钮 */
.ui-btn--primary {
  background: var(--btn-primary-bg);
  color: var(--btn-primary-text);
}

.ui-btn--primary:hover:not(.ui-btn--disabled) {
  background: var(--btn-primary-bg-hover);
}

.ui-btn--primary:active:not(.ui-btn--disabled) {
  opacity: 0.85;
}

/* 次按钮 */
.ui-btn--secondary {
  background: var(--btn-secondary-bg);
  color: var(--btn-secondary-text);
}

.ui-btn--secondary:hover:not(.ui-btn--disabled) {
  background: var(--btn-secondary-bg-hover);
}

/* 幽灵按钮 */
.ui-btn--ghost {
  background: var(--btn-ghost-bg);
  color: var(--btn-ghost-text);
}

.ui-btn--ghost:hover:not(.ui-btn--disabled) {
  background: var(--btn-ghost-bg-hover);
  color: var(--btn-ghost-text-hover);
}

/* 危险按钮 */
.ui-btn--danger {
  background: var(--btn-danger-bg);
  color: var(--btn-danger-text);
}

.ui-btn--danger:hover:not(.ui-btn--disabled) {
  background: var(--btn-danger-bg-hover);
  color: var(--btn-danger-text-hover);
}

/* 禁用状态 */
.ui-btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ui-btn--primary.ui-btn--disabled {
  background: var(--btn-primary-bg-disabled);
}

.ui-btn--secondary.ui-btn--disabled {
  background: var(--btn-secondary-bg-disabled);
}

/* 加载状态 */
.ui-btn__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: ui-btn-spin 0.6s linear infinite;
}

@keyframes ui-btn-spin {
  to {
    transform: rotate(360deg);
  }
}

.ui-btn--loading {
  pointer-events: none;
}
</style>
