<script setup lang="ts">
/**
 * SectionHeader - 区块标题组件
 *
 * 用于页面内各区块的标题，支持标题、副标题和右侧操作按钮。
 *
 * @props
 * - title: 主标题
 * - subtitle: 副标题（可选）
 * - size: 尺寸 ('sm' | 'md' | 'lg')
 */

interface Props {
  title: string
  subtitle?: string
  size?: 'sm' | 'md' | 'lg'
}

defineProps<Props>()
</script>

<template>
  <div class="ui-section-header" :class="`ui-section-header--${size}`">
    <div class="ui-section-header__main">
      <h3 class="ui-section-header__title">{{ title }}</h3>
      <p v-if="subtitle" class="ui-section-header__subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.action" class="ui-section-header__action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.ui-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--neo-space-4);
}

.ui-section-header__main {
  flex: 1;
}

.ui-section-header__title {
  font-size: var(--neo-font-size-lg);
  font-weight: var(--neo-font-weight-medium);
  line-height: var(--neo-line-height-normal);
  color: var(--neo-text-primary);
  margin: 0;
}

.ui-section-header__subtitle {
  font-size: var(--neo-font-size-sm);
  font-weight: var(--neo-font-weight-normal);
  line-height: var(--neo-line-height-normal);
  color: var(--neo-text-tertiary);
  margin: 4px 0 0 0;
}

.ui-section-header__action {
  flex-shrink: 0;
  margin-left: var(--neo-space-3);
}

/* 尺寸变体 */
.ui-section-header--sm .ui-section-header__title {
  font-size: var(--neo-font-size-md);
}

.ui-section-header--lg .ui-section-header__title {
  font-size: var(--neo-font-size-2xl);
  font-weight: var(--neo-font-weight-semibold);
}
</style>
