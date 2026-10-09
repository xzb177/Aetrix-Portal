<script setup lang="ts">
/**
 * 全局轻提示（暗房影院）：实色浮层 + 发丝线 + 左侧语义色细条，只淡入不横滑。
 * 语义色只染图标与左侧细条，正文走正文色（与 el-message 同口径）。
 */
import { CheckCircle, XCircle, AlertCircle, Info, X } from 'lucide-vue-next'
import { useToast } from '@/composables/useToast'

const { toasts, removeToast } = useToast()

const toastIcons = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertCircle,
  info: Info,
}
</script>

<template>
  <Teleport to="body">
    <TransitionGroup tag="div" name="toast" class="toast-container" aria-live="polite">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast"
        :class="`is-${toast.type}`"
        :role="toast.type === 'error' ? 'alert' : 'status'"
      >
        <component :is="toastIcons[toast.type]" :size="18" class="toast-icon" />
        <span class="toast-message">{{ toast.message }}</span>
        <button type="button" class="toast-close" aria-label="关闭提示" @click="removeToast(toast.id)">
          <X :size="15" />
        </button>
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 280px;
  max-width: 440px;
  padding: 12px 12px 12px 14px;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border-strong);
  border-left: 3px solid var(--au-info);
  border-radius: var(--au-r-md);
  box-shadow: var(--au-shadow-2);
  color: var(--au-text);
}

.toast.is-success { border-left-color: var(--au-success); }
.toast.is-error { border-left-color: var(--au-danger); }
.toast.is-warning { border-left-color: var(--au-warning); }

.toast-icon { flex-shrink: 0; color: var(--au-info); }
.is-success .toast-icon { color: var(--au-success); }
.is-error .toast-icon { color: var(--au-danger); }
.is-warning .toast-icon { color: var(--au-warning); }

.toast-message {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.toast-close {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: 4px;
  border: none;
  border-radius: var(--au-r-sm);
  background: transparent;
  color: var(--au-text-3);
  cursor: pointer;
  transition: background var(--au-fast) var(--au-ease), color var(--au-fast) var(--au-ease);
}

.toast-close:hover { background: var(--au-violet-soft); color: var(--au-text); }
.toast-close:focus-visible { outline: 2px solid var(--au-border-focus); outline-offset: 1px; }

/* 只淡入淡出（设计规则 7：不上浮、不横滑） */
.toast-enter-active,
.toast-leave-active { transition: opacity var(--au-med) var(--au-ease); }
.toast-enter-from,
.toast-leave-to { opacity: 0; }

@media (max-width: 640px) {
  .toast-container { left: 12px; right: 12px; top: 12px; }
  .toast { min-width: 0; max-width: none; }
}
</style>
