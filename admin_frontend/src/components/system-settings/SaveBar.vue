<!--
  SaveBar.vue
  Apple TV 风格系统配置页面 - 底部保存栏（Sticky）

  功能：
  - 显示已修改项数量
  - 放弃/保存按钮
  - 保存中状态
-->
<script setup lang="ts">
interface Props {
  dirtyCount: number
  saving?: boolean
}

interface Emits {
  (e: 'discard'): void
  (e: 'save'): void
}

withDefaults(defineProps<Props>(), {
  saving: false
})

const emit = defineEmits<Emits>()
</script>

<template>
  <transition name="save-bar-slide">
    <div v-if="dirtyCount > 0" class="save-bar">
      <!-- 左侧提示文字 -->
      <div class="save-bar-left">
        <span class="save-dot"></span>
        <span class="save-text">已修改</span>
        <span class="save-count">{{ dirtyCount }}</span>
        <span class="save-text">项</span>
      </div>

      <!-- 右侧操作按钮 -->
      <div class="save-bar-right">
        <button
          class="btn-discard touch-feedback"
          :disabled="saving"
          @click="emit('discard')"
        >
          放弃
        </button>
        <button
          class="btn-save touch-feedback"
          :disabled="saving"
          @click="emit('save')"
        >
          <span v-if="saving" class="btn-content">
            <svg class="spinner" width="16" height="16" viewBox="0 0 16 16">
              <circle
                cx="8"
                cy="8"
                r="6"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-opacity="0.3"
              />
              <path
                d="M8 2A6 6 0 0 1 14 8"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
              />
            </svg>
            保存中...
          </span>
          <span v-else class="btn-content">保存更改</span>
        </button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.save-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  padding-bottom: calc(12px + max(env(safe-area-inset-bottom), 8px));
  background-color: var(--bg-card);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--border-base);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.4);
}

/* 左侧文字 */
.save-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.save-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--warning);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.save-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.save-count {
  font-size: 16px;
  font-weight: 600;
  color: var(--warning);
}

/* 右侧按钮区 */
.save-bar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 放弃按钮 */
.btn-discard {
  padding: 0 16px;
  height: 44px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  background: transparent;
  border: none;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-discard:hover:not(:disabled) {
  color: var(--text-primary);
  background-color: var(--bg-card-hover);
}

.btn-discard:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 保存按钮 */
.btn-save {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 120px;
  height: 44px;
  padding: 0 20px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-inverse);
  background-color: var(--primary);
  border: none;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.btn-save:hover:not(:disabled) {
  background-color: var(--primary-hover);
}

.btn-save:active:not(:disabled) {
  background-color: var(--primary-active);
}

.btn-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 旋转动画 */
.spinner {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 滑入动画 */
.save-bar-slide-enter-active,
.save-bar-slide-leave-active {
  transition: transform var(--transition-base) ease, opacity var(--transition-base) ease;
}

.save-bar-slide-enter-from,
.save-bar-slide-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .save-bar {
    padding: 10px 12px;
    padding-bottom: calc(10px + max(env(safe-area-inset-bottom), 8px));
  }

  .save-text {
    font-size: 13px;
  }

  .save-count {
    font-size: 15px;
  }

  .btn-discard {
    padding: 0 14px;
    height: 40px;
    font-size: 13px;
  }

  .btn-save {
    min-width: 100px;
    height: 40px;
    padding: 0 16px;
    font-size: 13px;
  }
}
</style>
