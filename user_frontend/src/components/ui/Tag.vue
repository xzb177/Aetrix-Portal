<script setup lang="ts">
/**
 * Tag - 标签组件
 *
 * 用于显示状态、分类等标签信息。
 *
 * @props
 * - text: 标签文字
 * - variant: 样式变体 ('success' | 'warning' | 'danger' | 'info' | 'default')
 * - size: 尺寸 ('sm' | 'md')
 * - dot: 是否显示左侧圆点
 */

interface Props {
  text?: string
  variant?: 'success' | 'warning' | 'danger' | 'info' | 'default'
  size?: 'sm' | 'md'
  dot?: boolean
}

withDefaults(defineProps<Props>(), {
  variant: 'default',
  size: 'md',
  dot: false
})
</script>

<template>
  <span
    class="ui-tag"
    :class="[
      `ui-tag--${variant}`,
      `ui-tag--${size}`,
      { 'ui-tag--dot': dot }
    ]"
  >
    <span v-if="dot" class="ui-tag__dot"></span>
    <slot>{{ text }}</slot>
  </span>
</template>

<style scoped>
.ui-tag {
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-sm);
  font-weight: 500;
  white-space: nowrap;
}

/* 尺寸变体 */
.ui-tag--sm {
  font-size: 11px;
  padding: 2px 8px;
  line-height: 1.4;
}

.ui-tag--md {
  font-size: var(--text-caption-size);
  padding: 4px 10px;
  line-height: 1.4;
}

/* 颜色变体 */
.ui-tag--success {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.ui-tag--warning {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.ui-tag--danger {
  background: var(--color-danger-bg);
  color: var(--color-danger);
}

.ui-tag--info {
  background: var(--color-info-bg);
  color: var(--color-info);
}

.ui-tag--default {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-caption-color);
}

/* 圆点 */
.ui-tag--dot {
  padding-left: 6px;
}

.ui-tag--sm.ui-tag--dot {
  padding-left: 4px;
}

.ui-tag__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 6px;
  background: currentColor;
}

.ui-tag--sm .ui-tag__dot {
  width: 5px;
  height: 5px;
  margin-right: 4px;
}
</style>
