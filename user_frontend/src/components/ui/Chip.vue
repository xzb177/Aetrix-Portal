<script setup lang="ts">
/**
 * Chip - 筛选标签组件
 *
 * 用于筛选、分类选择，支持选中/未选中状态。
 * Pill 形态，圆角 9999px。
 *
 * @props
 * - selected: 是否选中
 * - size: 尺寸 ('sm' | 'md')
 * - disabled: 是否禁用
 */

interface Props {
  selected?: boolean
  size?: 'sm' | 'md'
  disabled?: boolean
  tag?: string
}

const props = withDefaults(defineProps<Props>(), {
  selected: false,
  size: 'md',
  disabled: false,
  tag: 'button'
})

defineEmits<{
  click: [event: Event]
}>()
</script>

<template>
  <component
    :is="tag"
    class="neo-chip"
    :class="[
      `neo-chip--${size}`,
      {
        'neo-chip--selected': selected,
        'neo-chip--disabled': disabled
      }
    ]"
    :disabled="disabled"
    @click="!disabled && $emit('click', $event)"
  >
    <span class="neo-chip__content">
      <slot />
    </span>
    <span v-if="selected" class="neo-chip__check">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M20 6L9 17l-5-5"/>
      </svg>
    </span>
  </component>
</template>

<style scoped>
.neo-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--neo-border-default);
  cursor: pointer;
  user-select: none;
  transition: all var(--neo-duration-fast) var(--neo-ease-default);
  outline: none;
}

/* 尺寸变体 */
.neo-chip--sm {
  height: 28px;
  padding: 0 12px;
  border-radius: 9999px;
  font-size: var(--neo-font-size-sm);
}

.neo-chip--md {
  height: var(--neo-chip-height);
  padding: var(--neo-chip-padding);
  border-radius: var(--neo-chip-radius);
  font-size: var(--neo-font-size-md);
}

/* 默认未选中态 */
.neo-chip:not(.neo-chip--selected):not(.neo-chip--disabled) {
  background: var(--neo-bg-surface-1);
  color: var(--neo-text-secondary);
}

.neo-chip:not(.neo-chip--selected):not(.neo-chip--disabled):hover {
  background: var(--neo-bg-surface-hover);
  border-color: var(--neo-border-strong);
  color: var(--neo-text-primary);
}

/* 选中态 */
.neo-chip--selected {
  background: var(--neo-primary-dim);
  border-color: var(--neo-primary);
  color: var(--neo-primary);
}

.neo-chip--selected:hover {
  background: rgba(16, 185, 129, 0.12);
  border-color: var(--neo-primary-hover);
  color: var(--neo-primary-hover);
}

/* 禁用态 */
.neo-chip--disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

/* 选中勾选图标 */
.neo-chip__check {
  display: flex;
  align-items: center;
  justify-content: center;
}

.neo-chip__check svg {
  width: 14px;
  height: 14px;
}

/* Focus 可访问性 */
.neo-chip:focus-visible {
  box-shadow: 0 0 0 2px var(--neo-bg-base),
              0 0 0 4px var(--neo-border-focus);
}

/* 按下态 */
.neo-chip:active:not(.neo-chip--disabled) {
  transform: scale(var(--neo-scale-press));
}

/* 减少动画 */
@media (prefers-reduced-motion: reduce) {
  .neo-chip {
    transition: none;
  }

  .neo-chip:active {
    transform: none;
  }
}
</style>
