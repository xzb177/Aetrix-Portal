<script setup lang="ts">
/**
 * SegmentedControl - 分段控制器组件
 *
 * 用于在 2-5 个选项之间切换，常用于视图切换。
 *
 * @props
 * - options: 选项数组 { label: string, value: any, icon?: Component }[]
 * - modelValue: 当前选中值
 * - size: 尺寸 ('sm' | 'md')
 */

interface Option {
  label: string
  value: any
  icon?: any
}

interface Props {
  options: Option[]
  modelValue: any
  size?: 'sm' | 'md'
}

defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: any]
}>()
</script>

<template>
  <div class="neo-segment" :class="`neo-segment--${size}`">
    <button
      v-for="option in options"
      :key="option.value"
      class="neo-segment__item"
      :class="{ 'neo-segment__item--active': modelValue === option.value }"
      @click="emit('update:modelValue', option.value)"
    >
      <component v-if="option.icon" :is="option.icon" class="neo-segment__icon" />
      <span class="neo-segment__label">{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.neo-segment {
  display: inline-flex;
  background: var(--neo-bg-surface-1);
  border-radius: var(--neo-segment-radius);
  padding: 3px;
  border: 1px solid var(--neo-border-default);
}

/* 尺寸变体 */
.neo-segment--sm {
  height: 32px;
  gap: 2px;
}

.neo-segment--md {
  height: var(--neo-segment-height);
  gap: 3px;
}

/* 选项按钮 */
.neo-segment__item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  padding: 0 14px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm);
  font-weight: var(--neo-font-weight-medium);
  cursor: pointer;
  transition: all var(--neo-duration-fast) var(--neo-ease-default);
  outline: none;
}

.neo-segment--sm .neo-segment__item {
  font-size: var(--neo-font-size-xs);
  padding: 0 10px;
}

/* 悬停态 */
.neo-segment__item:hover:not(.neo-segment__item--active) {
  color: var(--neo-text-primary);
}

/* 选中态 - 深绿底 + 内发光细边 */
.neo-segment__item--active {
  background: var(--neo-primary);
  color: var(--neo-text-inverse);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.15),
              0 0 0 1px var(--neo-primary),
              0 0 12px rgba(16, 185, 129, 0.4);
}

.neo-segment__item--active:hover {
  background: var(--neo-primary-hover);
}

/* 图标 */
.neo-segment__icon {
  width: 14px;
  height: 14px;
  stroke-width: 2;
}

/* 标签文字 */
.neo-segment__label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Focus 可访问性 */
.neo-segment__item:focus-visible {
  box-shadow: 0 0 0 2px var(--neo-bg-base),
              0 0 0 4px var(--neo-border-focus);
}

/* 按下态 */
.neo-segment__item:active {
  transform: scale(0.98);
}

/* 减少动画 */
@media (prefers-reduced-motion: reduce) {
  .neo-segment__item {
    transition: none;
  }

  .neo-segment__item:active {
    transform: none;
  }
}
</style>
