<template>
  <Teleport to="body">
    <Transition name="modal-backdrop">
      <div
        v-if="modelValue"
        class="modal-backdrop"
        @click="handleBackdropClick"
      />
    </Transition>

    <Transition name="modal-content">
      <div
        v-if="modelValue"
        :class="['modal-container', { 'modal-container--centered': centered }]"
        role="dialog"
        aria-modal="true"
      >
        <div
          :class="['modal-content-wrapper', `modal--${size}`]"
          @click.stop
        >
          <div v-if="$slots.header" class="modal-header">
            <slot name="header">
              <h3 class="modal-title">{{ title }}</h3>
            </slot>
            <button
              v-if="closable"
              type="button"
              class="modal-close"
              @click="handleClose"
              aria-label="关闭"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="modal-body" :class="{ 'modal-body--no-padding': noPadding }">
            <slot />
          </div>

          <div v-if="$slots.footer" class="modal-footer">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
export type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'full'

export interface ModalProps {
  modelValue: boolean
  title?: string
  size?: ModalSize
  centered?: boolean
  closable?: boolean
  closeOnBackdrop?: boolean
  noPadding?: boolean
}

const props = withDefaults(defineProps<ModalProps>(), {
  size: 'md',
  centered: true,
  closable: true,
  closeOnBackdrop: true,
  noPadding: false
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  close: []
  open: []
}>()

const handleClose = () => {
  emit('update:modelValue', false)
  emit('close')
}

const handleBackdropClick = () => {
  if (props.closeOnBackdrop) {
    handleClose()
  }
}

// ESC 键关闭
const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.modelValue && props.closable) {
    handleClose()
  }
}

if (import.meta.client) {
  onMounted(() => {
    document.addEventListener('keydown', handleKeydown)
  })
  onUnmounted(() => {
    document.removeEventListener('keydown', handleKeydown)
  })
}
</script>

<script lang="ts">
import { onMounted, onUnmounted } from 'vue'
export default {
  name: 'Modal'
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal-backdrop);
  background: var(--bg-overlay);
  backdrop-filter: blur(4px);
}

.modal-container {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  overflow-y: auto;
  display: flex;
  padding: 1rem;
}

.modal-container--centered {
  align-items: center;
  justify-content: center;
}

.modal-content-wrapper {
  position: relative;
  width: 100%;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 2rem);
}

.modal--sm { max-width: 400px; }
.modal--md { max-width: 540px; }
.modal--lg { max-width: 720px; }
.modal--xl { max-width: 960px; }
.modal--full { max-width: 100%; height: 100%; max-height: 100vh; border-radius: 0; }

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--divider-color);
  flex-shrink: 0;
}

.modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.modal-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.modal-close:hover {
  background: var(--bg-elevated-hover);
  color: var(--text-primary);
}

.modal-close svg {
  width: 18px;
  height: 18px;
}

.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
  flex: 1;
}

.modal-body--no-padding {
  padding: 0;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--divider-color);
  flex-shrink: 0;
}

/* 背景进入/离开动画 */
.modal-backdrop-enter-active,
.modal-backdrop-leave-active {
  transition: opacity 0.25s ease;
}

.modal-backdrop-enter-from,
.modal-backdrop-leave-to {
  opacity: 0;
}

/* 内容进入/离开动画 */
.modal-content-enter-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-content-leave-active {
  transition: all 0.2s ease-in;
}

.modal-content-enter-from {
  opacity: 0;
  transform: scale(0.95) translateY(10px);
}

.modal-content-leave-to {
  opacity: 0;
  transform: scale(0.95);
}

/* 响应式 */
@media (max-width: 640px) {
  .modal-container {
    padding: 0;
    align-items: flex-end;
  }

  .modal-content-wrapper {
    max-height: 85vh;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  }

  .modal--sm,
  .modal--md,
  .modal--lg,
  .modal--xl {
    max-width: 100%;
  }

  .modal-content-enter-from {
    transform: translateY(100%);
  }
}
</style>
