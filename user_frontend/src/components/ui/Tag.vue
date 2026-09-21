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
  border-radius: var(--neo-radius-xs);
  font-weight: var(--neo-font-weight-medium);
  white-space: nowrap;
}

/* 尺寸变体 */
.ui-tag--sm {
  font-size: var(--neo-font-size-xs);
  padding: 2px 8px;
  line-height: var(--neo-line-height-tight);
}

.ui-tag--md {
  font-size: var(--neo-font-size-sm);
  padding: 4px 10px;
  line-height: var(--neo-line-height-tight);
}

/* 颜色变体（与页面上其它徽标同一支语义色） */
.ui-tag--success {
  background: var(--neo-success-bg);
  color: var(--neo-success);
}

.ui-tag--warning {
  background: var(--neo-warning-bg);
  color: var(--neo-warning);
}

.ui-tag--danger {
  background: var(--neo-danger-bg);
  color: var(--neo-danger);
}

.ui-tag--info {
  background: var(--neo-info-bg);
  color: var(--neo-info);
}

.ui-tag--default {
  background: var(--neo-bg-surface-3);
  color: var(--neo-text-tertiary);
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
