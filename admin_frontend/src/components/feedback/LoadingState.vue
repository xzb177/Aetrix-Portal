<script setup lang="ts">
interface Props {
  type?: 'skeleton' | 'spinner' | 'dots'
  rows?: number
  fullscreen?: boolean
  text?: string
}

const props = withDefaults(defineProps<Props>(), {
  type: 'skeleton',
  rows: 5,
  fullscreen: false,
  text: '加载中...',
})
</script>

<template>
  <!-- 全屏加载 -->
  <div v-if="fullscreen" class="loading-fullscreen">
    <div class="loading-spinner-large">
      <svg class="spinner" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>
    <p v-if="text" class="loading-text">{{ text }}</p>
  </div>

  <!-- 骨架屏 -->
  <div v-else-if="type === 'skeleton'" class="loading-skeleton">
    <div v-for="i in rows" :key="i" class="skeleton-row">
      <div class="skeleton-avatar"></div>
      <div class="skeleton-content">
        <div class="skeleton-line skeleton-line-title"></div>
        <div class="skeleton-line skeleton-line-subtitle"></div>
      </div>
    </div>
  </div>

  <!-- Spinner 加载 -->
  <div v-else-if="type === 'spinner'" class="loading-spinner">
    <svg class="spinner" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
    </svg>
    <p v-if="text" class="loading-text-small">{{ text }}</p>
  </div>

  <!-- 点状加载 -->
  <div v-else-if="type === 'dots'" class="loading-dots">
    <span class="dot"></span>
    <span class="dot"></span>
    <span class="dot"></span>
  </div>
</template>

<style scoped>
/* 全屏加载 */
.loading-fullscreen {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  background: var(--bg-surface);
  z-index: 999;
}

.loading-spinner-large {
  width: 48px;
  height: 48px;
}

.loading-spinner-large .spinner {
  width: 100%;
  height: 100%;
  color: var(--primary);
  animation: spin 1s linear infinite;
}

.loading-text {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

/* 骨架屏 */
.loading-skeleton {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem 0;
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
}

.skeleton-avatar {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.skeleton-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.skeleton-line {
  height: 14px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.skeleton-line-title {
  width: 60%;
}

.skeleton-line-subtitle {
  width: 40%;
}

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* Spinner 加载 */
.loading-spinner {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 2rem;
}

.loading-spinner .spinner {
  width: 32px;
  height: 32px;
  color: var(--primary);
  animation: spin 1s linear infinite;
}

.loading-text-small {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 点状加载 */
.loading-dots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem;
}

.dot {
  width: 8px;
  height: 8px;
  background: var(--primary);
  border-radius: 50%;
  animation: dot-pulse 1.4s ease-in-out infinite;
}

.dot:nth-child(1) {
  animation-delay: 0s;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes dot-pulse {
  0%, 80%, 100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  40% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
