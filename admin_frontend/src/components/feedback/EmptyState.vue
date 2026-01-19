<script setup lang="ts">
import type { Component } from 'vue'

export interface EmptyStateProps {
  icon?: Component
  title?: string
  description?: string
  actionLabel?: string
  variant?: 'default' | 'search' | 'data' | 'error' | 'success'
  compact?: boolean
}

const props = withDefaults(defineProps<EmptyStateProps>(), {
  variant: 'default',
  compact: false,
  actionLabel: ''
})

const emit = defineEmits<{
  action: []
}>()
</script>

<template>
  <div :class="['empty-state', `empty-state--${variant}`, { 'empty-state--compact': compact }]">
    <!-- 内置 SVG 插图 -->
    <div v-if="!icon" class="empty-illustration">
      <!-- 默认空状态 -->
      <svg
        v-if="variant === 'default'"
        viewBox="0 0 200 200"
        fill="none"
        class="empty-svg"
      >
        <circle cx="100" cy="100" r="80" fill="currentColor" fill-opacity="0.05"/>
        <rect x="65" y="60" width="70" height="80" rx="4" fill="currentColor" fill-opacity="0.1"/>
        <rect x="75" y="75" width="50" height="6" rx="3" fill="currentColor" fill-opacity="0.2"/>
        <rect x="75" y="90" width="35" height="6" rx="3" fill="currentColor" fill-opacity="0.15"/>
        <rect x="75" y="105" width="40" height="6" rx="3" fill="currentColor" fill-opacity="0.15"/>
      </svg>

      <!-- 搜索空状态 -->
      <svg
        v-else-if="variant === 'search'"
        viewBox="0 0 200 200"
        fill="none"
        class="empty-svg"
      >
        <circle cx="80" cy="80" r="40" fill="currentColor" fill-opacity="0.05"/>
        <path
          d="M135 125L110 100M95 95C95 109.357 83.3574 121 69 121C54.6426 121 43 109.357 43 95C43 80.6426 54.6426 69 69 69C83.3574 69 95 80.6426 95 95Z"
          stroke="currentColor"
          stroke-width="4"
          stroke-linecap="round"
          stroke-opacity="0.3"
        />
      </svg>

      <!-- 数据空状态 -->
      <svg
        v-else-if="variant === 'data'"
        viewBox="0 0 200 200"
        fill="none"
        class="empty-svg"
      >
        <rect x="40" y="50" width="50" height="100" rx="4" fill="currentColor" fill-opacity="0.08"/>
        <rect x="105" y="70" width="55" height="80" rx="4" fill="currentColor" fill-opacity="0.05"/>
        <rect x="50" y="70" width="30" height="4" rx="2" fill="currentColor" fill-opacity="0.15"/>
        <rect x="50" y="85" width="25" height="4" rx="2" fill="currentColor" fill-opacity="0.12"/>
        <rect x="50" y="100" width="28" height="4" rx="2" fill="currentColor" fill-opacity="0.12"/>
      </svg>

      <!-- 错误空状态 -->
      <svg
        v-else-if="variant === 'error'"
        viewBox="0 0 200 200"
        fill="none"
        class="empty-svg empty-svg--error"
      >
        <circle cx="100" cy="100" r="70" fill="currentColor" fill-opacity="0.08"/>
        <path
          d="M100 60C93.5 60 88.5 65 88.5 71.5V88.5H71.5C65 88.5 60 93.5 60 100V128.5C60 135 65 140 71.5 140H128.5C135 140 140 135 140 128.5V100C140 93.5 135 88.5 128.5 88.5H111.5V71.5C111.5 65 106.5 60 100 60Z"
          fill="currentColor"
          fill-opacity="0.3"
        />
      </svg>

      <!-- 成功空状态 -->
      <svg
        v-else-if="variant === 'success'"
        viewBox="0 0 200 200"
        fill="none"
        class="empty-svg empty-svg--success"
      >
        <circle cx="100" cy="100" r="70" fill="currentColor" fill-opacity="0.1"/>
        <path
          d="M100 55C74.6 55 54 75.6 54 101C54 126.4 74.6 147 100 147C125.4 147 146 126.4 146 101C146 75.6 125.4 55 100 55ZM100 62C121.5 62 139 79.5 139 101C139 122.5 121.5 140 100 140C78.5 140 61 122.5 61 101C61 79.5 78.5 62 100 62ZM88 95.5L96 103.5L116 83.5L121 88.5L96 113.5L83 100.5L88 95.5Z"
          fill="currentColor"
          fill-opacity="0.5"
        />
      </svg>
    </div>

    <!-- 自定义图标 -->
    <div v-else class="empty-icon">
      <component :is="icon" :size="48" />
    </div>

    <!-- 标题 -->
    <h3 v-if="title || $slots.title" class="empty-title">
      <slot name="title">{{ title }}</slot>
    </h3>

    <!-- 描述 -->
    <p v-if="description || $slots.description" class="empty-description">
      <slot name="description">{{ description }}</slot>
    </p>

    <!-- 操作按钮 -->
    <button v-if="actionLabel || $slots.action" class="empty-action" @click="emit('action')">
      <slot name="action">{{ actionLabel }}</slot>
    </button>

    <!-- 自定义插槽 -->
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
}

.empty-state--compact {
  padding: 2.5rem 1.5rem;
}

.empty-illustration {
  margin-bottom: 1.5rem;
}

.empty-svg {
  width: 140px;
  height: 140px;
  color: var(--text-quaternary, rgba(250, 250, 250, 0.3));
}

.empty-state--compact .empty-svg {
  width: 100px;
  height: 100px;
}

.empty-svg--error {
  color: var(--color-danger, #ef4444);
}

.empty-svg--success {
  color: var(--color-success, #10b981);
}

.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--bg-input, rgba(255, 255, 255, 0.05));
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}

.empty-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-secondary, rgba(250, 250, 250, 0.7));
  margin: 0 0 0.75rem 0;
}

.empty-description {
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
  margin: 0 0 1.5rem 0;
  max-width: 380px;
}

.empty-action {
  padding: 0.75rem 1.5rem;
  background: var(--color-primary, #10b981);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 150ms ease;
}

.empty-action:hover {
  background: var(--color-primary-dark, #059669);
  transform: translateY(-1px);
}

.empty-action:active {
  transform: scale(0.97);
}

/* 进入动画 */
.empty-illustration,
.empty-icon {
  animation: fadeInScale 0.5s ease-out;
}

.empty-title,
.empty-description,
.empty-action {
  animation: fadeInUp 0.5s ease-out 0.1s both;
}

@keyframes fadeInScale {
  from {
    opacity: 0;
    transform: scale(0.85);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
