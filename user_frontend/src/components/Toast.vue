<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

export interface ToastMessage {
  id: number
  type: 'success' | 'error' | 'warning' | 'info'
  message: string
  duration?: number
}

const props = defineProps<{
  messages: ToastMessage[]
}>()

const emit = defineEmits<{
  (e: 'remove', id: number): void
}>()

// 自动移除消息
onMounted(() => {
  props.messages.forEach(msg => {
    const duration = msg.duration ?? 3000
    if (duration > 0) {
      setTimeout(() => {
        emit('remove', msg.id)
      }, duration)
    }
  })
})

// 获取图标
const getIcon = (type: string) => {
  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ'
  }
  return icons[type as keyof typeof icons] || icons.info
}

// 获取样式类
const getToastClass = (type: string) => {
  const classes = {
    success: 'toast-success',
    error: 'toast-error',
    warning: 'toast-warning',
    info: 'toast-info'
  }
  return classes[type as keyof typeof classes] || classes.info
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="toast"
          :class="getToastClass(msg.type)"
        >
          <span class="toast-icon">{{ getIcon(msg.type) }}</span>
          <span class="toast-message">{{ msg.message }}</span>
          <button @click="emit('remove', msg.id)" class="toast-close">
            ×
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 80px;
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-tooltip, 700);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  min-width: 280px;
  max-width: 90vw;
  background: var(--bg-elevated, #141414);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.15));
  border-radius: var(--radius-md, 10px);
  box-shadow: var(--shadow-lg, 0 12px 24px rgba(0, 0, 0, 0.5));
  backdrop-filter: blur(8px);
}

.toast-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: bold;
  flex-shrink: 0;
}

.toast-message {
  flex: 1;
  font-size: 0.875rem;
  color: var(--text-primary, #fafafa);
}

.toast-close {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
  border-radius: 4px;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  transition: all 0.2s ease;
}

.toast-close:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary, #fafafa);
}

.toast-close:active {
  transform: scale(0.9);
}

/* 成功状态 */
.toast-success {
  border-color: var(--brand-primary-light, rgba(16, 185, 129, 0.3));
}

.toast-success .toast-icon {
  background: var(--brand-primary-light, rgba(16, 185, 129, 0.2));
  color: var(--brand-primary, #10b981);
}

/* 错误状态 */
.toast-error {
  border-color: rgba(239, 68, 68, 0.3);
}

.toast-error .toast-icon {
  background: rgba(239, 68, 68, 0.2);
  color: var(--color-error, #ef4444);
}

/* 警告状态 */
.toast-warning {
  border-color: rgba(245, 158, 11, 0.3);
}

.toast-warning .toast-icon {
  background: rgba(245, 158, 11, 0.2);
  color: var(--color-warning, #f59e0b);
}

/* 信息状态 */
.toast-info {
  border-color: rgba(59, 130, 246, 0.3);
}

.toast-info .toast-icon {
  background: rgba(59, 130, 246, 0.2);
  color: var(--color-info, #3b82f6);
}

/* 过渡动画 */
.toast-enter-active {
  transition: all 0.3s ease;
}

.toast-leave-active {
  transition: all 0.2s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateY(-20px) translateX(-50%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateY(-10px) translateX(-50%);
}

.toast-move {
  transition: transform 0.3s ease;
}

/* 移动端适配 */
@media (max-width: 640px) {
  .toast-container {
    top: 70px;
    left: 1rem;
    right: 1rem;
    transform: none;
  }

  .toast {
    min-width: auto;
    width: 100%;
  }

  .toast-enter-from,
  .toast-leave-to {
    transform: translateY(-10px);
  }
}
</style>
