<script setup lang="ts">
import { CheckCircle, XCircle, AlertCircle, Info, X } from 'lucide-vue-next'
import { useToast, type ToastType } from '@/composables/useToast'

const { toasts, removeToast } = useToast()

// Toast 图标
const toastIcons = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertCircle,
  info: Info,
}

// Toast 颜色
// 与 Aurora 令牌一致的语义色
const toastColors = {
  success: { bg: 'rgba(52, 211, 153, 0.14)', border: '#34d399', icon: '#34d399' },
  error: { bg: 'rgba(251, 113, 133, 0.14)', border: '#fb7185', icon: '#fb7185' },
  warning: { bg: 'rgba(251, 191, 36, 0.14)', border: '#fbbf24', icon: '#fbbf24' },
  info: { bg: 'rgba(96, 165, 250, 0.14)', border: '#60a5fa', icon: '#60a5fa' },
}

const getToastColor = (type: ToastType) => toastColors[type]
</script>

<template>
  <Teleport to="body">
    <div class="toast-container">
      <Transition
        v-for="toast in toasts"
        :key="toast.id"
        name="toast"
      >
        <div
          class="toast"
          :style="{
            background: getToastColor(toast.type).bg,
            borderColor: getToastColor(toast.type).border,
          }"
        >
          <component
            :is="toastIcons[toast.type]"
            :size="20"
            :style="{ color: getToastColor(toast.type).icon }"
          />
          <span class="toast-message">{{ toast.message }}</span>
          <button class="toast-close" @click="removeToast(toast.id)">
            <X :size="16" />
          </button>
        </div>
      </Transition>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-radius: 12px;
  border-left: 4px solid;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
  min-width: 300px;
  max-width: 450px;
}

.toast-message {
  flex: 1;
  font-size: 0.875rem;
  color: var(--text-primary);
}

.toast-close {
  padding: 0.25rem;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.toast-close:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-primary);
}

/* Toast 动画 */
.toast-enter-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.toast-leave-active {
  transition: all 0.2s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

/* 移动端适配 */
@media (max-width: 640px) {
  .toast-container {
    left: 1rem;
    right: 1rem;
  }

  .toast {
    min-width: auto;
    max-width: none;
  }
}
</style>
