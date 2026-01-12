<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  type?: 'status-card' | 'quick-grid' | 'card' | 'list' | 'text'
  count?: number
  rows?: number
  height?: string
}

const props = withDefaults(defineProps<Props>(), {
  type: 'card',
  count: 1,
  rows: 3,
  height: '16px'
})

const skeletonStyle = computed(() => ({
  height: props.height,
}))
</script>

<template>
  <div class="skeleton-wrapper">
    <!-- 状态卡片骨架屏 -->
    <template v-if="type === 'status-card'">
      <div class="skeleton-status-card">
        <div class="skeleton-header">
          <div class="skeleton-title-long"></div>
          <div class="skeleton-badge"></div>
        </div>
        <div class="skeleton-divider"></div>
        <div class="skeleton-field-row">
          <div class="skeleton-label"></div>
          <div class="skeleton-field-value"></div>
        </div>
        <div class="skeleton-field-row">
          <div class="skeleton-label"></div>
          <div class="skeleton-field-value"></div>
        </div>
      </div>
    </template>

    <!-- 快捷网格骨架屏 -->
    <template v-else-if="type === 'quick-grid'">
      <div class="skeleton-quick-grid">
        <div class="skeleton-quick-item" v-for="i in 4" :key="i">
          <div class="skeleton-quick-icon"></div>
          <div class="skeleton-quick-label"></div>
          <div class="skeleton-quick-value"></div>
        </div>
      </div>
    </template>

    <!-- 卡片骨架屏 -->
    <template v-else-if="type === 'card'">
      <div class="skeleton-card" v-for="i in count" :key="i">
        <div class="skeleton-card-header">
          <div class="skeleton-title-medium"></div>
        </div>
        <div class="skeleton-card-body">
          <div class="skeleton-text-line" v-for="j in rows" :key="j"></div>
        </div>
      </div>
    </template>

    <!-- 列表骨架屏 -->
    <template v-else-if="type === 'list'">
      <div class="skeleton-list">
        <div class="skeleton-list-item" v-for="i in count" :key="i">
          <div class="skeleton-list-icon"></div>
          <div class="skeleton-list-content">
            <div class="skeleton-list-title"></div>
            <div class="skeleton-list-text"></div>
          </div>
        </div>
      </div>
    </template>

    <!-- 文本骨架屏 -->
    <template v-else-if="type === 'text'">
      <div class="skeleton-text-line" v-for="i in count" :key="i" :style="skeletonStyle"></div>
    </template>
  </div>
</template>

<style scoped>
.skeleton-wrapper {
  width: 100%;
}

/* 闪烁动画 */
@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

.skeleton-base {
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.03) 0%,
    rgba(255, 255, 255, 0.08) 50%,
    rgba(255, 255, 255, 0.03) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: 6px;
}

/* 状态卡片骨架屏 */
.skeleton-status-card {
  padding: 1rem;
  background: var(--bg-elevated, #141414);
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: var(--radius-md, 10px);
}

.skeleton-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.skeleton-title-long {
  width: 120px;
  height: 18px;
}

.skeleton-badge {
  width: 60px;
  height: 24px;
  border-radius: 12px;
}

.skeleton-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.1);
  margin: 1rem 0;
}

.skeleton-field-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.skeleton-label {
  width: 40px;
  height: 14px;
}

.skeleton-field-value {
  flex: 1;
  height: 32px;
}

/* 快捷网格骨架屏 */
.skeleton-quick-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

.skeleton-quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  background: var(--bg-elevated, #141414);
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: var(--radius-md, 10px);
  min-height: 90px;
}

.skeleton-quick-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm, 6px);
}

.skeleton-quick-label {
  width: 40px;
  height: 14px;
}

.skeleton-quick-value {
  width: 60px;
  height: 12px;
}

/* 卡片骨架屏 */
.skeleton-card {
  padding: 1rem;
  background: var(--bg-elevated, #141414);
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: var(--radius-md, 10px);
  margin-bottom: 0.75rem;
}

.skeleton-card-header {
  margin-bottom: 1rem;
}

.skeleton-title-medium {
  width: 30%;
  height: 16px;
}

.skeleton-card-body {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

/* 列表骨架屏 */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.skeleton-list-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  background: var(--bg-elevated, #141414);
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: var(--radius-md, 10px);
}

.skeleton-list-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm, 6px);
  flex-shrink: 0;
}

.skeleton-list-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.skeleton-list-title {
  width: 50%;
  height: 14px;
}

.skeleton-list-text {
  width: 70%;
  height: 12px;
}

/* 文本骨架屏 */
.skeleton-text-line {
  width: 100%;
}

/* 所有骨架元素的基础样式 */
.skeleton-title-long,
.skeleton-badge,
.skeleton-label,
.skeleton-field-value,
.skeleton-quick-icon,
.skeleton-quick-label,
.skeleton-quick-value,
.skeleton-title-medium,
.skeleton-list-icon,
.skeleton-list-title,
.skeleton-list-text,
.skeleton-text-line {
  @apply skeleton-base;
}

/* 移动端适配 */
@media (max-width: 640px) {
  .skeleton-status-card {
    padding: 0.75rem;
  }

  .skeleton-quick-item {
    padding: 0.75rem;
    min-height: 80px;
  }

  .skeleton-quick-icon {
    width: 36px;
    height: 36px;
  }
}
</style>
