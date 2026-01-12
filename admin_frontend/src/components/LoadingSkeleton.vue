<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  type?: 'card' | 'table' | 'list' | 'text' | 'avatar'
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
    <!-- 卡片骨架屏 -->
    <template v-if="type === 'card'">
      <div
        v-for="i in count"
        :key="i"
        class="skeleton-card"
      >
        <div class="skeleton-avatar"></div>
        <div class="skeleton-content">
          <div class="skeleton-title"></div>
          <div class="skeleton-text" v-for="j in rows" :key="j"></div>
        </div>
      </div>
    </template>

    <!-- 表格骨架屏 -->
    <template v-else-if="type === 'table'">
      <div class="skeleton-table">
        <div class="skeleton-thead">
          <div class="skeleton-th" v-for="j in 6" :key="j"></div>
        </div>
        <div class="skeleton-tbody">
          <div class="skeleton-tr" v-for="i in count" :key="i">
            <div class="skeleton-td" v-for="j in 6" :key="j"></div>
          </div>
        </div>
      </div>
    </template>

    <!-- 列表骨架屏 -->
    <template v-else-if="type === 'list'">
      <div class="skeleton-list">
        <div class="skeleton-list-item" v-for="i in count" :key="i">
          <div class="skeleton-list-avatar"></div>
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

    <!-- 头像骨架屏 -->
    <template v-else-if="type === 'avatar'">
      <div class="skeleton-avatar" v-for="i in count" :key="i"></div>
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
    rgba(255, 255, 255, 0.05) 0%,
    rgba(255, 255, 255, 0.1) 50%,
    rgba(255, 255, 255, 0.05) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: 6px;
}

/* 卡片骨架屏 */
.skeleton-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  margin-bottom: 0.75rem;
}

.skeleton-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  flex-shrink: 0;
}

.skeleton-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.skeleton-title {
  width: 40%;
  height: 16px;
}

.skeleton-text {
  width: 100%;
  height: 12px;
}

.skeleton-text:last-child {
  width: 60%;
}

/* 表格骨架屏 */
.skeleton-table {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

.skeleton-thead {
  display: flex;
  border-bottom: 1px solid var(--border-color);
}

.skeleton-th {
  flex: 1;
  height: 48px;
  margin: 0.5rem;
}

.skeleton-tbody {
  display: flex;
  flex-direction: column;
}

.skeleton-tr {
  display: flex;
  border-bottom: 1px solid var(--border-color-light);
}

.skeleton-tr:last-child {
  border-bottom: none;
}

.skeleton-td {
  flex: 1;
  height: 56px;
  margin: 0.5rem;
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
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.skeleton-list-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
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
.skeleton-avatar,
.skeleton-title,
.skeleton-text,
.skeleton-th,
.skeleton-td,
.skeleton-list-avatar,
.skeleton-list-title,
.skeleton-list-text,
.skeleton-text-line {
  @apply skeleton-base;
}

/* 移动端适配 */
@media (max-width: 640px) {
  .skeleton-card {
    padding: 0.75rem;
  }

  .skeleton-avatar {
    width: 36px;
    height: 36px;
  }

  .skeleton-list-avatar {
    width: 32px;
    height: 32px;
  }

  .skeleton-th,
  .skeleton-td {
    margin: 0.375rem;
  }

  .skeleton-th:first-child,
  .skeleton-td:first-child {
    margin-left: 0.5rem;
  }

  .skeleton-th:last-child,
  .skeleton-td:last-child {
    margin-right: 0.5rem;
  }
}
</style>
