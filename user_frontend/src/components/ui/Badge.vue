<script setup lang="ts">
/**
 * Badge - 徽章组件
 *
 * 小型状态徽章，用于显示状态、数量等。
 *
 * @props
 * - variant: 样式变体 ('success' | 'warning' | 'danger' | 'info' | 'default')
 * - size: 尺寸 ('sm' | 'md')
 * - dot: 是否只显示圆点
 */

interface Props {
  variant?: 'success' | 'warning' | 'danger' | 'info' | 'default'
  size?: 'sm' | 'md'
  dot?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'default',
  size: 'md',
  dot: false
})
</script>

<template>
  <span
    class="neo-badge"
    :class="[
      `neo-badge--${variant}`,
      `neo-badge--${size}`,
      { 'neo-badge--dot': dot }
    ]"
  >
    <span v-if="!dot" class="neo-badge__content">
      <slot />
    </span>
  </span>
</template>

<style scoped>
.neo-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--neo-badge-radius);
  font-weight: var(--neo-font-weight-medium);
  white-space: nowrap;
}

/* 尺寸变体 */
.neo-badge--sm {
  height: 16px;
  padding: 0 6px;
  font-size: 10px;
}

.neo-badge--md {
  height: var(--neo-badge-height);
  padding: var(--neo-badge-padding);
  font-size: var(--neo-badge-font-size);
}

/* Dot 模式 */
.neo-badge--dot {
  width: 8px;
  height: 8px;
  padding: 0;
  border-radius: 50%;
}

/* 变体样式 */
.neo-badge--success {
  background: var(--neo-success-bg);
  color: var(--neo-success);
}

.neo-badge--warning {
  background: var(--neo-warning-bg);
  color: var(--neo-warning);
}

.neo-badge--danger {
  background: var(--neo-danger-bg);
  color: var(--neo-danger);
}

.neo-badge--info {
  background: var(--neo-info-bg);
  color: var(--neo-info);
}

.neo-badge--default {
  background: var(--neo-bg-surface-2);
  color: var(--neo-text-secondary);
}
</style>
