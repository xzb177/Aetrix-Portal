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
  margin-bottom: var(--space-md);
}

.ui-section-header__main {
  flex: 1;
}

.ui-section-header__title {
  font-size: var(--text-subtitle-size);
  font-weight: var(--text-subtitle-weight);
  line-height: var(--text-subtitle-line);
  color: var(--text-subtitle-color);
  margin: 0;
}

.ui-section-header__subtitle {
  font-size: var(--text-caption-size);
  font-weight: var(--text-caption-weight);
  line-height: var(--text-caption-line);
  color: var(--text-caption-color);
  margin: 4px 0 0 0;
}

.ui-section-header__action {
  flex-shrink: 0;
  margin-left: var(--space-sm);
}

/* 尺寸变体 */
.ui-section-header--sm .ui-section-header__title {
  font-size: var(--text-body-size);
}

.ui-section-header--lg .ui-section-header__title {
  font-size: var(--text-title-size);
  font-weight: var(--text-title-weight);
}
</style>
