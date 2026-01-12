<script setup lang="ts">
import { computed } from 'vue'
import {
  Loader2,
  SearchX,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  Users,
} from 'lucide-vue-next'

export type StateType = 'loading' | 'empty' | 'error' | 'success'

interface Props {
  type: StateType
  title?: string
  message?: string
  searchable?: boolean
  retryable?: boolean
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  searchable: true,
  retryable: true,
  loading: false,
})

const emit = defineEmits<{
  retry: []
}>()

const stateConfig = computed(() => {
  switch (props.type) {
    case 'loading':
      return {
        icon: Loader2,
        iconClass: 'state-icon-loading',
        title: props.title || '加载中...',
        message: props.message,
      }
    case 'empty':
      return {
        icon: props.searchable ? SearchX : Users,
        iconClass: 'state-icon-empty',
        title: props.title || (props.searchable ? '未找到相关用户' : '暂无用户'),
        message: props.message || (props.searchable ? '尝试更换搜索关键词' : '点击下方按钮添加第一个用户'),
      }
    case 'error':
      return {
        icon: AlertCircle,
        iconClass: 'state-icon-error',
        title: props.title || '加载失败',
        message: props.message || '请检查网络连接后重试',
      }
    case 'success':
      return {
        icon: CheckCircle,
        iconClass: 'state-icon-success',
        title: props.title || '操作成功',
        message: props.message,
      }
    default:
      return null
  }
})

const showRetry = computed(() => {
  return props.type === 'error' && props.retryable
})
</script>

<template>
  <div class="list-state" :class="`state-${type}`">
    <div class="state-content">
      <div :class="['state-icon', stateConfig?.iconClass]">
        <component :is="stateConfig?.icon" :size="type === 'loading' ? 32 : 40" />
      </div>
      <h3 class="state-title">{{ stateConfig?.title }}</h3>
      <p v-if="stateConfig?.message" class="state-message">{{ stateConfig.message }}</p>
      <div v-if="showRetry" class="state-actions">
        <button
          :class="['retry-btn', { 'retry-btn-loading': loading }]"
          :disabled="loading"
          @click="emit('retry')"
        >
          <RefreshCw :size="16" />
          <span>重试</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.list-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  padding: 40px 20px;
}

.state-content {
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.state-icon {
  width: 80px;
  height: 80px;
  border-radius: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.state-icon-loading {
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
}

.state-icon-loading svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.state-icon-empty {
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-tertiary);
}

.state-icon-error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.state-icon-success {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.state-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-primary);
}

.state-message {
  font-size: 13px;
  color: var(--text-tertiary);
  max-width: 240px;
}

.state-actions {
  margin-top: 8px;
}

.retry-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 150ms ease;
}

.retry-btn:active:not(:disabled) {
  background: #4f46e5;
  transform: scale(0.97);
}

.retry-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.retry-btn-loading svg {
  animation: spin 1s linear infinite;
}
</style>
