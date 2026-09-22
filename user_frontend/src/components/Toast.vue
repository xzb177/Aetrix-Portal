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
    <div class="toast-container" role="status" aria-live="polite">
      <TransitionGroup name="toast">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="toast"
          :class="getToastClass(msg.type)"
        >
          <span class="toast-icon" aria-hidden="true">{{ getIcon(msg.type) }}</span>
          <span class="toast-message">{{ msg.message }}</span>
          <button
            type="button"
            class="toast-close"
            aria-label="关闭提示"
            @click="emit('remove', msg.id)"
          >
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
  /* 贴在吸顶导航下方，并让开刘海区 */
  top: calc(74px + env(safe-area-inset-top, 0px));
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
  /* 与页面其它浮层同一套表面：半透明 + 毛玻璃 + 强边框，不再是一块中性灰 */
  background: var(--au-surface-3);
  border: 1px solid var(--au-border-strong);
  border-radius: var(--au-r-md);
  box-shadow: var(--au-shadow-2);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
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
  line-height: 1.5;
  color: var(--au-text);
  word-break: break-word;
}

.toast-close {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--au-text-3);
  border-radius: var(--au-r-sm);
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  transition: background-color var(--au-fast) var(--au-ease),
              color var(--au-fast) var(--au-ease),
              transform var(--au-fast) var(--au-ease);
  flex-shrink: 0;
}

.toast-close:hover {
  background: var(--au-surface-2);
  color: var(--au-text);
}

.toast-close:active {
  transform: scale(0.9);
}

.toast-close:focus-visible {
  outline: 2px solid var(--au-primary);
  outline-offset: 1px;
}

/* 四种状态 = 四支语义色（底色与图标取同一支，不再手写 rgba） */
.toast-success { border-color: var(--au-success-border); }

.toast-success .toast-icon {
  background: var(--au-success-soft);
  color: var(--au-success);
}

.toast-error { border-color: var(--au-danger-border); }

.toast-error .toast-icon {
  background: var(--au-danger-soft);
  color: var(--au-danger);
}

.toast-warning { border-color: var(--au-warning-border); }

.toast-warning .toast-icon {
  background: var(--au-warning-soft);
  color: var(--au-warning);
}

.toast-info { border-color: var(--au-info-border); }

.toast-info .toast-icon {
  background: var(--au-info-soft);
  color: var(--au-info);
}

/* 过渡动画
   只做「淡入 + 轻微下移」，不碰水平位移：容器已经用 translateX(-50%) 居中了，
   子项再写一次 translateX(-50%) 会让每条通知先从左侧半个身位滑回来。 */
.toast-enter-active {
  transition: opacity var(--au-med) var(--au-ease),
              transform var(--au-med) var(--au-ease);
}

.toast-leave-active {
  transition: opacity var(--au-fast) var(--au-ease),
              transform var(--au-fast) var(--au-ease);
}

.toast-enter-from {
  opacity: 0;
  transform: translateY(-12px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.toast-move {
  transition: transform var(--au-med) var(--au-ease);
}

/* 移动端适配 */
@media (max-width: 640px) {
  .toast-container {
    top: calc(66px + env(safe-area-inset-top, 0px));
    left: 1rem;
    right: 1rem;
    transform: none;
  }

  .toast {
    min-width: auto;
    width: 100%;
  }
}

/* 减少动态效果：只保留透明度变化 */
@media (prefers-reduced-motion: reduce) {
  .toast-enter-from,
  .toast-leave-to {
    transform: none;
  }

  .toast-close:active {
    transform: none;
  }
}
</style>
