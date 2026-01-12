<script setup lang="ts">
/**
 * Card - 卡片容器组件
 *
 * 统一的卡片样式，提供玻璃拟态效果。
 *
 * @props
 * - padding: 卡片内边距 ('none' | 'sm' | 'md' | 'lg')
 * - hover: 是否支持悬停效果
 * - clickable: 是否可点击（带点击态）
 * - radius: 圆角大小 ('sm' | 'md' | 'lg')
 */

interface Props {
  padding?: 'none' | 'sm' | 'md' | 'lg'
  hover?: boolean
  clickable?: boolean
  radius?: 'sm' | 'md' | 'lg'
  tag?: string
}

const props = withDefaults(defineProps<Props>(), {
  padding: 'md',
  hover: false,
  clickable: false,
  radius: 'lg',
  tag: 'div'
})
</script>

<template>
  <component
    :is="tag"
    class="ui-card"
    :class="[
      `ui-card--padding-${padding}`,
      `ui-card--radius-${radius}`,
      {
        'ui-card--hover': hover,
        'ui-card--clickable': clickable
      }
    ]"
  >
    <slot />
  </component>
</template>

<style scoped>
.ui-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  box-shadow: var(--card-shadow);
  transition: background-color var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

/* Padding 变体 */
.ui-card--padding-none { padding: 0; }
.ui-card--padding-sm { padding: var(--space-sm); }
.ui-card--padding-md { padding: var(--space-md); }
.ui-card--padding-lg { padding: var(--space-lg); }

/* Radius 变体 */
.ui-card--radius-sm { border-radius: var(--radius-sm); }
.ui-card--radius-md { border-radius: var(--radius-md); }
.ui-card--radius-lg { border-radius: var(--radius-lg); }

/* 悬停效果 */
.ui-card--hover:hover,
.ui-card--clickable:active {
  background: var(--card-bg-hover);
}

.ui-card--clickable {
  cursor: pointer;
  user-select: none;
}

.ui-card--clickable:hover {
  background: var(--card-bg-hover);
}
</style>
