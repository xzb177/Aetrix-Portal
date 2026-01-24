<script setup lang="ts">
/**
 * Card - 卡片容器组件 (Neo-Noir 2.0)
 *
 * 统一的卡片样式，支持点击、悬停效果。
 *
 * @props
 * - padding: 卡片内边距 ('none' | 'sm' | 'md' | 'lg')
 * - hover: 是否支持悬停效果
 * - clickable: 是否可点击（带点击态）
 * - radius: 圆角大小 ('sm' | 'md' | 'lg')
 * - tag: HTML 标签
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
    class="neo-card"
    :class="[
      `neo-card--padding-${padding}`,
      `neo-card--radius-${radius}`,
      {
        'neo-card--hover': hover,
        'neo-card--clickable': clickable
      }
    ]"
  >
    <slot />
  </component>
</template>

<style scoped>
.neo-card {
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-default);
  box-shadow: var(--neo-shadow-sm);
  transition: background-color var(--neo-duration-fast) var(--neo-ease-default),
              border-color var(--neo-duration-fast) var(--neo-ease-default),
              transform var(--neo-duration-fast) var(--neo-ease-default);
  position: relative;
}

/* 内阴影边框效果（增强质感） */
.neo-card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: var(--neo-shadow-inset);
}

/* Padding 变体 */
.neo-card--padding-none { padding: 0; }
.neo-card--padding-sm { padding: var(--neo-space-3); }
.neo-card--padding-md { padding: var(--neo-card-padding); }
.neo-card--padding-lg { padding: var(--neo-space-5); }

/* Radius 变体 */
.neo-card--radius-sm { border-radius: var(--neo-radius-sm); }
.neo-card--radius-md { border-radius: var(--neo-radius-md); }
.neo-card--radius-lg { border-radius: var(--neo-card-radius); }

/* 悬停效果 */
.neo-card--hover:hover,
.neo-card--clickable:active {
  background: var(--neo-bg-surface-hover);
  border-color: var(--neo-border-strong);
}

.neo-card--clickable {
  cursor: pointer;
  user-select: none;
}

/* 点击态 */
.neo-card--clickable:active {
  transform: scale(var(--neo-scale-press));
}

/* 减少动画 */
@media (prefers-reduced-motion: reduce) {
  .neo-card {
    transition: none;
  }

  .neo-card--clickable:active {
    transform: none;
  }
}
</style>
