<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  title?: string
  message: string
  details?: string
  showRetry?: boolean
  retryLabel?: string
  showCopy?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: '加载失败',
  showRetry: true,
  showCopy: true,
  retryLabel: '重试',
})

const emit = defineEmits<{
  retry: []
  copyDetails: []
}>()

const showDetails = ref(false)
const copySuccess = ref(false)

function handleRetry() {
  emit('retry')
}

function handleCopyDetails() {
  if (props.details) {
    navigator.clipboard.writeText(props.details)
    copySuccess.value = true
    emit('copyDetails')
    setTimeout(() => {
      copySuccess.value = false
    }, 2000)
  }
}

function toggleDetails() {
  showDetails.value = !showDetails.value
}
</script>

<template>
  <div class="error-state">
    <!-- 错误图标 -->
    <div class="error-icon">
      <svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="1.5"
          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
        />
      </svg>
    </div>

    <!-- 标题 -->
    <h3 class="error-title">{{ title }}</h3>

    <!-- 错误信息 -->
    <p class="error-message">{{ message }}</p>

    <!-- 详情展开按钮 -->
    <button v-if="details" class="error-details-toggle" @click="toggleDetails">
      <span>{{ showDetails ? '隐藏' : '查看' }}详情</span>
      <svg
        class="w-4 h-4 transition-transform"
        :class="{ 'rotate-180': showDetails }"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- 详情内容 -->
    <Transition
      enter-active-class="transition-all duration-200"
      enter-from-class="opacity-0 -translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-2"
    >
      <div v-if="showDetails && details" class="error-details">
        <code class="error-details-text">{{ details }}</code>
        <button
          v-if="showCopy"
          class="error-copy-btn"
          :class="{ 'error-copy-btn-success': copySuccess }"
          @click="handleCopyDetails"
        >
          <svg v-if="!copySuccess" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
            />
          </svg>
          <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M5 13l4 4L19 7"
            />
          </svg>
          <span>{{ copySuccess ? '已复制' : '复制' }}</span>
        </button>
      </div>
    </Transition>

    <!-- 操作按钮 -->
    <div v-if="showRetry" class="error-actions">
      <button class="error-retry-btn" @click="handleRetry">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
        <span>{{ retryLabel }}</span>
      </button>
    </div>

    <!-- 自定义插槽 -->
    <slot />
  </div>
</template>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1.5rem;
  text-align: center;
}

.error-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--danger-bg);
  color: var(--danger);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}

.error-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.5rem 0;
}

.error-message {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0 0 1rem 0;
  max-width: 320px;
}

.error-details-toggle {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-tertiary);
  background: transparent;
  border: 1px solid var(--border-base);
  border-radius: 8px;
  cursor: pointer;
  transition: all 150ms ease;
  margin-bottom: 0.75rem;
}

.error-details-toggle:active {
  background: var(--bg-input);
}

.error-details {
  width: 100%;
  max-width: 400px;
  background: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  padding: 0.75rem;
  margin-bottom: 1rem;
  position: relative;
}

.error-details-text {
  display: block;
  font-size: 11px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  color: var(--text-tertiary);
  word-break: break-all;
  line-height: 1.5;
  padding-right: 3rem;
}

.error-copy-btn {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.375rem 0.625rem;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: 6px;
  cursor: pointer;
  transition: all 150ms ease;
}

.error-copy-btn:active {
  background: var(--bg-card-hover);
}

.error-copy-btn-success {
  color: var(--success);
  border-color: var(--success);
}

.error-actions {
  display: flex;
  gap: 0.75rem;
}

.error-retry-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  font-size: 14px;
  font-weight: 500;
  color: white;
  background: var(--primary);
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 150ms ease;
}

.error-retry-btn:active {
  background: var(--primary-active);
  transform: scale(0.97);
}
</style>
